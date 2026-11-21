# Documentary format — Sepia Atlas and Bathylora (strict)

These two channels are **documentary channels**. They are never produced by the normal batch
pipeline. The only production path is:

```bash
python3 -m tools.ytbot documentary init|collect|audit|narrate|render|qc
```

## Hard rules

1. **Researched archival photographs only.** Every image on screen is a real photograph,
   map, document or clearly labelled illustration found in a verified archive (Wikimedia
   Commons, Library of Congress, NARA, NOAA, USGS, museums) with its source, license and
   narration segment recorded in `sources.json`.
2. **No AI image as background.** Never generate an AI thumbnail and use it as the video
   background, never illustrate a whole episode with generated art, and never let the normal
   `run`/`distribute` pipeline create these channels. `batch.run_batch` refuses them and
   `distribute` excludes them.
3. **Thumbnail = real photograph + text on top.** The cover is built from a real archival
   photograph of the episode (never a generated image), with the channel's editorial title
   burned over it, exactly like the first two Sepia Atlas episodes. `documentary render`
   picks the first real source automatically and fails when there is none.
4. **Narration-to-image sync.** One paragraph per verified scene, in `sources.json` order;
   each photo appears exactly where its subject is narrated. Articles are written only after
   the photos are collected.
5. **Missing photo = labelled illustration or nothing, never a silent gap.** The passage is
   never cut; a generated illustration is allowed only with the on-screen label
   (`docs/GENERATED-ILLUSTRATIONS.md`) and is never used for the cover.
6. **Fixed audiovisual standard.** `0.9x` narration, documentary voice filter, subtle analog
   room tone, 1.2 s optical cross-dissolves, supersampled Ken Burns without tremor, chapters
   with per-image sources in the description, QC before upload. Duration is a target, not a
   gate: an episode that comes out longer than planned is accepted and published without
   re-rendering or re-narrating it.
7. **Approval before publication.** The first episode of each channel stays private for owner
   review; later episodes use the normal scheduling flow after approval.

## Where this is enforced

- `channels.DOCUMENTARY_CHANNELS`: the only two slugs treated this way.
- `batch.run_batch`: raises with the documentary command instead of generating an AI cover.
- `distribute.audit`: excludes both channels from the water-fill plan.
- `documentary_commands.cmd_render`: thumbnail source must be a real, non-generated photo.
- Tests in `tests/test_documentary.py` and `tests/test_distribute.py`.
