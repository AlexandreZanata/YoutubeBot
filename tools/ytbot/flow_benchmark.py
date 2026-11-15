"""Private, offline ASR/render experiments. Never calls production or browser APIs."""

from __future__ import annotations

import argparse
from collections import defaultdict
import fcntl
import difflib
from datetime import datetime
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import time
import uuid

from . import config, flow_media

INPUTS = (
    "can-you-ever-know-whether-your-thoughts-are-truly-your-own",
    "why-does-the-mind-turn-uncertainty-into-obsession",
)
ACTIVE = {"active", "activating", "deactivating", "reloading"}
PAUSE_PERMIT = None
CPU_QUOTA = 200
BENCHMARK_ROOT = None
FILTER_CANDIDATES = ("decode-loop", "scale-crop", "ass", "x264-video-only", "audio-volume-aac")
EXPERIMENTAL_ASR = {"openvino-cpu-t2": ("CPU", 2), "openvino-cpu-t4": ("CPU", 4), "openvino-gpu": ("GPU", 2)}
ASR_IDS = tuple(flow_media.ASR_CANDIDATES) + tuple(EXPERIMENTAL_ASR)


def process_stat(pid):
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return {"state": fields[0], "parent": int(fields[1]), "identity": fields[19]}


def paused_operation():
    if not PAUSE_PERMIT:
        return None
    permit = PAUSE_PERMIT
    if time.time() >= permit["deadline_unix"]:
        raise ProductionBusy("The owner's three-hour pause window has expired.")
    try:
        actual = process_stat(permit["pid"])
        partial = Path(permit["partial_video"])
        if actual["state"] != "T" or actual["identity"] != permit["process_identity"]:
            raise ProductionBusy("The owner-paused renderer changed or resumed; stopping benchmarks.")
        if partial.stat().st_size != permit["partial_size"]:
            raise ProductionBusy("The partial production video changed; stopping benchmarks.")
        expected = "youtubebot-" + permit["operation_id"] + ".service"
        if expected not in Path(f"/proc/{permit['pid']}/cgroup").read_text():
            raise ProductionBusy("Paused process is not in the expected production unit.")
    except OSError as error:
        raise ProductionBusy("Paused production process cannot be verified.") from error
    return permit["operation_id"]


class ProductionBusy(RuntimeError):
    """Fail closed without changing a production lock, record, unit or process."""


def assert_idle(production):
    allowed = paused_operation()
    result = subprocess.run(
        ["/usr/bin/systemctl", "--user", "list-units", "--all", "--plain", "--no-legend",
         "--no-pager", "youtubebot-*.service"], capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise ProductionBusy("User systemd state unavailable; no heavy work is allowed.")
    for line in result.stdout.splitlines():
        fields = line.split()
        permitted = bool(allowed and fields and fields[0] == f"youtubebot-{allowed}.service")
        if len(fields) < 4 or (fields[2] in ACTIVE and not permitted):
            raise ProductionBusy("A production unit is active; no heavy work is allowed.")
    for path in (Path(production) / ".local/ytbot-service/jobs").glob("*.json"):
        if path.name == "active-job.json":
            continue
        record = json.loads(path.read_text())
        if allowed and path.stem == allowed:
            continue
        pid = record.get("pid")
        if record.get("state") in {"accepted", "running"}:
            raise ProductionBusy("An admitted production operation needs to finish first.")
        if isinstance(pid, int) and pid > 0:
            try:
                parts = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
                if parts[0] != "Z" and parts[19] == record.get("process_identity"):
                    raise ProductionBusy("A production actor is still alive.")
            except FileNotFoundError:
                pass


def private_root(path, production):
    path, production = Path(path).resolve(), Path(production).resolve()
    if path == production or path.is_relative_to(production):
        raise ValueError("Benchmark files must be outside the installed production checkout.")
    if path.is_relative_to(config.ROOT.resolve()) and not path.is_relative_to(config.ROOT.resolve() / ".local"):
        raise ValueError("Use ignored .local state or a private directory outside the checkout.")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + ".part")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def input_file(root, index, name):
    path = root / "inputs" / f"input-{index}" / name
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Benchmark inputs must be independent private copies.")
    return path


def input_audio(root, index):
    wav = input_file(root, index, "narration.wav")
    return wav if wav.exists() else input_file(root, index, "narration.aac")


def screening_root(root, production, seconds, offset):
    destination = root / "screening" / f"quota-{CPU_QUOTA}-offset-{offset}-seconds-{seconds}"
    for index in (1, 2):
        folder = destination / "inputs" / f"input-{index}"
        if (folder / "narration.wav").exists():
            continue
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        source = input_audio(root, index)
        command = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-i", str(source),
                   "-ss", str(offset), "-t", str(seconds), "-ar", "16000", "-ac", "1",
                   "-c:a", "pcm_f32le", str(folder / "narration.wav")]
        bounded(command, destination / "extraction" / f"input-{index}", production)
        shutil.copyfile(input_file(root, index, "article.txt"), folder / "article.txt")
    save(destination / "scope.json", {"screening_only": True, "offset_seconds": offset,
                                       "duration_seconds": seconds, "cpu_quota_percent": CPU_QUOTA})
    return destination


def versions():
    result = {"python": sys.version.split()[0]}
    for package in ("av", "faster-whisper", "ctranslate2", "torch", "numpy"):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "unavailable"
    result["ffmpeg"] = subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0]
    return result


def telemetry():
    temperatures, clocks = [], []
    for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            temperatures.append(int(path.read_text()) / 1000)
        except (OSError, ValueError):
            pass
    for path in Path("/sys/devices/system/cpu").glob("cpu[0-9]*/cpufreq/scaling_cur_freq"):
        try:
            clocks.append(int(path.read_text()) / 1000)
        except (OSError, ValueError):
            pass
    try:
        gpu_clock = int(Path("/sys/class/drm/card1/gt_act_freq_mhz").read_text())
    except (OSError, ValueError):
        gpu_clock = None
    return {"load_average": list(os.getloadavg()), "intel_gpu_clock_mhz": gpu_clock,
            "max_temperature_c": max(temperatures, default=None),
            "mean_clock_mhz": statistics.mean(clocks) if clocks else None}


def diagnose(production):
    try:
        assert_idle(production)
        idle, reason = True, None
    except ProductionBusy as error:
        idle, reason = False, str(error)
    filters = subprocess.check_output(["ffmpeg", "-hide_banner", "-filters"], stderr=subprocess.DEVNULL, text=True)
    return {"schema": 1, "production_idle": idle, "benchmark_blocked_reason": reason,
            "versions": versions(), "telemetry": telemetry(),
            "cpu_count": os.cpu_count(), "free_bytes": shutil.disk_usage(production).free,
            "dri_access": os.access("/dev/dri/renderD128", os.R_OK | os.W_OK),
            "vmaf_available": "libvmaf" in filters,
            "optional_tools": {name: bool(shutil.which(name)) for name in ("whisper-cli", "vainfo", "intel_gpu_top", "cmake", "ninja")}}


def snapshot(root, production):
    """Copy only stable inputs, with no hard links or browser/provider state."""
    manifest = []
    for index, slug in enumerate(INPUTS, 1):
        source = Path(production) / ".local/ytbot/runs" / slug
        destination = root / "inputs" / f"input-{index}"
        if destination.exists():
            raise ValueError("Input snapshot already exists; choose a new private root.")
        destination.mkdir(parents=True, mode=0o700)
        for name in ("article.txt", "article.md", "narration.aac", "narration.ass", "metadata.json", "thumbnail.png"):
            file = source / name
            if file.is_symlink():
                raise ValueError("Input symlinks are not accepted.")
            if file.is_file():
                before = file.stat()
                shutil.copyfile(file, destination / name)
                if (before.st_size, before.st_mtime_ns) != (file.stat().st_size, file.stat().st_mtime_ns):
                    raise ValueError("An input changed during copying; snapshot is incomplete.")
                (destination / name).chmod(0o600)
        manifest.append({"input": index, "audio_sha256": digest(destination / "narration.aac"),
                         "article_sha256": digest(destination / "article.txt")})
    save(root / "manifest.json", {"inputs": manifest, "source_revision": subprocess.check_output(
        ["git", "-C", str(production), "rev-parse", "HEAD"], text=True).strip(),
        "excludes": ["video.mp4", "upload.json", "record.json", ".codex-media", "locks", "operation state"]})
    return manifest


def bounded(command, folder, production):
    """Every heavy child gets a fresh 200%/12G/16G/12h benchmark unit."""
    lock = (BENCHMARK_ROOT or folder.parent) / "benchmark.lock"
    lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another benchmark child is active; concurrent timing is prohibited.") from None
        return _bounded(command, folder, production)
    finally:
        os.close(descriptor)


def _bounded(command, folder, production):
    assert_idle(production)
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    unit = "flowbench-" + str(uuid.uuid4())
    resource = folder / "resources.txt"
    argv = ["/usr/bin/systemd-run", "--user", "--quiet", "--wait", "--collect", "--pipe",
            "--unit=" + unit, "--working-directory=" + str(folder.resolve()),
            f"--property=CPUQuota={CPU_QUOTA}%", "--property=MemoryHigh=12G", "--property=MemoryMax=16G",
            "--property=TasksMax=256", "--property=RuntimeMaxSec=12h", "--property=Restart=no",
            "--property=KillMode=control-group", "--property=UMask=0077",
            "--setenv=PYTHONPATH=" + str(config.ROOT), "--setenv=HF_HUB_OFFLINE=1",
            "--setenv=OPENVINO_TELEMETRY_DATA=0",
            "--", "/usr/bin/time", "-o", str(resource), "-f", "%e\n%U\n%S\n%M\n%x", *command]
    if BENCHMARK_ROOT:
        drivers = BENCHMARK_ROOT / "tooling/intel/root/usr/lib/x86_64-linux-gnu"
        if drivers.is_dir():
            position = argv.index("--")
            argv[position:position] = ["--setenv=LIBVA_DRIVERS_PATH=" + str(drivers / "dri"),
                                      "--setenv=LD_LIBRARY_PATH=" + str(drivers) + ":" + str(drivers / "intel-opencl")]
        vendors = BENCHMARK_ROOT / "tooling/ocl-vendors"
        if vendors.is_dir():
            position = argv.index("--")
            argv[position:position] = ["--setenv=OCL_ICD_VENDORS=" + str(vendors),
                "--setenv=NEO_CACHE_DIR=" + str(BENCHMARK_ROOT / "tooling/neo-cache"),
                "--setenv=XDG_CACHE_HOME=" + str(BENCHMARK_ROOT / "tooling/cache")]
        nasm = BENCHMARK_ROOT / "tooling/nasm/root/usr/bin"
        if nasm.is_dir():
            position = argv.index("--")
            argv[position:position] = ["--setenv=PATH=" + str(nasm) + ":" +
                                      str(BENCHMARK_ROOT / "tooling/build-env/bin") + ":/usr/local/bin:/usr/bin:/bin"]
    start, samples, aborted = time.monotonic(), [], None
    cgroup = None
    with (folder / "stdout.txt").open("w") as stdout, (folder / "stderr.txt").open("w") as stderr:
        process = subprocess.Popen(argv, stdout=stdout, stderr=stderr)
        try:
            while process.poll() is None:
                assert_idle(production)
                sample = telemetry()
                if cgroup is None:
                    probe = subprocess.run(["/usr/bin/systemctl", "--user", "show", unit + ".service",
                        "--property=ControlGroup", "--value"], capture_output=True, text=True, timeout=5)
                    relative = probe.stdout.strip()
                    if relative.startswith("/user.slice/"):
                        cgroup = Path("/sys/fs/cgroup") / relative.lstrip("/")
                if cgroup is not None:
                    for key in ("memory.current", "memory.peak", "cpu.stat", "cpu.max"):
                        try:
                            sample[key] = (cgroup / key).read_text().strip()
                        except OSError:
                            pass
                samples.append(sample)
                time.sleep(2)
        except BaseException as error:
            aborted = type(error).__name__
            # This prefix is constructed here and can never name a production unit.
            subprocess.run(["/usr/bin/systemctl", "--user", "stop", unit + ".service"],
                           check=False, capture_output=True, timeout=20)
            process.wait(timeout=30)
            raise
        finally:
            save(folder / "execution.json", {"command": command, "resource_command": argv,
                 "unit": unit, "elapsed_seconds": time.monotonic() - start,
                 "exit_code": process.poll(), "aborted": aborted, "samples": samples,
                 "versions": versions(), "cpu_quota_percent": CPU_QUOTA})
    if process.returncode:
        raise RuntimeError(f"Benchmark failed; inspect private files in {folder}.")
    lines = resource.read_text().splitlines()
    # GNU time can prepend a termination diagnostic on failed processes (handled above).
    elapsed, user, system, rss, code = map(float, lines[-5:])
    return {"wall_seconds": elapsed, "cpu_seconds": user + system,
            "mean_cpu_percent": (user + system) / elapsed * 100 if elapsed else 0,
            "max_rss_kib": rss, "exit_code": int(code)}


def run_asr(root, production, candidate, repeat, indices=(1, 2)):
    from src.engine.audio_mixer import get_audio_duration

    for index in indices:
        audio = input_audio(root, index)
        for trial in range(1, repeat + 1):
            folder = root / "results" / "asr" / candidate / f"input-{index}" / f"trial-{trial}"
            result = folder / "result.json"
            if result.exists():
                continue
            assert_idle(production)
            seconds = get_audio_duration(audio)
            if seconds <= 0:
                raise ValueError("Audio duration must be known.")
            command = [sys.executable, "-m", "tools.ytbot.flow_benchmark", "_asr",
                       "--audio", str(audio), "--candidate", candidate, "--output", str(folder / "segments.json")]
            if candidate in EXPERIMENTAL_ASR:
                device, threads = EXPERIMENTAL_ASR[candidate]
                command = [str(BENCHMARK_ROOT / "tooling/ov-env/bin/python"), "-m", "tools.ytbot.benchmark_openvino",
                           "--audio", str(audio), "--model", str(BENCHMARK_ROOT / "tooling/ov-model"),
                           "--output", str(folder / "segments.json"), "--device", device, "--threads", str(threads)]
            resource = bounded(command, folder, production)
            save(result, {"stage": "asr", "candidate": candidate, "input": index, "trial": trial,
                          "duration_seconds": seconds, "rtf": resource["wall_seconds"] / seconds,
                          "audio_sha256": digest(audio),
                          "options": flow_media.ASR_CANDIDATES.get(candidate, EXPERIMENTAL_ASR.get(candidate)),
                          "environment": flow_media.ASR_ENVIRONMENT.get(candidate, {}), **resource})


def run_render(root, production, candidate, repeat, asr_candidate="standard", indices=(1, 2), limit=None):
    from src.engine.audio_mixer import get_audio_duration
    from src.engine.subtitle_generator import save_ass_subtitles
    from src.engine.video_composer import build_single_pass_command

    for index in indices:
        audio = input_audio(root, index)
        for trial in range(1, repeat + 1):
            destination = root if limit is None else root / "calibration" / f"seconds-{limit}"
            folder = destination / "results" / "render" / candidate / f"input-{index}" / f"trial-{trial}"
            if (folder / "result.json").exists():
                continue
            assert_idle(production)
            seconds = get_audio_duration(audio) + 5.0
            if limit is not None:
                seconds = min(seconds, limit)
            asr = root / "results/asr" / asr_candidate / f"input-{index}" / f"trial-{trial}/segments.json"
            segments = json.loads(asr.read_text())
            subtitle = root / "subtitles" / candidate / f"input-{index}-trial-{trial}.ass"
            subtitle.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            save_ass_subtitles(segments, subtitle, font_size=97, width=1920, height=1080,
                               alignment=5, outline_width=4, margin_horizontal=192)
            output = folder / "video.mp4"
            arguments = dict(image_path=config.ROOT / "assets/backgrounds/fallem_prince.mp4",
                narr_path=audio, bgm_path=None, subtitle_path=subtitle, output_path=output,
                narr_vol=2.0, bgm_vol=0.0, width=1920, height=1080, fps=30,
                total_duration=seconds, background_is_video=True)
            preparation_resource = None
            if candidate.endswith("-cached-ass"):
                from .subtitle_cache import preparation

                prep, movie, changes = preparation(subtitle,
                    destination / "caption-cache" / candidate / f"input-{index}-trial-{trial}", seconds)
                preparation_resource = bounded(prep,
                    destination / "preparation" / candidate / f"input-{index}-trial-{trial}", production)
                command = flow_media.cached_video_command(arguments, movie, candidate)
            else:
                build = {key: value for key, value in arguments.items() if key != "total_duration"}
                command = flow_media.encoding_command(build_single_pass_command(**build, duration=seconds), candidate)
            scope = root / "scope.json"
            if scope.exists():
                # Keep the production loop's phase on the original global timeline.
                offset = json.loads(scope.read_text())["offset_seconds"]
                background_frames = offset * 30 % (24 * 30)
                position = command.index("-filter_complex") + 1
                command[position] = command[position].replace("[0:v]", f"[0:v]trim=start_frame={background_frames},setpts=PTS-STARTPTS,", 1)
            command[-1:-1] = ["-nostdin", "-progress", "pipe:1", "-nostats"]
            resource = bounded(command, folder, production)
            if preparation_resource:
                resource["preparation_seconds"] = preparation_resource["wall_seconds"]
                resource["encoding_seconds"] = resource["wall_seconds"]
                resource["wall_seconds"] += preparation_resource["wall_seconds"]
                resource["cpu_seconds"] += preparation_resource["cpu_seconds"]
                resource["max_rss_kib"] = max(resource["max_rss_kib"], preparation_resource["max_rss_kib"])
                resource["mean_cpu_percent"] = resource["cpu_seconds"] / resource["wall_seconds"] * 100
            frames = math.ceil(seconds * 30)
            progress = (folder / "stdout.txt").read_text()
            counters = {field: re.findall(rf"^{field}=(\d+)$", progress, flags=re.MULTILINE)
                        for field in ("frame", "dup_frames", "drop_frames")}
            save(folder / "result.json", {"stage": "render", "candidate": candidate,
                 "input": index, "trial": trial, "duration_seconds": seconds, "expected_frames": frames,
                 "effective_fps": frames / resource["wall_seconds"], "size_bytes": output.stat().st_size,
                 "asr_candidate": asr_candidate, "audio_sha256": digest(audio),
                 "progress_counters": {key: int(values[-1]) if values else None for key, values in counters.items()}, **resource})


def run_filters(root, production, candidate, repeat, asr_candidate, indices=(1, 2)):
    from src.engine.classic_filters import background_filter
    from src.engine.subtitle_generator import save_ass_subtitles

    for index in indices:
        for trial in range(1, repeat + 1):
            folder = root / "results/filters" / candidate / f"input-{index}" / f"trial-{trial}"
            if (folder / "result.json").exists():
                continue
            subtitle = root / "subtitles/filters" / f"input-{index}.ass"
            if candidate in {"ass", "x264-video-only"}:
                segments = json.loads((root / "results/asr" / asr_candidate / f"input-{index}/trial-1/segments.json").read_text())
                subtitle.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                save_ass_subtitles(segments, subtitle, font_size=97, width=1920, height=1080,
                                   alignment=5, outline_width=4, margin_horizontal=192)
            if candidate == "audio-volume-aac":
                command = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-i", str(input_audio(root, index)),
                           "-t", "30", "-vn", "-af", "volume=2.0", "-c:a", "aac", "-b:a", "128k", "-f", "null", "-"]
            else:
                command = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-threads", "2",
                           "-stream_loop", "-1", "-i", str(config.ROOT / "assets/backgrounds/fallem_prince.mp4"),
                           "-t", "30", "-an", "-filter_threads", "1"]
                if candidate != "decode-loop":
                    vf = background_filter(subtitle if candidate in {"ass", "x264-video-only"} else None,
                                           1920, 1080, 30, True)
                    command += ["-vf", vf]
                if candidate == "x264-video-only":
                    command += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-threads:v", "2"]
                command += ["-f", "null", "-"]
            resource = bounded(command, folder, production)
            save(folder / "result.json", {"stage": "filters", "candidate": candidate,
                 "input": index, "trial": trial, "duration_seconds": 30,
                 "effective_fps": 900 / resource["wall_seconds"], **resource})


def normalize(text):
    return re.findall(r"[^\W_]+(?:'[^\W_]+)?", text.lower().replace("’", "'"), flags=re.UNICODE)


def edit_distance(reference, hypothesis):
    """Exact Myers bit-vector Levenshtein distance, including long articles."""
    if not reference:
        return len(hypothesis)
    masks = defaultdict(int)
    for index, token in enumerate(reference):
        masks[token] |= 1 << index
    positive, negative, distance = (1 << len(reference)) - 1, 0, len(reference)
    high = 1 << (len(reference) - 1)
    for token in hypothesis:
        equal = masks[token]
        vertical = equal | negative
        horizontal = (((equal & positive) + positive) ^ positive) | equal
        plus = negative | ~(horizontal | positive)
        minus = positive & horizontal
        distance += bool(plus & high) - bool(minus & high)
        plus = (plus << 1) | 1
        positive = (minus << 1) | ~(vertical | plus)
        negative = plus & vertical
    return distance


def error_rates(reference, hypothesis):
    words, recognized = normalize(reference), normalize(hypothesis)
    chars, transcribed = " ".join(words), " ".join(recognized)
    if not words or not chars:
        raise ValueError("A nonempty reference is required.")
    return {"wer": edit_distance(words, recognized) / len(words),
            "cer": edit_distance(chars, transcribed) / len(chars)}


def timed_tokens(segments):
    result = []
    for segment in segments:
        words = normalize(segment["text"])
        for index, word in enumerate(words):
            result.append((word, segment["start"] + (segment["end"] - segment["start"]) * (index + 0.5) / len(words)))
    return result


def compare_asr(article, baseline, candidate):
    from src.engine.transcription_cache import valid_segments

    text = lambda rows: " ".join(row["text"] for row in rows)
    base, fast = error_rates(article, text(baseline)), error_rates(article, text(candidate))
    reference, hypothesis = timed_tokens(baseline), timed_tokens(candidate)
    alignment = difflib.SequenceMatcher(None, [x[0] for x in reference], [x[0] for x in hypothesis], autojunk=False)
    deviations = [abs(reference[a+k][1] - hypothesis[b+k][1])
                  for a, b, size in alignment.get_matching_blocks() for k in range(size)]
    ordered = valid_segments(candidate) and all(b["start"] >= a["start"] and b["end"] >= a["end"]
                                                 for a, b in zip(candidate, candidate[1:]))
    return {"reference": "existing article, normalized words; not an audited spoken transcript",
            "baseline": base, "candidate": fast,
            "wer_delta_pp": (fast["wer"] - base["wer"]) * 100,
            "cer_delta_pp": (fast["cer"] - base["cer"]) * 100,
            "median_interpolated_token_deviation_seconds": statistics.median(deviations) if deviations else None,
            "matched_word_fraction": len(deviations) / len(reference) if reference else 0,
            "ordered_timestamps": bool(ordered),
            "start_delta_seconds": abs(candidate[0]["start"] - baseline[0]["start"]),
            "end_delta_seconds": abs(candidate[-1]["end"] - baseline[-1]["end"]),
            "missing_or_duplicated_blocks_review": "pending", "english_and_timestamp_review": "pending",
            "approved": False}


def compare(root, production, candidate, repeat, indices=(1, 2), reference_segments=None):
    for index in indices:
        article = input_file(root, index, "article.txt").read_text()
        for trial in range(1, repeat + 1):
            base = (Path(reference_segments) if reference_segments else
                    root / "results/asr/standard" / f"input-{index}" / f"trial-{trial}/segments.json")
            path = root / "results/asr" / candidate / f"input-{index}" / f"trial-{trial}"
            save(path / "quality.json", compare_asr(article, json.loads(base.read_text()),
                                                    json.loads((path / "segments.json").read_text())))


def probe(path):
    return json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams",
                                               "-show_format", "-of", "json", str(path)], text=True))


def video_metrics(root, production, candidate, repeat, indices=(1, 2)):
    filters = subprocess.check_output(["ffmpeg", "-hide_banner", "-filters"], text=True, stderr=subprocess.DEVNULL)
    vmaf = "libvmaf" in filters
    for index in indices:
        for trial in range(1, repeat + 1):
            assert_idle(production)
            base = root / "results/render/standard" / f"input-{index}" / f"trial-{trial}/video.mp4"
            path = root / "results/render" / candidate / f"input-{index}" / f"trial-{trial}"
            video = path / "video.mp4"
            if (path / "quality.json").exists():
                continue
            source, target = probe(base), probe(video)
            streams = lambda item: next(s for s in item["streams"] if s["codec_type"] == "video")
            before, after = streams(source), streams(target)
            folder = path / "metrics"
            count = 3 if vmaf else 2
            graph = f"[0:v]setpts=PTS-STARTPTS,split={count}[c1][c2]" + ("[c3]" if vmaf else "") + ";"
            graph += f"[1:v]setpts=PTS-STARTPTS,split={count}[r1][r2]" + ("[r3]" if vmaf else "") + ";"
            graph += "[c1][r1]ssim[s];[c2][r2]psnr[p]"
            maps = ["-map", "[s]", "-map", "[p]"]
            if vmaf:
                graph += f";[c3][r3]libvmaf=log_fmt=json:log_path={folder / 'vmaf.json'}:n_threads=2[m]"
                maps += ["-map", "[m]"]
            command = ["ffmpeg", "-nostdin", "-hide_banner", "-threads", "2", "-i", str(video),
                       "-threads", "2", "-i", str(base), "-filter_complex_threads", "1",
                       "-filter_complex", graph, *maps, "-an", "-f", "null", "-"]
            bounded(command, folder, production)
            stderr = (folder / "stderr.txt").read_text()
            ssim = re.findall(r"All:([0-9.]+)", stderr)
            psnr = re.findall(r"average:([0-9.]+|inf)", stderr)
            audio = []
            for label, file in (("standard", base), ("candidate", video)):
                command = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(file), "-map", "0:a:0",
                           "-c:a", "copy", "-f", "hash", "-hash", "sha256", "-"]
                bounded(command, folder / label, production)
                audio.append((folder / label / "stdout.txt").read_text().strip())
            if not vmaf and BENCHMARK_ROOT:
                executable = BENCHMARK_ROOT / "tooling/vmaf-build/tools/vmaf"
                if executable.is_file():
                    command = [sys.executable, "-m", "tools.ytbot.flow_benchmark", "_vmaf",
                               "--reference", str(base), "--distorted", str(video),
                               "--executable", str(executable), "--folder", str(folder / "vmaf")]
                    bounded(command, folder / "vmaf", production)
            score_file = folder / "vmaf.json" if vmaf else folder / "vmaf/vmaf.json"
            score = json.loads(score_file.read_text())["pooled_metrics"]["vmaf"]["mean"] if score_file.exists() else None
            same_timing = abs(float(after["duration"]) - float(before["duration"])) <= 1 / 30
            measurements = {"ssim": float(ssim[-1]) if ssim else None,
                            "psnr_db": ("inf" if psnr[-1] == "inf" else float(psnr[-1])) if psnr else None,
                            "vmaf": score, "audio_aac_sha256_equal": bool(audio[0] and audio[0] == audio[1]),
                            "dimensions": [after["width"], after["height"]], "fps": after["avg_frame_rate"],
                            "frame_count_equal": after.get("nb_frames") == before.get("nb_frames") and "nb_frames" in after,
                            "duration_equal_within_one_frame": same_timing,
                            "size_ratio": video.stat().st_size / base.stat().st_size,
                            "visual_ab_frames_reviewed": 0, "subtitle_windows_reviewed": 0,
                            "approved": False}
            save(path / "quality.json", measurements)


def standalone_vmaf(reference, distorted, executable, folder):
    """Decode to private FIFOs; never materialize hundreds of GB of raw video."""
    folder = Path(folder)
    pipes = [folder / "reference.yuv", folder / "distorted.yuv"]
    children, logs = [], []
    try:
        for source, pipe in zip((reference, distorted), pipes):
            os.mkfifo(pipe, 0o600)
            log = (folder / (pipe.stem + "-decode.log")).open("w")
            logs.append(log)
            children.append(subprocess.Popen(["ffmpeg", "-nostdin", "-v", "error", "-y",
                "-threads", "1", "-i", str(source), "-map", "0:v:0", "-an",
                "-pix_fmt", "yuv420p", "-f", "rawvideo", str(pipe)], stderr=log))
        subprocess.run([str(executable), "--reference", str(pipes[0]), "--distorted", str(pipes[1]),
                        "--width", "1920", "--height", "1080", "--pixel_format", "420",
                        "--bitdepth", "8", "--threads", "2", "--json",
                        "--output", str(folder / "vmaf.json")], check=True)
        if any(child.wait(timeout=30) for child in children):
            raise RuntimeError("A VMAF input decoder failed.")
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=15)
        for log in logs:
            log.close()
        for pipe in pipes:
            pipe.unlink(missing_ok=True)


def summarize(root):
    groups = defaultdict(list)
    for path in root.glob("**/results/*/*/input-*/trial-*/result.json"):
        row = json.loads(path.read_text())
        scope = path.parents[5]
        label = str(scope.relative_to(root))
        setting = json.loads((scope / "scope.json").read_text()) if (scope / "scope.json").exists() else {}
        quota = row.get("cpu_quota_percent", setting.get("cpu_quota_percent", 400 if "quota-400" in label else 200))
        row["quality"] = json.loads(path.with_name("quality.json").read_text()) if path.with_name("quality.json").exists() else None
        groups[(label, quota, row["stage"], row["candidate"], row["input"])].append(row)
    result = []
    for (scope, quota, stage, candidate, index), trials in sorted(groups.items()):
        times = [row["wall_seconds"] for row in trials]
        baseline = groups.get((scope, quota, stage, "standard", index), [])
        median = statistics.median(times)
        record = {"scope": scope, "cpu_quota_percent": quota,
                  "stage": stage, "candidate": candidate, "input": index,
                  "repeats": len(times), "median_seconds": median,
                  "min_seconds": min(times), "max_seconds": max(times),
                  "stdev_seconds": statistics.pstdev(times) if len(times) > 1 else None,
                  "gain": statistics.median([row["wall_seconds"] for row in baseline]) / median if baseline else None,
                  "timing_measured": True, "approved": False,
                  "quality": [row["quality"] for row in trials if row["quality"] is not None]}
        for key in ("duration_seconds", "rtf", "effective_fps", "size_bytes", "cpu_seconds", "mean_cpu_percent", "max_rss_kib", "cgroup_memory_peak_bytes"):
            values = [row[key] for row in trials if isinstance(row.get(key), (int, float))]
            if values:
                record[key] = statistics.median(values)
        result.append(record)
    return {"schema": 1, "approved": False, "default_profile": "standard", "timings": result,
            "reason": "Full timing, objective quality and blind review are all required; missing evidence never passes."}


def report(root):
    summary = summarize(root)
    save(root / "aggregate.json", summary)
    lines = ["# Flow benchmark results", "", "Default: standard. Timing alone never approves a candidate.", "",
             "| Scope | Quota | Stage | Candidate | Input | Repeats | Median s | Min–max s | Gain | Approved |",
             "|---|---:|---|---|---:|---:|---:|---:|---:|---|"]
    for row in summary["timings"]:
        gain = f"{row['gain']:.3f}x" if row["gain"] is not None else "pending"
        lines.append(f"| {row['scope']} | {row['cpu_quota_percent']}% | {row['stage']} | {row['candidate']} | {row['input']} | {row['repeats']} | "
                     f"{row['median_seconds']:.2f} | {row['min_seconds']:.2f}–{row['max_seconds']:.2f} | {gain} | pending |")
    if not summary["timings"]:
        lines.append("| All | 200% | All | All | both | 0 | pending | pending | pending | no |")
    (root / "aggregate.md").write_text("\n".join(lines) + "\n")
    return summary


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for verb in ("diagnose", "snapshot", "permit-pause", "asr", "render", "filters", "compare-asr", "compare-video", "report"):
        command = commands.add_parser(verb)
        command.add_argument("--root", type=Path, required=True)
        command.add_argument("--production-root", type=Path, required=True)
        command.add_argument("--cpu-quota", type=int, choices=(200, 400), default=200)
        if verb == "permit-pause":
            command.add_argument("--operation-id", required=True)
            command.add_argument("--pid", type=int, required=True)
            command.add_argument("--deadline", required=True)
        if verb in {"asr", "render", "filters", "compare-asr", "compare-video"}:
            candidates = (FILTER_CANDIDATES if verb == "filters" else flow_media.ASR_CANDIDATES
                          if verb in {"asr", "compare-asr"} else flow_media.RENDER_CANDIDATES)
            if verb in {"asr", "compare-asr"}:
                candidates = ASR_IDS
            command.add_argument("--candidate", choices=candidates, required=True)
            command.add_argument("--repeat", type=int, choices=range(1, 11), default=1)
            command.add_argument("--sample-seconds", type=int, choices=(300, 600))
            command.add_argument("--offset-seconds", type=int, default=900)
            command.add_argument("--input-index", type=int, choices=(1, 2))
        if verb in {"render", "filters"}:
            command.add_argument("--asr-candidate", choices=ASR_IDS, default="standard")
        if verb in {"render", "compare-video"}:
            command.add_argument("--render-limit-seconds", type=int, choices=(30, 60))
        if verb == "compare-asr":
            command.add_argument("--reference-segments", type=Path,
                                 help="existing copied full standard cache; requires one explicit input index")
    worker = commands.add_parser("_asr")
    worker.add_argument("--audio", type=Path, required=True)
    worker.add_argument("--candidate", choices=flow_media.ASR_CANDIDATES, required=True)
    worker.add_argument("--output", type=Path, required=True)
    worker = commands.add_parser("_vmaf")
    worker.add_argument("--reference", type=Path, required=True)
    worker.add_argument("--distorted", type=Path, required=True)
    worker.add_argument("--executable", type=Path, required=True)
    worker.add_argument("--folder", type=Path, required=True)
    return root


def main():
    global PAUSE_PERMIT, CPU_QUOTA, BENCHMARK_ROOT
    os.umask(0o077)
    args = parser().parse_args()
    if args.command == "_vmaf":
        if "flowbench-" not in Path("/proc/self/cgroup").read_text():
            raise ValueError("VMAF worker requires an isolated flowbench unit.")
        standalone_vmaf(args.reference, args.distorted, args.executable, args.folder)
        return
    if args.command == "_asr":
        # Internal worker is also fenced: manual invocation cannot skip the unit/quota boundary.
        cgroup = Path("/proc/self/cgroup").read_text()
        if "flowbench-" not in cgroup:
            raise ValueError("ASR worker requires an isolated flowbench unit.")
        for key, value in flow_media.ASR_ENVIRONMENT.get(args.candidate, {}).items():
            os.environ[key] = value
        last = [-30.0]

        def progress(seconds):
            if seconds - last[0] >= 30:
                last[0] = seconds
                print(f"[benchmark] transcribed through {seconds:.2f}s", flush=True)

        segments = flow_media.candidate_transcription(args.audio, "en", args.candidate, progress)
        from src.engine.transcription_cache import valid_segments
        if not valid_segments(segments):
            raise RuntimeError("Candidate returned no valid speech.")
        save(args.output, segments)
        return
    root = private_root(args.root, args.production_root)
    BENCHMARK_ROOT = root
    CPU_QUOTA = args.cpu_quota
    permit = root / "paused-production.json"
    if permit.exists():
        PAUSE_PERMIT = json.loads(permit.read_text())
    if args.command == "permit-pause":
        if permit.exists():
            raise ValueError("An existing pause permit cannot be extended or overwritten.")
        identity = process_stat(args.pid)
        if identity["state"] != "T":
            raise ProductionBusy("The specified renderer must already be stopped by its owner.")
        partial = args.production_root / ".local/ytbot/runs" / INPUTS[0] / "video.mp4"
        deadline = datetime.fromisoformat(args.deadline).timestamp()
        if not time.time() < deadline <= time.time() + 3 * 3600:
            raise ValueError("The pause deadline must be within three hours.")
        PAUSE_PERMIT = {"operation_id": str(uuid.UUID(args.operation_id)), "pid": args.pid,
                        "process_identity": identity["identity"], "partial_video": str(partial),
                        "partial_size": partial.stat().st_size, "deadline_unix": deadline}
        assert_idle(args.production_root)
        save(permit, PAUSE_PERMIT)
        print("Recorded bounded owner-authorized pause; production was not changed.")
        return
    if args.command == "diagnose":
        result = diagnose(args.production_root)
        save(root / "diagnostic.json", result)
        print(json.dumps(result, indent=2))
    elif args.command == "snapshot":
        snapshot(root, args.production_root)
    elif args.command == "report":
        report(root)
    else:
        if args.sample_seconds:
            root = screening_root(root, args.production_root, args.sample_seconds, args.offset_seconds)
        elif CPU_QUOTA != 200:
            # Full 400% results also need their own namespace and immutable inputs.
            destination = root / "full" / f"quota-{CPU_QUOTA}"
            if not (destination / "inputs").exists():
                shutil.copytree(root / "inputs", destination / "inputs")
            root = destination
    if args.command == "asr":
        run_asr(root, args.production_root, args.candidate, args.repeat,
                (args.input_index,) if args.input_index else (1, 2))
    elif args.command == "render":
        run_render(root, args.production_root, args.candidate, args.repeat, args.asr_candidate,
                   (args.input_index,) if args.input_index else (1, 2), args.render_limit_seconds)
    elif args.command == "filters":
        run_filters(root, args.production_root, args.candidate, args.repeat, args.asr_candidate,
                    (args.input_index,) if args.input_index else (1, 2))
    elif args.command == "compare-asr":
        if args.reference_segments and (not args.input_index or not args.reference_segments.resolve().is_relative_to(BENCHMARK_ROOT)):
            raise ValueError("A copied reference requires one input index and a path within the private benchmark root.")
        compare(root, args.production_root, args.candidate, args.repeat,
                (args.input_index,) if args.input_index else (1, 2), args.reference_segments)
    elif args.command == "compare-video":
        if args.render_limit_seconds:
            root = root / "calibration" / f"seconds-{args.render_limit_seconds}"
        video_metrics(root, args.production_root, args.candidate, args.repeat,
                      (args.input_index,) if args.input_index else (1, 2))


if __name__ == "__main__":
    main()
