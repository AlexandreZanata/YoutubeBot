# Desktop manager

`desktop/` is a Rust + Slint application: a read-only view of the bot's private records with
monthly metrics and, on its home page (Central), every WhatsApp sales conversation that needs
the owner, plus two bounded actions per network (open the visible login window, stop the
hidden browser). Commands and layout of the code are in [desktop/README.md](../desktop/README.md).

## Contract

- **Read-only.** The app never writes `.local/`, never opens a network connection and never
  reads cookies or tokens (`account.json` only carries state, handle, display name and
  verification time). The only file it writes is the owner's preferences:
  `$XDG_CONFIG_HOME/ytbot-manager/settings.json` (theme, refresh interval, project root);
  `YTBOT_MANAGER_CONFIG` overrides that path.
- **Bounded actions.** "Abrir janela" and "Parar navegador" run
  `python3 -m tools.ytbot commercial|social open|stop --network <key>` with a fixed argument
  list on a worker thread. No shell, no arbitrary command. YouTube profiles have no action
  here; their pipeline is `run`, `shorts` and `distribute`.
- **Central links.** "Abrir conversa" and "Ficha do cliente" hand one validated target to
  `xdg-open`: only `https://wa.me/<10 to 15 digits>` (the owner's own browser or WhatsApp
  opens the chat) and only a `ficha.md` inside `.local/commercial/whatsapp/sales/clientes/`
  (resolved, so `..` cannot leave it). Nothing else is opened and nothing is sent.
- **Never invent data.** A missing file shows "sem registro" (or "não conectada" for a
  session), a broken one shows an error with "Tentar novamente". Unknown fields are ignored,
  a broken JSONL line or `upload.json` is skipped and counted in Configurações → Diagnóstico.
- **Non-blocking.** Records load on a worker thread, thumbnails decode on another, actions run
  on a third; the footer reports every result.

## Data sources

| Area | Files (under `.local/`) |
| --- | --- |
| Channels | `accounts/registry.json`, `ytbot/runs/*/` (fallem prince), `ytbot/channels/<slug>/runs/*/{upload,metadata}.json` |
| Shorts | `ytbot/channels/zaflas/shorts/*/{upload,metadata}.json`, `thumbnail.png` |
| Community | `<channel data>/community-history.jsonl`, falling back to `community.json` |
| Login warning | `ytbot/needs-login.json` |
| X | `social/x/{account,posts,replies,discovery}.json`, post text from `promotion/agenda.json` |
| WhatsApp | `commercial/whatsapp/{account.json,rules.json,events.jsonl,journal.jsonl}` |
| Mercado Livre | `commercial/mercadolivre/{account,products}.json` |
| Central (sales) | `commercial/whatsapp/sales/central.json`, written by the agent after every cycle (contract in [WhatsApp sales](COMMERCIAL-WHATSAPP-SALES.md)) |
| Sessions | the account files above, `browser.pid` and Chrome's `SingletonLock` checked through `/proc` |

## Counting rules

All counts come from the `reports` crate; Slint only displays strings.

- Time zone: America/Cuiaba through `chrono-tz`, independent of the machine's zone.
- A video is **published** when `upload.json` is scheduled, has a `videoId` and its slot is at
  or before now; **scheduled** while the slot is ahead; a **draft** when the upload has no
  confirmed schedule (drafts are counted regardless of the period).
- Periods: "Este mês" is the whole calendar month (future days included), "Últimos 30 dias" is
  today and the 29 days before, "Personalizado" takes two inclusive dates (`DD/MM/AAAA`).
- The channel filter applies to videos, Shorts and upcoming slots. X, WhatsApp and Mercado
  Livre are network-wide.
- X posts count `state: posted` by `posted_at`; deleted posts are listed but not counted.
- WhatsApp counts unique event ids by the listener's `at` timestamp.
- Mercado Livre: `products.json` is a snapshot of the latest capture, so the card counts that
  capture's products when it happened inside the period.
- Community: every journal transition (`started`, `unconfirmed`, `posted`) is appended by the
  bot to `community-history.jsonl`; posts in the period count `posted` entries. Without the
  history only the last entry of `community.json` is known, and the card says so.

## Screens

| Section | Shortcut | Content |
| --- | --- | --- |
| Central | Ctrl+1 | Home. Funnel groups (Com você, Em conversa, Prospecção, Encerrados); "Precisa de você" with every conversation the owner must take over (priority, `barbearia-1 Nome`, reason, phone, last message, "Abrir conversa", "Ficha do cliente"); recent messages of every lead; the 14 states with counts |
| Visão geral | Ctrl+2 | Period and channel filters, six month cards, upcoming slots |
| Canais | Ctrl+3 | One card per channel (binding, published × scheduled × drafts, last, next, Community); Enter opens the video table |
| Shorts | Ctrl+4 | Zaflas Shorts with thumbnail, slot and state |
| Social (X) | Ctrl+5 | Posts, replies and discovery counters, session, posts of the period |
| Comercial | Ctrl+6 | WhatsApp session, rules and latest message per contact; Mercado Livre session and last capture |
| Sessões | Ctrl+7 | Every profile with live browser state (polled every 5 s) and the open/stop actions |
| Configurações | Ctrl+8 | Theme, project root, refresh interval, read-only diagnostics, shortcuts |

Central priorities: "Atender agora" (red) is a buying signal (quote collected, wants to close,
asked for a person or a call), "Precisa de você" (amber) is a question or negotiation the bot
may not answer, "Verificar" (accent) is a failed send or a blocked contact writing again.

States: skeleton while the first load runs, "VAZIO" for an empty period, "SEM REGISTRO" for a
missing source, "ERRO" with a retry action, and a page-wide notice when the root has no
`.local/`. A `needs-login.json` marker shows a warning strip on every page.

## Keyboard

| Keys | Action |
| --- | --- |
| Ctrl+R | Reload every record |
| Ctrl+K | Focus the search field (filters the current page, accent-insensitive) |
| Ctrl+1 … Ctrl+8 | Go to a section (Ctrl+1 is the Central) |
| ↑ ↓ ← → PageUp PageDown Home End | Move in the page's list; the selection scrolls into view |
| Enter | Open the selected channel; on the Central, open the selected conversation |
| Esc | Leave the channel detail, clear selection and search |
| Tab / Shift+Tab | Next / previous control; every control draws a 2 px focus ring |

## Design system

Tokens live in `desktop/apps/manager/ui/theme.slint`; every color is defined for both themes
on one line.

- **Color:** neutral black/white/gray surfaces, one discrete blue for links and the focus ring,
  green/amber/red only for status text and small marks (the word always carries the meaning).
- **Contrast:** `apps/manager/tests/contrast.rs` parses the tokens and fails below WCAG AA:
  4.5:1 for every text and status color on every surface, 3:1 for focus ring, control outline
  and filled button.
- **Spacing:** 4, 8, 12, 16, 20, 24, 32 px. **Radii:** 4, 8, 12 px. **Elevation:** a hairline
  border; a faint shadow only in the light theme.
- **Type:** Noto Sans at 12/14/16/20/28 px. Slint 1.18 has no line-height property, so labels
  reserve 1.4 × the font size as their minimum height.
- **Themes:** light and dark switch live (sidebar button or Configurações) and persist. The
  std-widgets inputs follow through `Palette.color-scheme`.
- **Layout:** minimum 1024×720, opens at 1280×800, grids reflow from two to three columns.

## Layers

| Layer | Crate | Responsibility |
| --- | --- | --- |
| Aggregation | `crates/reports` | Tolerant readers, periods, counts per period/channel; no UI, no writes |
| Domain | `crates/manager-core` | Sessions, live browser state, settings, `SessionActions` + `CliActions` |
| View model | `apps/manager/src/view.rs` | Formats reports into Slint structs |
| UI | `apps/manager/ui/*.slint` | Tokens, controls, pages, keyboard bindings |
| Entry point | `apps/manager/src/main.rs` | Threads, timers, callbacks, preferences |

Neither `reports` nor `manager-core` depends on Slint. `tests/test_desktop_catalog.py` keeps the
Rust channel table equal to `tools/ytbot/channels.py`.

## Renderer

The window uses Slint's **femtovg** (OpenGL) renderer. The software renderer produced
corrupted, striped frames on the owner's desktop session. If OpenGL is unavailable, set
`SLINT_BACKEND=winit-software` explicitly.

## Screenshots

`docs/images/desktop/` holds every page in both themes, captured from the synthetic root of
`desktop/scripts/demo_root.py` (no private data) with `desktop/scripts/capture.py`, which
drives the app only through its keyboard shortcuts.

## Known limits

- Mercado Livre has no capture history; a `captures.jsonl` written by the commercial module
  would make the monthly product count exact.
- Community history starts with this version; earlier months only know the last post.
- Outside the Central, links are shown as text; only the Central's wa.me and ficha targets
  are opened.
