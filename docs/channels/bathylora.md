# Bathylora

English-only deep-ocean science documentaries built on authentic oceanographic photography and
verifiable expedition records, on `@Bathylora` (`UCxuhkOi4CDDStvQFpRGsoXA`).
Slogan: **The Ocean Has Stories We Have Never Seen.**

## Positioning

Bathylora reveals the extraordinary real world hidden beneath Earth's oceans through authentic
underwater imagery, scientific discoveries and cinematic documentary storytelling. It must feel
like a curated independent science documentary — scientific, mysterious without sensationalism,
contemplative, respectful of marine life — never horror, conspiracy, monster lore or a generic
AI slideshow.

## Schedule profile

Audience: United States science-curious viewers, roughly 25 to 45, who watch deep-ocean
documentaries in the evening prime window. Cuiaba is one hour ahead of US Eastern time in
November.

| Slot (America/Cuiaba) | US Eastern | US Pacific | Why |
| --- | --- | --- | --- |
| 21:00 | 20:00 | 17:00 | Evening prime window (8 to 10 p.m. local), when documentary and science long-form are watched on both coasts |

One video every two days, unchanged; 21:00 Cuiaba is already prime-time optimal and is kept.

## Video format

- Target duration: **15 to 25 minutes** average (`1,900` to `3,200` American English words at
  `0.9x`), with tolerance up to **40 minutes** (`~5,100` words) when a subject genuinely warrants
  deeper scientific coverage (never pad with filler). Cadence: one quality documentary
  every two days at 21:00 (`interval_days=2`).
- Documentary arc: opening hook with a remarkable documented observation (0:00–0:35),
  scientific context and location (0:35–3:00), deep-sea exploration of habitats, expeditions and
  evidence (3:00–10:00), main scientific discovery and open questions (10:00–15:00+), and a
  contemplative grounded ending (avoid generic cliches about "the ocean keeping secrets").
- Visual storytelling uses real oceanographic photographs and ROV frames that directly match the
  narration, with subtle supersampled Ken Burns motion (100% to 105%, alternating in and out),
  smooth 1.2s optical cross-dissolves (`xfade=transition=fade`, never dip-to-black cuts between
  photos) and no distortion. Never artificially upscale low-resolution plates as "native 4K" and
  never use AI-generated underwater creatures as documentary evidence.
- **Narration-to-image synchronization (mandatory)**: Every photograph shown on screen must
  correspond directly to what the narrator is saying at that exact moment. Never pad a run with
  generic filler images unrelated to the spoken passage. Each entry in `sources.json` must record
  a concrete `narration_segment` matching the exact spoken passage in `article.txt`, be placed
  via `documentary.timeline_aligned`, and be audited against the narration text before rendering.
- **Narration & broadcast voice filter (mandatory for all episodes)**: adult, calm, precise
  American English, Cove voice, locked at **`0.9x` speed**
  (`slow_narration(run_dir, factor=0.9)` -> `narration-90x.aac`, never sped up). Always apply
  the lightweight single-pass broadcast documentary voice chain (`DOCUMENTARY_VOICE_FILTER`:
  `75 Hz` highpass, `+4 dB @ 125 Hz` warm chest presence, `-2.5 dB @ 320 Hz` de-mud,
  `+2.5 dB @ 3.2 kHz` clarity, `-1.5 dB @ 6.5 kHz` de-ess, optical-style `acompressor` +
  `alimiter` targeting `~ -16 LUFS` with clean peak headroom below `0 dBFS`). No music by
  default; mix a barely audible, warm filtered analog room-tone (`90 Hz - 2.8 kHz` filtered pink
  noise sitting ~35 dB below the narration, faded in/out) under the voice rather than harsh raw
  white noise or artificial underwater sound effects. Use `mux_audio` to re-master audio on an
  existing `silent.mp4` (`-c:v copy`) without re-rendering video.
- Open immediately on the real image and premise; end with a clean Bathylora end screen.

## Visual identity — Abyssal Cinema

Bathylora uses its own exclusive identity, **Abyssal Cinema**, completely distinct from Sepia
Atlas (never sepia, aged gold or brown).

| Role | Color | Hex |
| --- | --- | --- |
| Primary dark background | Abyssal Black | `#030B12` |
| Surfaces & depth layers | Deep Ocean | `#071F2C` |
| Brand highlight | Bioluminescent Cyan | `#55D9D0` |
| Secondary information | Ocean Mist | `#B5D2D7` |
| Primary text | Arctic White | `#EDF7F5` |
| Supporting elements | Submersed Teal | `#164958` |

Typography: clean, contemporary editorial sans-serif (`Inter`) for bold legible titles and
sober secondary copy, with technical tabular proportions for depths, dates and coordinates.
Avoid exaggerated sci-fi fonts, neon glows, 3D bevels and horror typography.

The official emblem is **The Depth Mark**: a minimalist circular symbol composed of a refined
horizontal sea-surface line, a vertical descending path disappearing into abyssal negative
space, and a tiny luminous Bioluminescent Cyan (`#55D9D0`) point at the lower extremity. Never
use sharks, monstrous tentacles, skulls, tridents, detailed submarines or NOAA logos. The
permanent identity lock lives in `tools/ytbot/prompts/bathylora/identity.txt`; brand assets
live in `assets/brand/bathylora/`.

### Reusable thumbnail models

Every thumbnail is episode-specific, built on an authentic licensed underwater photograph,
maximum four short words in Arctic White / Bioluminescent Cyan, generous abyssal negative space
and a discreet Depth Mark signature:

- **Model A — The Encounter**: one real deep-sea animal centered against dark water (`assets/brand/bathylora/template-a-encounter.png`).
- **Model B — The Discovery**: an underwater geological formation, vent, seamount or ROV expedition scene showing scale (`assets/brand/bathylora/template-b-discovery.png`).
- **Model C — The Unknown**: a genuinely unusual verified scientific photograph framed cleanly without deceptive manipulation (`assets/brand/bathylora/template-c-unknown.png`).

Never fabricate composite creatures, glowing eyes, arrows, circles or fake discoveries.

## Editorial pillars & initial 12-episode queue

1. **Creatures of the Deep (30%)** — bigfin squid, anglerfish, dumbo octopuses, giant isopods, deep-sea jellyfish, glass sponges, deep-sea corals.
2. **Ocean Expeditions (20%)** — ROVs, submersibles, documented dives and deep-sea exploration challenges.
3. **The Abyss Explained (20%)** — pressure, absence of sunlight, oceanic zones, biological adaptations.
4. **Hidden Ocean Worlds (15%)** — seamounts, hydrothermal vents, canyons, abyssal plains, brine pools.
5. **Extraordinary Marine Biology (10%)** — bioluminescence, camouflage, symbiosis, chemosynthesis.
6. **Underwater History & Shipwrecks (5%)** — verified submerged sites with cleared media rights.

Initial editorial queue (each topic verified for real archival imagery before production):

1. What NOAA Cameras Really Found in the Deep Ocean *(Pilot — Episode 1)*
2. The Strange World of the Bigfin Squid
3. Life in the Ocean's Midnight Zone
4. The Extraordinary Animals Living Without Sunlight
5. Inside the World of Hydrothermal Vents
6. The Hidden Gardens of Deep-Sea Corals
7. Why Deep-Sea Creatures Look So Unusual
8. The Amazing Biology of the Dumbo Octopus
9. How Scientists Explore the Deepest Ocean
10. The Remarkable Life Found on Underwater Mountains
11. How Bioluminescence Works in the Deep Sea
12. What We Have Actually Seen Near the Deepest Ocean Trenches

## Research, scientific archives and licensing

Priority sources:
- **NOAA Ocean Exploration** (`https://oceanexplorer.noaa.gov/`, data tools, media collections, and Wikimedia Commons `PD-USGov-NOAA` official mirrors).
- **NOAA Fisheries**, **NOAA National Marine Sanctuaries**, **NOAA NCEI**.
- **USGS** (subsea geology, canyons, margins, methane seeps).
- Open museum, university and oceanographic archives with explicit commercial-compatible licenses (`Public domain`, `PD-USGov-NOAA`, `PD-USGov-USGS`, `CC0`, `CC BY`).

For every downloaded image, `sources.json` records: internal ID, file, original title,
institution, author/team, expedition, date, location, depth (when available), species,
source page URL, download URL, license, commercial use status, attribution requirement,
resolution, original description, narration segment, start/end time and verification status.

- NOAA works produced by federal employees are generally public domain, but third-party items
  hosted on NOAA pages may carry restrictions — verify every record individually.
- Preserve required attribution and never display the NOAA logo as if Bathylora were affiliated.
- Include the disclosure: *"Bathylora is an independent educational channel and is not affiliated
  with NOAA or other research institutions."*
- Visual fallback when no authentic photograph exists: widen archive search, use verified
  scientific maps or clearly labelled original explanatory diagrams, or rewrite/cut the passage.

## Description chapters

Every episode description carries a chapter time map with one line per image and its
source institution (AI illustrations named as such). See [video chapters](../VIDEO-CHAPTERS.md).

## YouTube Studio configuration

- Official description (English, includes NOAA non-affiliation disclosure).
- Keywords: `deep sea documentary, ocean exploration, marine biology, deep sea creatures, underwater discoveries, ocean science, abyssal zone, marine life, deep ocean, hydrothermal vents, underwater expedition, NOAA exploration, ROV footage, ocean biodiversity, ocean documentaries, scientific discoveries`.
- Official playlist taxonomy (populated only as real episodes are approved; never fake playlists with nonexistent videos): *Creatures of the Deep*, *The Abyss Explained*, *Ocean Expeditions*, *Strange Marine Life*, *Hidden Ocean Worlds*, *Discoveries Beneath the Surface*.

## Publication

The first episode, **What NOAA Cameras Really Found in the Deep Ocean**, stays private for
owner review; it is never published or scheduled automatically. Later episodes use the normal
upload and scheduling flow only after approval.

## Shorts

One Short every two days at 21:00, 90 to 140 American English words, one true verifiable deep-sea
observation, one generated 9:16 atmospheric Abyssal Cinema illustration (never presented as a
real scientific field photograph) and no custom thumbnail.

## Status

Profile, prompts, channel entry, Abyssal Cinema visual identity, Depth Mark brand assets,
scientific archive collector (`documentary.collect_ocean`), deterministic CLI pipeline
(`python3 -m tools.ytbot documentary init|collect|audit|narrate|render|qc`) and documentary
renderer (`0.9x` speed, `DOCUMENTARY_VOICE_FILTER`, subtle analog room-tone, `1.2s`
cross-dissolves, parallel `h264_nvenc`) are integrated in YoutubeBot. For exact step-by-step
episode production instructions usable by any agent, see
[the Bathylora production pipeline runbook](bathylora-pipeline.md). The pilot episode package
is prepared under `.local/ytbot/channels/bathylora/runs/` for owner review; nothing is
published automatically.
