"""FFmpeg Single-Pass Stable NVENC GPU Video Composer module."""

import subprocess
from pathlib import Path

from src.engine.classic_filters import background_filter, video_encoding_args


def parse_out_time_sec(line: str) -> float:
    """Parse out_time_ms or out_time from FFmpeg progress output line."""
    if line.startswith("out_time_ms="):
        val = line.split("=")[1].strip()
        return float(val) / 1000000.0 if val.isdigit() else -1.0
    if line.startswith("out_time="):
        parts = line.split("=")[1].strip().split(":")
        if len(parts) == 3:
            try:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            except ValueError:
                return -1.0
    return -1.0


def build_single_pass_command(
    image_path: Path,
    narr_path: Path,
    bgm_path: Path | None,
    subtitle_path: Path | None,
    output_path: Path,
    narr_vol: float = 2.0,
    bgm_vol: float = 0.15,
    width: int = 1920,
    height: int = 1080,
    fps: int = 15,
    duration: float = 0.0,
    background_is_video: bool = False,
) -> list[str]:
    """Construct stable single-pass FFmpeg NVENC command."""
    vf = background_filter(subtitle_path, width, height, fps, background_is_video)
    loop = ["-stream_loop", "-1"] if background_is_video else ["-loop", "1", "-framerate", "1"]

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-thread_queue_size", "1024", *loop, "-i", str(image_path),
        "-thread_queue_size", "1024", "-i", str(narr_path)
    ]

    if bgm_path and bgm_path.is_file():
        cmd.extend(["-thread_queue_size", "1024", "-stream_loop", "-1", "-i", str(bgm_path)])
        af = f"[1:a]volume={narr_vol}[narr];[2:a]volume={bgm_vol}[bgm];[narr][bgm]amix=inputs=2:duration=longest:normalize=0[aout]"
        filter_complex = f"[0:v]{vf}[vout];{af}"
        cmd.extend(["-filter_complex", filter_complex, "-map", "[vout]", "-map", "[aout]"])
    else:
        filter_complex = f"[0:v]{vf}[vout]"
        cmd.extend(["-filter_complex", filter_complex, "-map", "[vout]", "-map", "1:a", "-af", f"volume={narr_vol}"])

    if duration > 0:
        cmd.extend(["-t", f"{duration:.3f}"])

    cmd.extend([
        *video_encoding_args(fps), "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", str(output_path)
    ])
    return cmd


def execute_ffmpeg(command, progress_callback=None, total_duration=0.0, *, env=None):
    """Run an internally constructed command and report its actual encoder result."""
    command = list(command)
    options = {"env": env} if env is not None else {}
    if progress_callback:
        command[-1:-1] = ["-progress", "pipe:1", "-nostats"]
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **options)
        for line in proc.stdout:
            sec = parse_out_time_sec(line.strip())
            if sec >= 0 and total_duration > 0:
                progress_callback(min(99.0, (sec / total_duration) * 100.0), sec)
        _, errors = proc.communicate()
        return proc.returncode == 0, errors
    result = subprocess.run(command, capture_output=True, text=True, **options)
    return result.returncode == 0, result.stderr


def render_single_pass_video(
    image_path: Path,
    narr_path: Path,
    bgm_path: Path | None,
    subtitle_path: Path | None,
    output_path: Path,
    narr_vol: float = 2.0,
    bgm_vol: float = 0.15,
    width: int = 1920,
    height: int = 1080,
    fps: int = 15,
    progress_callback=None,
    total_duration: float = 0.0,
    background_is_video: bool = False,
) -> bool:
    """Execute stable single-pass GPU video render with error capture."""
    cmd = build_single_pass_command(
        image_path, narr_path, bgm_path, subtitle_path, output_path,
        narr_vol, bgm_vol, width, height, fps, duration=total_duration,
        background_is_video=background_is_video,
    )
    def execute(command):
        return execute_ffmpeg(command, progress_callback, total_duration)

    ok, errors = execute(cmd)
    unavailable = ("cannot load libcuda", "no nvenc capable devices", "unsupported device",
                   "openencodesessionex failed", "unknown encoder 'h264_nvenc'")
    if not ok and any(message in errors.lower() for message in unavailable):
        # Keep resolution, frame rate, filters, audio and output timing intact.
        # CRF 18 provides a high-quality CPU path on PCs without NVIDIA hardware.
        cmd = list(cmd)
        index = cmd.index("-c:v")
        cmd[index:index + 8] = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]
        print("[render] NVIDIA encoding unavailable; using CPU H.264 at CRF 18.", flush=True)
        ok, errors = execute(cmd)
    if not ok and errors:
        print(f"[FFmpeg error]: {errors[-500:]}")
    return ok
