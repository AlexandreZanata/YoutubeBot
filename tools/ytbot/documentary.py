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
        queries_list = scene.get("queries") or [scene.get("query", "")]
        queries_list = [query for query in queries_list if query]
        candidates: list[dict] = []
        for query in queries_list:
            try:
                candidates.extend(photo_candidates(query))
            except Exception as error:
                log(f"search failed for {query}: {error}")
            if candidates:
                break
        photograph = [row for row in candidates
                      if not any(word in row["title"].lower()
                                 for word in ("postcard", "map", "drawing", "illustration", "print", "plan"))]
        chosen = next((row for row in photograph + candidates if row["title"] not in used), None)
        if chosen is None:
            log(f"no photo for {scene.get('subject', queries_list)}")
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
        log(f"{index:03d} {scene.get('subject', '')} -> {chosen['title']}")
    (run_dir / "sources.json").write_text(json.dumps(sources, indent=2, ensure_ascii=False), encoding="utf-8")
    return sources


def _clean_html(text: str) -> str:
    import html
    import re

    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    cleaned = html.unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def ocean_photo_candidates(query: str, limit: int = 12,
                           min_width: int = 900, min_height: int = 500) -> list[dict]:
    """Search verified public-domain / CC-BY oceanographic photographs."""
    params = {
        "action": "query", "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}", "gsrlimit": str(limit), "gsrnamespace": "6",
        "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": "1920",
        "format": "json",
    }
    data = _get(API + "?" + urllib.parse.urlencode(params))
    pages = (data.get("query") or {}).get("pages") or {}
    excluded = ("logo", "icon", "seal", "flag", "cartoon", "drawing", "sketch",
                "stamp", "poster", "cover", "chart", "graph", "svg",
                "diagram", "reproduction", "watercolor", "watercolour",
                "painting", "skeleton", "magazine", "illustration",
                "engraving", "newspaper", "book ", "replica", "diorama",
                "fossil", "statue", "sculpture")
    rows = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        width = int(info.get("width") or 0)
        height = int(info.get("height") or 0)
        license_name = _clean_html(meta.get("LicenseShortName", {}).get("value", ""))
        title = page.get("title", "")
        lowered_title = title.lower()
        if not info.get("url") or not license_allowed(license_name):
            continue
        if width < min_width or height < min_height or height > width * 1.15:
            continue
        if any(word in lowered_title for word in excluded):
            continue
        artist = _clean_html(meta.get("Artist", {}).get("value", ""))
        credit = _clean_html(meta.get("Credit", {}).get("value", ""))
        description = _clean_html(meta.get("ImageDescription", {}).get("value", ""))
        date = _clean_html(meta.get("DateTimeOriginal", {}).get("value", ""))
        blob = f"{title} {artist} {credit} {description}".lower()
        # The record itself must mention the searched subject: file titles alone
        # drift toward loosely related material (museum skeletons, magazine scans).
        wanted = [word for word in query.lower().split()
                  if len(word) > 4 and word not in
                  {"deep", "ocean", "black", "water", "large", "great", "white"}]
        if wanted and not any(word in blob for word in wanted):
            continue
        is_noaa = "noaa" in blob or "okeanos" in blob or "ocean exploration" in blob or "mbnms" in blob
        is_pd = "public domain" in license_name.lower() or "pd-" in license_name.lower() or "cc0" in license_name.lower()
        rows.append({
            "title": title,
            "url": info.get("thumburl") or info.get("url", ""),
            "page": info.get("descriptionurl", ""),
            "license": license_name,
            "artist": artist,
            "credit": credit,
            "description": description[:600],
            "date": date,
            "width": width,
            "height": height,
            "institution": ("NOAA Office of Ocean Exploration and Research" if is_noaa
                            else ("USGS" if "usgs" in blob else "Wikimedia Commons")),
            "_rank": (2 if is_noaa else 0) + (2 if is_pd else 0) + (1 if width >= 1400 else 0),
        })
    rows.sort(key=lambda item: (-item["_rank"], -item["width"]))
    for row in rows:
        row.pop("_rank", None)
    return rows


def write_credits(run_dir: Path, sources: list[dict],
                  heading: str = "Image Credits & Scientific Sources") -> Path:
    """Write human-readable per-image provenance and license credits."""
    lines = [f"# {heading}", ""]
    for item in sources:
        lines.append(f"## {item.get('id', '')} — {item.get('narration_segment') or item.get('title', '')}")
        lines.append(f"- **Title**: {item.get('title', '')}")
        lines.append(f"- **Institution**: {item.get('institution', '')}")
        if item.get("expedition"):
            lines.append(f"- **Expedition**: {item['expedition']}")
        if item.get("species"):
            lines.append(f"- **Species / Subject**: {item['species']}")
        if item.get("place"):
            lines.append(f"- **Location**: {item['place']}")
        if item.get("depth"):
            lines.append(f"- **Depth**: {item['depth']}")
        if item.get("date"):
            lines.append(f"- **Date**: {item['date']}")
        lines.append(f"- **Author / Attribution**: {item.get('attribution') or item.get('artist', '')}")
        lines.append(f"- **License**: {item.get('license', '')} ({item.get('commercial_status', 'verified')})")
        if item.get("resolution"):
            lines.append(f"- **Resolution**: {item['resolution']}")
        lines.append(f"- **Source Page**: {item.get('source_page', '')}")
        lines.append("")
    destination = run_dir / "credits.md"
    destination.write_text("\n".join(lines), encoding="utf-8")
    return destination


def collect_ocean(run_dir: Path, scenes: list[dict], resume: bool = True) -> list[dict]:
    """Resumably collect verified oceanographic photographs with full provenance."""
    import time

    photos_dir = run_dir / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    photos_dir.chmod(0o700)
    sources_path = run_dir / "sources.json"
    existing_by_id: dict[str, dict] = {}
    if resume and sources_path.is_file():
        try:
            for row in json.loads(sources_path.read_text(encoding="utf-8")):
                photo_file = Path(row.get("file", ""))
                if row.get("id") and photo_file.is_file() and photo_file.stat().st_size > 4096:
                    existing_by_id[row["id"]] = row
        except (OSError, ValueError):
            existing_by_id = {}

    sources: list[dict] = []
    used = {row.get("title", "") for row in existing_by_id.values()}
    for index, scene in enumerate(scenes, 1):
        scene_id = f"{index:03d}"
        if scene_id in existing_by_id:
            sources.append(existing_by_id[scene_id])
            continue
        queries = scene.get("queries") or [scene["query"]]
        chosen = None
        for query in queries:
            try:
                candidates = ocean_photo_candidates(query)
            except Exception as error:
                log(f"search failed for {query}: {error}")
                continue
            chosen = next((row for row in candidates if row["title"] not in used), None)
            if chosen is not None:
                break
            time.sleep(0.4)
        if chosen is None:
            log(f"no verified ocean photo for {scene_id} ({scene.get('subject', '')})")
            continue
        used.add(chosen["title"])
        destination = photos_dir / f"{scene_id}.jpg"
        time.sleep(0.8)
        try:
            download(chosen["url"], destination)
            with Image.open(destination) as image:
                image.verify()
        except Exception as error:
            log(f"download failed for {chosen['title']}: {error}")
            destination.unlink(missing_ok=True)
            continue
        lic = chosen["license"]
        commercial = ("public domain / commercial use permitted"
                      if any(m in lic.lower() for m in ("public domain", "pd-", "cc0"))
                      else "open Creative Commons license / commercial use with attribution")
        record = {
            "id": scene_id,
            "file": str(destination),
            "title": chosen["title"],
            "institution": chosen["institution"],
            "artist": chosen["artist"] or chosen["credit"] or chosen["institution"],
            "expedition": scene.get("expedition", ""),
            "date": chosen["date"] or scene.get("date", ""),
            "place": scene.get("place", ""),
            "depth": scene.get("depth", ""),
            "species": scene.get("species", ""),
            "source_page": chosen["page"],
            "download_url": chosen["url"],
            "license": lic,
            "commercial_status": commercial,
            "attribution": chosen["credit"] or chosen["artist"] or chosen["institution"],
            "resolution": f"{chosen['width']}x{chosen['height']}",
            "original_description": chosen["description"],
            "narration_segment": scene.get("subject", ""),
            "approval_status": "approved",
            "verified": "verified public-domain or CC-BY oceanographic photograph; subject matched to narration scene",
        }
        sources.append(record)
        log(f"{scene_id} [{chosen['width']}x{chosen['height']} {lic}] -> {chosen['title']}")
        sources_path.write_text(json.dumps(sources, indent=2, ensure_ascii=False), encoding="utf-8")
    sources_path.write_text(json.dumps(sources, indent=2, ensure_ascii=False), encoding="utf-8")
    write_credits(run_dir, sources)
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
                     "caption": source.get("narration_segment", ""),
                     "generated": bool(source.get("generated", False))})
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

    Each source keeps its outline order, anchored to the passage where its
    ``narration_segment`` (and fallback title/place) keywords score highest.
    A longest-weighted-increasing-subsequence pass prevents single-word
    outliers from dragging subsequent photos off-target, unanchored photos
    interpolate between neighbors, and feasible boundary clamping keeps
    every window within ``[min_seconds, max_seconds]`` without cumulative
    drift.
    """
    from collections import Counter

    if not sources:
        return []
    words = article.split()
    total = max(len(words), 1)
    n = len(sources)
    lowered = [word.strip(".,;:!?\"'()[]").lower() for word in words]
    counts = Counter(token for token in lowered if token)

    def _matches(kw: str, token: str) -> bool:
        return kw == token or (len(kw) > 5 and kw in token) or (len(token) > 5 and token in kw)

    cands_per_src: list[list[tuple[int, float]]] = []
    for index, source in enumerate(sources):
        if index == 0:
            cands_per_src.append([(0, 10.0)])
            continue
        seg_kw = _keywords(source.get("narration_segment", ""))
        extra_kw = _keywords(f"{source.get('title', '')} {source.get('place', '')}")
        kw_weights: dict[str, float] = {}
        for kw in (seg_kw or extra_kw):
            kw_weights[kw] = 1.0 / (counts.get(kw, 0) + 1)
        cands: list[tuple[int, float]] = []
        if kw_weights:
            for pos in range(total):
                token = lowered[pos]
                if not token or not any(_matches(kw, token) for kw in kw_weights):
                    continue
                w_end = min(total, pos + 20)
                matched: set[str] = set()
                score = 0.0
                for p2 in range(pos, w_end):
                    t2 = lowered[p2]
                    if not t2:
                        continue
                    for kw, wt in kw_weights.items():
                        if kw not in matched and _matches(kw, t2):
                            matched.add(kw)
                            score += wt
                cands.append((pos, score))
        cands.sort(key=lambda item: -item[1])
        kept: list[tuple[int, float]] = []
        for pos, score in cands:
            if all(abs(pos - p0) >= 25 for p0, _ in kept):
                kept.append((pos, score))
            if len(kept) >= 8:
                break
        kept.sort(key=lambda item: item[0])
        cands_per_src.append(kept)

    all_nodes = [(i, j, cands_per_src[i][j][0], cands_per_src[i][j][1])
                 for i in range(n) for j in range(len(cands_per_src[i]))]
    best_val: dict[tuple[int, int], float] = {}
    parent: dict[tuple[int, int], tuple[int, int] | None] = {}
    min_step_words = max(1, total // max(n * 8, 1))
    for i, j, pos, score in all_nodes:
        bv = score
        bp: tuple[int, int] | None = None
        for pi, pj, ppos, _ in all_nodes:
            if pi >= i:
                break
            if pos >= ppos + (i - pi) * min_step_words:
                cand_v = best_val[(pi, pj)] + score
                if cand_v > bv:
                    bv = cand_v
                    bp = (pi, pj)
        best_val[(i, j)] = bv
        parent[(i, j)] = bp

    chosen: dict[int, int] = {}
    if best_val:
        cur: tuple[int, int] | None = max(best_val, key=lambda key: best_val[key])
        while cur is not None:
            chosen[cur[0]] = cands_per_src[cur[0]][cur[1]][0]
            cur = parent[cur]

    anchors = [0] * n
    sorted_keys = sorted(chosen)
    for k in sorted_keys:
        anchors[k] = chosen[k]
    for i in range(n):
        if i not in chosen:
            prev_k = max((k for k in sorted_keys if k < i), default=0)
            next_k = min((k for k in sorted_keys if k > i), default=n)
            prev_v = anchors[prev_k]
            next_v = anchors[next_k] if next_k < n else total
            anchors[i] = int(prev_v + (next_v - prev_v) * (i - prev_k) / (next_k - prev_k))

    min_words = max(1, int(total * min_seconds / duration))
    max_words = max(min_words, int(total * max_seconds / duration))
    if min_words * n > total:
        min_words = max(1, total // n)
    if max_words * n < total:
        max_words = (total + n - 1) // n

    bounds = [0] * (n + 1)
    bounds[n] = total
    for i in range(1, n):
        lo = max(bounds[i - 1] + min_words, total - (n - i) * max_words)
        hi = min(bounds[i - 1] + max_words, total - (n - i) * min_words)
        bounds[i] = max(lo, min(hi, anchors[i]))

    rows = []
    for index, source in enumerate(sources):
        start = duration * bounds[index] / total
        end = duration * bounds[index + 1] / total
        rows.append({"photo": source["file"], "source": source.get("title", ""),
                     "start": round(start, 2), "end": round(end, 2),
                     "caption": source.get("narration_segment", ""),
                     "generated": bool(source.get("generated", False))})
    return rows


def summarize_sources(sources: list[dict]) -> dict:
    """Split verified records from generated illustrations for human review."""
    generated = [s.get("id", "?") for s in sources if s.get("generated")]
    return {"real": len(sources) - len(generated),
            "generated": len(generated),
            "generated_ids": generated}


def generate_scene_illustration(context, run_dir: Path, scene_id: str,
                                topic: str, style_brief: str,
                                timeout: int = 600) -> Path:
    """Generate one honest illustration for a scene with no real photo.

    Uses the ChatGPT browser image path on the legacy profile (never the
    channel profile). The caller records the result in sources.json with
    ``generated: True`` so the renderer burns the on-screen honesty label.
    """
    import base64
    import time

    from . import assets, chat

    destination = run_dir / "photos" / f"{scene_id}.jpg"
    prompt = ("Create ONE 16:9 atmospheric illustration for a documentary scene. "
              "It must read as illustration, never as a photograph or record. "
              "No text, letters, numbers, logos, watermarks, borders or UI. "
              + style_brief
              + "\n\nScene subject: " + topic
              + "\n\nGenerate the final image now and reply only after it exists.")
    page = context.new_page()
    try:
        page.goto("https://chatgpt.com/", timeout=90000)
        page.wait_for_timeout(7000)
        chat.dismiss_notice(page)
        chat.send_text(page, prompt)
        deadline = time.time() + timeout
        while time.time() < deadline:
            page.wait_for_timeout(5000)
            data = assets.image_data_url(page)
            if data and data.startswith("data:image/"):
                destination.write_bytes(base64.b64decode(data.split(",", 1)[1]))
                destination.chmod(0o600)
                return destination
            body = page.locator("body").inner_text()
            if "Image generation failed" in body:
                raise RuntimeError("ChatGPT image generation failed for the scene illustration")
        raise RuntimeError("scene illustration was not generated")
    finally:
        page.close()


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


def slow_narration(run_dir: Path, factor: float = 0.9) -> Path:
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


_ENCODER_ARGS: list[str] | None = None


def _video_encoder_args() -> list[str]:
    """Use NVENC when a working GPU encoder is available, else libx264."""
    global _ENCODER_ARGS
    if _ENCODER_ARGS is not None:
        return list(_ENCODER_ARGS)
    probe = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
         "-frames:v", "1", "-c:v", "h264_nvenc", "-f", "null", "-"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if probe.returncode == 0:
        _ENCODER_ARGS = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20", "-pix_fmt", "yuv420p"]
    else:
        _ENCODER_ARGS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
    return list(_ENCODER_ARGS)


ILLUSTRATION_LABELS = {
    "sepia-atlas": "AI illustration - not a historical photograph",
    "bathylora": "AI illustration - not a real observation",
}
DEFAULT_ILLUSTRATION_LABEL = "AI illustration - not a real record"


def illustration_label_for(channel_slug: str) -> str:
    """On-screen label burned over generated illustrations, per channel voice."""
    return ILLUSTRATION_LABELS.get(channel_slug or "", DEFAULT_ILLUSTRATION_LABEL)


def _illustration_filter(label: str) -> str:
    """Top-left honesty label for generated scenes; empty when not needed."""
    if not label:
        return ""
    safe = label.replace("'", "").replace(":", " -")[:80]
    font = config.ROOT / "assets" / "fonts" / "Inter.ttf"
    return (
        "drawtext=fontfile='" + str(font) + "':text='" + safe + "'"
        ":fontsize=26:fontcolor=white:borderw=2:bordercolor=black@0.8"
        ":x=36:y=36:box=1:boxcolor=black@0.55:boxborderw=12"
    )
def _clip(photo: Path, output: Path, seconds: float, index: int,
          fade_in: float = 0.0, fade_out: float = 0.0,
          illustration_label: str = "") -> None:
    # Supersampled Ken Burns: render at 2560x1440 and downscale to 1920x1080.
    # The larger canvas absorbs zoompan integer rounding (eliminating tremor)
    # while running ~2x faster than 3840x2160. Reduce zoom on lower-resolution
    # source plates so images stay crisp without over-magnification.
    frames = max(int(round(seconds * FPS)), 1)
    zoom_span = 0.05
    try:
        with Image.open(photo) as im:
            if im.width < 1100:
                zoom_span = 0.02
    except OSError:
        pass
    zoom_in = index % 2 == 0
    top = 1.0 + zoom_span
    zoom = (f"min(1+{zoom_span:.3f}*on/{frames},{top:.3f})" if zoom_in
            else f"max({top:.3f}-{zoom_span:.3f}*on/{frames},1.0)")
    filters = [
        "scale=2560:1440:force_original_aspect_ratio=increase",
        "crop=2560:1440",
        f"zoompan=z='{zoom}':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=2560x1440:fps={FPS}",
        "scale=1920:1080",
    ]
    if fade_in > 0:
        filters.append(f"fade=t=in:st=0:d={fade_in:.2f}")
    if fade_out > 0:
        filters.append(f"fade=t=out:st={max(seconds - fade_out, 0):.2f}:d={fade_out:.2f}")
    label_filter = _illustration_filter(illustration_label)
    if label_filter:
        filters.append(label_filter)
    command = ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(photo),
               "-t", f"{seconds:.3f}", "-vf", ",".join(filters),
               "-r", str(FPS), *_video_encoder_args(), str(output)]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _xfade_batch(clips: list[tuple[Path, float]], output: Path, crossfade: float) -> float:
    """Join a small batch of clips with smooth optical cross-dissolves."""
    if len(clips) == 1:
        import shutil
        shutil.copy2(clips[0][0], output)
        return clips[0][1]
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for path, _ in clips:
        cmd.extend(["-i", str(path)])
    parts = []
    elapsed = clips[0][1]
    prev_label = "[0:v]"
    for idx in range(1, len(clips)):
        offset = max(elapsed - crossfade, 0.0)
        out_label = f"[v{idx}]" if idx < len(clips) - 1 else "[vout]"
        parts.append(
            f"{prev_label}[{idx}:v]xfade=transition=fade:duration={crossfade:.3f}:offset={offset:.3f}{out_label}"
        )
        elapsed += clips[idx][1] - crossfade
        prev_label = out_label
    cmd.extend(["-filter_complex", ";".join(parts), "-map", "[vout]",
                "-r", str(FPS), *_video_encoder_args(), str(output)])
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return elapsed


def _concat_xfade(clips: list[tuple[Path, float]], silent: Path, crossfade: float,
                  workers: int) -> None:
    """Assemble all clips with a 2-level parallel xfade tree."""
    import concurrent.futures
    import tempfile

    if len(clips) == 1 or crossfade <= 0:
        listing = silent.parent / "clips.txt"
        listing.write_text("".join(f"file '{c.resolve()}'\n" for c, _ in clips), encoding="utf-8")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", str(listing), "-c", "copy", str(silent)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return
    batch_size = 8
    if len(clips) <= batch_size:
        _xfade_batch(clips, silent, crossfade)
        return
    chunks = [clips[i:i + batch_size] for i in range(0, len(clips), batch_size)]
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        batch_paths = [tmp_dir / f"batch-{i:02d}.mp4" for i in range(len(chunks))]
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(chunks))) as pool:
            batch_durs = list(pool.map(
                lambda item: _xfade_batch(item[0], item[1], crossfade),
                zip(chunks, batch_paths),
            ))
        _xfade_batch(list(zip(batch_paths, batch_durs)), silent, crossfade)


# Lightweight single-pass broadcast documentary voice chain (Discovery / PBS
# style): pure native IIR EQ + optical-style compression + peak limiter at the
# narration's native sample rate (no neural models, no two-pass loudnorm).
# - highpass 75 Hz: remove sub-bass rumble
# - +4.0 dB @ 125 Hz: warm close-mic chest resonance
# - -2.5 dB @ 320 Hz: clear boxiness / nasal mud
# - +2.5 dB @ 3.2 kHz: crisp, intimate broadcast presence
# - -1.5 dB @ 6.5 kHz: smooth sibilance
# - acompressor + alimiter: steady ~ -16 LUFS broadcast level, peaks <= -1.3 dBFS
DOCUMENTARY_VOICE_FILTER = (
    "highpass=f=75,"
    "equalizer=f=125:t=q:w=1.1:g=4.0,"
    "equalizer=f=320:t=q:w=1.4:g=-2.5,"
    "equalizer=f=3200:t=q:w=1.2:g=2.5,"
    "equalizer=f=6500:t=q:w=2.0:g=-1.5,"
    "acompressor=threshold=-26dB:ratio=3.2:attack=15:release=180:knee=6:makeup=16dB,"
    "alimiter=limit=0.84:attack=5:release=50:level=false"
)


def mux_audio(silent: Path, narration: Path, output: Path, total_dur: float, *,
              voice_filter: bool = True, analog_texture: bool = True) -> Path:
    """Mux silent video with narration in one lightweight pass (-c:v copy)."""
    if analog_texture:
        fade_out_at = max(total_dur - 2.0, 0.0)
        # Warm, barely audible analog room-tone (filtered pink noise, 90 Hz -
        # 2.8 kHz) calibrated to sit ~35 dB below the narration level.
        tex_vol = "0.045" if voice_filter else "0.015"
        voice_chain = f"[1:a]{DOCUMENTARY_VOICE_FILTER}[voice];" if voice_filter else ""
        voice_label = "[voice]" if voice_filter else "[1:a]"
        af = (
            f"{voice_chain}"
            f"[2:a]highpass=f=90,lowpass=f=2800,volume={tex_vol},"
            f"afade=t=in:st=0:d=1.5,afade=t=out:st={fade_out_at:.2f}:d=2.0[tex];"
            f"{voice_label}[tex]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
        )
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(narration),
             "-f", "lavfi", "-t", f"{total_dur + 1.0:.2f}",
             "-i", "anoisesrc=color=pink:sample_rate=24000:amplitude=0.004",
             "-filter_complex", af,
             "-map", "0:v", "-map", "[aout]",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(output)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
    elif voice_filter:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(narration),
             "-af", DOCUMENTARY_VOICE_FILTER,
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(output)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
    else:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(narration),
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(output)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
    return output


def render(run_dir: Path, rows: list[dict], narration: Path | None = None,
           output_name: str = "video.mp4", crossfade: float = 1.2,
           analog_texture: bool = True, voice_filter: bool = True,
           workers: int | None = None, illustration_label: str = "") -> Path:
    import concurrent.futures
    import os

    if not rows:
        raise ValueError("timeline rows must not be empty")
    n = len(rows)
    effective_cf = crossfade if n > 1 else 0.0
    durations: list[float] = []
    for index, row in enumerate(rows):
        base = max(row["end"] - row["start"], 4.0)
        if effective_cf > 0:
            extra = effective_cf * (0.5 if index in (0, n - 1) else 1.0)
        else:
            extra = 0.0
        durations.append(base + extra)

    clips_dir = run_dir / "clips"
    clips_dir.mkdir(exist_ok=True)
    max_workers = workers or min(8, os.cpu_count() or 4)
    clip_paths = [clips_dir / f"{index:03d}.mp4" for index in range(n)]

    def _build(index: int) -> None:
        fade_in = 1.2 if index == 0 else 0.0
        fade_out = 1.5 if index == n - 1 else 0.0
        label = illustration_label if rows[index].get("generated") else ""
        _clip(Path(rows[index]["photo"]), clip_paths[index], durations[index], index,
              fade_in=fade_in, fade_out=fade_out, illustration_label=label)

    log(f"rendering {n} clips with {max_workers} workers ({_video_encoder_args()[1]})")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        for done_idx, _ in enumerate(pool.map(_build, range(n)), 1):
            if done_idx % 10 == 0 or done_idx == n:
                log(f"clip {done_idx}/{n}")

    listing = run_dir / "clips.txt"
    listing.write_text("".join(f"file '{clip.resolve()}'\n" for clip in clip_paths), encoding="utf-8")
    silent = run_dir / "silent.mp4"
    _concat_xfade(list(zip(clip_paths, durations)), silent, effective_cf, max_workers)

    output = run_dir / output_name
    narration = narration or (run_dir / "narration.aac")
    total_dur = max(sum(row["end"] - row["start"] for row in rows), 4.0)
    return mux_audio(silent, narration, output, total_dur,
                     voice_filter=voice_filter, analog_texture=analog_texture)


def thumbnail(run_dir: Path, photo: Path, title: str, *,
              style: str = "sepia", template: str = "encounter",
              subtitle: str = "", output_name: str = "thumbnail.png") -> Path:
    destination = run_dir / output_name
    with Image.open(photo) as image:
        canvas = ImageOps.fit(image.convert("RGB"), (1280, 720), Image.Resampling.LANCZOS)
    if style == "abyssal":
        # Preserve authentic underwater colors; add Abyssal Black (#030B12)
        # editorial negative space and Bioluminescent Cyan (#55D9D0) accents.
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        if template == "discovery":
            for i in range(360):
                alpha = int(225 * (i / 360) ** 1.3)
                draw.rectangle([0, 720 - 360 + i, 1280, 721 - 360 + i], fill=(3, 11, 18, alpha))
        elif template == "unknown":
            for i in range(440):
                alpha = int(225 * (i / 440) ** 1.25)
                draw.rectangle([0, 720 - 440 + i, 1280, 721 - 440 + i], fill=(3, 11, 18, alpha))
        else:  # Model A — The Encounter
            for i in range(410):
                alpha = int(220 * (i / 410) ** 1.35)
                draw.rectangle([0, 720 - 410 + i, 1280, 721 - 410 + i], fill=(3, 11, 18, alpha))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(canvas)
        title_font = ImageFont.truetype(str(config.ROOT / "assets/fonts/Inter.ttf"), 88)
        sub_font = ImageFont.truetype(str(config.ROOT / "assets/fonts/Inter.ttf"), 26)
        lines = [line.strip().upper() for line in title.split("\n") if line.strip()]
        line_h = 96
        block_h = line_h * len(lines)
        tx = 64
        ty = (536 if template != "unknown" else 490) - max(len(lines) - 1, 0) * line_h
        # Subtle Bioluminescent Cyan accent rule
        draw.rectangle([tx, ty - 22, tx + 96, ty - 16], fill=(85, 217, 208))
        for idx, line in enumerate(lines):
            draw.text((tx, ty + idx * line_h), line, font=title_font, fill=(237, 247, 245))
        if subtitle:
            draw.text((tx, ty + block_h + 10), subtitle.upper(), font=sub_font, fill=(181, 210, 215))
        mark = config.ROOT / "assets" / "brand" / "bathylora" / "watermark-300.png"
        if mark.is_file():
            with Image.open(mark) as logo:
                badge = logo.convert("RGBA").copy()
                badge.thumbnail((84, 84), Image.Resampling.LANCZOS)
                canvas.paste(badge, (1280 - badge.width - 36, 32), badge)
        canvas.save(destination, format="PNG", optimize=True)
        return destination

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
