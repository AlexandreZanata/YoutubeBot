"""Export blind frame/caption-window pairs from private artifacts; never opens a browser."""

import argparse
import json
from pathlib import Path
import random
import subprocess
import sys

from . import config, flow_benchmark as bench, flow_media


def export(root, candidate, index, trial):
    from PIL import Image, ImageDraw
    from src.engine.classic_filters import background_filter

    video = root / "results/render" / candidate / f"input-{index}" / f"trial-{trial}/video.mp4"
    reference = bench.input_file(root, index, "narration.ass")
    if not video.is_file() or not reference.is_file():
        raise ValueError("A complete candidate and copied original standard ASS are required.")
    asr = json.loads((root / "results/asr/openvino-gpu" / f"input-{index}" / f"trial-{trial}/segments.json").read_text())
    duration = float(bench.probe(video)["format"]["duration"])
    background = config.ROOT / "assets/backgrounds/fallem_prince.mp4"
    stream = next(item for item in bench.probe(background)["streams"] if item["codec_type"] == "video")
    if stream["r_frame_rate"] != "30/1" or not stream.get("nb_frames"):
        raise ValueError("Frame review requires the measured 30-fps background loop.")
    background_frames = int(stream["nb_frames"])
    points = [("frame", round((n + 0.5) * min(duration, asr[-1]["end"]) / 10 * 30)) for n in range(10)]
    for n in range(10):
        segment = asr[min(len(asr)-1, int((n + 0.5) * len(asr) / 10))]
        points.append(("caption-window", round((segment["start"] + segment["end"]) / 2 * 30)))
    folder = root / "review" / candidate / f"input-{index}"
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    escaped = str(reference.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "'\\\\''")
    pairs, mapping = [], []
    for number, (kind, frame) in enumerate(points):
        baseline, fast = folder / f"reference-{number}.png", folder / f"candidate-{number}.png"
        phase = frame % background_frames
        vf = (f"trim=start_frame={phase},setpts=PTS-STARTPTS," +
              background_filter(None, 1920, 1080, 30, True) +
              f",setpts=PTS+{frame}/(30*TB),subtitles=filename='{escaped}',setpts=PTS-STARTPTS")
        commands = [
            ["ffmpeg", "-nostdin", "-v", "error", "-threads", "2", "-stream_loop", "-1", "-i",
             str(background), "-filter_threads", "1", "-vf", vf,
             "-frames:v", "1", "-fps_mode", "passthrough", "-pix_fmt", "rgb24", str(baseline)],
            ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{frame/30:.9f}", "-threads", "2",
             "-i", str(video), "-frames:v", "1", "-pix_fmt", "rgb24", str(fast)],
        ]
        for command in commands:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        sides = [baseline, fast]
        random.SystemRandom().shuffle(sides)
        mapping.append({"number": number, "kind": kind, "frame": frame,
                        "A": "standard" if sides[0] == baseline else "candidate"})
        pairs.append((kind, frame, sides))
    for start in range(0, len(pairs), 5):
        sheet = Image.new("RGB", (960, 5 * 294), "#202020")
        draw = ImageDraw.Draw(sheet)
        for row, (kind, frame, sides) in enumerate(pairs[start:start+5]):
            for column, path in enumerate(sides):
                with Image.open(path) as source:
                    sheet.paste(source.resize((480, 270)), (column * 480, row * 294 + 24))
                draw.text((column * 480 + 8, row * 294 + 5), f"{start+row+1} {kind} {frame/30:.3f}s {'A' if column==0 else 'B'}", fill="white")
        sheet.save(folder / f"sheet-{start//5+1}.png")
    bench.save(folder / "blind-mapping.json", mapping)
    bench.save(folder / "review.json", {"frames_exported": 10, "caption_window_centers_exported": 10,
               "reviewed": False, "note": "Static centers do not prove temporal/audio review; operator review still required."})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--production-root", type=Path, required=True)
    parser.add_argument("--candidate", choices=flow_media.RENDER_CANDIDATES, required=True)
    parser.add_argument("--input-index", type=int, choices=(1, 2), required=True)
    parser.add_argument("--trial", type=int, default=1)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    root = bench.private_root(args.root, args.production_root)
    if args.worker:
        if "flowbench-" not in Path("/proc/self/cgroup").read_text():
            raise ValueError("Frame export requires its isolated benchmark unit.")
        export(root, args.candidate, args.input_index, args.trial)
    else:
        bench.BENCHMARK_ROOT = root
        permit = root / "paused-production.json"
        bench.PAUSE_PERMIT = json.loads(permit.read_text()) if permit.exists() else None
        bench.bounded([sys.executable, "-m", "tools.ytbot.flow_review", "--root", str(root),
            "--production-root", str(args.production_root), "--candidate", args.candidate,
            "--input-index", str(args.input_index), "--trial", str(args.trial), "--worker"],
            root / "review-execution" / f"input-{args.input_index}", args.production_root)


if __name__ == "__main__":
    main()
