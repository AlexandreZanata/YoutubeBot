# Infinite Random Worlds channel profile

## Identity

| Field | Value |
| --- | --- |
| Channel | Infinite Random Worlds |
| Owner shorthand | "infinite random worlds" or "mundos infinitos" |
| Handle | `@InfiniteRandomWorlds` |
| Channel ID | `UCY3Zp50I6Y6semQQccJxRPg` |
| Language | English only |
| Tagline | Don't try to find meaning here. |
| Visual identity | None fixed: every episode chooses its own style |
| Background | The episode thumbnail itself, with the standard subtitle treatment |
| Upload account | `infinite` (upload-only profile) |
| Generation account | `legacy` (ChatGPT plus audio-capture extension) |

The account was signed in by the owner in a visible window on 15/11/2026. Studio shows the
profile bound to `UCY3Zp50I6Y6semQQccJxRPg`; verify the channel ID again before the first
upload of any batch.

## Content shape

Public sample from the Videos tab on 15/11/2026: 73 videos, 4 subscribers, 18 to 58.8
minutes, median 33.0 minutes and mean 34.1 minutes. The channel publishes one video per day.
Titles are standalone speculative premises, each with its own world:

- *The World Where Dinosaurs Survived the Extinction*
- *The Machine That Kept Rome Alive for 1,900 Years*
- *Every Time He Opened the Door, Another Life Became Real*
- *Humanity Discovered That Numbers Were Alive, Then They Found Something Beyond Mathematics*

Rules taken from that sample:

- One self-contained story per episode, in English, with a unique world and cast.
- Target **4,500 to 6,000 words**, about **32 to 43 minutes** at the channel pace.
- No recurring protagonist, narrator persona, era or setting between episodes.
- Titles name the specific world and conflict, without revealing the ending.
- Description is one topic-specific paragraph, no calls to action or external links.

## Video treatment

This channel deliberately has no background video. The render path uses the generated
thumbnail as the still background, so the image matches the story and the burned-in
subtitles sit over it. The rest of the standard treatment stays unchanged:

- 1920x1080, 30 fps, single-pass GPU render.
- Narration from ChatGPT Read aloud with the channel's existing voice.
- No background music and no audio mixing other than the narration.
- Subtitles always burned in.
- Five-second silent tail after the narration (the standard quick finish).
- Title, description, tags and custom thumbnail applied in Studio.

The thumbnail prompt allows any coherent style per episode: photorealism, painting, retro
science fiction, dark fantasy, archival documentary or surreal collage. It must not reuse a
character, face, palette, era or composition from another episode, and must contain no text
or logos.

## Commands

```bash
python3 -m tools.ytbot run --channel infinite-random-worlds --account legacy \
  --upload-account infinite --count 1
```

Cadence is one video per day in the 12:00 slot, and batches run only on an explicit owner
request.

## Chapters and sequels

A chapter two or a direct sequel is the one exception to the unique-world rule. Put the
source story in `context.txt` inside the run directory before the asset stage. The article
generation reads it as established canon, keeps the original names, world rules and events,
and continues from the ending without retelling it. The topic names the chapter, for
example `The Elven Kingdom That Returned After a Thousand Years: Chapter 2`.
