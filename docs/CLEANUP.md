# Cleanup rule

Disk exhaustion is a media failure, not a retry problem. Every `run` and every `shorts`
batch calls the cleanup rule before it touches a browser, a render or Studio.

## What the rule removes

| Target | Detail |
| --- | --- |
| Trash | everything under `~/.local/share/Trash/files` and `info` |
| Upload staging | leftovers in `.local/ytbot/upload-tmp` |
| Scheduled media | `video.mp4`, `narration.wav`, `thumbnail.frame.png` and `upload-*.mp4` in runs whose `upload.json` has `scheduled: true` and a video ID |
| Build cache | `~/.cache/go-build` when the free space is below 20 GB |

## What it never removes

- Runs without a confirmed scheduled upload: an unscheduled or uncertain video keeps every
  file.
- `article.txt`, `narration.aac`, `narration.ass`, `metadata.json`, `thumbnail.png`,
  `record.json` and `upload.json`, so the text, the compressed audio, the metadata and the
  audit trail survive.
- Browser profiles, cookies, credentials, the owner's original local media and any other
  repository.
- A scheduled video is safe to prune because YouTube already holds the file and the public
  ID; a re-render can use the retained narration.

## Command

```bash
python3 -m tools.ytbot cleanup --dry-run
python3 -m tools.ytbot cleanup
```

The dry run prints the space it would free. Both commands report the remaining free space at
the end.

## Order of operations

1. Cleanup runs.
2. The space guard checks the requested batch size against the free space.
3. If the guard still fails, the batch stops with the available and required gigabytes instead
   of rendering into a full disk.

## Integration

`command_run` and `command_shorts` call `cleanup.before_run()` before starting. The
distribution mode calls the normal `run` command, so it inherits the rule. The cleanup is
idempotent and does not need a lock: it only touches runs that already have a scheduled
upload record.
