"""Rasterize unchanged static ASS only at frame-exact display changes."""

import math
from pathlib import Path
from PIL import Image


def event_frame(value, fps):
    hours, minutes, tail = value.split(":")
    seconds, centiseconds = tail.split(".")
    ticks = (int(hours) * 3600 + int(minutes) * 60 + int(seconds)) * 100 + int(centiseconds.ljust(2, "0"))
    return (ticks * fps + 99) // 100


def preparation(subtitle, folder, duration, fps=30, width=1920, height=1080):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    frames = math.ceil(duration * fps)
    changes = {0, frames}
    for line in Path(subtitle).read_text().splitlines():
        if not line.startswith("Dialogue:"):
            continue
        fields = line.split(",", 9)
        if len(fields) != 10 or fields[8] or "{\\" in fields[9]:
            raise ValueError("Animated or custom ASS effects require the standard renderer.")
        for value in fields[1:3]:
            changes.add(min(frames, max(0, event_frame(value, fps))))
    changes = sorted(changes)
    blank = folder / "transparent.png"
    Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(blank)
    escaped = str(blank.resolve()).replace("'", "'\\''")
    lines = ["ffconcat version 1.0"]
    for index, frame in enumerate(changes):
        lines += [f"file '{escaped}'", f"option framerate {fps}"]
        if index + 1 < len(changes):
            lines.append(f"duration {(changes[index+1]-frame)/fps:.9f}")
    concat = folder / "states.ffconcat"
    concat.write_text("\n".join(lines) + "\n")
    escaped = str(Path(subtitle).resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "'\\\\''")
    movie = folder / "captions.mov"
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", "-threads", "1",
               "-filter_threads", "1", "-f", "concat", "-safe", "0", "-i", str(concat),
               "-vf", f"format=rgba,subtitles=filename='{escaped}':alpha=1", "-an",
               "-c:v", "qtrle", "-pix_fmt", "argb", "-fps_mode", "passthrough",
               "-video_track_timescale", str(fps), str(movie)]
    return command, movie, changes
