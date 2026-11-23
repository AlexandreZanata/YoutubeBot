"""AI storyboard planning and channel-faithful scene prompt generation for Shorts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .. import channels
from ..accounts_store import write_private
from . import credits
from .models import SceneSpec, Storyboard, assert_channel_policy, assert_shorts_scope
from .settings import load_settings

CHANNEL_VISUAL_GUIDES: dict[str, dict[str, str]] = {
    "whispers-from-heaven": {
        "style": "Sacred Brown Engraving & reverent biblical atmosphere",
        "palette": "warm sepia, aged parchment brown, subtle candlelight gold",
        "lighting": "soft golden dawn or warm lantern glow, gentle atmospheric shafts",
        "camera": "slow reverent dolly or gentle upward tilt, calm restrained motion",
        "constraints": "historically respectful sacred imagery, no modern objects, no startling flashes",
    },
    "reflection": {
        "style": "Reverent cinematic biblical storytelling, ARRI Alexa 35 film look",
        "palette": "warm amber sunrise, muted teal shadows, natural earth tones",
        "lighting": "natural golden sunrise, soft volumetric sunbeams, tranquil sky",
        "camera": "steady contemplative tracking shot, subtle natural motion",
        "constraints": "historically respectful setting, no modern objects, calm upper third for subtitles",
    },
    "midnight-tales": {
        "style": "Painterly cinematic sleep-story realism",
        "palette": "deep midnight blue, soft slate, warm amber window glow",
        "lighting": "gentle moonlight and a single warm lantern source, soft haze",
        "camera": "ultra-slow soothing drift, calm hypnotic motion",
        "constraints": "soothing sleep environment, no sudden cuts, no horror or startling visuals",
    },
    "infinite-random-worlds": {
        "style": "Original speculative worldbuilding cinema",
        "palette": "cohesive atmospheric palette tailored to the imagined world",
        "lighting": "dramatic cosmic or bioluminescent natural horizon light",
        "camera": "smooth wide-to-medium exploratory camera glide",
        "constraints": "maintain consistent world physics, architecture and environment across every clip",
    },
    "fallem-prince": {
        "style": "Dark monochrome gothic engraving & symbolic philosophical cinema",
        "palette": "pure monochrome ink black, silver highlights, deep charcoal midtones",
        "lighting": "stark chiaroscuro contrast, moonlight rim light, deep shadows",
        "camera": "deliberate slow push-in or symbolic still-to-motion drift",
        "constraints": "symbolic philosophical imagery, no bright modern colors, no kitsch",
    },
    "vocal-pages": {
        "style": "Quiet contemplative literary realism",
        "palette": "muted warm neutrals, soft window daylight, natural wood and paper",
        "lighting": "diffused afternoon window light with soft dust motes",
        "camera": "intimate steady handheld or slow macro pan",
        "constraints": "subtle human objects and lived-in quiet spaces, restrained motion",
    },
    "zanata": {
        "style": "Minimalist philosophical and psychological editorial cinema",
        "palette": "warm editorial cream, deep slate shadows, subtle brass accents",
        "lighting": "clean directional architectural studio light, crisp shadows",
        "camera": "measured geometric dolly or steady architectural tilt",
        "constraints": "visual metaphor matching behavioral/philosophical ideas, no clutter",
    },
    "zaflas": {
        "style": "Brazilian agribusiness editorial realism (agricultura e pecuária no Brasil)",
        "palette": "natural cerrado and lavoura greens, rich red soil, golden hour sunlight",
        "lighting": "golden hour sunrise or late afternoon farm sun, realistic dust and mist",
        "camera": "smooth drone-like field glide or grounded close-up on crops, soil and cattle",
        "constraints": "authentic Brazilian farm equipment, soil, soybean/corn crops or cattle; no futuristic sci-fi",
    },
    "sepia-atlas": {
        "style": "Illustrative archival minimalism (clearly marked illustrative reconstruction only)",
        "palette": "aged gold, antique ivory, archival charcoal sepia",
        "lighting": "soft vintage natural daylight with subtle film grain",
        "camera": "restrained steady pan over evocative period scenery",
        "constraints": "never fabricate real historical photographic records; illustrative atmosphere only",
    },
    "bathylora": {
        "style": "Abyssal Cinema illustrative deep-ocean visualization",
        "palette": "abyssal black #030B12, deep ocean #071F2C, bioluminescent cyan #55D9D0, ocean mist #B5D2D7",
        "lighting": "subtle submersible beam and faint natural bioluminescence in dark water",
        "camera": "slow drifting underwater ROV-like glide",
        "constraints": "never fabricate real scientific specimen footage; illustrative deep-ocean ambiance only",
    },
}

_CAMERA_MOTIONS = (
    "slow steady push-in",
    "gentle vertical tilt upward",
    "smooth lateral parallax drift",
    "calm atmospheric glide forward",
    "subtle slow orbit around the focal subject",
    "measured pull-back revealing the environment",
)


def _split_sentences(text: str) -> list[str]:
    clean = re.sub(r"\s+", " ", (text or "")).strip()
    if not clean:
        return []
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", clean) if p.strip()]
    return parts or [clean]


def _expand_units_to_count(units: list[str], desired: int) -> list[str]:
    """Split long clauses/word spans when a script has fewer sentences than target clips."""
    expanded: list[str] = []
    for unit in units:
        if len(expanded) + (len(units) - units.index(unit)) < desired and ("," in unit or ";" in unit):
            sub = [p.strip() for p in re.split(r"(?<=[,;])\s+", unit) if p.strip()]
            expanded.extend(sub or [unit])
        else:
            expanded.append(unit)
    while len(expanded) < desired:
        longest_idx = max(range(len(expanded)), key=lambda i: len(expanded[i].split()))
        words = expanded[longest_idx].split()
        if len(words) < 4:
            break
        mid = len(words) // 2
        expanded[longest_idx:longest_idx + 1] = [" ".join(words[:mid]), " ".join(words[mid:])]
    return expanded


def _segment_script_with_timestamps(
    script_text: str,
    total_duration_sec: float,
    max_scenes: int,
    transcript_segments: list[dict[str, Any]] | None,
) -> list[tuple[float, float, str]]:
    desired = max(1, min(max_scenes, round(total_duration_sec / 7.5)))
    if total_duration_sec >= 25.0 and max_scenes >= 3:
        desired = max(desired, 3)

    if transcript_segments:
        target_dur = max(5.5, min(9.0, total_duration_sec / max(1, desired)))
        grouped: list[tuple[float, float, str]] = []
        cur_start = 0.0
        cur_end = 0.0
        buf: list[str] = []
        for seg in transcript_segments:
            txt = str(seg.get("text") or "").strip()
            if not txt:
                continue
            s_t = float(seg.get("start") or cur_end)
            e_t = max(s_t + 0.2, float(seg.get("end") or (s_t + 1.0)))
            if not buf:
                cur_start = s_t
            buf.append(txt)
            cur_end = e_t
            if (cur_end - cur_start) >= target_dur and len(grouped) < max_scenes - 1:
                grouped.append((round(cur_start, 2), round(cur_end, 2), " ".join(buf)))
                buf = []
                cur_start = cur_end
        if buf:
            grouped.append((round(cur_start, 2), round(max(cur_end, total_duration_sec), 2), " ".join(buf)))
        elif grouped:
            start, _, txt = grouped[-1]
            grouped[-1] = (start, round(total_duration_sec, 2), txt)
        if grouped and not (len(grouped) == 1 and desired > 1 and total_duration_sec >= 14.0):
            if grouped[0][0] > 0.0:
                _, end, txt = grouped[0]
                grouped[0] = (0.0, end, txt)
            return grouped[:max_scenes]

    sentences = _split_sentences(script_text) or ["Cinematic visual opening."]
    sentences = _expand_units_to_count(sentences, desired)
    desired = min(desired, len(sentences))

    chunks: list[str] = []
    if len(sentences) <= desired:
        chunks = sentences
    else:
        step = len(sentences) / desired
        for idx in range(desired):
            start_i = int(round(idx * step))
            end_i = int(round((idx + 1) * step))
            piece = " ".join(sentences[start_i:end_i]).strip()
            if piece:
                chunks.append(piece)

    weights = [max(1, len(chunk.split())) for chunk in chunks]
    total_weight = sum(weights)
    timeline: list[tuple[float, float, str]] = []
    cursor = 0.0
    for idx, (chunk, weight) in enumerate(zip(chunks, weights)):
        if idx == len(chunks) - 1:
            end = round(total_duration_sec, 2)
        else:
            end = round(cursor + total_duration_sec * (weight / total_weight), 2)
        timeline.append((round(cursor, 2), max(round(cursor + 1.0, 2), end), chunk))
        cursor = end
    return timeline


def _clean_excerpt_for_prompt(text: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    return clean[:220]


def plan_short_storyboard(
    channel_slug: str,
    topic: str,
    script_text: str,
    *,
    total_duration_sec: float = 45.0,
    transcript_segments: list[dict[str, Any]] | None = None,
    settings: dict[str, Any] | None = None,
) -> Storyboard:
    """Create a vertical 9:16 scene storyboard aligned to the Short narration."""
    assert_shorts_scope("shorts", width=1080, height=1920, visual_mode="ai-video")
    active = settings or load_settings()
    assert_channel_policy(channel_slug, active)
    channel = channels.get(channel_slug)

    provider = str(active.get("provider", "google-flow"))
    model = str(active.get("model", "veo-2-fast"))
    max_scenes = int(active.get("max_scenes_per_short", 6))
    duration = max(5.0, float(total_duration_sec))

    guide = CHANNEL_VISUAL_GUIDES.get(channel_slug, CHANNEL_VISUAL_GUIDES["vocal-pages"])
    visual_identity = f"{guide['style']}. Palette: {guide['palette']}. Lighting: {guide['lighting']}."
    continuity_anchor = (
        f"Cohesive visual world for '{topic}'. Maintain consistent {guide['palette']}, "
        f"{guide['lighting']}, and unbroken visual continuity across all clips."
    )

    segments = _segment_script_with_timestamps(
        script_text, duration, max_scenes, transcript_segments
    )
    per_scene_credits = credits.estimate_scene_cost(provider, model, active)

    scenes: list[SceneSpec] = []
    for idx, (start_sec, end_sec, section_text) in enumerate(segments, start=1):
        scene_dur = round(max(1.0, end_sec - start_sec), 2)
        excerpt = _clean_excerpt_for_prompt(section_text)
        motion = _CAMERA_MOTIONS[(idx - 1) % len(_CAMERA_MOTIONS)]
        visual_desc = (
            f"Scene {idx} illustrating: {excerpt}. {guide['style']} with {motion}."
        )
        lang_hint = (
            "Brazilian agricultural countryside setting (do not put any words on screen). "
            if channel.language == "pt-BR"
            else ""
        )
        prompt = (
            f"Vertical 9:16 cinematic video clip (1080x1920). Topic: {topic}. "
            f"Narrative moment: {excerpt}. {lang_hint}"
            f"Visual style: {guide['style']}. Color palette: {guide['palette']}. "
            f"Lighting: {guide['lighting']}. Camera movement: {motion} ({guide['camera']}). "
            f"Continuity: {continuity_anchor} "
            f"Framing: keep the focal subject in the middle and lower two thirds, leaving the upper third calmer for centered burned-in subtitles. "
            f"Rules: {guide['constraints']}; absolutely no text, no letters, no numbers, no logos, no watermarks."
        )
        scenes.append(
            SceneSpec(
                scene_id=f"scene_{idx:02d}",
                scene_index=idx,
                script_section=section_text,
                start_sec=start_sec,
                end_sec=end_sec,
                duration_sec=scene_dur,
                visual_description=visual_desc,
                generation_prompt=prompt,
                aspect_ratio="9:16",
                estimated_credits=per_scene_credits,
                provider=provider,
                model=model,
                status="pending",
            )
        )

    total_est = round(sum(scene.estimated_credits for scene in scenes), 2)
    return Storyboard(
        channel=channel_slug,
        topic=topic,
        language=channel.language,
        scope="shorts",
        visual_mode="ai-video",
        provider=provider,
        model=model,
        aspect_ratio="9:16",
        total_duration_sec=round(duration, 2),
        estimated_total_credits=total_est,
        actual_total_credits=0.0,
        visual_identity=visual_identity,
        continuity_anchor=continuity_anchor,
        synthetic_disclosure_required=bool(active.get("synthetic_disclosure", True)),
        scenes=scenes,
        status="planned",
    )


def format_flow_prompt_sheet(storyboard: Storyboard, run_dir: Path) -> str:
    """Format an actionable prompt guide for the Assisted Google Flow workflow."""
    lines = [
        f"# Google Flow Shorts Storyboard: {storyboard.topic}",
        "",
        f"- Channel: `{storyboard.channel}` (`{storyboard.language}`)",
        f"- Aspect Ratio: `{storyboard.aspect_ratio}` (1080x1920 Shorts only)",
        f"- Provider / Model: `{storyboard.provider}` / `{storyboard.model}`",
        f"- Total Narration Duration: `{storyboard.total_duration_sec:.2f}s`",
        f"- Estimated Credits: `{storyboard.estimated_total_credits:.1f}`",
        f"- Visual Identity: {storyboard.visual_identity}",
        "",
        "## Instructions for Google Flow (Assisted Workflow)",
        "",
        "1. Open Google Flow (`https://labs.google/fx/tools/flow`) in your logged-in Google AI Pro account.",
        "2. Set aspect ratio to **9:16 (Portrait)** and select your preferred Veo model.",
        "3. Generate each scene below and save the downloaded `.mp4` files inside:",
        f"   `{run_dir / 'clips'}` (named `scene_01.mp4`, `scene_02.mp4`, ...).",
        "4. Re-run the Short command or click Resume in the Desktop Studio to validate and assemble.",
        "",
    ]
    for scene in storyboard.scenes:
        lines.extend([
            f"### {scene.scene_id} ({scene.start_sec:.2f}s - {scene.end_sec:.2f}s, {scene.duration_sec:.2f}s)",
            "",
            f"**Script excerpt:** {scene.script_section}",
            "",
            f"**Save clip as:** `clips/{scene.scene_id}.mp4`",
            "",
            "**Prompt:**",
            "```text",
            scene.generation_prompt,
            "```",
            "",
        ])
    return "\n".join(lines)


def save_storyboard(run_dir: Path, storyboard: Storyboard) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    if not run_dir.is_symlink():
        run_dir.chmod(0o700)
    path = run_dir / "storyboard.json"
    write_private(path, storyboard.to_dict())
    prompt_sheet = run_dir / "flow-prompts.md"
    prompt_sheet.write_text(format_flow_prompt_sheet(storyboard, run_dir), encoding="utf-8")
    prompt_sheet.chmod(0o600)
    return path


def load_storyboard(run_dir: Path) -> Storyboard | None:
    path = run_dir / "storyboard.json"
    if not path.is_file() or path.is_symlink():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return Storyboard.from_dict(data)
