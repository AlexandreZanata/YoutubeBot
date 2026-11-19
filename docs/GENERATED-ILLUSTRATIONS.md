# Generated illustrations (honest fallback when no real photo exists)

When no authentic photograph, map, document or clearly-labelled alternative exists for a
scene, **the passage stays**: never cut narration just because the archive came up empty —
cutting creates logical gaps. Instead:

1. Generate an illustration in ChatGPT (browser path, channel art style).
2. Save it as `photos/<id>.jpg` and record the source entry with
   `"generated": true`, `"license": "AI illustration (not a documentary record)"` and the
   exact `narration_segment` it illustrates.
3. The renderer burns a visible label in the **top-left corner** for the whole time that
   image is on screen:
   - Sepia Atlas: `AI illustration — not a historical photograph`
   - Bathylora: `AI illustration — not a real observation`
   - Style: small, high-contrast, sober, in the channel palette; never hidden, never tiny.
4. The same label rule applies to thumbnails built from generated art: the video always
   tells the viewer, on screen, what is illustration and what is record.

Forbidden:
- Presenting a generated image as a photograph, archival record or scientific observation.
- Silently dropping a passage to hide a missing image.
- Reusing one illustration for two different subjects.

This rule lives in code: `documentary.timeline` carries the `generated` flag from
`sources.json`, `_clip` burns the label via `drawtext`, and the audit counts generated
images separately so a human reviews them before render.
