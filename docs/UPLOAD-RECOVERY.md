# Upload recovery

Every upload uses bounded waits and `[upload]`, `[details]` and `[schedule]` logs. A wait
that would previously last 30 minutes must end with a clear `UploadBlocked`, a recorded
draft (video ID and slot) or a verified success. Never re-upload a video that already has
an `upload.json` video ID; schedule the existing draft.

## Preflight

`upload_guard.preflight` checks before touching Studio:

- `video.mp4` exists and is nonempty.
- `metadata.json` has a title and description.
- `thumbnail.png` exists and is a valid image of at least 640x360.

A missing item blocks the upload with the action: render the topic, regenerate metadata or
retry the Codex thumbnail.

## Catalog

| Symptom | Detection | Automatic action | If it persists |
| --- | --- | --- | --- |
| Studio asks for login | `Fazer login` / `Sign in` in the page | `UploadBlocked`; sign in to the bot profile | Do not retry; refresh the session |
| Channel chooser or wrong channel | `Selecione um canal` / `Select a channel`, or channel ID mismatch | `ensure_channel` selects the profile; `page_blocked` stops | Select the channel once and rerun |
| Page blank or Create/Upload missing | goto timeout or missing button | Retry the page once; log the URL | Stop; check Studio/session/layout |
| Upload dialog does not open | no `#textbox`/draft dialog after `Editar rascunho` | Reopen the edit page or `?d=ud`; if a video ID exists, schedule it | Do not upload a second copy; report the ID |
| Upload stuck | no `Envio concluído` for 15 minutes | Log every 60s; `UploadBlocked` | Check connection/Studio; record any ID |
| Video ID missing | ID regex empty | Retry the read; log the page | Open Studio content and find the draft |
| Title becomes the filename | edit-page title differs after reload | `video_details` reapplies title/description and verifies | Block; fix in Studio manually |
| Description empty | edit-page description empty | Same details pass | Block; regenerate metadata |
| SEO tags empty | `input[aria-label=Tags]` empty | Description keeps the `TAGS:` line; report tags separately | Fill tags manually when the UI allows |
| Thumbnail missing/invalid | preflight fails | Stop; retry the Codex thumbnail | Regenerate the run thumbnail |
| Thumbnail upload missing | no `studiothumbnail` 200 | Never save early; `UploadBlocked` | Retry the details pass |
| Thumbnail still default | editor shows a different image after save | Reapply and verify the image | Stop; do not schedule without it |
| Audience question rejected | `madeForKids` validation remains | Set both components + handler; verify | Leave the draft and report |
| Checks do not finish | no `Verificações concluídas` | Wait at most 5 minutes; close and verify the slot | Leave the draft with video ID/slot; rerun later |
| Date picker changed | input absent, calendar present | `_set_date` supports both; verify the model | Block with the slot |
| Done button label changed | `Concluir`/`Done`/`Publish` | Accept the known labels; click via JS | Block; inspect the dialog |
| Video already scheduled | `scheduled_at` true | Return success; no dialog | None |
| False confirmation | one `scheduled_at` read fails | Three reads with delays | Do not open the dialog again blindly |
| End screen missing | Best for viewer/Subscribe absent | `verify_end_screen`; retry `add_end_screen` | Block; fix the end screen |
| Codex thumbnail empty path | image path empty/invalid | Preserve the fence; retry once intentionally | Block the upload; no ChatGPT fallback |
| Codex login/model unavailable | Codex exits or no image tool | Stop; sign in/configure | Do not switch providers |
| Read aloud unavailable/audio timeout | article/audio stage error | Record the asset failure; no upload | Rerun the audio stage |
| Wrong account/channel | channel ID mismatch | `ensure_channel` stops | Sign in/select the channel |

## Rules

- Every wait is bounded; the bot never sleeps 30 minutes without a log.
- Verify before retrying; never retry an uncertain upload or schedule twice.
- If a video ID exists, schedule the existing draft; do not upload another file.
- If checks are pending, leave the draft, record the video ID and slot, and report.
- The description carries the hashtags and `TAGS:` line; the SEO tags field may need a
  separate manual pass.
- Keep media, references and private logs out of Git.
