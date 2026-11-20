# Bathylora — Step-by-Step Documentary Production Pipeline (Agent Runbook)

Follow these steps **in exact order, without skipping any step and without inventing flags or scripts**.
This pipeline is deterministic, resumable, and enforces all Bathylora standards automatically
(`0.9x` narration speed, `DOCUMENTARY_VOICE_FILTER`, subtle analog room-tone, `1.2s` optical
cross-dissolves, parallel `h264_nvenc`, **Abyssal Cinema** thumbnails, and NOAA provenance).

---

## HARD RULES (NEVER VIOLATE)

1. **English only (American English)** in script, narration, subtitles, title, description, tags and thumbnail.
2. **NO fabricated science or AI creatures**: every image in the video and thumbnail MUST be a real, verified public-domain (`PD-USGov-NOAA`, `PD-USGov-USGS`, `CC0`) or commercial-compatible `CC BY` scientific photograph.
3. **Collect photos BEFORE writing `article.txt`**: never write a script about photos you do not have.
4. **Every photo must match what is being spoken**: write one focused paragraph per verified photo in the exact order of `sources.json`, explicitly naming the species, expedition, place, or depth shown.
5. **Target length**: `1,900` to `3,200` words (`15` to `25` minutes at `0.9x`), tolerance up to `5,100` words (`40` minutes). Never pad with filler.
6. **Pure spoken prose in `article.txt`**: NO `#` headings, NO bullet lists, NO numbered lists, NO URLs, NO stage directions, NO intro/outro meta-commentary.
7. **Always use the `documentary` CLI**: do NOT write custom `ffmpeg` commands or change speed, voice filter, noise, or cross-dissolve settings.
8. **Never reuse Sepia Atlas visuals**: Bathylora uses **Abyssal Cinema** (`#030B12`, `#071F2C`, `#55D9D0`, `#B5D2D7`, `#EDF7F5`, `#164958`) and **The Depth Mark**.
9. **Mandatory NOAA disclaimer** in every description:
   `Bathylora is an independent educational channel and is not affiliated with NOAA or other research institutions.`
10. **NEVER publish or schedule automatically**: stop after Step 7 (`qc`) and present the package to the owner for approval.

---

## STEP 0 — Choose the Episode Topic & Initialize the Folder

Pick the next unused topic from `docs/channels/bathylora.md` (or the owner's requested topic), check for duplicates, and initialize the run folder:

```bash
python3 -m tools.ytbot check --channel bathylora "The Strange World of the Bigfin Squid"
python3 -m tools.ytbot documentary init --channel bathylora --title "The Strange World of the Bigfin Squid"
```

This creates:
- `.local/ytbot/channels/bathylora/runs/<slug>/topic.txt`
- `.local/ytbot/channels/bathylora/runs/<slug>/scenes.json` (starter template)
- `.local/ytbot/channels/bathylora/runs/<slug>/metadata.json` (starter template with NOAA disclaimer)

Write down `<slug>` (for example: `the-strange-world-of-the-bigfin-squid`).

---

## STEP 1 — Fill `scenes.json` (30 to 50 Concrete Visual Scenes)

Edit `.local/ytbot/channels/bathylora/runs/<slug>/scenes.json` with a JSON array of **30 to 50 scenes** following the 5-act documentary arc:
1. Opening hook & expedition context (scenes 1–4: NOAA vessel / ROV / bathymetry / first real encounter)
2. Habitat & physical conditions (scenes 5–10: depth zone, pressure, darkness, currents)
3. Species & biological exploration (scenes 11–28: specific verified organisms, anatomy, behaviors)
4. Main scientific discovery & open questions (scenes 29–36: expeditions, measurements, what remains unknown)
5. Grounded contemplative closing (scenes 37–40: wider ecosystem / seafloor / ROV view)

**Exact JSON schema for each item in `scenes.json`**:

```json
[
  {
    "subject": "Bigfin squid Magnapinna with long elbowed arms in deep water",
    "species": "Magnapinna sp.",
    "expedition": "NOAA Ocean Exploration",
    "place": "Gulf of Mexico",
    "depth": "2,000-3,300 m",
    "queries": [
      "NOAA Magnapinna bigfin squid",
      "Magnapinna sp."
    ]
  }
]
```

Rules for queries:
- Always put `"NOAA ..."` first so the collector prioritizes `PD-USGov-NOAA` `1920x1080` plates.
- Provide 2–3 specific search queries per scene (species Latin name + common name + NOAA/Okeanos Explorer).

---

## STEP 2 — Collect & Audit Real Scientific Photographs

Run:

```bash
python3 -m tools.ytbot documentary collect --channel bathylora --run <slug>
```

What this command does automatically:
- Downloads only verified public-domain / CC0 / CC-BY landscape photographs (`>= 900x500`), prioritizing NOAA and USGS records.
- Resumes safely if interrupted (already downloaded files are kept).
- Writes `sources.json` (full provenance & licensing) and `credits.md`.
- Prints every downloaded image's `id`, `resolution`, `license`, `title`, and `original_description`.

**MANDATORY MANUAL CHECK BEFORE STEP 3**:
Read EVERY printed `original_description` line!
- If a downloaded image does NOT actually show what its `subject` says (for example, a shrimp query returned hydrothermal mussels):
  - Either move that entry to the matching section of `sources.json` and update its `narration_segment`, `species`, `place`, and `depth` to match the true `original_description`, OR
  - Delete that photo file, refine its query in `scenes.json`, and re-run `documentary collect`.
- Target **30 to 50 verified photos** (minimum hard floor: 20).

---

## STEP 3 — Write `article.txt` & Pass the Hard Alignment Audit

Open `.local/ytbot/channels/bathylora/runs/<slug>/sources.json` and write `.local/ytbot/channels/bathylora/runs/<slug>/article.txt` strictly following these rules:

- **One focused paragraph (~55 to 75 words) for each entry in `sources.json`, in exact sequential order (`[01]` -> `[last]`)**.
  - Example: 38 photos × 65 words ≈ `2,470 words` ≈ **`19.5 minutes` at `0.9x`** (dead center of `15–25 min`!).
- **Visual anchor rule**: in every paragraph, explicitly mention the **exact species / expedition / seamount / volcano / depth / feature** recorded in that photo's `narration_segment` and `original_description`.
- **Scientific tone**: calm, accurate, contemplative American English; clearly distinguish observed facts from open scientific questions; NO horror/monster tropes; NO cliché ending like *"the ocean keeps its secrets"*.
- **Clean prose only**: NO `#` headers, NO `-` bullets, NO `1.` lists, NO URLs, NO `[Scene 1]` tags.

Run the hard alignment audit gate:

```bash
python3 -m tools.ytbot documentary audit --channel bathylora --run <slug>
```

- **If `AUDIT FAILED`**: fix every flagged `CHECK` scene or length/formatting issue and re-run `documentary audit` until it prints **`AUDIT PASSED`** (`>= 80%` alignment; aim for `95–100%`).
- Do NOT proceed to Step 4 until `audit` exits `0`!

---

## STEP 4 — Capture Official Cove Voice Narration & Lock `0.9x` Speed

Run:

```bash
python3 -m tools.ytbot documentary narrate --channel bathylora --run <slug>
```

What this command does automatically:
- Switches to the `legacy` browser profile (ChatGPT + audio-capture extension; never touches the `bathylora` upload profile).
- Sends `article.txt` verbatim to ChatGPT, clicks **Read aloud** (Cove voice), and saves `narration.aac`. (If `narration.aac` already exists, it skips capture automatically.)
- Renders `narration-90x.aac` at the locked **`0.9x`** documentary pace via `slow_narration(factor=0.9)` and reports exact decoded duration.

Wait for completion. If ChatGPT session expired, stop and notify the owner (never retry in a loop).

---

## STEP 5 — Complete `metadata.json`

Edit `.local/ytbot/channels/bathylora/runs/<slug>/metadata.json` so it contains:
- `title`: best factual title (`<= 100` chars, no clickbait)
- `title_options`: 3 factual title options
- `description`: 120–180 word English summary naming real expeditions/species/institutions + `Bathylora is an independent educational channel and is not affiliated with NOAA or other research institutions.` + `#deepsea #oceanexploration #marinebiology #oceandocumentary #bathylora #science`
- `tags`: 12–16 relevant English tags
- `scientific_references`: list of real NOAA/USGS/archive references used
- `playlists`: 1–3 matching Bathylora playlists

---

## STEP 6 — Render Final Video, Thumbnail, Subtitles & Metadata

Choose the strongest real high-resolution photograph ID from `sources.json` for the thumbnail (e.g. `012`), a **2 to 4 word** title (use `\n` for two crisp lines on the dark left margin), and the matching Abyssal Cinema template (`encounter` = Model A animal, `discovery` = Model B geological/expedition scale, `unknown` = Model C unusual sighting):

```bash
python3 -m tools.ytbot documentary render \
  --channel bathylora \
  --run <slug> \
  --thumb-photo 012 \
  --thumb-title "THE BIGFIN\nSQUID" \
  --thumb-template unknown
```

What this command locks automatically (do NOT override):
- Exact `timeline-09x.json` aligned to the real decoded duration of `narration-90x.aac`
- Supersampled Ken Burns (`2560x1440 -> 1920x1080`, 5% zoom on HD plates, 2% zoom on `<1100px` plates)
- Smooth `1.2s` optical cross-dissolves (`xfade=transition=fade`) + `1.2s` fade-in + `1.5s` fade-out
- Parallel `h264_nvenc` encoding (with automatic `libx264` fallback)
- `DOCUMENTARY_VOICE_FILTER` (`~ -16 LUFS` broadcast mastering) + subtle filtered pink-noise analog room-tone (`90 Hz – 2.8 kHz`, ~35 dB below voice)
- `thumbnail.png` (`1280×720`, Abyssal Cinema palette + Depth Mark signature, natural underwater colors)
- `subtitles.srt` (accurate scientific taxonomy spelling) + `metadata.txt`

---

## STEP 7 — Automated Quality Control & Visual Frame Check (STOP BEFORE PUBLISHING)

Run the hard QC gate:

```bash
python3 -m tools.ytbot documentary qc --channel bathylora --run <slug>
```

This verifies:
- `1920x1080`, `30 fps`, H.264 + AAC, duration inside `14–42 min`
- Broadcast loudness between `-19.0` and `-13.0 LUFS` and `True Peak < 0.0 dBFS`
- `thumbnail.png` is `1280×720`
- Every source in `sources.json` has `license` and `source_page`
- Mandatory NOAA non-affiliation disclaimer is present in `metadata.json`
- Extracts 4 check frames into `.local/ytbot/channels/bathylora/runs/<slug>/qc/`

**FINAL HUMAN-HANDOFF CHECKLIST**:
1. Open `thumbnail.png` and all 4 images in `qc/` with `read_file` to verify visually that every frame is sharp, natural, non-black, and unstretched.
2. Confirm `credits.md`, `metadata.txt`, `subtitles.srt`, and `video-09x.mp4` exist.
3. **STOP HERE.** Report the verified paths, duration, LUFS/peak metrics, photo count, and QC summary to the owner. **NEVER upload, schedule, or publish without explicit owner approval.**

---

## Troubleshooting (Exact Error -> Exact Fix)

| Problem | Exact Action |
| --- | --- |
| `only N photos collected` in Step 2 | Add broader `"NOAA <species/habitat>"` backup queries in `scenes.json` and re-run `documentary collect` (it resumes automatically). |
| `alignment match rate < 80%` in Step 3 | Read the `CHECK` lines printed by `documentary audit`; make sure each paragraph explicitly uses the main species/place keyword from `sources.json` in exact order, then re-run `audit`. |
| `article.txt contains markdown headings` in Step 3 | Remove all `#`, `*`, `-`, numbered headers, and URLs from `article.txt`; keep pure prose paragraphs only. |
| `audio loudness outside -19 to -13 LUFS` in Step 7 | Verify `narration.aac` is not silent/corrupt; if audio only needs re-mastering, run `documentary.mux_audio()` without re-rendering video (~17s). |
| ChatGPT session expired in Step 4 | STOP immediately and notify the owner to sign in manually on the `legacy` browser profile. Never retry in a loop. |
| Want to tweak thumbnail text/photo after Step 6 | Call `documentary.thumbnail(run_dir, photo, title, style="abyssal", template=...)` or re-run `render` (clips stay intact if needed). |
