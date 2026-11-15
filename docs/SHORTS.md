# Shorts protocol

Vertical Shorts use a separate, faster path from the long-form batch. They are generated only
when the owner explicitly asks for Shorts.

## Format

| Field | Value |
| --- | --- |
| Canvas | 1080x1920, 9:16 |
| Duration | about 35 to 55 seconds |
| Script | 90 to 130 Brazilian Portuguese words |
| Background | `assets/backgrounds/zaflas_agro_shorts.mp4` |
| Audio | ChatGPT Read aloud, Cove voice |
| Subtitles | centered, large condensed sans, burned in |
| Thumbnail | custom 1280x720 in the Zaflas Shorts style, generated per short |
| End screen | not applied |
| Upload | Zaflas upload-only profile |
| Generation | legacy profile with ChatGPT and audio capture |
| Schedule | 2 per day at 09:00 and 18:00 America/Cuiaba |
| Media | `.local/ytbot/channels/zaflas/shorts/` (symlink to `/data/zaflas-shorts`) |

The long-form Zaflas videos remain one per day at 12:00. Shorts are separate uploads.

Zaflas is the only Portuguese channel. A short script that comes back in English is rejected
and rewritten once; a second English result fails the asset before audio, render or upload.

## Command

```bash
python3 -m tools.ytbot shorts --channel zaflas --count 12 --per-day 2
```

Optional: `--start-date YYYY-MM-DD`, `--skip-slots N` (leave the first N schedule slots to
another run), `--start-index N`, `--upload-account zaflas`.

## Fast protocol

Each short runs through four stages and logs its own duration:

1. **Script** (`script Ns`): one ChatGPT message with `prompts/zaflas_agro/shorts.txt`,
   90 to 130 Portuguese words, rejected outside 60 to 180 words.
2. **Audio** (`audio Ns`): Read aloud through the capture extension, saved as
   `narration.aac`.
3. **Thumbnail** (`thumbnail Ns`): Codex renders one 1280x720 image with
   `prompts/zaflas_agro/thumbnail-shorts.txt` and saves `thumbnail.png`. The style copies
   the channel's existing Shorts: one huge cropped Portuguese word in the background, the
   short question in ultra condensed uppercase with one or two yellow or green accent words,
   and one photoreal farm detail on the right. The readable question stays inside the
   central band that survives a 9:16 crop. A frame is used only when the image is missing.
4. **Render** (`render Ns`): one pass at 1080x1920, 30 fps, portrait background, burned-in
   subtitles, no music and no end screen.
5. **Upload** (`upload Ns`): one Studio page per short. Title and description are filled in
   the upload dialog, the thumbnail is uploaded in the Miniaturas section, the audience
   answer is applied, and the schedule is set **in the same dialog** with
   `upload_dialog.schedule_in_dialog`. The edit page is not opened, no end screen is added
   and tags are not typed.

This removes the edit-page load, the details pass, the tag chips and the two per-video
`Programado` verifications that the long-form path needs. A short should take about two to
three minutes end to end.

The upload file is staged in `.local/ytbot/upload-tmp/` before Studio reads it. Studio
reports `Arquivo ilegível` when the file is hard-linked inside the `/data` symlink, so never
hand Studio a path under `channels/zaflas/shorts` directly.

## Failure handling

- `Arquivo ilegível` aborts the upload; do not retry the same staged path.
- If the dialog closes before `Envio concluído`, the upload is unconfirmed; check the Studio
  content list before sending the file again.
- A short with a recorded `upload.json` video ID is never uploaded twice; schedule the draft.
- Record failures and continue with the next topic.
