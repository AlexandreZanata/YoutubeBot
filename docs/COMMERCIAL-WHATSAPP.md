# WhatsApp Web module

The commercial module carries one owner-operated WhatsApp Web session. It sends the owner's
own messages with human pacing; it is not a bulk or marketing tool. The Zaflas sales agent
uses this same sender, DOM map and journal; its rules live in
[the sales agent contract](COMMERCIAL-WHATSAPP-SALES.md).

## Boundaries

- One account, one session, one chat at a time.
- No broadcast and no group scraping. The only list import and automated replies are the
  sales agent's: an owner-reviewed list, 10 first contacts per day, replies only to funnel
  leads allowed by `rules.json`.
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
| Chat by number | `https://web.whatsapp.com/send?phone=<55DDDNUMBER>` | Opens a chat with an unsaved number |
| Number without WhatsApp | text `Phone number shared via url is invalid` | Localized; the sales agent marks `invalid-number` |
| Chat row | `[data-testid="cell-frame-container"]` | One per conversation |
| Row title | `[data-testid="cell-frame-title"] span[title]` | Saved name or formatted number; a contact without photo also shows its initial as a text line |
| Row time | `[data-testid="chat-list-timestamp"]` | `3:15 PM`, `Sunday`, `8/20/2026` |
| Row preview | `[data-testid="last-msg-status"]` | Groups prefix `You:` / sender name |
| Our last message | `svg title` `wds-ic-delivered` / `wds-ic-read` in the row | 1:1 chats show no `You:` prefix |
| Unread badge | `[data-testid="icon-unread-count"]` | aria-label `2 unread messages` |
| Open chat title | `#main [data-testid="conversation-info-header-chat-title"]` | Saved contact name or formatted number of the open conversation |
| Composer | `div[data-testid="conversation-compose-box-input"]` | `contenteditable`, `aria-label="Type a message to ..."` |
| Send button | `button[aria-label="Send"]` | Appears after the composer has text |
| Attach button | `button[aria-label="Attach"]` | Opens the attach menu |
| Attach menu | `Document`, `Photos & videos`, `Camera`, `Audio`, `Contact`, `Poll`, `Pix`, `Event`, `New sticker` | Localized labels |
| Image input | `input[type=file][accept="image/*"]` | Accepts a local file directly |
| Messages | `[data-testid="msg-container"]` | One per bubble |
| Bubble direction | closest `[data-id]` starting with `true_` (ours) or `false_` | Older clients; in 2026 `data-id` is the bare message id, still used to confirm a new bubble |
| Outgoing bubble | `[data-testid="msg-container"]:has(span[data-icon="tail-out"])` | Fallback; only the first bubble of a group has a tail |
| Incoming bubble | `[data-testid="msg-container"]:has(span[data-icon="tail-in"])` | Fallback; untailed bubbles continue the group |
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
3. `live`: the interval since the previous send (or since the chat opened) is a random value
   between `--min-interval` and `--max-interval` (default 8 to 25 seconds) and includes the
   typing; the sales agent passes its own per-message intervals.
4. Optional image: set the image input, wait for the preview, click Send in the preview.
5. Type the message in small chunks, 35 to 95 ms per character, extra 150 to 450 ms after
   `.`, `,`, `?` and `!`. Never paste the whole text.
6. Click Send (or press Enter when the button is absent).
7. Poll for up to 8 s until the newest outgoing bubble is new (its `data-id` was not there
   before typing) and contains the first characters of the message. A message with a link
   waits at least 3 s after typing for the preview card.
8. Journal `sent` or `unconfirmed`. `sent` is final; `unconfirmed` is never retried blindly.

## Incoming event listener

The listener turns incoming messages into durable events and records which contact wrote.
It reads the **chat list previews** instead of opening conversations, so it never marks the
owner's chats as read.

```bash
python3 -m tools.ytbot commercial listen --network whatsapp --once
python3 -m tools.ytbot commercial listen --network whatsapp --interval 30
python3 -m tools.ytbot commercial events --network whatsapp --limit 20
python3 -m tools.ytbot commercial rules  --network whatsapp --mode allow \
  --contacts "Renê,Frotas do L"
```

Event schema in `.local/commercial/whatsapp/events.jsonl`:

```json
{"id":"<sha256[0:20]>","at":"2026-11-17T12:35:50","message_at":"12:32 PM",
 "chat":"Renê","text":"Já mudei","unread":true,"allowed":true}
```

- `chat` is the contact or group name; group previews keep the sender prefix (`João: Sim`).
- `id` hashes chat, preview and time; `seen.json` stores the last 5000 ids so a scan never
  duplicates an event.
- `allowed` comes from `rules.json`: `mode: allow` replies only to listed contacts; `mode:
  block` replies to everyone except them. Matching is case-insensitive and accepts partial
  names. The default is `allow` with an empty list, so nothing is auto-approved.
- Rows are read through the test ids above; a row whose last message carries the delivered or
  read check, or a preview that starts with `You:`/`Você:`, is the owner's own message and is
  skipped. Older layouts fall back to the row text, where the title is the line before the time.

Limits: the listener sees only the newest preview per chat, so it does not backfill history;
media show as labels (`Photo`, `Sticker`, `Audio`); an edited message can re-emit if its
preview changes. Automated replies come only from the
[sales agent](COMMERCIAL-WHATSAPP-SALES.md), only to funnel leads allowed by `rules.json`;
phone entries in `rules.json` match chat titles by their last eight digits.

The approach follows the WhatsApp Web adapter already validated in
[MeuAssistente](https://github.com/AlexandreZanata/MeuAssistente): contact-scoped observation,
hashed deduplication and explicit filters. This module keeps the lighter preview-based scan
so it cannot disturb the owner's unread state.

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
| Page or connection closed after a suspend | `TargetClosedError` in `sales run` | The run reconnects on its own (3 times in a row at most); a send in progress is fenced, never retried |
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
