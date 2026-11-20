# Sepia Atlas

English-only historical documentaries built on authentic archival photography, on `@SepiaAtlas`
(`UCJNamJBuijKJ5G7CgLgd7EQ`). Slogan: **Real Photographs. Forgotten Stories.**

## Positioning

A cinematic historical documentary channel about forgotten places, everyday life in the past,
vanished cities, old technologies and remarkable true stories, told through authentic archival
photographs. It must feel like a curated museum documentary, never a mass-produced AI slideshow
or a generic photograph compilation.

## Schedule profile

Audience: United States documentary viewers, skewing 40 and older, who watch historical
documentaries in the evening prime window the way broadcast documentaries are scheduled.
Cuiaba is one hour ahead of US Eastern time in November.

| Slot (America/Cuiaba) | US Eastern | US Pacific | Why |
| --- | --- | --- | --- |
| 21:00 | 20:00 | 17:00 | Broadcast-style prime time (8 to 10 p.m. local), when long documentary viewing happens on both coasts |

One video every two days, unchanged; 21:00 Cuiaba is already prime-time optimal and is kept.

## Video format

- Target duration: **15 to 25 minutes** average (`1,900` to `3,200` English words at `0.9x`),
  with tolerance up to **40 minutes** (`~5,100` words) when a subject genuinely requires deeper
  coverage (never pad with filler). One video every two days at 21:00.
- Documentary arc: opening hook with a concrete image, historical context, exploration, turning
  point, consequences and a reflective ending. No generic introductions, no section headings,
  no invented facts, quotations, dates or sources.
- Visual storytelling uses real archival photographs that directly match the narration, with
  subtle Ken Burns motion (100% to 105%, alternating in and out), smooth 1.2s optical
  cross-dissolves (`xfade=transition=fade`, never dip-to-black cuts between photos) and no
  distortion. Never fabricate or silently alter a historical photograph.
- **Narration-to-image synchronization (mandatory)**: Every photograph shown on screen must
  correspond directly to what the narrator is saying at that exact moment. Never pad a run
  with generic filler photographs unrelated to the spoken passage. Each entry in `sources.json`
  must record a concrete `narration_segment` matching the exact spoken passage in `article.txt`,
  be placed via `documentary.timeline_aligned`, and be audited against the narration text before
  rendering so no image appears out of sync with the voiceover.
- **Narration & broadcast voice filter (mandatory for all upcoming episodes)**: adult, calm,
  natural American English, Cove voice, locked at **`0.9x` speed**
  (`slow_narration(run_dir, factor=0.9)` -> `narration-90x.aac`, never sped up). Always apply
  the lightweight single-pass broadcast documentary voice chain (`DOCUMENTARY_VOICE_FILTER`:
  `75 Hz` highpass, `+4 dB @ 125 Hz` warm chest presence, `-2.5 dB @ 320 Hz` de-mud,
  `+2.5 dB @ 3.2 kHz` clarity, `-1.5 dB @ 6.5 kHz` de-ess, optical-style `acompressor` +
  `alimiter` targeting `~ -16 LUFS` with clean peak headroom below `0 dBFS`). No music by
  default; mix a barely audible, warm filtered analog room-tone (`90 Hz - 2.8 kHz` filtered pink
  noise sitting ~35 dB below the narration, faded in/out) under the voice rather than harsh raw
  white noise. Use `mux_audio` to re-master audio on an existing `silent.mp4` (`-c:v copy`)
  without re-rendering video.
- No long intro. Open on the photograph and the premise; the brand appears discreetly later.
  End with a simple Sepia Atlas end screen.

## Visual identity

Cinematic Archival Minimalism. Palette: Archival Black `#14110E`, Aged Gold `#C49A60`, Antique
Ivory `#F1E7D4`, Weathered Bronze `#76614A`, Faded Paper `#B9AA95`. Editorial historical serif
titles, a clean sober sans for supporting text, a discreet archive-label face for dates.

The symbol is **The Atlas Frame**: an antique photographic frame enclosing a four-point
cartographic star, with negative space suggesting a doorway into another era. Never clocks,
globes, hourglasses or magnifying glasses. The permanent identity lock lives in
`tools/ytbot/prompts/sepia_atlas/identity.txt`; brand assets live in
`assets/brand/sepia_atlas/`.

Thumbnails are episode-specific: one real historical photograph as protagonist, high contrast
without altering the record, a two to four word ivory or gold title, negative space and a small
Sepia Atlas signature. Never use a generated image as if it were a historical photograph.

## Research and image rights

Priority sources: Library of Congress, US National Archives, Smithsonian Open Access, Wikimedia
Commons, public university archives, historical digital libraries and museum collections.

For every image: internal ID, file, original title, institution, author, date or period, place,
source page URL, download URL, license or documented permission, attribution requirement,
narration segment, start and end time, and historical verification result. "Available online" is
not "free for commercial use", and "no known restrictions" is not automatically public domain.
Unclear rights are not used.

When no authentic photograph of an event exists, use an honest alternative: a clearly identified
context photograph, historical map, original document, contemporary illustration marked as
illustrative, or an original explanatory diagram. The viewer must never be misled into thinking a
reconstruction is an authentic record.

## Description chapters

Every episode description carries a chapter time map with one line per image and its
source institution (AI illustrations named as such). See [video chapters](../VIDEO-CHAPTERS.md).

## Publication

The first episode, **What Life Really Looked Like in America in 1900**, stays private for owner
review; it is never published or scheduled automatically. Later episodes may use the normal
upload and scheduling flow after approval.

## Shorts

One Short every two days at 09:00, 90 to 140 English words, one true historical detail or photograph,
one generated vertical image in the archival style (never presented as a document) and no custom
thumbnail.

## Status

Profile, prompts, channel entry, visual identity and branding are in the bot and in Studio.
`tools/ytbot/documentary.py` collects public-domain photographs from Wikimedia Commons with
their license records, builds a narration-aligned scene timeline (`timeline_aligned`), and
renders the supersampled Ken Burns montage in parallel (using `h264_nvenc` when available,
with `libx264` fallback) through a two-level `xfade` cross-dissolve tree with the `0.9x`
narration and subtle analog room-tone. The first episode package is prepared under the channel
runs folder for owner review; nothing is published automatically.

## Strict production path

Only the documentary pipeline (`documentary init|collect|audit|narrate|render|qc`) produces
this channel. Researched archival photographs carry the video; the cover is a real photograph
with the episode title over it, like the first two episodes. Never an AI thumbnail used as the
background, never the normal batch path. See [documentary format](../DOCUMENTARY-FORMAT.md).
