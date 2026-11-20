# Video chapters — time map with image sources (Sepia Atlas & Bathylora)

Every documentary episode carries its image map in the YouTube description, under the
heading `VIDEO CHAPTERS — every image with its source:`. One line per image (or merged
group), each with the timestamp where that image appears and where the image came from —
including AI illustrations, which are named as such.

## Format

```text
VIDEO CHAPTERS — every image with its source:
0:00 A crowded immigrant street in New York — Library of Congress
0:59 Tenement housing — Wikimedia
...
```

- First line always starts at `0:00`; at least 3 chapters; every chapter is at least
  10 seconds long (shorter windows merge into the next chapter, otherwise YouTube
  disables chapters entirely).
- Source names are compact: `Library of Congress`, `NARA`, `NOAA Ocean Exploration`,
  `USGS`, `Smithsonian`, `Wikimedia`, or `AI illustration` (+ `(+ AI illustration)`
  when a merged chapter covers a generated scene).
- Full per-image provenance (page URLs, licenses, narration segments) stays in
  `sources.json` / `credits.md`; the description carries title + institution only so the
  whole description stays under YouTube's 5000-character limit (code enforces ≤4900).

## Rules

1. Never publish a documentary episode without the chapter block in the description.
2. Never present a generated illustration as a record: it is named `AI illustration`
   in chapters AND labelled on screen while shown
   (see [generated illustrations](GENERATED-ILLUSTRATIONS.md)).
3. Never cut narration to hide a missing photo; the passage stays and the illustration
   (or honest context photo) covers it, labelled.
4. `documentary.apply_description_chapters` builds the block from `timeline-09x.json`
   + `sources.json` and is called automatically by `documentary render`; the chapters
   are pushed to YouTube with the rest of the metadata before scheduling.
