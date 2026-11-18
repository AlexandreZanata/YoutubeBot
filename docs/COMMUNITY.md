# Community posts

The bot checks the selected channel's Community tab after the asset stage. The rule is one
post per rolling 24 hours: if the newest post is younger than 24 hours, it changes nothing. If the tab is empty or the newest post is from an earlier
day, it publishes one question post that always carries a dedicated square art generated for
that post in the channel's visual style, a link to the related video and, on Zaflas, the site
https://zaflas.com.br/. The automatic flow generates that art with Codex; it never crops a
video thumbnail, and when the art cannot be generated it publishes nothing. An unconfirmed
publish is recorded in `.local/ytbot/community.json` and is never retried blindly.

`community.json` keeps only the latest entry (it drives the 24-hour check). Every journal
transition (`started`, `unconfirmed`, `posted`) is also appended, with the channel slug, to
`community-history.jsonl` in the same folder; the [desktop manager](DESKTOP.md) counts monthly
posts from it and falls back to the single entry on older installs.

```bash
python3 -m tools.ytbot community --channel fallem-prince
python3 -m tools.ytbot community --channel fallem-prince --topic "An exact topic"
```

The channel must be explicit. The same check runs automatically inside
`python3 -m tools.ytbot run`.

## Language

Community text follows the channel language without exception: English on Fallem Prince,
Whispers From Heaven, Infinite Random Worlds and Vocal Pages, and Brazilian Portuguese only
on Zaflas. The image and the video it references follow the same channel. Never publish an
English post on Zaflas or a Portuguese post on any other channel.

## Post content

Every post has three mandatory parts:

1. A dedicated square image generated for that post, in the channel's visual style. Do not
   reuse a video thumbnail or its crop; the post art is its own piece. Each day uses its own
   dated attempt directory, because the Codex fence rejects a changed prompt under the same
   state.
2. A link to the video the post is about, in the text.
3. On Zaflas only, the site `https://zaflas.com.br/` in the text, the same one used in the
   video description.

## YouTube options mapped

| Post type | YouTube support | Bot behavior |
| --- | --- | --- |
| Text | Message only, no poll | Supported as the fallback when no thumbnail exists |
| Image | Up to 10 JPG/PNG/GIF/WEBP files, 16 MB each, suggested 1:1, accepted 2:5 to 5:2 | One dedicated square art generated for the post in the channel style |
| GIF | Animated GIF counts as an image | Allowed by YouTube; automatic flow sends a static thumbnail |
| Video | Search, paste a URL or pick a channel video | Catalogued; not used by the automatic first post |
| Playlist | Paste a playlist URL into the message | Catalogued; not used by the automatic first post |
| Text poll | Question plus 2 to 4 options, 65 characters each | Catalogued; not used by the automatic first post |
| Image poll | Question plus 2 to 4 image answers, captions up to 36 characters | Catalogued; not used by the automatic first post |
| Quiz | Question, 2 to 4 answers, one correct, answers up to 80 characters (30 with image), optional 500-character explanation | Catalogued; not used by the automatic first post |
| Mentions | `@handle` inside the message | Catalogued; not used automatically |
| Scheduled post | Date, time and time zone in the post dialog | Catalogued; the bot publishes immediately when today has no post |
| Edit or delete | Activity history and each post menu | Not automated; private state is never rewritten silently |

YouTube also limits how many posts a channel can create in 24 hours. The bot never retries
a "limit reached" response; it reports it and leaves the tab unchanged. Posts and images
must follow the YouTube Community Guidelines.

## References

- [Create a post](https://support.google.com/youtube/answer/7124474)
- [Manage your posts and comments](https://support.google.com/youtube/answer/9526028)
