# Community posts

The bot checks the selected channel's Community tab after the asset stage. The rule is one
post per calendar day, counted after 00:00 in the channel timezone. If the newest post is
from today, it changes nothing. If the tab is empty or the newest post is from an earlier
day, it publishes one question post with the topic of the first prepared video, a short text
and a square crop of that video's thumbnail. An unconfirmed publish is recorded in
`.local/ytbot/community.json` and is never retried blindly.

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

## YouTube options mapped

| Post type | YouTube support | Bot behavior |
| --- | --- | --- |
| Text | Message only, no poll | Supported as the fallback when no thumbnail exists |
| Image | Up to 10 JPG/PNG/GIF/WEBP files, 16 MB each, suggested 1:1, accepted 2:5 to 5:2 | Default: one square 1080x1080 crop of the video thumbnail |
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
