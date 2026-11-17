# Religious Shorts

Vertical Shorts for **the word of reflection** and **Whispers From Heaven**. One generated
background image per short, in the channel's visual style, with burned-in subtitles.

## Format

| Field | Value |
| --- | --- |
| Canvas | 1080x1920, 9:16 |
| Duration | 40 to 60 seconds |
| Script | 90 to 140 English words |
| Background | one generated vertical image per short (`shorts_background.txt`) |
| Subtitles | burned in, centered, large sans |
| Music | none |
| End screen | not applied |
| Thumbnail | the background frame; no custom thumbnail upload |
| Generation | legacy profile with ChatGPT and the capture extension |
| Upload | `reflection` or `youtube-2` (Whispers) upload-only profile |

The background is a dedicated piece for that short: a cinematic biblical scene for
reflection, Sacred Brown Engraving for Whispers. It never contains text; the subtitles carry
the words. The upper third stays calmer so the captions remain readable.

## Schedule

Shorts use hours different from the channel's long videos, two per day:

| Channel | Long videos | Shorts |
| --- | --- | --- |
| the word of reflection | 05:00 and 17:00 | 08:00 and 20:00 |
| Whispers From Heaven | 00:00 and 12:00 | 09:00 and 21:00 |

America/Cuiaba. One short is never scheduled within 60 minutes of now.

## Command

```bash
python3 -m tools.ytbot faith-shorts --channel reflection --count 5
python3 -m tools.ytbot faith-shorts --channel whispers-from-heaven --count 5
```

Optional: `--start-date YYYY-MM-DD`, `--skip-slots N` to leave the first slots to another run.

## Topics

The queue lives in `tools/ytbot/faith_shorts.py` (`CHANNELS`): five premises per channel.

- reflection: Hannah, Elijah in the cave, Peter's nets, the widow's oil, Joseph in prison.
- Whispers: the long night, the shepherd and the ninety-nine, the whispered prayer, the peace
  in the storm, the weary gathered one by one.

## Protocol

1. Write 90 to 140 English words with `prompts/<channel>/shorts.txt`.
2. Capture the Read aloud audio.
3. Generate the vertical background with `shorts_background.txt` (1080x1920, no text).
4. Render 1080x1920, 30 fps, subtitles burned in.
5. Build the short metadata: title + `#Shorts`, short description and tags.
6. Upload with the channel profile, no custom thumbnail and no end screen.
7. Schedule in the reserved slot.

## Rules

- English only; the channel language comes from `channels.py`.
- One biblical moment per short, faithful to the text, no invented verses or promises.
- No call to action, no altar call, no slogan; end on a quiet line.
- Never reuse another short's background; each short gets its own image.
- A short with a recorded `upload.json` is never uploaded twice.
