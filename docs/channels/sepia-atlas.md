# Sepia Atlas

English-only historical documentaries built on authentic archival photography, on `@SepiaAtlas`
(`UCJNamJBuijKJ5G7CgLgd7EQ`). Slogan: **Real Photographs. Forgotten Stories.**

## Positioning

A cinematic historical documentary channel about forgotten places, everyday life in the past,
vanished cities, old technologies and remarkable true stories, told through authentic archival
photographs. It must feel like a curated museum documentary, never a mass-produced AI slideshow
or a generic photograph compilation.

## Video format

- 14 to 18 minutes, 2,200 to 2,700 English words, one video every two days at 21:00.
- Documentary arc: opening hook with a concrete image, historical context, exploration, turning
  point, consequences and a reflective ending. No generic introductions, no section headings,
  no invented facts, quotations, dates or sources.
- Visual storytelling uses real archival photographs that directly match the narration, with
  subtle Ken Burns motion (100% to 103-106%), 10 to 20 seconds per image, gentle dissolves and
  no distortion. Never fabricate or silently alter a historical photograph.
- Narration: adult, calm, natural American English, Cove voice, never sped up. No music by
  default; an optional barely audible analog texture may sit under the voice.
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

## Publication

The first episode, **What Life Really Looked Like in America in 1900**, stays private for owner
review; it is never published or scheduled automatically. Later episodes may use the normal
upload and scheduling flow after approval.

## Shorts

One Short per day at 21:00, 90 to 140 English words, one true historical detail or photograph,
one generated vertical image in the archival style (never presented as a document) and no custom
thumbnail.

## Status

Profile, prompts, channel entry and visual identity are in the bot. The channel branding in
Studio, the archival-photo research pipeline and the Ken Burns renderer are staged separately;
the current renderer produces a still background under the narration, so the full photo-montage
format needs the documentary render step before the first episode is final.
