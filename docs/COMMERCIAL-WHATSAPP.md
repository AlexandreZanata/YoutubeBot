# WhatsApp Web module

The commercial module carries one owner-operated WhatsApp Web session. It sends the owner's
own messages with human pacing; it is not a bulk or marketing tool.

## Boundaries

- One account, one session, one chat at a time.
- No broadcast, no list import, no group scraping, no automated replies.
- `send` is dry-run unless `--live`.
- Every message is journaled; a `sent` entry blocks a repeat until `--force`.
- Private state lives in `.local/commercial/whatsapp/` and is never committed.

## Session

| Item | Value |
| --- | --- |
| Profile | `.local/commercial/whatsapp/profile` |
| Journal | `.local/commercial/whatsapp/journal.jsonl` |
| Account registry | `.local/commercial/registry.json` (via `SocialStore`) |
| CDP port | 9325 |
| Hidden display | `:93` (Xvfb) |
| Login page | <https://web.whatsapp.com/> |

Commands:

```bash
python3 -m tools.ytbot commercial open   --network whatsapp   # visible QR window
python3 -m tools.ytbot commercial status --network whatsapp   # hidden check
python3 -m tools.ytbot commercial stop   --network whatsapp   # stop the hidden browser
```

`open` launches a visible Chrome on the profile. The owner scans the QR code with the phone
(WhatsApp, Linked devices, Link a device). The session persists in the profile. `status` and
`send` reuse a running browser on port 9325 and only start a hidden one when the port is down.

Session expiry is normal after long periods or a manual unlink. `status` then reports
`login-required` (QR canvas) or `unknown`; run `open` again and rescan.

## WhatsApp Web structure, mapped

The 2026 web client is a React app without `#main` or `footer`. The stable anchors are:

| Element | Selector | Notes |
| --- | --- | --- |
| App root | `#app` | Present when the client loaded |
| Session ready | `#pane-side` / `[data-testid="chat-list"]` | Chat list rendered means logged in |
| QR screen | `canvas` | Logged out; `#pane-side` absent |
| Search | `input[placeholder="Search or start a new chat"]` | Real `<input>`, use `fill` |
| Chat row | `[data-testid="cell-frame-container"]` | One per conversation |
| Composer | `div[data-testid="conversation-compose-box-input"]` | `contenteditable`, `aria-label="Type a message to ..."` |
| Send button | `button[aria-label="Send"]` | Appears after the composer has text |
| Attach button | `button[aria-label="Attach"]` | Opens the attach menu |
| Attach menu | `Document`, `Photos & videos`, `Camera`, `Audio`, `Contact`, `Poll`, `Pix`, `Event`, `New sticker` | Localized labels |
| Image input | `input[type=file][accept="image/*"]` | Accepts a local file directly |
| Messages | `[data-testid="msg-container"]` | One per bubble |
| Outgoing bubble | `[data-testid="msg-container"]:has(span[data-icon="tail-out"])` | Tail icon marks our side |
| Incoming bubble | `[data-testid="msg-container"]:has(span[data-icon="tail-in"])` | Other side |
| Message text | `span.selectable-text` inside the bubble | Read for verification |

Localization: the selectors above are language independent except the button `aria-label`s
(`Send`/`Enviar`, `Attach`/`Anexar`). The sender tries both.

## State machine

```text
start
  -> page loads web.whatsapp.com
  -> if canvas and no #pane-side: LOGIN_REQUIRED (open the visible window, scan QR)
  -> if #pane-side: LOGGED_IN
       -> fill search with the contact
       -> if the result list is empty: CONTACT_NOT_FOUND (stop, report)
       -> Enter opens the chat
       -> composer attached: CHAT_READY
            -> dry-run: report and stop
            -> live: wait 8-25 s, type in chunks, click Send
                 -> tail-out bubble contains the text: SENT
                 -> otherwise: UNCONFIRMED (journal, never blind retry)
```

## Send flow, step by step

1. `open_chat`: load the web app, wait for the chat list, fill the search input, wait two
   seconds, press Enter, wait for the composer, pause 1-3 seconds.
2. `dry_run`: log the computed interval and stop without typing.
3. `live`: sleep a random interval between `--min-interval` and `--max-interval` (default
   8 to 25 seconds), the same shape as the Telegram publisher's minimum/maximum interval.
4. Optional image: set the image input, wait for the preview, click Send in the preview.
5. Type the message in small chunks, 35 to 95 ms per character, extra 150 to 450 ms after
   `.`, `,`, `?` and `!`. Never paste the whole text.
6. Click Send (or press Enter when the button is absent).
7. Verify that the last outgoing bubble contains the first characters of the message.
8. Journal `sent` or `unconfirmed`. `sent` is final; `unconfirmed` is never retried blindly.

## Journal and idempotency

`journal.jsonl` keeps one line per attempt:

```json
{"key":"<sha256[0:20]>","to":"Nome","state":"started","at":"..."}
{"key":"<sha256[0:20]>","to":"Nome","state":"sent","at":"..."}
```

The key hashes `to + text + image name`. `send` refuses a key already marked `sent` unless
`--force` is passed. `dry-run` never marks `sent`.

## Failure matrix

| Symptom | Detection | Action |
| --- | --- | --- |
| QR screen | `canvas` present, no `#pane-side` | `commercial open --network whatsapp`, scan, rerun |
| "unknown" state | neither canvas nor chat list after 9 s | Reload once, then `open` again |
| Contact not found | no chat rows after typing | Check the exact saved name or phone; stop |
| Chat does not open | composer missing after Enter | Press Enter again once; if it persists, `open` and open manually |
| Send button missing | no `Send`/`Enviar` after typing | Press Enter as fallback; verify the bubble |
| Image attach fails | no image input | Click `Attach` first; confirm the file is a real image |
| Message unconfirmed | last outgoing bubble lacks the text | Journal `unconfirmed`; do not retry blindly |
| Session expired | `status` returns `login-required` | Owner rescans the QR |
| Browser stuck | CDP port refuses connections | `commercial stop --network whatsapp`, then `status` |
| Port 9325 busy | another profile owns it | Stop the other browser; never reuse a foreign profile |
| Disk or profile error | browser fails to start | Check free space and profile permissions (0700) |

## Troubleshooting runbook

```bash
# 1. Is the profile alive?
python3 -m tools.ytbot commercial status --network whatsapp

# 2. If login is required, open the visible window and scan
python3 -m tools.ytbot commercial open --network whatsapp

# 3. If the browser is wedged
python3 -m tools.ytbot commercial stop --network whatsapp
python3 -m tools.ytbot commercial status --network whatsapp

# 4. Validate the full path without sending
python3 -m tools.ytbot commercial send --network whatsapp --to "Contato" \
  --text "teste" --dry-run
```

Do not delete the profile to "fix" a session: deleting it forces a new QR scan and loses the
linked device. Do not copy another Chrome profile over this one.

## Validation checklist

- [ ] `status` returns `logged-in`.
- [ ] `send --dry-run` finds the chat and the composer.
- [ ] A live test reaches `sent` in the journal.
- [ ] A repeated command returns `duplicate` without sending.
- [ ] The last outgoing bubble matches the message.
- [ ] No private file appears in `git status`.

## Known limits

- WhatsApp Web is unofficial automation; a UI change can break selectors. The DOM map above is
  the contract to re-check first.
- No read receipts control, no typing indicator spoofing beyond normal typing, no multi-account.
- The pacing is a safety floor, not a guarantee against limits; stop on any rate-limit banner.
- Attachments accept images only through the implemented path; documents use the same input
  but are not enabled by the CLI yet.
