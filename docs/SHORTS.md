# Shorts protocol

Vertical Shorts use a separate, faster path from the long-form batch. Every channel publishes
them, always with one generated background image and burned-in subtitles.

## Format

| Field | Value |
| --- | --- |
| Canvas | 1080x1920, 9:16 |
| Duration | about 35 to 55 seconds |
| Script | 90 to 130 Brazilian Portuguese words |
| Background | one generated 1080x1920 image per Short, in the channel art style |
| Audio | ChatGPT Read aloud, Cove voice |
| Subtitles | centered, large condensed sans, burned in |
| Thumbnail | none; the generated image is the video background |
| Related video | one different, already-published long video of the same channel |
| End screen | not applied |
| Upload | Zaflas upload-only profile |
| Generation | legacy profile with ChatGPT and audio capture |
| Schedule | 2 per day at 09:00 and 18:00 America/Cuiaba |
| Media | `.local/ytbot/channels/zaflas/shorts/` (symlink to `/data/zaflas-shorts`) |

The long-form Zaflas videos remain one per day at 11:00 America/Cuiaba (12:00 in
Sao Paulo/Brasilia). Shorts are separate uploads and keep their own hours.

The 35-to-55-second duration is a target. A Short that comes out longer is accepted and
published without being re-rendered.

## Related video link

Every Short links to a different long video already published on the same channel. The link is
set in Studio's **Related video** field after the Short is scheduled, never points to another
Short and never points to an unpublished draft. The linker rotates through the channel's public,
processed videos so two Shorts in the same batch do not reuse the same target.

## One image per Short

Every Short generates its own 1080x1920 image from that story's subject and place. Never reuse
a background, character or composition from another Short. The image request leads with the
topic and asks for a scene specific to it; after generation the bot compares a perceptual
signature with the channel's other Shorts and, when a new image is too similar, keeps the old
attempt and generates a different scene once.

Zaflas is the only Portuguese channel. A short script that comes back in English is rejected
and rewritten once; a second English result fails the asset before audio, render or upload.

## Channels with Shorts

Every channel now publishes Shorts. Each one keeps its own generated art style, topic queue
and slot hours, and no Short receives a custom thumbnail:

| Channel | Protocol | Cadence |
| --- | --- | --- |
| Zaflas | `faith-shorts` | 2 per day at 09:00/18:00 |
| the word of reflection | `faith-shorts` | 2 per day at 08:00/20:00 |
| Whispers From Heaven | `faith-shorts` | 2 per day at 09:00/21:00 |
| zanata | `faith-shorts` | 1 per day at 09:00 |
| fallem prince | `faith-shorts` | 1 per day at 21:00 |
| Infinite Random Worlds | `faith-shorts` | 1 per day at 09:00 |
| Vocal Pages | `faith-shorts` | 1 per day at 21:00 |
| Midnight Tales | `faith-shorts` | 1 every 2 days at 09:00 |
| Sepia Atlas | `faith-shorts` | 1 every 2 days at 09:00 |
| Bathylora | `faith-shorts` | 1 every 2 days at 21:00 |

## Intelligent Shorts distribution

```bash
python3 -m tools.ytbot distribute-shorts --count 10
python3 -m tools.ytbot distribute-shorts --count 10 --dry-run
```

The same water-fill as the long-video distribution: count the scheduled Shorts of each
Shorts-enabled channel and give the next Short to the channel with fewer scheduled ones. The
new slots skip every slot already taken, so a batch never overwrites an existing Short. Each
channel keeps its own protocol, language and style.

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
3. **Thumbnail** (`thumbnail Ns`): Codex renders one vertical 9:16 image with
   `prompts/zaflas_agro/thumbnail-shorts.txt` and saves `thumbnail.png` at **1080x1920**.
   The title sits in the upper half in ultra condensed uppercase with one or two yellow or
   green accent words, and the lower half carries one photoreal farm detail. Never crop a
   16:9 design for a short: the phone frame would cut the text.
4. **Render** (`render Ns`): one pass at 1080x1920, 30 fps, portrait background, burned-in
   subtitles, no music and no end screen.
5. **Upload** (`upload Ns`): the proven long-form path with a custom thumbnail and no end
   screen. The title, description, thumbnail and schedule are applied through the edit page,
   and the video id is resolved by the unique title when the Studio share link stays in
   `Criando o link...`. The dialog-only schedule was abandoned: Studio can close the upload
   wizard before saving, which loses the draft.

A short should take about three to four minutes end to end.

The upload file is staged in `.local/ytbot/upload-tmp/` before Studio reads it. Studio
reports `Arquivo ilegível` when the file is hard-linked inside the `/data` symlink, so never
hand Studio a path under `channels/zaflas/shorts` directly.

## Failure handling

- `Arquivo ilegível` aborts the upload; do not retry the same staged path.
- If the dialog closes before `Envio concluído`, the upload is unconfirmed; check the Studio
  content list before sending the file again.
- A short with a recorded `upload.json` video ID is never uploaded twice; schedule the draft.
- Record failures and continue with the next topic.

## Optional AI Video Mode (Shorts Only)

Shorts optionally support `--visual-mode ai-video` using Google Flow (`google-flow`),
manual clip import (`manual-import`), or explicitly approved paid Gemini Video API
(`gemini-api`), while keeping `--visual-mode static` as the default. Long-form pipelines
never use AI video clips. See [Google Flow Shorts](GOOGLE-FLOW-SHORTS.md).


## Gemini engine

Shorts are generated with Gemini (owner approval 2026-11-26). The script, the vertical
background image and the read-aloud narration all come from the signed-in Gemini session in
the Google Flow browser profile (`https://gemini.google.com/app`, CDP port 9345). No API key
is used. Narration is captured from the default PulseAudio monitor, trimmed of silence and
encoded as AAC; the approved voice is the Gemini read-aloud male voice (~148 Hz, close to a
lighter Cove). The local renderer still burns the subtitles and assembles the 1080x1920
video. `faith-shorts --engine gemini` selects it explicitly and `distribute-shorts` passes
it for every new Shorts batch; `--engine chatgpt` keeps the old ChatGPT path. Long videos
keep ChatGPT: the Gemini web app refuses long read-aloud texts (tested with 576 and 2,000
words), so it cannot narrate a 60+ minute episode.
