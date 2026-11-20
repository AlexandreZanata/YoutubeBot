# WhatsApp lanchonete ordering agent (Brasa & Pão)

The lanchonete agent takes orders on the owner's WhatsApp Web session, from the first message to
a confirmed order ficha for the kitchen. It is a separate module beside the Zaflas sales agent
and inherits the same building blocks: the sender, the DOM map, the listener, the resumable
journal, the private `SalesStore` (locking, phone validation, do-not-contact hashes), the model
router, local transcription and pacing. It never touches the sales funnel.

The demo brand is **Brasa & Pão**, a neighbourhood lanchonete. The owner replaces the name,
address, hours and prices in the rules file before the first live use; no value is
invented outside that file.

## Files

| File | Role |
| --- | --- |
| `tools/ytbot/commercial/whatsapp/lanchonete/lanchonete_rules.toml` | Identity, menu, extras, delivery, payments, hours, intents, texts, limits |
| `lanchonete/context.md` | Context rules the optional model receives (only catalog ids, never a price) |
| `lanchonete/rules.py` | Loads and validates the rules; menu rendering and allowed money values |
| `lanchonete/order.py` | The cart: lines, extras, fees, payment, change, totals, WhatsApp summary, ficha |
| `lanchonete/parser.py` | Local Portuguese order reading (items, quantities, extras, notes, fields, unknown fragments) |
| `lanchonete/semantics.py` | Semantic menu comparisons, category inquiries, destructive-action detection and harassment policy |
| `lanchonete/interpreter.py` | Optional model reading of free-form text into catalog ids |
| `lanchonete/guard.py` | Rejects a reply with a price, link or term outside the rules/order |
| `lanchonete/agent.py` | Conversation state machine, field collection, confirmation, owner hand-off |
| `lanchonete/store.py` | Customers, order numbering, `pedidos/` folders and the private index |
| `lanchonete/commands.py` | `commercial lanchonete ...` CLI |

Private state under `.local/commercial/whatsapp/lanchonete/` (0700/0600):

| Path | Content |
| --- | --- |
| `leads.json` | Customers, chat title, state, draft cart and counters |
| `conversations/<customer>.jsonl` | Full memory of the chat |
| `pedidos.json` | Confirmed-order index (number, total, type, payment, ficha path) |
| `pedidos/<number>/pedido.md` | Kitchen ficha: customer, address, items, extras, totals, payment |
| `pedidos/<number>/pedido.json` | The same order as data |
| `pedidos/<number>/conversa.md` | The conversation that produced the order |
| `clientes/<label>-<id>/midia/` | Photos and voice notes the customer sent |
| `decisions.jsonl`, `handoff.jsonl`, `llm-usage.jsonl` | Decisions, owner hand-offs, model cost |
| `debug/` | Private screenshots of a failed send |

The shared `journal.jsonl`, `events.jsonl`, `seen.json`, `rules.json` and `llm.env` keep their
formats. Journal lines gain `kind: lanchonete-order`, `lead` and `intent`.

## Menu, extras and payments

The menu has 32 items in six categories: burgers, hot dogs, portions, combos, drinks and
desserts. Every item has a fixed price in cents, aliases for WhatsApp spelling and a short
description. Extras have their own price and the categories where they apply:

| Extra | Price | Extra | Price |
| --- | --- | --- | --- |
| Bacon | R$ 4,00 | Queijo | R$ 2,50 |
| Cheddar | R$ 3,50 | Ovo | R$ 2,00 |
| Maionese da casa | R$ 2,00 | Cebola caramelizada | R$ 2,50 |
| Presunto | R$ 2,50 | Calabresa | R$ 3,00 |
| Molho especial | R$ 1,50 | Batata palha | R$ 2,00 |
| Hambúrguer extra | R$ 7,00 | Frango extra | R$ 6,00 |
| Catupiry | R$ 3,50 | Ovomaltine | R$ 2,00 |
| Calda de chocolate | R$ 2,00 | Chantilly | R$ 1,50 |

An extra is charged per unit: two X-Bacon with bacon cost `2 × (R$ 24,00 + R$ 4,00)`. The
kitchen ficha lists the unit price and the total of each line. The full menu, descriptions and
aliases are in the rules file; the bot sends them from there, never from a hardcoded copy.

Delivery is R$ 5,00, free above R$ 60,00, with a R$ 15,00 minimum for delivery. Pickup has no
fee and no minimum. Payment methods: Pix, cash (with change) and card (debit or credit at
delivery or pickup). The bot never stores or sends a Pix key; on a Pix order the owner receives
the ficha and sends the key in the same chat.

## Hours and service

- Orders: every day, 18:00–23:00, America/Cuiaba.
- A draft started before 23:00 may be finished until 23:30; after that the bot closes.
- Outside the window the bot sends one closed notice per `closed_notice_minutes` (60) and
  stores the message. It does not take an order for later without the owner.
- It only replies to people who wrote first. There is no prospecting, no broadcast and no
  follow-up.

## Conversation state machine

```text
first message ─▶ ordering ──"só isso / fechar"──▶ asks the missing fields ──▶ confirming
                    │                                                           │
                    │                                                    SIM   │   correction
                    │                                                           ▼   │
                    │                                                       confirmed
                    │                                                           │
                    ├─ "cancela" ─▶ cancelled (before the kitchen)             │
                    ├─ refusal / opt-out ─▶ do-not-contact                      │
                    ├─ outside hours ─▶ closed                                  │
                    └─ staff/person/media/complaint ─▶ needs-owner ◀────────────┘
owner typed in the chat ─▶ human        send not confirmed ─▶ unconfirmed
```

| State | Automated messages | Leaves by |
| --- | --- | --- |
| `new` | Greeting + menu (or the customer's order) | First reply |
| `ordering` | Cart, next question | "fechar" → field collection |
| `confirming` | Full summary, correction | SIM → confirmed; max corrections → owner |
| `confirmed` | None; new messages notify the owner | Owner resolves |
| `cancelled` | "Pedido cancelado" | New message starts a new order |
| `closed` | Closed notice once per hour | Window opens and customer writes |
| `needs-owner`, `human` | None; new messages notify the owner | `resolve` |
| `unconfirmed` | None; the owner checks the chat | `recover` or `resolve` |
| `do-not-contact` | Never | Owner decision; a new message only notifies |

The bot collects, in this order: order type (delivery or pickup), full address (delivery only),
name, payment method and change (cash only). Before confirming it checks the R$ 15,00 delivery
minimum, the R$ 300,00 automatic-order ceiling and the per-item quantity limit. A larger order
goes to the owner with the cart intact.

## Confirmation and ficha

The customer sees the complete order and must answer `SIM` (or an equivalent) before anything
reaches the kitchen:

```text
Confere seu pedido? 🧾

*Pedido:* entrega
*Nome:* Maria
*Endereço:* Rua das Flores, 123 — Centro
*Itens:*
• 2x X-Bacon (Bacon extra) — R$ 56,00
• 1x Coca-Cola lata 350 ml — R$ 6,00
*Subtotal:* R$ 62,00
*Entrega:* sem taxa
*Total:* R$ 62,00
*Pagamento:* Dinheiro — troco para R$ 100,00 (troco de R$ 38,00)
```

After `SIM` the order becomes `BP-YYYYMMDD-NNN`, the ficha is written and the owner gets a hot
notification with the total, type, payment and ficha path. A correction updates the summary
without losing the order; after `max_confirmations` (2) the owner takes over. A cancellation
after confirmation is a hot hand-off, because the kitchen may already have started.

## What the bot answers

Texts are in the rules file. The important cases:

| Customer says | Behaviour |
| --- | --- |
| "oi", "boa noite" | Greeting and prompt asking for items, a category or the menu (never dumps the full menu unasked) |
| "quero 2 x-bacon com bacon extra e uma coca" | Adds both lines with the exact extra price and shows the cart (plurals and trailing `x2`/`2x` match; `"sem cebola"` stays `"sem cebola"`) |
| "quero um lanche", "bebidas" | Sends only the requested category options and prices (preserving choices for ordinal/item replies) |
| "tira a coca", "sem a batata", "mais um x-salada" | Removes or adds the line and shows the new cart |
| "coloca bacon" | Adds the extra to the last line (or asks for an item if the cart is empty) |
| "quanto custa o x-bacon?", "tem x-tudo?" | Item description/price or ingredient/availability answer and offer question; does not add unasked |
| "qual o total?", "o que eu pedi?" | Shows the current cart and subtotal without treating it as a complaint |
| "me manda o cardápio" | Sends the configured `menu.url` website/app link or the text menu |
| "entrega ou retirada?" | Answers the delivery fee, minimum, free threshold and estimate |
| "aceita pix?" | Pix, cash and card; Pix key comes from the attendant |
| "pode fechar", "só isso" | Asks delivery/pickup, combines address + payment (re-asking only what is missing, including higher cash change), then full summary (accepts `👍`/`👎` on yes/no prompts) |
| "cadê meu pedido?" after confirmation | One holding reply (`confirmed_followup`), then silent owner hand-off, no invented status |
| "faltou item", "veio frio" | Owner hand-off (complaint) |
| "quero falar com o atendente" | Owner hand-off |
| "para de mandar mensagem" | Blocked and removed from the reply rules forever |
| "é robô?" | Honest answer: virtual attendant, owner follows the chat |
| Audio | Transcribed locally; the transcript is the order text |
| Photo, video, document | Owner hand-off; a caption is read as text |
| Anything outside the menu or size/diet variant ("coca zero") | Never invents or silently substitutes regular drinks; offers the matching category or hands to the owner |

The bot never writes a price, discount, free item, guarantee, Pix key or delivery promise
outside the rules. The guard checks every outgoing batch against the catalog and the current
order; a blocked batch becomes a short hand-off to the owner.

## Per-customer state and restart

Every customer has one row in `leads.json` (state, cart, delivery fields, awaiting message,
counters) and one `conversations/<id>.jsonl` memory file. Opening or restarting the bot reads
that state from disk; there is no shared conversation buffer. Two customers can order at the
same time without seeing each other's items.

`run --recover` is the normal restart flag: it only clears `unconfirmed` rows left by a failed
send, without resending anything. `human` and `needs-owner` remain untouched until the owner
uses `resolve`; those are real hand-offs, not transient failures. `opening` avoids the old
history entirely and `_open_chat` verifies the WhatsApp title before reading or sending, so a
stale tab cannot write one customer's bubbles into another customer's memory.

## Model use

The free-first `sales.llm.ModelRouter` is reused. The model has one job: read a free-form
message into catalog ids and field values, using `context.md`. It never writes a customer
message and never supplies a price or total. An invented id, an extra outside the item's
category, an invalid quantity or an over-limit order rejects the whole model answer; the local
parser or the fixed question handles the turn. Without an API key the bot still works from the
local parser and the fixed texts.

## Commands

Everything is dry-run unless `--live`. `run` needs the logged-in WhatsApp session; the rest
works offline.

```bash
python3 -m tools.ytbot commercial lanchonete check    --network whatsapp [--ping]
python3 -m tools.ytbot commercial lanchonete menu     --network whatsapp [--json]
python3 -m tools.ytbot commercial lanchonete simulate --network whatsapp --at 19:00 \
  --text "oi" --text "quero 2 x-bacon com bacon extra e uma coca" --text "fechar" \
  --text "retirada" --text "Ana" --text "pix" --text "sim"
python3 -m tools.ytbot commercial lanchonete allow     --network whatsapp \
  --phone "+55 66 90000-0001" --name "Cliente Teste" [--chat "Título no WhatsApp"]
python3 -m tools.ytbot commercial lanchonete opening   --network whatsapp --customer C...
python3 -m tools.ytbot commercial lanchonete customers --network whatsapp [--state ordering]
python3 -m tools.ytbot commercial lanchonete pedidos   --network whatsapp [--today]
python3 -m tools.ytbot commercial lanchonete ficha     --network whatsapp --order BP-20261118-001
python3 -m tools.ytbot commercial lanchonete resolve   --network whatsapp --customer C... \
  --state closed
python3 -m tools.ytbot commercial lanchonete recover   --network whatsapp --customer C...
python3 -m tools.ytbot commercial lanchonete recover   --network whatsapp --all
python3 -m tools.ytbot commercial lanchonete block     --network whatsapp --customer C...
python3 -m tools.ytbot commercial lanchonete run       --network whatsapp --once
python3 -m tools.ytbot commercial lanchonete run       --network whatsapp --live --interval 10 \
  [--recover]
```

- `check` validates the rules and prints the menu/payment/counter summary; `--ping` makes one
  small routed model call.
- `menu` prints the exact chat menu, extras with their prices and the payment rules.
- `simulate` plays a full conversation offline with a fresh temporary state and prints every
  reply, state and the order. It never sends and never touches the real database.
- `allow` registers a number and the exact WhatsApp chat title, so a saved contact can be
  recognized before the first message. `run --only <phone>` restricts the run to those numbers;
  repeat `--only` for more than one. Without `--only` the bot answers any chat that writes
  first, which is the normal dedicated-number mode.
- `opening` sends one greeting/menu to a registered customer without replaying the old chat.
  It skips blocks already recorded as sent, so a failed menu can be completed without repeating
  the bubbles the customer already received.
- `run` scans the chat list, answers ordering customers and confirms orders. A send failure
  fences only that customer (`unconfirmed`) and notifies the owner; the other chats continue.
  A browser page that closed outside a send reconnects up to three times. `SIGTERM` ends
  between two steps. `--recover` clears transient unconfirmed states at startup without
  retrying the uncertain message.
- `recover` clears `unconfirmed` for one customer or all of them; `resolve` hands a chat back
  to the bot after the owner handled it; `block` adds the number to the do-not-contact list.

## Safeguards

- `--live` is required to send; the default prints the plan.
- Only chats with a first inbound message are touched. Group-like previews (`João: ...` on a
  non-phone chat) are skipped; there is no group ordering.
- The journal records each message before typing; an `unconfirmed`, `error` or dangling
  `started` key is never retried. The affected customer is fenced and the run continues with
  the other chats. A `started`/`error` entry whose error is exactly "the text did not reach the
  composer; nothing was sent" may be retried, because no bubble was created.
- Refusal or opt-out goes to the do-not-contact store and the reply rules; no message ever
  again, including after a restart.
- At most 40 automated replies per customer per day and 30 bot replies per open order before the
  owner takes over; pure punctuation/emoji noise (`"???"`, `"👀"`) does not consume `max_unknown` strikes.
- A pending cart is persisted; the bot only confirms after the explicit summary confirmation.
  Orders exceeding `max_order_cents` or `max_lines` hand off to the owner immediately rather than
  collecting checkout fields first.
- Closed-hours messages after the single hourly notice write an internal `closed-ack` (`suppressed`)
  marker so unanswered out-of-hours messages never replay into the cart when the shop opens.
- Extras beyond `max_extras_per_item` truncate to the limit with a notice rather than dropping the item.
- The Pix key is never written to the rules, the ficha, the journal or the logs.
- One conversation at a time, human pacing between bubbles and between chats; no paste, no
  broadcast, no detection evasion.
- `needs-owner` keeps a per-customer cooldown on normal notifications, while waiting complaints
  (`"cadê o atendimento?"`) raise a `hot` hand-off immediately and send one holding confirmation.
- Incoming reading runs `effective(history)` so replaced chat-list previews never double-count
  alongside the opened chat bubble, and identical customer repeats within five minutes collapse
  into one turn.
- Partial orders apply valid catalog items, ask only about unrecognized items/sauces (without
  turning secondary items into notes), deflect first-strike sexual innuendo neutrally (escalating
  to `needs-owner` with `hot` priority on repetition or explicit content), and require explicit
  `SIM` confirmation before destructive reductions (`"deixa só um"`, `"tira tudo"`), `>3x` cart
  jumps, or uncertain numeric quantities in voice transcripts.
- Confirmed orders are written before the owner is notified; a disk error is an alert, not a
  silent confirmation.

## Physical test checklist (owner account)

Automated tests use fixtures only; these steps need the owner's WhatsApp and a second phone:

- [ ] `commercial status --network whatsapp` returns `logged-in`.
- [ ] `commercial lanchonete check --network whatsapp --ping` answers `{"pong": true}`.
- [ ] From the second phone, send "oi"; the greeting and five menu bubbles arrive in order.
- [ ] Send "quero 2 x-bacon com bacon extra e uma coca"; the cart shows R$ 62,00.
- [ ] Send "fechar", answer the five fields and confirm; the ficha appears under
      `.local/commercial/whatsapp/lanchonete/pedidos/` and the owner notification carries the
      total and the path.
- [ ] Send "tira a coca" at the summary; the summary updates instead of confirming.
- [ ] Send "meu pedido atrasou" after confirmation; only the owner is notified.
- [ ] Send "para de mandar mensagem"; no automated reply follows.
- [ ] Type in the chat yourself; the next run marks the customer `human`.
- [ ] Check the bubble directions and the click-to-chat invalid-number text against the
      [DOM map](COMMERCIAL-WHATSAPP.md).

## Known limits

- The listener sees only the newest preview per chat; the full text and media are read when the
  chat opens.
- A named (saved) chat is opened by title; a group with a name and no sender prefix could slip
  through. Use a dedicated number and review `customers`; `block` stops it.
- Delivery is a flat city fee; there is no neighbourhood table or geocoding. A distant address
  is confirmed by the owner.
- The voice transcription depends on the local faster-whisper model and the GPU; if it fails
  the audio goes to the owner.
- The menu, extras and fees are owner data: a wrong value in the rules file is sent as written
  and must be corrected there, never in code.
