"""Build a documentary from authentic public-domain archival photographs."""

from __future__ import annotations

import json
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import config, logic

WIDTH, HEIGHT = 1920, 1080
FPS = 30
API = "https://commons.wikimedia.org/w/api.php"
ALLOWED = ("public domain", "cc0", "cc by", "cc-by", "pd-")


def log(message: str) -> None:
    print(f"[documentary] {message}", flush=True)


HEADERS = {"User-Agent": "SepiaAtlasDocumentary/1.0 (archival research; https://github.com/AlexandreZanata/YoutubeBot)"}


def _get(url: str) -> dict:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def license_allowed(value: str) -> bool:
    lowered = (value or "").lower()
    return any(marker in lowered for marker in ALLOWED)


def period_ok(title: str, date: str) -> bool:
    """Reject modern photographs; a title year must be from the period."""
    import re

    def years(text: str) -> list[int]:
        return [int(year) for year in re.findall(r"(?:18|19|20)\d{2}", text or "")]

    title_years = years(title)
    if title_years:
        return all(1880 <= year <= 1915 for year in title_years)
    date_years = years(date)
    return bool(date_years) and 1880 <= min(date_years) <= 1915


def photo_candidates(query: str, limit: int = 4) -> list[dict]:
    params = {
        "action": "query", "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}", "gsrlimit": str(limit), "gsrnamespace": "6",
        "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": "1920",
        "format": "json",
    }
    data = _get(API + "?" + urllib.parse.urlencode(params))
    pages = (data.get("query") or {}).get("pages") or {}
    rows = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        license_name = meta.get("LicenseShortName", {}).get("value", "")
        rows.append({
            "title": page.get("title", ""),
            "url": info.get("thumburl") or info.get("url", ""),
            "page": info.get("descriptionurl", ""),
            "license": license_name,
            "artist": meta.get("Artist", {}).get("value", ""),
            "date": meta.get("DateTimeOriginal", {}).get("value", ""),
        })
    return [row for row in rows
            if row["url"] and license_allowed(row["license"])
            and period_ok(row["title"], row["date"])]


def download(url: str, destination: Path, attempts: int = 3) -> None:
    import time

    for attempt in range(attempts):
        request = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                destination.write_bytes(response.read())
            destination.chmod(0o600)
            return
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(3 * (attempt + 1))


def collect(run_dir: Path, queries: list[dict]) -> list[dict]:
    """Download one public-domain photograph per scene description."""
    photos_dir = run_dir / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    photos_dir.chmod(0o700)
    sources = []
    used = set()
    for index, scene in enumerate(queries, 1):
        candidates = photo_candidates(scene["query"])
        photograph = [row for row in candidates
                      if not any(word in row["title"].lower()
                                 for word in ("postcard", "map", "drawing", "illustration", "print", "plan"))]
        chosen = next((row for row in photograph + candidates if row["title"] not in used), None)
        if chosen is None:
            log(f"no photo for {scene['query']}")
            continue
        used.add(chosen["title"])
        name = f"{index:03d}.jpg"
        destination = photos_dir / name
        import time
        time.sleep(1.0)
        try:
            download(chosen["url"], destination)
            with Image.open(destination) as image:
                image.verify()
        except Exception as error:
            log(f"download failed for {chosen['title']}: {error}")
            destination.unlink(missing_ok=True)
            continue
        record = {
            "id": f"{index:03d}",
            "file": str(destination),
            "title": chosen["title"],
            "institution": "Wikimedia Commons",
            "artist": chosen["artist"],
            "date": chosen["date"],
            "place": scene.get("place", ""),
            "source_page": chosen["page"],
            "download_url": chosen["url"],
            "license": chosen["license"],
            "attribution": chosen["artist"] or "Wikimedia Commons",
            "narration_segment": scene.get("subject", ""),
            "verified": "selected from the public-domain Commons record; subject matched by the scene query",
        }
        sources.append(record)
        log(f"{index:03d} {scene['query']} -> {chosen['title']}")
    (run_dir / "sources.json").write_text(json.dumps(sources, indent=2, ensure_ascii=False), encoding="utf-8")
    return sources


def timeline(article: str, duration: float, sources: list[dict]) -> list[dict]:
    """Split the narration by words and give each photograph a proportional slot."""
    words = article.split()
    total = max(len(words), 1)
    per_photo = total / max(len(sources), 1)
    rows = []
    for index, source in enumerate(sources):
        start_word = int(index * per_photo)
        end_word = int((index + 1) * per_photo) if index < len(sources) - 1 else total
        start = duration * start_word / total
        end = duration * end_word / total
        rows.append({"photo": source["file"], "source": source.get("title", ""),
                     "start": round(start, 2), "end": round(end, 2),
                     "caption": source.get("narration_segment", "")})
    return rows


STOPWORDS = {
    "with", "from", "that", "this", "these", "those", "have", "were", "been",
    "their", "there", "which", "when", "where", "what", "about", "into",
    "over", "under", "after", "before", "between", "through", "during",
    "street", "united", "states", "american", "america", "file", "circa",
    "city", "cities", "town", "towns", "people", "time", "life",
    "home", "house", "work", "workers", "day", "daily", "year", "years",
    "century", "early", "old", "small", "large", "big", "great", "men",
    "women", "children", "family", "families", "man", "woman", "child",
    "road", "roads", "place", "places", "group", "view", "general",
    "national", "historic", "historical", "york", "new",
}


def _keywords(text: str) -> list[str]:
    import re

    tokens = re.findall(r"[a-z]{4,}", (text or "").lower())
    seen: list[str] = []
    for token in tokens:
        if token in STOPWORDS or token in seen:
            continue
        seen.append(token)
    return seen[:12]


def timeline_aligned(article: str, duration: float, sources: list[dict],
                      min_seconds: float = 6.0, max_seconds: float = 60.0) -> list[dict]:
    """Place each photograph where its own subject is actually narrated.

    Each source keeps its outline order, but its window is anchored to the
    word position where its rarest keywords (subject + archival title +
    place) best match the narration. Every window lasts between
    ``min_seconds`` and ``max_seconds`` and windows partition the audio
    sequentially, so every photo covers the passage that talks about it
    without gaps or overlaps.
    """
    from collections import Counter

    words = article.split()
    total = max(len(words), 1)
    lowered = [word.strip(".,;:!?\"'()[]").lower() for word in words]
    counts = Counter(token for token in lowered if token)
    anchors: list[int] = []
    cursor = 0
    for index, source in enumerate(sources):
        keywords = _keywords(
            f"{source.get('narration_segment', '')} {source.get('title', '')} "
            f"{source.get('place', '')}")
        # Rarest first: distinctive subjects anchor precisely, generic ones
        # fall back to an even spread instead of piling onto one passage.
        keywords.sort(key=lambda keyword: (counts.get(keyword, 0), len(keyword)))
        keywords = keywords[:8]
        fallback = int(index * total / max(len(sources), 1))
        if not keywords:
            anchors.append(max(fallback, cursor))
            cursor = anchors[-1] + 1
            continue
        positions: list[int] = []
        for keyword in keywords:
            for pos in range(cursor, total):
                token = lowered[pos]
                if not token:
                    continue
                if (keyword == token
                        or (len(keyword) > 5 and keyword in token)
                        or (len(token) > 5 and token in keyword)):
                    positions.append(pos)
                    break
        if not positions:
            anchors.append(max(fallback, cursor))
        else:
            positions.sort()
            anchors.append(max(positions[len(positions) // 2], cursor))
        cursor = anchors[-1] + 1
    min_words = max(1, int(total * min_seconds / duration))
    max_words = max(min_words, int(total * max_seconds / duration))
    if min_words * len(sources) > total:
        min_words = max(1, total // len(sources))
        max_words = max(min_words, max_words)
    gaps = ([anchors[index + 1] - anchors[index] for index in range(len(anchors) - 1)]
            + [total - anchors[-1]])
    base = [max(gap, min_words) for gap in gaps]
    # Bounded proportional fit: f_i = clip(base_i * s, min_words, max_words)
    # with s bisected so the word spans add up to exactly `total`.
    low, high = 0.0, 1.0
    while sum(min(base_i * high, max_words) for base_i in base) < total:
        high *= 2.0
    for _ in range(80):
        mid = (low + high) / 2.0
        if sum(min(base_i * mid, max_words) for base_i in base) < total:
            low = mid
        else:
            high = mid
    spans = [0] * len(base)
    fractions: list[tuple[float, int]] = []
    for index, base_i in enumerate(base):
        exact = min(max(base_i * high, min_words), max_words)
        whole = int(exact)
        spans[index] = whole
        fractions.append((exact - whole, index))
    remainder = total - sum(spans)
    fractions.sort(key=lambda item: (-item[0], item[1]))
    for _, index in fractions:
        if remainder <= 0:
            break
        if spans[index] < max_words:
            spans[index] += 1
            remainder -= 1
    if remainder > 0:
        # Only when every window already hit the cap; keep the exact total.
        spans[-1] += remainder
    rows = []
    cursor_word = 0
    for index, source in enumerate(sources):
        start_word = cursor_word
        end_word = total if index == len(sources) - 1 else min(total, cursor_word + spans[index])
        if end_word <= start_word:
            end_word = min(total, start_word + 1)
        start = duration * start_word / total
        end = duration * end_word / total
        rows.append({"photo": source["file"], "source": source.get("title", ""),
                     "start": round(start, 2), "end": round(end, 2),
                     "caption": source.get("narration_segment", "")})
        cursor_word = end_word
    return rows


def exact_duration(path: Path) -> float:
    """True audio length in seconds, decoded rather than trusting the container.

    Captured AAC files can carry timestamp gaps that make the container
    duration wrong (seen: 1225 s reported for 1147 s of samples), so measure
    the decoded PCM instead.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        command = ["ffmpeg", "-y", "-v", "error", "-i", str(path),
                   "-c:a", "pcm_s16le", "-ar", "24000", tmp.name]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=duration",
             "-of", "default=nw=1:nk=1", tmp.name],
            capture_output=True, text=True, check=True)
    return float(probe.stdout.strip())


def slow_narration(run_dir: Path, factor: float = 0.8) -> Path:
    """Render a slower, calmer narration track without touching the original.

    The slowdown runs on decoded PCM so the result is exactly
    ``1 / factor`` times the true sample count, regardless of container
    timestamp gaps in the captured audio.
    """
    destination = run_dir / f"narration-{int(factor * 100):02d}x.aac"
    if destination.is_file():
        return destination
    import tempfile

    source = run_dir / "narration.aac"
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(source),
                        "-c:a", "pcm_s16le", "-ar", "24000", str(raw)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        slowed = Path(tmp) / "slowed.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw),
                        "-filter:a", f"atempo={factor}",
                        "-c:a", "pcm_s16le", "-ar", "24000", str(slowed)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=duration",
             "-of", "default=nw=1:nk=1", str(slowed)],
            capture_output=True, text=True, check=True)
        ratio = float(probe.stdout.strip()) / exact_duration(source)
        if abs(ratio - 1 / factor) > 0.02:
            raise RuntimeError(f"slowdown ratio {ratio:.3f} is not 1/{factor}")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(slowed),
                        "-c:a", "aac", "-b:a", "192k", str(destination)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    destination.chmod(0o600)
    return destination


def _clip(photo: Path, output: Path, seconds: float, index: int) -> None:
    # Supersampled Ken Burns: render the move at 3840x2160 and downscale to
    # 1920x1080. The larger canvas absorbs the integer rounding of zoompan,
    # which is what reads as a "tremor" at 1080p. The move itself stays slow:
    # 100% -> 105% over the whole clip, alternating in and out.
    frames = max(int(seconds * FPS), 1)
    zoom_in = index % 2 == 0
    zoom = f"min(1+0.05*on/{frames},1.05)" if zoom_in else f"max(1.05-0.05*on/{frames},1.0)"
    vf = (
        "scale=3840:2160:force_original_aspect_ratio=increase,"
        "crop=3840:2160,"
        f"zoompan=z='{zoom}':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":s=3840x2160:fps={FPS},"
        "scale=1920:1080,"
        f"fade=t=in:st=0:d=0.5,fade=t=out:st={max(seconds - 0.5, 0):.2f}:d=0.5"
    )
    command = ["ffmpeg", "-y", "-loop", "1", "-i", str(photo), "-t", f"{seconds:.2f}",
               "-vf", vf, "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "20", "-pix_fmt", "yuv420p", str(output)]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def render(run_dir: Path, rows: list[dict], narration: Path | None = None,
           output_name: str = "video.mp4") -> Path:
    clips = []
    clips_dir = run_dir / "clips"
    clips_dir.mkdir(exist_ok=True)
    for index, row in enumerate(rows):
        seconds = max(row["end"] - row["start"], 4.0)
        clip = clips_dir / f"{index:03d}.mp4"
        _clip(Path(row["photo"]), clip, seconds, index)
        clips.append(clip)
        if index % 10 == 0:
            log(f"clip {index + 1}/{len(rows)}")
    listing = run_dir / "clips.txt"
    listing.write_text("".join(f"file '{clip.resolve()}'\n" for clip in clips), encoding="utf-8")
    silent = run_dir / "silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c", "copy", str(silent)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    output = run_dir / output_name
    narration = narration or (run_dir / "narration.aac")
    subprocess.run(["ffmpeg", "-y", "-i", str(silent), "-i", str(narration),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(output)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return output


def thumbnail(run_dir: Path, photo: Path, title: str) -> Path:
    destination = run_dir / "thumbnail.png"
    with Image.open(photo) as image:
        canvas = ImageOps.fit(image.convert("RGB"), (1280, 720), Image.Resampling.LANCZOS)
    canvas = ImageOps.colorize(canvas.convert("L"), black="#14110E", white="#F1E7D4", mid="#76614A")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for i in range(430):
        alpha = int(190 * (1 - i / 430))
        draw.rectangle([0, 720 - 430 + i, 1280, 721 - 430 + i], fill=(20, 17, 14, alpha))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(config.ROOT / "assets/fonts/Playfair.ttf"), 92)
    draw.text((60, 470), title, font=font, fill=(241, 231, 212))
    mark = config.ROOT / "assets" / "brand" / "sepia_atlas" / "watermark-e.png"
    if mark.is_file():
        with Image.open(mark) as logo:
            badge = logo.copy()
            badge.thumbnail((86, 86), Image.Resampling.LANCZOS)
            canvas.paste(badge, (1280 - badge.width - 34, 30), badge)
    canvas.save(destination, format="PNG", optimize=True)
    return destination
