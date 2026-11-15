"""Bounded local candidates shared by isolated benchmarks and the qualified flow."""

from functools import partial
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

ASR_CANDIDATES = {
    "standard": ("large-v3-turbo", 0, 0),
    **{f"turbo-t{threads}": ("large-v3-turbo", threads, 0) for threads in (2, 4, 8)},
    **{f"turbo-b{batch}-t2": ("large-v3-turbo", 2, batch) for batch in (4, 8)},
    "distil-large-v3-t2": ("distil-large-v3", 2, 0),
    "medium.en-t2": ("medium.en", 2, 0),
    "turbo-onednn-t2": ("large-v3-turbo", 2, 0),
    "turbo-no-vad-t2": ("large-v3-turbo", 2, 0),
}
ASR_ENVIRONMENT = {"turbo-onednn-t2": {"CT2_USE_MKL": "0"}}
ASR_TRANSCRIBE_OPTIONS = {"turbo-no-vad-t2": {"vad_filter": False}}
RENDER_CANDIDATES = {
    "standard": ("libx264", "veryfast", 18, 0, 0),
    **{f"{preset}-crf{crf}-t2": ("libx264", preset, crf, 2, 1)
       for preset in ("veryfast", "superfast", "ultrafast") for crf in (14, 16, 18)},
    "qsv-icq18": ("h264_qsv", "veryfast", 18, 2, 1),
    "qsv-qp18": ("h264_qsv", "veryfast", 18, 2, 1),
    "vaapi-qp18": ("h264_vaapi", None, 18, 2, 1),
    **{f"qsv-qp{qp}": ("h264_qsv", "veryfast", qp, 2, 1) for qp in (20, 22, 24)},
    **{f"vaapi-qp{qp}": ("h264_vaapi", None, qp, 2, 1) for qp in (20, 22, 24)},
    **{f"vaapi-qp{qp}-cached-ass": ("h264_vaapi", None, qp, 2, 2) for qp in (20, 22)},
}
# Provisional only. FAST_QUALIFIED is false until the full acceptance matrix passes.
FAST_ASR = "openvino-gpu"
FAST_RENDER = "vaapi-qp20-cached-ass"


def candidate_transcription(audio, language, candidate, progress_callback=None):
    from src.core.ai_transcriber import _transcribe_uncached

    model, threads, batch = ASR_CANDIDATES[candidate]
    return _transcribe_uncached(str(audio), model, language, False,
                                cpu_threads=threads, batch_size=batch,
                                progress_callback=progress_callback,
                                **ASR_TRANSCRIBE_OPTIONS.get(candidate, {}))


def transcribe_fast(audio, language, fallback, notify):
    from src.engine.transcription_cache import cached_transcription, valid_segments

    if FAST_ASR == "openvino-gpu" and language != "en":
        notify("asr", "unsupported_language")
        return fallback()
    if FAST_ASR == "openvino-gpu":
        model, threads, batch = "openvino-large-v3-turbo-int8-b568445", 2, 0
        engine = local_openvino
    else:
        model, threads, batch = ASR_CANDIDATES[FAST_ASR]
        engine = partial(candidate_transcription, candidate=FAST_ASR)

    def recognize(path, _model, lang, _words):
        return engine(path, lang)

    try:
        options = {"cpu_threads": threads, "batch_size": batch, "without_timestamps": False,
                   "backend": FAST_ASR, **ASR_TRANSCRIBE_OPTIONS.get(FAST_ASR, {})}
        if FAST_ASR == "openvino-gpu":
            lock = json.loads((runtime_tools() / "tooling/openvino-toolchain.json").read_text())
            options.update(engine_versions=lock["openvino_packages"], model=lock["openvino_model"])
        result = cached_transcription(audio, model, language, False, recognize,
                                      options=options)
        if valid_segments(result):
            return result
    except Exception:
        pass
    notify("asr", "candidate_failed")
    return fallback()


def runtime_tools():
    from . import config

    return config.ROOT / ".local/flow-tools"


def runtime_environment():
    from . import config

    root = runtime_tools() / "tooling"
    drivers = root / "intel/root/usr/lib/x86_64-linux-gnu"
    if not drivers.is_dir():
        return None
    env = {key: value for key, value in os.environ.items()
           if key in {"HOME", "PATH", "LANG", "LC_ALL", "XDG_RUNTIME_DIR"}}
    env.update(PYTHONPATH=str(config.ROOT), HF_HUB_OFFLINE="1", OPENVINO_TELEMETRY_DATA="0",
               LIBVA_DRIVERS_PATH=str(drivers / "dri"),
               LD_LIBRARY_PATH=str(drivers) + ":" + str(drivers / "intel-opencl"),
               OCL_ICD_VENDORS=str(root / "ocl-vendors"), NEO_CACHE_DIR=str(root / "neo-cache"),
               XDG_CACHE_HOME=str(root / "cache"))
    return env


def local_openvino(audio, language):
    from . import config

    # These two English videos are the qualification corpus; other languages keep standard.
    if language != "en":
        raise ValueError("The local OpenVINO profile has only been evaluated in English.")
    root = runtime_tools() / "tooling"
    lock = json.loads((root / "openvino-toolchain.json").read_text())
    if lock["openvino_model"]["revision"] != "b568445dd5dc8c695bde596f8acbb4694fd6ba64":
        raise ValueError("OpenVINO model revision differs from the qualified candidate.")
    environment = runtime_environment()
    if environment is None:
        raise ValueError("The private OpenVINO runtime is incomplete.")
    with TemporaryDirectory(prefix=".flow-asr-", dir=Path(audio).resolve().parent) as temporary:
        output = Path(temporary) / "segments.json"
        subprocess.run([str(root / "ov-env/bin/python"), "-m", "tools.ytbot.openvino_engine",
            "--audio", str(Path(audio).resolve()), "--model", str(root / "ov-model"),
            "--output", str(output), "--device", "GPU", "--threads", "2"],
            cwd=Path(temporary), env=environment, check=True, capture_output=True, text=True,
            timeout=3 * 3600)
        return json.loads(output.read_text())


def encoding_command(command, candidate):
    """Replace only video encoder/thread flags; preserve filters, audio and timeline."""
    encoder, preset, quality, threads, filter_threads = RENDER_CANDIDATES[candidate]
    command = list(command)
    start, end = command.index("-c:v"), command.index("-g")
    flags = ["-c:v", encoder]
    if preset:
        flags += ["-preset", preset]
    quality_flag = ("-crf" if encoder == "libx264" else
                    "-q:v" if candidate.startswith("qsv-qp") else
                    "-global_quality:v" if encoder == "h264_qsv" else "-qp")
    flags += [quality_flag, str(quality)]
    if threads:
        flags += ["-threads:v", str(threads)]
    command[start:end] = flags
    if filter_threads:
        command[1:1] = ["-filter_complex_threads", str(filter_threads)]
    if encoder == "h264_vaapi":
        command[1:1] = ["-vaapi_device", "/dev/dri/renderD128"]
        index = command.index("-filter_complex") + 1
        command[index] = command[index].replace("[vout]", ",format=nv12,hwupload[vout]", 1)
    elif encoder == "h264_qsv":
        command[1:1] = ["-init_hw_device", "qsv=hw,child_device=/dev/dri/renderD128,child_device_type=vaapi"]
        if candidate.startswith("qsv-qp"):
            command[-1:-1] = ["-low_power", "1"]
    return command


def cached_video_command(arguments, movie, candidate):
    from src.engine.video_composer import build_single_pass_command

    build = {key: value for key, value in arguments.items()
             if key not in {"progress_callback", "total_duration"}}
    build.update(subtitle_path=None, duration=arguments["total_duration"])
    command = build_single_pass_command(**build)
    index = command.index("-filter_complex")
    stream = command[:index].count("-i")
    command[index:index] = ["-i", str(movie)]
    index = command.index("-filter_complex") + 1
    overlay = (f"[bg];[{stream}:v]format=gbrap,unpremultiply=inplace=1,format=yuva420p[sub];"
               "[bg][sub]overlay=alpha=straight:format=yuv420[vout]")
    command[index] = command[index].replace("[vout]", overlay, 1)
    # Bound the input decoder as well as the output encoder on this two-core quota.
    first_input = command.index("-i")
    command[first_input:first_input] = ["-threads", "2"]
    return encoding_command(command, candidate)


def render_fast(arguments, fallback, notify):
    from src.engine.video_composer import build_single_pass_command, execute_ffmpeg

    output = Path(arguments["output_path"])
    # A failed optimized attempt must never truncate an existing complete result.
    with TemporaryDirectory(prefix=".flow-render-", dir=output.parent) as directory:
        temporary = Path(directory) / "video.mp4"
        build = {key: value for key, value in arguments.items()
                 if key not in {"progress_callback", "total_duration"}}
        build.update(output_path=temporary, duration=arguments["total_duration"])
        try:
            if FAST_RENDER.endswith("-cached-ass") and build.get("subtitle_path") is not None:
                from .subtitle_cache import preparation

                prep, movie, _changes = preparation(build["subtitle_path"], Path(directory) / "captions",
                    arguments["total_duration"], arguments["fps"], arguments["width"], arguments["height"])
                ok, _errors = execute_ffmpeg(prep, env=runtime_environment())
                if not ok:
                    raise ValueError("Subtitle cache preparation failed.")
                candidate_arguments = {**arguments, "output_path": temporary}
                command = cached_video_command(candidate_arguments, movie, FAST_RENDER)
            else:
                command = encoding_command(build_single_pass_command(**build), FAST_RENDER)
            ok, _errors = execute_ffmpeg(command, arguments["progress_callback"], arguments["total_duration"],
                                         env=runtime_environment())
            if ok and temporary.is_file() and temporary.stat().st_size:
                temporary.replace(output)
                return True
        except (OSError, ValueError):
            pass
        notify("render", "candidate_failed")
        standard = Path(directory) / "standard.mp4"
        if fallback(standard) and standard.is_file() and standard.stat().st_size:
            standard.replace(output)
            return True
    return False
