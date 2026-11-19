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
| Replies | OpenCode Go free models first in rotation, then `deepseek-v4.1-flash` → `muse-spark-1.3-contributor` (updated the same evening). |
| Daily limit | 50 first contacts per day. |

## Files

| File | Role |
| --- | --- |
| `tools/ytbot/commercial/whatsapp/sales/sales_rules.toml` | Rules: opening, follow-up, facts, prices, intents, limits, hours, pacing, model |
| `tools/ytbot/commercial/whatsapp/sales/context.md` | Context model sent to the model (pt-BR instructions) |
| `sales/rules.py` | Loads and validates the rules; derives the allowed values |
| `sales/classifier.py` | Local Portuguese intent classifier with conversation context |
| `sales/llm.py` | Free-first model router (live catalog, parallel probe, rotation, pauses, fallback) and the OpenCode Go client |
| `sales/decide.py` | Classifier + model + guard + fixed texts into one decision |
| `sales/guard.py` | Rejects model text with values, links, terms or claims outside the rules |
| `sales/pacing.py` | Wait proportional to message length |
| `sales/agent.py` | Conversation state machine, follow-ups, openings, owner hand-off |
| `sales/store.py` | Leads, memory, do-not-contact list, logs |
| `sales/notify.py` | Owner hand-off record and desktop notification with the contact |
| `sales/rehearsal.py` + `scenarios.json` | Offline conversation rehearsal with the real model |
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

Leads come only from the owner's review. The slow, read-only research module described in
[Maps research](COMMERCIAL-MAPS-RESEARCH.md) can collect public listings into a candidate CSV
with the owner's own Google account; the owner still edits the file and imports it, so no row
enters the funnel without approval. Manual search also works: open Maps, search a category and
city, open each business without a website, and copy name and phone into a CSV:

```csv
name,phone,city,category,maps_url,website,note
Barbearia Exemplo,(65) 90000-0001,Cuiabá,Barbearia,https://maps.app.goo.gl/...,,
```

`import` accepts `name` and `phone` (required) plus the optional columns. It rejects a row whose
phone is not a valid Brazilian number, whose `website` is filled (the opening says they have no
site) or whose `maps_url` is not a Google Maps link; it skips duplicates and numbers on the
do-not-contact list. Importing is the owner's approval of the list. How the list is found and
filtered on Google Maps is in [Maps research](COMMERCIAL-MAPS-RESEARCH.md). Keep the CSV outside the
repository.

## Lead names and phone contacts

Every lead gets a category number when it enters the funnel: the CSV `category` becomes a slug
and a counter (`Barbearia` → `barbearia-1`, `barbearia-2`; `Salão de Beleza` →
`salao-de-beleza-1`; empty → `lead-N`). Numbers are never reused or renumbered. The phone
contact name is `<label> <name>` (`barbearia-1 Barbearia do Zé`), so searching `barbearia` on
the phone lists the whole niche and the label identifies the lead in notifications and in the
Central. When the owner saves that contact, WhatsApp shows it as the chat title; the agent
matches titles by phone digits, saved contact name or label prefix.

Each import writes `sales/contatos/novos-<data>.vcf` with the new batch and rewrites
`sales/contatos/todos.vcf` with every lead that may still be contacted (refused and invalid
numbers are left out). Import the file on the phone (Contacts → Import, or
contacts.google.com → Import, which syncs to the phone and WhatsApp). `sales contacts`
rewrites `todos.vcf` on demand.

Acquisition contract: every source (the reviewed Maps CSV, a manual Maps search, Receita
Federal data) adds leads through `SalesStore.import_rows(rows, now, source)` with `source` in
`google-maps-reviewed`, `google-maps-manual`, `receita-federal`, `manual`. The research CSV uses
`--source google-maps-manual`. Rows carry `name`, `phone` and optionally `category`, `city`,
`maps_url`, `website`, `note`; the same validation, do-not-contact check, numbering and vCard
apply to all of them.

## Central snapshot

After every cycle and every owner command the agent writes `sales/central.json` for the desktop
manager's Central page: `states` (19 states with Portuguese label, group and count),
`interventions` (conversations with the owner, hot first, with label, name, phone, wa.me link,
reason, last message and ficha), `messages` (the 100 most recent, both directions), `leads`
and `fichas`: every client folder with a `ficha.json` (also one from an earlier test cycle
whose lead link was reset), newest first, with `kind` (`site` or `sistema`), `status`,
`resumo`, `sections` (only the filled fields, as label/value), `pendencias`, `duvidas` (client
questions for the quote), `media` (absolute paths inside the client folder only: kind, name,
caption, time), `ficha_md`, `folder`, phone and wa.me link. The desktop Central shows them
with the photos. `sales central` refreshes it and prints what needs the owner.

| Group | States |
| --- | --- |
| Com você | `won` Venda fechada (site), `buying` Quer comprar (sistema), `needs-owner` Precisa de você, `quote-requested` Orçamento a fazer, `unconfirmed` Envio não confirmado, `owner` Você está atendendo, `lost` Desistiu |
| Em conversa | `qualifying` Coletando dados, `engaged` Em conversa, `gatekeeper` Falando com funcionário |
| Prospecção | `new` Novo, `opening` Abrindo conversa, `opened` Abordado, `followed-up` Follow-up enviado |
| Encerrados | `referred` Indicou o responsável, `closed` Encerrado, `no-response` Sem resposta, `do-not-contact` Não contatar, `invalid-number` Número sem WhatsApp |

## Commands

Everything is dry-run unless `--live`. `run` needs the logged-in WhatsApp session; the other
commands work offline.

```bash
python3 -m tools.ytbot commercial sales check    --network whatsapp [--ping]
python3 -m tools.ytbot commercial sales models   --network whatsapp
python3 -m tools.ytbot commercial sales import   --network whatsapp --csv ~/leads.csv
python3 -m tools.ytbot commercial sales activate --network whatsapp --all
python3 -m tools.ytbot commercial sales pause    --network whatsapp --lead L1a2b3c4d5e
python3 -m tools.ytbot commercial sales leads    --network whatsapp [--state opened]
python3 -m tools.ytbot commercial sales contacts --network whatsapp
python3 -m tools.ytbot commercial sales central  --network whatsapp [--json]
python3 -m tools.ytbot commercial sales simulate --network whatsapp --text "Quanto custa?"
python3 -m tools.ytbot commercial sales rehearse --network whatsapp [--only negoci] [--no-llm]
python3 -m tools.ytbot commercial sales run      --network whatsapp --once
python3 -m tools.ytbot commercial sales run      --network whatsapp --live --interval 10
python3 -m tools.ytbot commercial sales run      --network whatsapp --live --prospect --limit 3
python3 -m tools.ytbot commercial sales queue list --network whatsapp
python3 -m tools.ytbot commercial sales queue send --network whatsapp --dry-run
python3 -m tools.ytbot commercial sales queue send --network whatsapp --live --limit 1
python3 -m tools.ytbot commercial sales handoffs --network whatsapp
python3 -m tools.ytbot commercial sales history  --network whatsapp --lead L1a2b3c4d5e
python3 -m tools.ytbot commercial sales resolve  --network whatsapp --lead L1a2b3c4d5e --state engaged
python3 -m tools.ytbot commercial sales block    --network whatsapp --lead L1a2b3c4d5e
```

- `check` validates the rules and shows the counters; `--ping` makes one tiny paid call.
- `simulate` prints the decision and the delays for a hypothetical message; it never sends.
- `rehearse` replays the customer conversations in `sales/scenarios.json` (27, synthetic lead)
  through the real agent, rules and model with a fake WhatsApp, and prints each reply, state
  and hand-off. Run it after editing the rules; about US$ 0.02 per full run.
- `run` scans the chat list (listener), stores incoming messages of funnel leads, answers
  them, sends due follow-ups and, with `--prospect`, opens new leads up to the daily limit.
  Without `--live` it prints the decisions and changes no lead state. In continuous mode
  (without `--once`), `--prospect` opens at most one company per `between_openings` cooldown
  (120 to 180 seconds, persisted across restarts via `opened_at`) without blocking the loop,
  so the bot keeps scanning and replying to already-opened companies between openings; `--limit`
  caps the total openings of that run while keeping the reply loop alive afterward. Pass
  `--only-csv <path>` or `--only-leads <id1,id2>` to restrict `run` strictly to a target batch
  (and any referral created by those leads), leaving all other leads and personal chats untouched.
  A failed opening never stops the line and is never retried: `unconfirmed` stays fenced and an
  `error` keeps its `open_error`, each pulls one owner-approved replacement from
  `sales/importar/reserva-*.csv` to the end of the queue (same city first), and prospecting
  moves on with the 2–3 minute pacing. An `unconfirmed` or failed reply/follow-up (or any failure
  in `--once` / manual `queue send`) still stops the run immediately without touching further
  chats. An edited `sales_rules.toml` is reloaded
  before the next cycle; an invalid edit is reported and the previous rules stay in use. When the
  browser page or the CDP connection closes outside a send (including before typing inside
  `_open_chat`; the computer slept, Chrome restarted; seen on 2026-11-18 as `TargetClosedError`
  after a night), the run reconnects to the hidden browser and continues, up to 3 times in a row;
  a failed send still stops the run. Chat-list echo suppression compares only the latest outgoing
  bubble (so short customer replies like `"Bom dia"` or `"Tudo bem?"` are never dropped), and
  WhatsApp Business auto-replies (`auto_reply`) are always decided locally regardless of length.
  When a contact is actively typing (`"digitando..."` / `"typing..."` in the chat list or open
  chat header — strictly typing only, never audio recording), the lead is categorized in the
  `typing` wait state (`typing: true`, `state: "typing"`, `action: "wait"`): the bot sends
  nothing (also re-checking right before sending after model inference) until the contact finishes
  typing, then merges and answers all arrived bubbles together (capped at
  `max_typing_wait_seconds = 60` so a stuck browser indicator can never stall a chat).
  A `SIGTERM` asks the run to stop: it finishes the current step (never in the middle of a send),
  closes its WhatsApp tab and releases the run lock, so restarts no longer leave extra tabs in the
  hidden browser. A second `SIGTERM` stops at once; `SIGKILL` still leaves the tab open.
- `resolve` hands a conversation back to the agent after the owner handled it; `block` adds the
  number to the do-not-contact list.
- Every imported number starts with `reply_active: true`. If it writes before an opening, the
  agent stores the message and answers it (the lead moves to `engaged`); it never sends an
  opening to someone already in conversation. `activate --all` re-enables older leads,
  `pause --lead <id>` stops automatic replies and sends the message to "Precisa de você". `sales leads` and the
  Central show `reply: ativo` or `pausado`.
- Openings stay one number at a time, in import order, up to 50/day and only in the opening
  window. Use `--limit 1` to start exactly one number per invocation or `--limit 10` for the
  daily batch; the existing pacing, journal and repeat fences apply to both.
- The owner's selected list may be kept in
  `.local/commercial/whatsapp/sales/importar/<city>-<date>.csv`, using the same columns as
  `import` (`name,phone,city,category,maps_url,website,note`). The folder is private and is
  never read automatically; importing is still the owner's explicit command.

## Opening queue (owner, 2026-11-18)

One number per command, in the order of the owner's CSV, with the business name in the
opening. There is no second store: the queue is a view of `leads.json`.

```bash
python3 -m tools.ytbot commercial sales import --network whatsapp \
  --csv .local/commercial/whatsapp/sales/importar/<city>-<date>.csv --source google-maps-manual
python3 -m tools.ytbot commercial sales queue list --network whatsapp          # order, status, next
python3 -m tools.ytbot commercial sales queue send --network whatsapp --dry-run   # exact messages
python3 -m tools.ytbot commercial sales queue send --network whatsapp --live --limit 1
```

- **Membership and order.** `import` gives each new lead from a Maps source
  (`google-maps-reviewed`, `google-maps-manual`) a `queue_position` in CSV row order; earlier
  imports come first. Referrals (their own opening and limit), other sources, duplicates and
  do-not-contact numbers never enter the queue, and nothing is sent at import. The order is
  never re-sorted by score at send time.
- **Status** comes from the lead, never from a separate file: `pending` (`new`), `sending`
  (`opening`), `sent` (opened, whatever happened after), `unconfirmed`, `skipped`
  (do-not-contact, no WhatsApp, or the number wrote first and is already being answered) and
  `error` (the chat did not open; nothing was typed, so a later manual `send` may try again).
  `queue list` masks every phone.
- **Sending.** `queue send` is a dry run unless `--live`; `--limit` defaults to 1 (use 10 for the
  day's batch, still one conversation at a time). Live, it takes the same run lock as `run`,
  opens the same hidden WhatsApp browser and goes through `prospect` → `open_lead` →
  `send_sequence`: the lead becomes `opening` with `opened_at` before the browser acts, the
  journal fences every bubble, and a lead is `sent` only when `open_lead` returns `opened`. It
  stops at the first `unconfirmed` and retries nothing by itself; an `error` (chat never opened,
  nothing typed) is skipped and the next number goes on, keeping the 2–3 minute pacing. A failed
  opening pulls one owner-approved replacement from `sales/importar/reserva-*.csv` to the end of
  the queue (same city first) and is never retried. The opening window
  (07:00 to 17:00, Monday to Friday), the 50/day limit, pacing, do-not-contact and invalid
  numbers apply exactly as in `run --prospect`; a blocked run prints the reason.
- **One sender at a time.** `queue send --live` and `run` share the lock, so one refuses while
  the other runs. Stop the `run` loop (SIGTERM ends it between two steps), send, then start it
  again; replies wait for the next `run` cycle meanwhile.
- **Crash recovery.** A lead left in `opening` (the process died mid-send) is reconciled by the
  next `queue send --live` or `run --live`: it becomes `unconfirmed`, the owner is notified,
  and it is never sent again. `queue send` then stops so the owner checks that chat first.
- **The message.** The third bubble names the business exactly as on Google Maps:
  "Sou o Alexandre da empresa Zaflas Inova Simples, nossa empresa cria sistemas, sites e
  aplicativos. Eu vi que no Google Maps a empresa {company} ainda não tem site." `{company}`
  is the lead `name` (never the label, the saved contact name, a staff name or the note),
  spaces normalized, trailing punctuation removed ("Vem Sorrir em Sinop." would end the
  sentence) and cut at a word within `company_max_chars` (120); without a name the
  previous "vocês não têm site" text (`[opening] unnamed`) is sent. Greeting, order, delays and
  the four links are unchanged, and the opening never goes through the model. The phone number
  is never written in a message.

## Conversation state machine

```text
new ──opening──▶ opened ──72 h without answer──▶ followed-up ──96 h──▶ no-response
                   │                                  │
                   └────────── incoming ──────────────┴──▶ engaged ◀──▶ qualifying ──▶ quote-requested
engaged ──refusal──▶ needs-owner (indication ask sent)
engaged ──opt-out (parar, spam)──▶ do-not-contact     engaged ──unknown / call / media──▶ needs-owner
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
| First contact | opening | — | "Bom dia" (Boa tarde/Boa noite by hour) → "Tudo bem?" → introduction naming the business ("…a empresa {company} ainda não tem site.") → "Nós temos alguns exemplos…" → four links, one per message |
| "Nesse momento não estou precisando", "não, obrigado", "agora não", "não" after the quote offer | `refusal` | ask_referral | Sends the five-bubble indication request, then hands the chat to the owner (owner decision 2026-11-19) |
| "Para de mandar", "spam", "vou denunciar" | `opt_out` | block | Fixed apology, never contact again |
| Business auto-reply (absence, hours, menu) | `auto_reply` | ignore | Nothing, avoids bot loops |
| "É robô?", "é automático?" | `bot_question` | reply | Fixed honest answer: an automated assistant helps; the owner follows every chat |
| "Como conseguiu meu número?" | `how_got_number` | reply | Fixed: public Google Maps profile, plus the offer to stop |
| "Quem é?" | `who_are_you` | reply | Alexandre, Zaflas Inova Simples, what it does |
| Wants a simple site, "como funciona?" | `site_institutional` | reply | Static site explained for laypeople; R$ 500 average, R$ 250 down, about 15 days; server R$ 39,90/month (boleto or Pix) or R$ 45 (card); offer a quote |
| Asks for a system, app, scheduling, store, login | `system_request` | reply | Fixed: "Sim, nós podemos fazer isso." + "Você gostaria que eu fizesse um orçamento?" |
| Asks for an unusual project or custom platform (casino, betting, raffle, marketplace, social network, portal, SaaS) | `custom_platform` | qualify | Starts the requirements interview directly (`brief_kind: system`), asking how the system should work and what features it needs before handing off to the owner |
| "Quanto custa?" | `price` | reply | Site values from the facts; systems need a quote; offer a quote |
| "Qual o prazo?" | `deadline` | reply | About 15 days for a site; systems in the quote |
| Server, hosting, monthly fee | `hosting` | reply | Server values |
| Domain, `.com.br`, `registro.br` | `domain` | reply | Layperson explanation (`suaempresa.com.br`), `https://registro.br/` to test names, 3 options: buy manually, buy manually + we help configure, or we buy (+R$ 40 on 1st monthly fee for 1 year) |
| Payment, down payment, Pix, card | `payment` | reply | R$ 250 down; the rest in the quote |
| Asks for examples | `examples` | reply | The four links, one per message |
| "Não estou conseguindo abrir o link", "os sites não abrem", "não dá pra clicar" | `links_not_opening` | reply | Fixed: WhatsApp blocks links from numbers not saved in the phone; save the contact (Alexandre, da Zaflas Inova Simples) and tap again, or copy the address (zaflas.com.br) into the browser. No hand-off |
| "Tenho interesse", "gostei" | `interested` | reply | Offer a quote |
| "Sim" after the quote offer | `quote_accept` | qualify | Asks the business type and what the site or system should have |
| Project description while qualifying | `quote_details` | quote | Fixed ack; the owner prepares the quote (notified) |
| "Me liga", meeting, visit | `call_request` | handoff 🔥 | Fixed: asks the best time; the owner calls |
| "Quero falar com o Alexandre", "não com robô", "falar com gente" | `human_request` | handoff 🔥 | Fixed: "Claro! Já continuo com você pessoalmente." |
| "Quero fechar", "pode começar", "como pago a entrada" | `ready_to_buy` | handoff 🔥 | Fixed: the owner sends the next steps |
| "Me chama amanhã", "estou ocupado", "agora não posso" (never a refusal) | `callback_later` | handoff 🔥 | Fixed: "Sem problema! Te chamo depois então." |
| "Tá caro", "faz por 300?", desconto, parcelar | `negotiation` | handoff | Fixed: the owner decides conditions |
| "É golpe?", "é confiável?" | `trust_concern` | handoff | Fixed: acknowledges the care; the owner answers |
| "Não entendi", "como assim?" | `confused` | reply | Simpler explanation once; a second time is `stuck` |
| Same question again, or 8 bot replies without a quote | `stuck` | handoff | Fixed: "Desculpa se não fui claro! Já te respondo pessoalmente." |
| Audio | `audio` | handoff | Fixed: cannot listen now, asks for text; owner notified |
| Photo, video, document, location | `media` | handoff | Fixed ack; owner notified. A caption is read as the message text |
| Sticker or GIF only | `sticker` | ignore | Nothing |
| "Já temos site" | `already_has_site` | close | Thanks; available later |
| "Irei encaminhar para o responsável!!", "vou encaminhar para a diretoria/marketing", "já encaminhei" | `forwarded_to_decider` | close | Fixed: "Entendido, muito obrigado! Fico no aguardo do retorno." (no hand-off; chat reopens automatically if the decider writes back) |
| "Vou pensar", "mais pra frente" | `later` | close | Available whenever they want |
| "Tudo bem e você?" | `greeting_reply` | reply | Short answer and an open question |
| "Obrigado", "ok" | `thanks` | ignore | Nothing |
| Anything not in the facts: city, invoice, contract, technology, e-mail, ambiguous text | `unknown` | handoff | Fixed: "Certo! Vou verificar direitinho e já te respondo."; owner notified |
| Message outside 07:00–17:00 | — | — | Stored; answered at the start of the next reply window |
| The owner typed in the chat | — | — | Any message the bot did not send, after the bot's latest message in that chat (older personal or archived-cycle messages do not count), found when the chat opens to answer or to follow up; state `owner`, automation pauses |
| A refused contact writes again | — | — | No automated answer; owner notified |

## Staff, referral, closing and end states (owner, 2026-11-17)

```text
Someone says they will forward the proposal ("Irei encaminhar para o responsável!!", "vou encaminhar para o marketing")
  └─▶ forwarded_to_decider · fixed thanks + wait ("Entendido, muito obrigado! Fico no aguardo do retorno.") → state closed
      (no second contact request, no owner hand-off; chat reopens to engaged automatically if the decider writes back)

A staff member answers ("sou funcionária", "o dono não está", "vou passar pro dono")
  └─▶ gatekeeper · state gatekeeper (the bot keeps the chat)
      "Muito obrigado pelo retorno!"
      "Você poderia me passar o contato de quem cuida das decisões sobre site e divulgação
       da empresa? Assim eu falo direto com a pessoa e não tomo o seu tempo."
      "E com quem eu falo, por gentileza?"          (only while the name is unknown)
      their name → "Prazer, Paula! Você poderia me passar o contato …"
      no contact again ("ele te chama") → kind close, state closed

The chat receives a number ("o número do Carlos é (65) 9…")
  └─▶ referral (only a valid Brazilian number from the text, never the chat's own)
      to the staff member: "Muito obrigado, Paula! Vou falar com Carlos agora."  → referred
      new lead: next number of the same category (barbearia-2 "Carlos · Barbearia X"),
      source referral, vCard batch, linked to the staff chat
      opening to the new number, in the opening window, own daily limit (10), first in line:
        greeting → "Tudo bem?" → "Paula, da empresa Barbearia X, me passou o seu contato. Sou
        o Alexandre, da Zaflas Inova Simples: criamos sistemas, sites e aplicativos. Vi que no
        Google Maps a empresa Barbearia X ainda não tem site." → examples → links
      names never take an article ("da Felipe" was wrong in the 2026-11-17 test): the article
      goes with "empresa", people's names stand alone; the context model says the same
      a contact card without a visible number → owner: "salve o número e chame"
      a number already in the contacts (owner, 2026-11-18: a referred contact is always
        messaged) → that lead gets a new cycle and the same referral opening; its earlier
        history stays. Only a lead the owner is closing (owner, quote-requested, won,
        buying), an uncertain send (unconfirmed, opening), a number without WhatsApp or one
        on the do-not-contact list goes to the owner instead:
        "O número indicado já está nos contatos (barbearia-2, estado …)"

"Quero fechar" / "como pago a entrada" (checked before the quote "sim")
  ├─ the conversation is about the institutional site → close_site, state won:
  │     "Que ótimo! Para começarmos o seu site institucional, a entrada é de R$ 250. Pode
  │      fazer o Pix para uma destas chaves:" → "financeiro@zaflas.com.br" →
  │     "8e725568-04bd-47e9-9615-cf090a1929a7" → "Assim que a entrada for paga, começamos a
  │      construir o seu site. Se puder, me manda o comprovante por aqui."   🔥 owner
  ├─ about an app or a system → state buying ("Quer comprar"), no keys        🔥 owner
  └─ unclear → state buying with "não ficou claro se é site ou sistema"       🔥 owner
"Paguei / fiz o Pix / comprovante" in won → 🔥 "confira o Pix" at once; receipts are saved
A refusal after real interest (site or system) → state lost ("Desistiu"), thanks, owner
decides; it does not block the number. An opt-out or a refusal at the opening still blocks.
```

The interest of a lead (`site` or `system`) comes from what the conversation talked about:
system requests and app/system prices mark `system`; the institutional site, hosting and the
site close mark `site`, never overriding `system`. In `won`, `buying`, `lost` (and every owner
state) the bot stops answering; the Central lists them under "Com você".

### Prices: the site only

All values in the rules (R$ 500, R$ 250, R$ 39,90, R$ 45, 15 dias) are of the static
institutional site. Apps and systems are made to measure; their price and time depend on the
features and requirements and come only from the owner's quote. The rules state it in the facts,
in every price reference text and in the context model, and two fixed answers make it plain:

| Client | Intent | Answer |
| --- | --- | --- |
| "Então um aplicativo sai 500 reais?" | `app_at_site_price` | "Não, os R$ 500 são só do site institucional…", then made to measure, then the quote offer |
| "Quanto custa um aplicativo?" | `system_price` | Made to measure, not the site price, value in a specific quote, quote offer |
| "Vocês fazem aplicativo de delivery?" | `system_request` | "Sim, nós podemos fazer isso." + the made-to-measure note + quote offer |

The guard rejects any model sentence with a money value or a number of days that mentions an
app, system, store or scheduling without also saying "institucional".

## Client folder (ficha) and quote collection

After the contact accepts the quote (`quote_accept` → `qualifying`), every message is project
material (`quote_details`, action `collect`): text, photos (logo, place, work), phone numbers to
display on the site, and voice messages. Each round the model extracts the complete brief from
the client's own words (`sales/dossier.md`; empty fields stay empty, and "I don't have one yet"
or "you choose" is recorded instead of re-asked) and asks for at most two missing topics in plain
layperson Portuguese (`[brief] required`: business & services, contact/hours/social media for the
site, main brand colors & visual style, and domain choice; then `optional` once: logo, photos,
references), checked by the guard. When the collection reaches the domain step (and `registro.br`
was not sent yet), the bot sends `[brief] domain_messages`: a layperson explanation of what a
domain is (`suaempresa.com.br`), `https://registro.br/` in its own bubble to test available
names, and the three options (buy manually, buy manually and we help configure, or let us buy and
configure with an additional R$ 40 on the first monthly fee for the 1-year domain). The
collection ends when the client says it is done ("é isso", "só isso", "pode fazer o orçamento"),
when nothing required is missing, or after `max_collect_turns` (6). The bot then sends "Perfeito,
anotei tudo! Vou preparar o orçamento e te mando por aqui.", the lead becomes `quote-requested`
and the owner gets a 🔥 notification with the ficha path.

`.local/commercial/whatsapp/sales/clientes/<empresa>-<lead>/` (0700, files 0600):

| File | Content |
| --- | --- |
| `ficha.md` | Status, contact, summary, company, project, visual identity (main brand colors, visual style, background, logo, photos, references), domain (`registro.br` name & purchase/config option), contact & social media for the site, received materials with links, open items |
| `ficha.json` | The same brief as data, plus the lead and the file list |
| `conversa.md` | Whole conversation; audio shows its transcript, media its file |
| `midia/` | Images and voice messages the client sent (`20261117-155800-image.jpg`) |

### Apps and systems: the requirements interview (owner, 2026-11-18)

The bot does not hand the chat over just because the client wants more than the institutional
site. It interviews first, gently, and only then calls the owner:

```text
system_request (first time) → "Sim, nós podemos fazer isso" + clarification + offer question
the interview starts when the interest is an app or system and the client
  accepts the offer ("sim")                                   ┐
  asks for an unusual/custom platform ("site de cassino?")    │→ state qualifying, brief_kind system
  describes the system again after the offer                  ├→ [brief_system] start/start_custom
  asks something outside the facts ("emite nota fiscal?")     │   + tailored question
  wants to close ("quero fechar")  → start_buy, buy_intent    ┘
each answer → the model (`sales/dossier_system.md`) updates the requirements and writes the next
  message: a short restatement of what it understood + at most two simple questions, in the
  `[brief_system] required` order (company; the problem to solve; who uses it and roughly how
  many; main functions; how it is done today; phone app, browser or both; links to Pix,
  invoices, WhatsApp or other systems), then the optional items once
  a client question (price, deadline, "is it possible") is noted in `duvidas_do_cliente` and
  answered by the owner with the quote; the bot never promises a function
nothing missing, "é isso", or `max_collect_turns` (10) → the summary to confirm:
  "Deixa eu confirmar se entendi tudo certinho:" → summary → "Está certo? Se quiser ajustar…"
  a correction ("faltou…", "mas…") → updated summary (at most `max_confirmations` 2)
  "sim / certo / isso mesmo" → "Perfeito, anotei tudo! …" and 🔥 owner:
    quote-requested "Ficha do sistema completa: orçamento a fazer", or
    buying "Quer comprar o sistema: ficha de requisitos completa" when the client wanted to close
```

The summary and every question pass the guard (no numbers, prices, deadlines, links, promises);
an unsafe summary falls back to `resumo`, and without a safe one the bot hands over directly.
Overrides still win during the interview: opt-out, refusal, human or call request, links that
do not open, the robot question. The ficha (`kind` sistema) holds company, problem and goal, who
uses it, functions, data and reports, platforms and integrations, references, deadline, brand,
client questions and open items.

Material that arrives after the hand-off (a forgotten logo) is still downloaded and the ficha
is rebuilt (status "orçamento com o dono") without any message to the client; the owner gets
one reminder. `sales ficha --lead L…` rebuilds a folder on demand.

## Images and voice messages

When the agent opens a chat to answer, it reads every bubble since its last message:

- Images (`data-testid="image-thumb"`) are saved from their full-resolution `blob:` image; an
  album (several photos in one bubble) saves every photo; the caption is the message text. Outside the quote stage an image without caption is `media`
  (hand-off); during it, it is material.
- Voice messages are captured through a hook installed only on the bot's page
  (`sender.MEDIA_HOOK`: records the media WhatsApp plays or turns into object URLs, muted), then
  transcribed locally by faster-whisper large-v3-turbo on the GPU, Portuguese, beam 5 with word
  timestamps (`sales/transcribe.py`; ~2.5 s model load + ~0.5 s for a 26 s note; the project's
  subtitle transcriber is the fallback). The transcript is the message: classified, answered
  and stored as "Cliente (áudio transcrito)"; numbers heard with confidence below 0.6 are kept
  in `uncertain`. The voice never leaves the PC.
- Measured on the owner's test notes: beam 1, beam 5, a vocabulary prompt and hotwords gave the
  same words, and "9h74" was heard with 0.99 confidence, so it was what the client said. An
  impossible clock time is approximated to the logical value by carrying the minutes
  (`9h74` → `10h14`, `25:10` → `1:10`) and the brief notes the client's original words.
- If the audio cannot be read or transcribed, it falls back to the `audio` hand-off.
- Videos and documents are noted as `[vídeo]` / `[documento]` and handed to the owner.

## Typing safety

Before typing, `_open_by_phone` waits until the composer is visible (1.5 s hydration grace plus
the open-chat pause). Before typing a message, the composer gets focus by a click (8 s) or, when
something covers it (a new message banner while the chat scrolls), by focusing the element itself;
a leftover draft is cleared. After typing, and again right after the pacing wait before clicking Send,
the composer must still contain the text (if chat hydration cleared the draft once during the wait,
it re-types once before Send; otherwise it fails cleanly with nothing sent). Bubble confirmation
polls for 12 s matching either the raw prefix or normalized `text_key`. Any failure or `unconfirmed`
outcome is journaled with a private screenshot in `.local/commercial/whatsapp/sales/debug/`, and the
lead becomes `unconfirmed`: a failed reply/follow-up (or `--once` / `queue send`) stops the run,
while a failed cold opening in continuous `run --live --prospect` pauses further openings and keeps
reply monitoring active. After checking the chat, `sales resolve --state engaged|qualifying|opened`
hands it back; messages that arrived meanwhile are answered on the next cycle.

## Owner test reset

`sales reset --lead L… --yes` archives the conversation to
`conversations/<lead>.cycle<N>.jsonl` and makes the lead `new` again, with journal keys of a
new cycle, so the opening can be tested again on the owner's own test number. The automation
never resets; a number on the do-not-contact list cannot be reset; the daily limit applies.

## Hand-off to the owner

The bot stops at the first moment it cannot move the sale forward on its own. It sends one
short holding message, notifies the owner with the contact, moves the lead to `needs-owner`
(or `quote-requested`) and sends nothing more until `resolve`. Found with 24 simulated
conversations on the real model (2026-11-17).

| Priority | When | Intents and triggers |
| --- | --- | --- |
| 🔥 hot — answer within minutes | Buying signal | `quote_details` (project collected, ficha ready), `ready_to_buy` ("quero fechar", "como pago a entrada"), `human_request` ("quero falar com o Alexandre/com gente"), `call_request`, `callback_later` ("me chama amanhã") |
| ⚠️ needed — the bot lacks information or authority | The answer is not in the rules or needs a person | `negotiation` (caro, desconto, "faz por 300", parcelar), `trust_concern` ("é golpe?"), `unknown` (cidade, contrato, nota fiscal, tecnologia, e-mail), `audio`, `media`, the model's own `handoff`, `stuck` |
| 🛑 alert — something went wrong | Operational | send not confirmed, refused contact wrote again, outside `rules.json`, daily reply limit |

`stuck` is detected by the agent, not by words: the contact asked the same thing again (the
same intent twice in a row, e.g. "Quanto custa?" → "Mas quanto custa?", or a second
"não entendi"), or the bot already answered `max_bot_replies_before_owner` (8) times without
reaching a quote.

Each hand-off is a line in `handoff.jsonl` and a desktop notification (`notify-send`, urgency
critical for hot and alert):

```json
{"at": "2026-11-17T15:40:00-04:00", "lead": "L…", "name": "Barbearia Teste",
 "phone": "+55 65 90000-0001", "wa_link": "https://wa.me/5565900000001",
 "priority": "hot", "label": "🔥 Atender agora",
 "reason": "Quer fechar: perguntou como começar ou pagar", "intent": "ready_to_buy",
 "last_message": "Quero fechar, como faço pra pagar a entrada?",
 "recent": ["Alexandre: …", "Cliente: …"]}
```

New messages in a conversation that is already with the owner are stored and produce at most
one reminder per `owner_reminder_minutes` (30). `sales handoffs` lists the waiting
conversations; after answering, `sales resolve --state engaged` hands one back to the bot
(its repeat and reply counters restart).

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
5. A refusal from either side blocks. A local hand-off signal (buying, negotiation, human,
   trust, callback) is never weakened by the model: between two hand-offs the higher
   priority wins, and a model reply cannot cancel one. `handoff` sends only the owner's ack. Fixed intents and
   every `block`, `handoff`, `quote` or `ignore` action send the rules' text. Model text is sent
   only for `reply`, `qualify` and `close`, and only when the guard accepts it.
6. The guard rejects any money value, number, percentage, e-mail, link, forbidden term
   (discount, free, guarantee, installment, Pix key, password, CPF/CNPJ…), claim to be human,
   or a reply that says the quote will be made while also asking "Você gostaria que eu
   fizesse um orçamento?"; the rules' text for that intent is sent instead. A robot question
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
| Between two chats | 10–30 s (none when the next reply stays in the same chat) |

The send is confirmed as soon as the new bubble appears (polled for up to 8 s). The chat list
is scanned every 2 s (`--interval`, without reloading WhatsApp Web when the chat list is already
mounted, reading the top rows in one DOM evaluation). A chat that is already open for the same lead is reused:
no page reload and no between-chats pause, so a reply goes out about 10 to 20 s after the
message instead of 40 to 70 s (measured 2026-11-18: 43 s from the scan to the delivered reply,
30 s of it in the pause and the reload). One conversation at a time; typing stays the sender's chunked typing, never a paste. All values
live in `[opening]` and `[pacing]` of the rules file.

## Safeguards

- `--live` is required to send; the default prints the plan.
- Refusal or opt-out → salted hash in `do-not-contact.json`, removal from the `rules.json`
  allow list, and no message ever again, including follow-ups and re-imports.
- At most 50 first contacts per day (America/Cuiaba), weekdays 07:00–17:00 (replies also 07:00–17:00).
- The opening is recorded before the browser acts and its journal keys are per lead, so it is
  never repeated, even after a crash.
- One follow-up after 72 h without an answer; `no-response` 96 h later, then silence.
- Answers wait `pacing.reply_debounce_seconds` (30 s) after the newest incoming bubble, so a
  person splitting a thought into two or three messages is read as one turn and never answered
  mid-thought by a machine. The live loop enables it; direct unit calls do not.
- `referral_ask.messages` holds the owner's indication request as five short bubbles, sent when
  the lead refuses. Right after it the chat moves to `needs-owner` and the bot stops answering
  there: the owner takes over. A true opt-out ("para de me mandar", "spam", "me remove") still
  goes to the permanent do-not-contact list with its fixed apology.
- At most 12 automated replies per lead per day; then the owner takes over.
- Every message is journaled `started` before typing; an `unconfirmed`, `error` or dangling
  `started` key is never retried and the run stops.
- Honest answer to "is this a robot?"; the model may never deny being automated.
- No detection evasion, no identity switching, no second account.
- Only leads in the funnel get automated replies, and only when `rules.json` allows them
  (opening a lead adds its number in `allow` mode; a `block` entry always wins).

## Models: free first, rotation, fallback (owner, 2026-11-17)

`sales/llm.py` (`ModelRouter`) decides which OpenCode Go model answers each call:

1. **Discovery.** The live catalog `https://opencode.ai/inference/go/v1/models` (cached in
   `sales/models.json`, refreshed every hour) marks a model as free when its input and output
   prices are 0 and it speaks chat-completions. On 2026-11-17: `longcat-2.5-free`,
   `hy4-flash-free`, `beam-free`, `iceman-contributor-free`. A free model added later is used
   automatically; a paid model is never used unless it is in `llm.fallback`.
2. **Fast health check.** When the router starts and at every refresh, all free models get a
   tiny prompt in parallel (`probe_timeout_seconds` 8; measured 3.1 s for all four); a failing
   one is paused before any client waits on it.
3. **Rotation.** Calls go round-robin over the healthy free models. A free model has
   `free_timeout_seconds` (20) to answer; a timeout or an error pauses it `cooldown_seconds`
   (120), "no credits" or a rate limit (402, 429, quota) pauses it
   `no_credit_cooldown_seconds` (1800), and a reply that is not a JSON object moves on.
   A small optional lookup (the staff or decider name in a gatekeeper message) is `quick`:
   `quick_timeout_seconds` (8) per model and `quick_attempts` (2) models, then the local
   pattern result is used. Measured 2026-11-18: a hung `longcat-2.5-free` held that lookup,
   and the reply, for 20 s. The client ficha is `long`: a large compact JSON written after
   reasoning. The healthy free models race (`long_race` 4: all asked at once, the first JSON
   wins, the losers are abandoned), each with `long_timeout_seconds` (45),
   `long_max_output_tokens` (8192) and `reasoning_effort` `long_reasoning_effort` ("low"; a
   model that rejects the field is asked again without it and remembered). Measured
   2026-11-18: the system ficha took 30 to 90 s with 5000 to 7000 output tokens, mostly
   reasoning, and sequential timeouts made some turns last 3 to 5 minutes; "low" effort took
   beam-free from 40 s to 11 s and muse-spark from 54 s to 22 s.
4. **Fallback.** With no free model answering: `deepseek-v4.1-flash`, then
   `muse-spark-1.3-contributor` (the only paid models the code accepts).
5. Models without JSON mode (`iceman-contributor-free` rejects `response_format`) are called
   without it; the prompts already demand JSON and the guard still checks every text.
6. A model "unknown" never overrides an owner fixed answer the local classifier recognized.

`sales models` prints the free models, their privacy flags and pauses after a fresh probe;
`sales check --ping` makes one routed call. Each decision records the model that answered.

Measured on the owner's key (2026-11-17): every free model answered `{"pong": true}` at
cost 0 in 0.8–2.7 s; the fallbacks in 1.3 s (DeepSeek) and 5 s (Muse).

### Privacy

The model receives the business name, category and city, the conversation and the rules; phone
numbers never leave the PC. Per the catalog:

| Model | Trains on prompts | Zero retention |
| --- | --- | --- |
| `longcat-2.5-free`, `hy4-flash-free`, `deepseek-v4.1-flash` | no | yes |
| `beam-free` | no | no |
| `iceman-contributor-free`, `muse-spark-1.3-contributor` | **yes** | no |

The owner chose the free tier including the contributor models. To keep client conversations
out of training, add them to `llm.exclude` (free) or remove Muse from `llm.fallback`.

The key is read from `OPENCODE_GO_API_KEY` or `.local/commercial/whatsapp/sales/llm.env`, is
sent only in the Authorization header with `User-Agent: YoutubeBot-Sales/1.0` and one
`x-opencode-session` per conversation, and never appears in logs, errors or records.

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
- A contact saved in the owner's phone shows its saved name as the chat title, not the
  number. Each time the agent opens a lead's chat by number it reads the header title and
  stores it as the lead's `chat`, so replies under that name reach the lead. A title already
  bound to another lead is never taken over. Before this (2026-11-18), a test number saved
  under a longer name had its reply dropped by the listener.
