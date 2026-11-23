"""FFmpeg vertical adaptation, transition normalization and audio/subtitle assembly for Shorts."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .. import config
from .models import Storyboard, assert_shorts_scope
from .validator import validate_clip


def log(message: str) -> None:
    print(f"[shorts-assembler] {message}", flush=True)


def _run_ffmpeg(command: list[str]) -> tuple[bool, str]:
    from src.engine.video_composer import execute_ffmpeg

    ok, errors = execute_ffmpeg(command)
    unavailable = (
        "cannot load libcuda",
        "no nvenc capable devices",
        "unsupported device",
        "openencodesessionex failed",
        "unknown encoder 'h264_nvenc'",
    )
    if not ok and any(message in errors.lower() for message in unavailable):
        cmd = list(command)
        if "-c:v" in cmd and "h264_nvenc" in cmd:
            idx = cmd.index("-c:v")
            # Replace ["-c:v", "h264_nvenc", "-preset", ...] up to next flag before "-pix_fmt" or output.
            end_idx = idx + 2
            while end_idx < len(cmd) and cmd[end_idx] not in ("-pix_fmt", "-an", "-c:a", "-movflags", "-t"):
                end_idx += 1
            cmd[idx:end_idx] = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]
            ok, errors = execute_ffmpeg(cmd)
    return ok, errors


def _escape_subtitles_path(subtitle_path: Path) -> str:
    return (
        str(subtitle_path.resolve())
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "'\\\\''")
    )


def adapt_clip_to_vertical(
    input_clip: Path,
    output_clip: Path,
    target_duration: float,
    *,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    fit_mode: str = "crop",
    fade_sec: float = 0.25,
) -> Path:
    """Normalize any generated clip into a silent 1080x1920 30fps H.264 Shorts segment."""
    assert_shorts_scope("shorts", width=width, height=height, visual_mode="ai-video")
    validation = validate_clip(input_clip, min_duration=0.4)
    if not validation.valid:
        raise RuntimeError(f"cannot adapt invalid clip {input_clip.name}: {validation.reason}")

    target = max(1.0, float(target_duration))
    clip_dur = max(0.4, validation.duration_sec)
    output_clip.parent.mkdir(parents=True, exist_ok=True)

    if fit_mode == "pad":
        scale_filter = (
            f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )
    else:
        scale_filter = (
            f"scale=w={width}:h={height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1"
        )

    filters = [scale_filter, f"fps={fps}", "format=yuv420p"]
    input_args: list[str] = []

    if clip_dur >= target:
        pass
    elif target <= clip_dur * 1.45:
        factor = target / clip_dur
        filters.append(f"setpts={factor:.6f}*PTS")
    elif target <= clip_dur * 2.05:
        filters.append("split[fwd][rev_in];[rev_in]reverse[rev];[fwd][rev]concat=n=2:v=1:a=0")
    else:
        input_args = ["-stream_loop", "-1"]

    if fade_sec > 0 and target > (fade_sec * 2.0 + 0.5):
        out_start = max(0.2, target - fade_sec)
        filters.append(f"fade=t=in:st=0:d={fade_sec:.2f},fade=t=out:st={out_start:.2f}:d={fade_sec:.2f}")

    vf = ",".join(filters)
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *input_args,
        "-i",
        str(input_clip),
        "-vf",
        vf,
        "-an",
        "-t",
        f"{target:.3f}",
        "-c:v",
        "h264_nvenc",
        "-preset",
        "p3",
        "-rc",
        "constqp",
        "-qp",
        "24",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        "-g",
        str(fps * 2),
        str(output_clip),
    ]
    ok, errors = _run_ffmpeg(cmd)
    if not ok:
        raise RuntimeError(f"clip adaptation failed for {input_clip.name}: {errors[-400:]}")
    return output_clip


def render_static_fallback_clip(
    image_path: Path,
    output_clip: Path,
    target_duration: float,
    *,
    scene_index: int = 1,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    fade_sec: float = 0.25,
) -> Path:
    """Render a smooth vertical motion clip from a still fallback image."""
    assert_shorts_scope("shorts", width=width, height=height, visual_mode="ai-video")
    if not image_path.is_file():
        raise FileNotFoundError(f"fallback image is missing: {image_path}")

    target = max(1.0, float(target_duration))
    total_frames = max(1, int(round(target * fps)))
    output_clip.parent.mkdir(parents=True, exist_ok=True)

    # Alternate zoom-in / zoom-out softly between fallback scenes.
    if scene_index % 2 == 1:
        zoom_expr = "min(zoom+0.0007,1.08)"
    else:
        zoom_expr = "if(lte(zoom,1.0),1.08,max(1.0,zoom-0.0007))"

    filters = [
        f"scale=w={width}:h={height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
        f"zoompan=z='{zoom_expr}':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}",
        "setsar=1",
        "format=yuv420p",
    ]
    if fade_sec > 0 and target > (fade_sec * 2.0 + 0.5):
        out_start = max(0.2, target - fade_sec)
        filters.append(f"fade=t=in:st=0:d={fade_sec:.2f},fade=t=out:st={out_start:.2f}:d={fade_sec:.2f}")

    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(image_path),
        "-vf",
        ",".join(filters),
        "-an",
        "-t",
        f"{target:.3f}",
        "-c:v",
        "h264_nvenc",
        "-preset",
        "p3",
        "-rc",
        "constqp",
        "-qp",
        "24",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        str(output_clip),
    ]
    ok, errors = _run_ffmpeg(cmd)
    if not ok:
        raise RuntimeError(f"fallback clip render failed: {errors[-400:]}")
    return output_clip


def _resolve_fallback_source(run_dir: Path) -> tuple[Path, bool]:
    thumb = run_dir / "thumbnail.png"
    if thumb.is_file():
        return thumb, False
    from src.engine.standard_backgrounds import resolve_standard_background

    candidate = config.ROOT / "assets" / "backgrounds" / f"{config.THUMBNAIL_THEME}.jpg"
    resolved, is_video = resolve_standard_background(
        candidate, config.THUMBNAIL_THEME, portrait=True
    )
    if not resolved.is_file():
        raise FileNotFoundError(
            "No fallback image or background video exists in the Short run directory."
        )
    return resolved, is_video


def _scene_durations_for_total(storyboard: Storyboard, total_duration: float) -> list[float]:
    if not storyboard.scenes:
        return []
    raw = [max(1.0, float(scene.duration_sec)) for scene in storyboard.scenes]
    current_sum = sum(raw)
    if current_sum <= 0:
        per = total_duration / len(raw)
        return [round(per, 3)] * len(raw)
    scaled = [round(max(1.0, d * (total_duration / current_sum)), 3) for d in raw]
    diff = round(total_duration - sum(scaled), 3)
    scaled[-1] = round(max(1.0, scaled[-1] + diff), 3)
    return scaled


def assemble_short_video(
    run_dir: Path,
    storyboard: Storyboard,
    *,
    narration_path: Path | None = None,
    subtitle_path: Path | None = None,
    narr_vol: float = 2.0,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> Path:
    """Assemble validated clips and any static fallbacks with untouched narration & subtitles."""
    assert_shorts_scope("shorts", width=width, height=height, visual_mode="ai-video")
    from src.engine.audio_mixer import get_audio_duration

    narration = narration_path or (run_dir / "narration.aac")
    if not narration.is_file():
        raise FileNotFoundError(f"Short narration audio is missing: {narration}")
    total_duration = get_audio_duration(narration)
    if total_duration <= 0:
        raise RuntimeError("Short narration duration is unknown")

    durations = _scene_durations_for_total(storyboard, total_duration)
    if not durations:
        raise RuntimeError("Storyboard has no scenes to assemble")

    work_dir = run_dir / ".shorts-asm-tmp"
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    final_output = run_dir / "video.mp4"
    temp_output = run_dir / "video.ai.tmp.mp4"
    temp_output.unlink(missing_ok=True)

    try:
        normalized_paths: list[Path] = []
        fallback_source: tuple[Path, bool] | None = None
        for idx, (scene, target_dur) in enumerate(zip(storyboard.scenes, durations)):
            norm_path = work_dir / f"norm_{idx + 1:02d}.mp4"
            clip_candidate = Path(scene.output_path) if scene.output_path else None
            if (
                scene.status == "validated"
                and clip_candidate is not None
                and validate_clip(clip_candidate, min_duration=0.4).valid
            ):
                adapt_clip_to_vertical(
                    clip_candidate,
                    norm_path,
                    target_dur,
                    width=width,
                    height=height,
                    fps=fps,
                )
            else:
                if fallback_source is None:
                    fallback_source = _resolve_fallback_source(run_dir)
                src_path, src_is_video = fallback_source
                if src_is_video:
                    adapt_clip_to_vertical(
                        src_path,
                        norm_path,
                        target_dur,
                        width=width,
                        height=height,
                        fps=fps,
                    )
                else:
                    render_static_fallback_clip(
                        src_path,
                        norm_path,
                        target_dur,
                        scene_index=scene.scene_index,
                        width=width,
                        height=height,
                        fps=fps,
                    )
            normalized_paths.append(norm_path)

        concat_txt = work_dir / "concat.txt"
        concat_txt.write_text(
            "".join(f"file '{path.resolve()}'\n" for path in normalized_paths),
            encoding="utf-8",
        )

        cmd = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_txt),
            "-i",
            str(narration),
        ]
        if subtitle_path is not None and subtitle_path.is_file():
            escaped_ass = _escape_subtitles_path(subtitle_path)
            cmd.extend(["-vf", f"subtitles=filename='{escaped_ass}'"])
        cmd.extend([
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-af",
            f"volume={narr_vol:.2f}",
            "-t",
            f"{total_duration:.3f}",
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p3",
            "-rc",
            "constqp",
            "-qp",
            "24",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(temp_output),
        ])
        ok, errors = _run_ffmpeg(cmd)
        if not ok:
            raise RuntimeError(f"Short AI assembly failed: {errors[-500:]}")

        final_check = validate_clip(
            temp_output,
            require_portrait=True,
            min_duration=max(1.0, total_duration * 0.85),
        )
        if not final_check.valid:
            raise RuntimeError(f"Assembled Short failed validation: {final_check.reason}")

        os.replace(temp_output, final_output)
        final_output.chmod(0o600)
        log(f"assembled vertical AI Short: {final_output} ({final_check.duration_sec:.2f}s)")
        return final_output
    finally:
        temp_output.unlink(missing_ok=True)
        shutil.rmtree(work_dir, ignore_errors=True)
