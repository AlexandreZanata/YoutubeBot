# WhatsApp sales agent (Zaflas Inova Simples)

The sales agent offers sites, systems and apps from Zaflas Inova Simples to businesses that
have no website on Google Maps. It holds real conversations on the owner's WhatsApp Web
session, following one versioned rules file. It reuses the sender, the DOM map, the listener
and the journal in [WhatsApp Web](COMMERCIAL-WHATSAPP.md); there is no second send path.

## Owner decisions (2026-11-17)

| Topic | Decision |
| --- | --- |
| First contact | One-to-one prospecting, only to numbers from a list the owner approved. No broadcast. |
| Lead source | A CSV the owner builds by reviewing Google Maps. No scraping, no Places API. |
| Replies | OpenCode Go plan, model `deepseek-v4.1-flash` only, called like OpenTatu's client. |
| Daily limit | 10 first contacts per day. |

## Files

| File | Role |
| --- | --- |
| `tools/ytbot/commercial/whatsapp/sales/sales_rules.toml` | Rules: opening, follow-up, facts, prices, intents, limits, hours, pacing, model |
| `tools/ytbot/commercial/whatsapp/sales/context.md` | Context model sent to the model (pt-BR instructions) |
| `sales/rules.py` | Loads and validates the rules; derives the allowed values |
| `sales/classifier.py` | Local Portuguese intent classifier with conversation context |
| `sales/llm.py` | OpenCode Go client (Bearer key, `x-opencode-session`, JSON mode, no retries) |
| `sales/decide.py` | Classifier + model + guard + fixed texts into one decision |
| `sales/guard.py` | Rejects model text with values, links, terms or claims outside the rules |
| `sales/pacing.py` | Wait proportional to message length |
| `sales/agent.py` | Conversation state machine, follow-ups, openings, owner hand-off |
| `sales/store.py` | Leads, memory, do-not-contact list, logs |
| `sales/commands.py` | `commercial sales ...` CLI |

Private state under `.local/commercial/whatsapp/sales/` (0700 directory, 0600 files):

| File | Content |
| --- | --- |
| `leads.json` | Imported leads, state and counters (phone numbers live only here) |
| `conversations/<lead>.jsonl` | Full memory: every message sent and received |
| `do-not-contact.json` | Salted hashes of refused numbers; survives a lead reset |
| `decisions.jsonl` | Each decision: intent, source, guard violations, messages |
| `handoff.jsonl` | Conversations sent to the owner, with the reason |
| `llm-usage.jsonl` | Model, tokens, cost and duration per call; never content |
| `llm.env` | `OPENCODE_GO_API_KEY=...` (the owner's test key) |

The shared `journal.jsonl`, `events.jsonl` and `rules.json` keep their formats; journal lines
gain `kind` (`sales-opening`, `sales-reply`, `sales-followup`), `lead` and `intent`.

## Leads from Google Maps

Scraping Google Maps breaks Google's terms, so leads come only from the owner's review. Open
Maps, search a category and city, open each business without a website, and copy name and
phone into a CSV:

```csv
name,phone,city,category,maps_url,website,note
Barbearia Exemplo,(65) 90000-0001,Cuiabá,Barbearia,https://maps.app.goo.gl/...,,
```

`import` accepts `name` and `phone` (required) plus the optional columns. It rejects a row whose
phone is not a valid Brazilian number, whose `website` is filled (the opening says they have no
site) or whose `maps_url` is not a Google Maps link; it skips duplicates and numbers on the
do-not-contact list. Importing is the owner's approval of the list. Keep the CSV outside the
repository.

## Commands

Everything is dry-run unless `--live`. `run` needs the logged-in WhatsApp session; the other
commands work offline.

```bash
python3 -m tools.ytbot commercial sales check    --network whatsapp [--ping]
python3 -m tools.ytbot commercial sales import   --network whatsapp --csv ~/leads.csv
python3 -m tools.ytbot commercial sales leads    --network whatsapp [--state opened]
python3 -m tools.ytbot commercial sales simulate --network whatsapp --text "Quanto custa?"
python3 -m tools.ytbot commercial sales run      --network whatsapp --once
python3 -m tools.ytbot commercial sales run      --network whatsapp --live --interval 30
python3 -m tools.ytbot commercial sales run      --network whatsapp --live --prospect --limit 3
python3 -m tools.ytbot commercial sales handoffs --network whatsapp
python3 -m tools.ytbot commercial sales history  --network whatsapp --lead L1a2b3c4d5e
python3 -m tools.ytbot commercial sales resolve  --network whatsapp --lead L1a2b3c4d5e --state engaged
python3 -m tools.ytbot commercial sales block    --network whatsapp --lead L1a2b3c4d5e
```

- `check` validates the rules and shows the counters; `--ping` makes one tiny paid call.
- `simulate` prints the decision and the delays for a hypothetical message; it never sends.
- `run` scans the chat list (listener), stores incoming messages of funnel leads, answers
  them, sends due follow-ups and, with `--prospect`, opens new leads up to the daily limit.
  Without `--live` it prints the decisions and changes no lead state. It stops on the first
  send that is not confirmed.
- `resolve` hands a conversation back to the agent after the owner handled it; `block` adds the
  number to the do-not-contact list.

## Conversation state machine

```text
new ──opening──▶ opened ──72 h without answer──▶ followed-up ──96 h──▶ no-response
                   │                                  │
                   └────────── incoming ──────────────┴──▶ engaged ◀──▶ qualifying ──▶ quote-requested
engaged ──refusal / opt-out──▶ do-not-contact     engaged ──unknown / call / media──▶ needs-owner
engaged ──already has a site / later──▶ closed    send not confirmed ──▶ unconfirmed
owner typed in the chat ──▶ owner                 number without WhatsApp ──▶ invalid-number
```

| State | Automated messages | Leaves by |
| --- | --- | --- |
| `new` | Opening (in the opening window, daily limit) | Opening, or the lead writes first |
| `opening` | — (recorded before the browser acts) | Opening confirmed or fenced |
| `opened` | One follow-up after 72 h without an answer | Incoming, follow-up, 96 h |
| `followed-up` | None | Incoming, or `no-response` after 96 h |
| `engaged` | Replies | Intent action |
| `qualifying` | Replies; any project text becomes `quote_details` | Details → `quote-requested` |
| `closed` | None until the lead writes again | Incoming → `engaged` |
| `quote-requested`, `needs-owner`, `owner`, `unconfirmed` | None; new messages notify the owner | `resolve` |
| `do-not-contact` | Never | A new message only notifies the owner |
| `no-response`, `invalid-number` | Never | Incoming (no-response) |

## Cases

Texts are in `sales_rules.toml`; "fixed" texts are sent verbatim, the others may be reworded by
the model using only the facts.

| Case | Intent | Action | Answer |
| --- | --- | --- | --- |
| First contact | opening | — | "Bom dia" (Boa tarde/Boa noite by hour) → "Tudo bem?" → introduction → "Nós temos alguns exemplos…" → four links, one per message |
| "Nesse momento não estou precisando", "não, obrigado", "agora não", "não" after the quote offer | `refusal` | block | Fixed thanks, then never contact again |
| "Para de mandar", "spam", "vou denunciar" | `opt_out` | block | Fixed apology, never contact again |
| Business auto-reply (absence, hours, menu) | `auto_reply` | ignore | Nothing, avoids bot loops |
| "É robô?", "é automático?" | `bot_question` | reply | Fixed honest answer: an automated assistant helps; the owner follows every chat |
| "Como conseguiu meu número?" | `how_got_number` | reply | Fixed: public Google Maps profile, plus the offer to stop |
| "Quem é?" | `who_are_you` | reply | Alexandre, Zaflas Inova Simples, what it does |
| Wants a simple site, "como funciona?" | `site_institutional` | reply | Static site explained for laypeople; R$ 500 average, R$ 250 down, about 15 days; server R$ 39,90/month (boleto or Pix) or R$ 45 (card); offer a quote |
| Asks for a system, app, scheduling, store, login | `system_request` | reply | Fixed: "Sim, nós podemos fazer isso." + "Você gostaria que eu fizesse um orçamento?" |
| "Quanto custa?" | `price` | reply | Site values from the facts; systems need a quote; offer a quote |
| "Qual o prazo?" | `deadline` | reply | About 15 days for a site; systems in the quote |
| Server, hosting, monthly fee | `hosting` | reply | Server values |
| Payment, down payment, Pix, card | `payment` | reply | R$ 250 down; the rest in the quote |
| Asks for examples | `examples` | reply | The four links, one per message |
| "Tenho interesse", "gostei" | `interested` | reply | Offer a quote |
| "Sim" after the quote offer | `quote_accept` | qualify | Asks the business type and what the site or system should have |
| Project description while qualifying | `quote_details` | quote | Fixed ack; the owner prepares the quote (notified) |
| "Me liga", meeting, visit | `call_request` | handoff | Fixed: asks the best time; the owner calls |
| Audio | `audio` | handoff | Fixed: cannot listen now, asks for text; owner notified |
| Photo, video, document, location | `media` | handoff | Fixed ack; owner notified |
| Sticker or GIF only | `sticker` | ignore | Nothing |
| "Já temos site" | `already_has_site` | close | Thanks; available later |
| "Vou pensar", "mais pra frente" | `later` | close | Available whenever they want |
| "Tudo bem e você?" | `greeting_reply` | reply | Short answer and an open question |
| "Obrigado", "ok" | `thanks` | ignore | Nothing |
| Anything not in the facts: city, invoice, contract, negotiation ("faz por 300?"), complaint, ambiguous text | `unknown` | handoff | Fixed: "Boa pergunta! Vou verificar direitinho e já te respondo."; owner notified |
| Message outside 07:00–21:00 | — | — | Stored; answered at the start of the next reply window |
| The owner typed in the chat | — | — | Detected when the chat opens; state `owner`, automation pauses |
| A refused contact writes again | — | — | No automated answer; owner notified |

## Decision pipeline

1. The listener scans chat previews; events from funnel leads (matched by phone digits or the
   saved name) enter the lead's memory. Other chats are never touched.
2. In live mode the agent opens the chat by number, reads the recent bubbles, replaces a
   truncated preview with the full text and pauses if the last bubble is a message the owner
   typed.
3. The local classifier labels the unanswered text. Short refusals, opt-outs, auto-replies,
   robot questions and media labels are final without a model call.
4. Otherwise the model receives the context model, the facts, the intents, the lead's public
   profile, the full history and the local label, and answers JSON:
   `{"intent", "messages", "handoff", "do_not_contact", "reason"}`.
5. A refusal from either side blocks. `handoff` sends only the owner's ack. Fixed intents and
   every `block`, `handoff`, `quote` or `ignore` action send the rules' text. Model text is sent
   only for `reply`, `qualify` and `close`, and only when the guard accepts it.
6. The guard rejects any money value, number, percentage, e-mail, link, forbidden term
   (discount, free, guarantee, installment, Pix key, password, CPF/CNPJ…) or claim to be human
   that is not in the rules; the rules' text for that intent is sent instead. A robot question
   inside a longer message always gets the honest text first.
7. Without a key, or when the call fails, the local intent decides with the fixed texts and
   unknown cases go to the owner.

## Pacing

Every interval is counted from the previous send and already includes the typing, so the
contact sees the messages arrive at these gaps. Owner values (2026-11-17):

| Message | Interval |
| --- | --- |
| Greeting ("Bom dia" / "Boa tarde") | 4 s |
| "Tudo bem?" | 2 s |
| Introduction | 8 s |
| "Nós temos alguns exemplos…" | 8 s |
| Each link | 4 s (at least 3 s after typing it, for the preview card) |
| Reply message | its length at 20 characters per second, ±15 %, clamped to 2–10 s |
| First message of a reply | plus reading time, 40 characters per second, 1–4 s |
| Between two chats | 10–30 s |

The send is confirmed as soon as the new bubble appears (polled for up to 8 s). One
conversation at a time; typing stays the sender's chunked typing, never a paste. All values
live in `[opening]` and `[pacing]` of the rules file.

## Safeguards

- `--live` is required to send; the default prints the plan.
- Refusal or opt-out → salted hash in `do-not-contact.json`, removal from the `rules.json`
  allow list, and no message ever again, including follow-ups and re-imports.
- At most 10 first contacts per day (America/Cuiaba), weekdays 08:30–17:30.
- The opening is recorded before the browser acts and its journal keys are per lead, so it is
  never repeated, even after a crash.
- One follow-up after 72 h without an answer; `no-response` 96 h later, then silence.
- At most 12 automated replies per lead per day; then the owner takes over.
- Every message is journaled `started` before typing; an `unconfirmed`, `error` or dangling
  `started` key is never retried and the run stops.
- Honest answer to "is this a robot?"; the model may never deny being automated.
- No detection evasion, no identity switching, no second account.
- Only leads in the funnel get automated replies, and only when `rules.json` allows them
  (opening a lead adds its number in `allow` mode; a `block` entry always wins).

## Model and privacy

- Endpoint `https://opencode.ai/inference/go/openai/v1/chat/completions`, `Authorization:
  Bearer`, `User-Agent: YoutubeBot-Sales/1.0`, `x-opencode-session: zaflas-sales-<lead>`, JSON
  mode, temperature 0.3, no redirects or automatic retries. Research and limits: OpenTatu
  `docs/opencode-go.md`.
- Only `deepseek-v4.1-flash` is accepted; the rules loader and the client refuse any other.
- The key is read from `OPENCODE_GO_API_KEY` or `.local/commercial/whatsapp/sales/llm.env`;
  it never appears in logs, errors or records.
- The model receives the business name, category and city, the conversation and the rules.
  Phone numbers never leave the PC. DeepSeek on OpenCode Go is zero-retention under an
  agreement renewed monthly (valid through 2026-11-30 at the OpenTatu research); re-check it.
- Each call costs about US$ 0.0005 on the Go plan; `llm-usage.jsonl` records the charge.

## Physical test checklist (owner account)

Automated tests use fixtures only; these steps need the owner's WhatsApp and a second phone:

- [ ] `commercial status --network whatsapp` returns `logged-in`.
- [ ] `sales check --ping` answers `{"pong": true}`.
- [ ] Import a CSV with only the owner's second phone; `sales run --prospect --once` (dry-run)
      lists the opening.
- [ ] `sales run --live --prospect --limit 1 --once`: the eight bubbles arrive in order and
      each link shows its preview card.
- [ ] Reply "quanto custa um site?" from the second phone; `sales run --live --once` answers
      with the rules' values.
- [ ] Reply "não, obrigado"; the agent thanks, the lead becomes `do-not-contact`, and a new
      message only notifies the owner.
- [ ] Type a reply yourself in the chat; the next run marks the lead `owner`.
- [ ] Confirm that bubble directions (`data-id` prefix) and the click-to-chat invalid-number
      text still match the [DOM map](COMMERCIAL-WHATSAPP.md).

## Known limits

- The listener sees only the newest preview per chat; the full text is read when the chat is
  opened to answer. In dry-run the decision uses the preview.
- WhatsApp may restrict accounts that message many unknown numbers; the daily limit and the
  pacing reduce the risk but do not remove it. Stop at the first warning banner.
- The link preview wait is at least 3 s inside the 4 s interval; a slow site may still send
  without its card.
- Bubble direction comes from tails or row classes (in the 2026 client `data-id` is the bare
  message id); re-check them after a WhatsApp Web update.
- A contact saved in the owner's phone shows its saved name as the chat title; the lead must
  carry that name (the CSV `name`) for its replies to be matched.
