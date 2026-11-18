# Google Maps lead research

Status: contract only (owner, 2026-11-18). No code exists yet; this file is what the owner and
the bot use to pick the businesses most likely to buy a site, a system, an app or the
"Ajuste do Google Maps" service, and the specification for the module that will automate it.

The research produces an owner-reviewed CSV for the WhatsApp sales agent
([WHATSAPP-SALES](COMMERCIAL-WHATSAPP-SALES.md)). It never sends a message, never writes on
Google and never imports by itself: importing stays the owner's approval of the list.

## Operating model

The bot does what a person does in one browser tab: open Google Maps, type a search, scroll
the list, open one business, read it, go back. Nothing else.

| Rule | Value |
| --- | --- |
| Profile | `.local/commercial/maps/profile` (private, never committed) |
| Login | the owner signs in to a valid Google account by hand in the visible window; no password, two-step or challenge automation |
| Runtime | after login, hidden Chrome/Xvfb on its own display and CDP port, like the other commercial modules; visible only for login and challenges |
| Tabs | one; Maps and the confirmation searches share it |
| Pace | 4 to 12 s between two businesses, 20 to 60 s between two searches |
| Volume | one city per run; at most 120 businesses read per day (owner-tunable) |
| Stop | at a CAPTCHA, "unusual traffic", a sign-in challenge or an unknown layout: stop the run, record `needs-attention`, notify the owner; never bypass |
| Identity | one account, one IP, the normal browser; never rotate accounts, proxies or user agents |
| Writes | none: no reviews, no "Sugerir uma edição", no messages from Maps |

Google's terms restrict automated access to Maps. Keep the module owner-operated, slow and
low-volume, and stop at the first challenge. If the volume ever needs to grow, use the paid
Google Places API with the owner's own key instead of scaling the browser.

Every run is resumable and lives in `.local/commercial/maps/runs/<city-slug>/<date>/`:
`queries.jsonl` (searches done), `listings.jsonl` (raw business data),
`checks.jsonl` (confirmation evidence), `candidatos.csv`, `ajuste-maps.csv` and `report.md`.
A business already read in the run is never opened again.

## Input and searches

Input: city and state, e.g. `Lucas do Rio Verde - MT`. Each search is
`<categoria> em <Cidade> - <UF>` (`dentista em Lucas do Rio Verde - MT`). The run walks the
category catalog below in priority order until the daily limit.

| Group | Searches (pt-BR) | Best offer |
| --- | --- | --- |
| Health and beauty | dentista, clínica odontológica, clínica de estética, fisioterapia, psicólogo, nutricionista, clínica veterinária, salão de beleza, barbearia, studio de pilates, academia | site + scheduling system |
| Agribusiness (strong in Lucas do Rio Verde) | revenda de insumos agrícolas, peças para máquinas agrícolas, oficina de máquinas agrícolas, consultoria agronômica, georreferenciamento, irrigação, transportadora, veterinário de grandes animais | site + quote form; systems for orders, fleet or field visits |
| Home and construction | materiais de construção, móveis planejados, marmoraria, vidraçaria, serralheria, energia solar, ar-condicionado, dedetização | site + quote form, catalog |
| Automotive | oficina mecânica, auto center, funilaria, autopeças, loja de pneus, auto elétrica | site + service scheduling |
| Professional services | contabilidade, advocacia, imobiliária, despachante, corretora de seguros, engenharia, arquitetura | institutional site |
| Food | restaurante, pizzaria, hamburgueria, marmitaria, padaria, confeitaria | site with menu + WhatsApp ordering |
| Education | escola de idiomas, autoescola, escola de música, reforço escolar | site + enrollment |
| Retail and pets | pet shop, ótica, floricultura, gráfica, loja de roupas | site + catalog |
| Hospitality | hotel, pousada | site + booking |

Never listed: franchises and chains (the decision is at headquarters), government and public
services, banks and cooperatives, large companies with a corporate site, gambling and betting,
adult content, political organizations, pyramid or multilevel schemes. The owner edits this
list.

## Data read from each business

| Field | Where in the listing |
| --- | --- |
| `name`, `category`, `address` | panel header and address line |
| `phone` | phone line; mark `mobile` when it is a Brazilian mobile (9 digits starting with 9) |
| `website_field` | the "Website" button or link, exactly as shown (may be a social profile) |
| `social` | Instagram, Facebook, TikTok links shown in the listing or as its website |
| `rating`, `reviews` | stars and review count |
| `last_review_days` | reviews sorted by "Mais recentes": age of the newest one |
| `hours`, `photos` | hours present or not; photo count bucket (0, 1-9, 10+) |
| `unclaimed` | the listing shows "Reivindicar esta empresa" / "Você é o proprietário desta empresa?" |
| `status` | "Fechado permanentemente" or "Fechado temporariamente" |
| `maps_url` | the place link (`https://www.google.com/maps/place/...` or `https://maps.app.goo.gl/...`) |

Only public listing data. A personal-looking review, reviewer names or photos of people are
never stored.

## Filters

Hard exclusions, whatever the score: closed (permanently or temporarily), no phone, an
excluded category or chain, already a lead or on the do-not-contact list
(`commercial sales leads`), or an own site already linked on Maps and working.

The `website_field` is classified first:

| Class | Meaning |
| --- | --- |
| `none` | no website on Maps |
| `social-only` | the "site" is Instagram, Facebook, TikTok, Linktree, `wa.me`/WhatsApp, bio-link pages |
| `marketplace` | iFood, aiqfome, Anota AI, Goomer, Doctoralia, Booking or similar |
| `free-builder` | `business.site` (Google's discontinued sites) or `sites.google.com` |
| `own` | an own domain: checked in the confirmation step below |

## Confirmation search (does it really have no site?)

For every business still in the list without a working own site on Maps, the bot confirms
before scoring:

1. In the same tab, a normal Google search for `"<name>" <city>`; read only the first page of
   results.
2. Ignore social networks, marketplaces and directories (guiamais, apontador, telelistas,
   solutudo, econodata, cnpj sites, casadosdados, reclameaqui, tripadvisor, doctoralia,
   LinkedIn, YouTube, iFood, OLX, Mercado Livre and similar).
3. A result counts as the business's own site when its domain or page title carries the
   distinctive words of the name and the page shows the same city or phone.
4. Also try the two obvious domains, `<name-slug>.com.br` and `<name-slug>.com`: one request
   each, 5 s timeout, same city/phone check.
5. Record the URLs checked and the signal that matched in `checks.jsonl`.

| Outcome | Next step |
| --- | --- |
| `no-site` | main target: site (and system/app by category) |
| `site-not-on-maps` | own site found but missing on Maps: "Ajuste do Google Maps" list |
| `weak-site` | found but down, expired, a parking page or no HTTPS: redesign list for the owner |
| `has-site` | dropped |

## Score and tiers

| Signal | Points |
| --- | --- |
| Rating 4.5+ / 4.0-4.4 | 20 / 12 |
| Reviews 100+ / 30-99 / 10-29 | 15 / 10 / 5 |
| Newest review within 90 days / 365 days | 10 / 5 |
| `social-only` / `none` / `marketplace` or `free-builder` | 15 / 10 / 8 |
| Category group: health and beauty / agribusiness, home, automotive, services / others | 15 / 10 / 8 |
| Mobile phone (WhatsApp-capable) / landline only | 10 / 3 |
| Maps gaps: unclaimed / no hours / fewer than 10 photos | 5 / 2 / 2 |
| 10+ photos | 3 |

Tier A is 70 points or more, tier B 50 to 69; tier C (below 50) is listed in the report but
not exported. A well-rated, active business that already pays attention to social media but
has no site is the best lead: it values its image and has customers searching for it.

## Output

`candidatos.csv` uses the sales import columns, `website` empty:

```csv
name,phone,city,category,maps_url,website,note
Clínica Exemplo,(65) 90000-0001,Lucas do Rio Verde,Clínica odontológica,https://maps.app.goo.gl/...,,A 84 · social-only · 4.8 (134) · agendamento
```

`note` carries the tier, score, website class, rating and the suggested product, so the owner
reviews quickly and the conversation knows the context. `ajuste-maps.csv` has the same
columns plus the site found in `website`; it waits until the sales rules have the
"Ajuste do Google Maps" opening and price (the current import rejects a filled `website`).
`report.md` counts each stage, lists the top candidates and every exclusion with its reason.

After the owner reviews and edits the file, the import adds the leads with source
`google-maps-manual` (`commercial sales import --network whatsapp --csv <file>`; the
`--source` option is part of the implementation below).

## "Ajuste do Google Maps" service

What Zaflas fixes on the client's Business Profile: website link, WhatsApp/phone, opening and
holiday hours, main and extra categories, description, products and services, photos (logo,
cover, facade, inside, team), booking or menu link, address or service area, attributes,
replies to reviews and periodic posts.

Price and delivery time are not in the rules yet. Until the owner adds them to
`sales_rules.toml` facts, the bot may describe the service and must hand the price question to
the owner.

How Zaflas does it from its own Google account (labels as of 2026-11; Google renames menus,
so follow the screen):

1. **Client gives access (recommended).** The client, signed in to the Google account that
   owns the profile, searches the business name on Google or opens it in the Google Maps app,
   then "⋮ Mais" → "Configurações do Perfil da Empresa" → "Pessoas e acesso" → "Adicionar" →
   Zaflas's e-mail → access "Administrador" (Manager) → "Convidar". Zaflas accepts the e-mail
   invite and edits through "Editar perfil" while signed in. Zaflas asks only for Manager,
   never Owner: managers cannot add or remove people or delete the profile, and new users have
   a 7-day restriction on some actions.
2. **Profile not claimed.** The listing shows "Reivindicar esta empresa". The client claims it
   with their own Google account and completes the verification Google offers (phone or SMS,
   e-mail, video or mail); Zaflas can guide them on a call. Then step 1. Zaflas never claims a
   client's business as its own.
3. **Someone else owns it** (former employee, previous agency). The client requests ownership
   in the same claim flow; the current owner gets an e-mail and has 3 days to answer. Without
   an answer, the client's confirmation e-mail may offer "Ver solicitação" → "Verificar"
   (not guaranteed). For a service-area business, contact Google support and choose transfer
   of ownership. Never create a duplicate profile.
4. **No access yet, client's written OK.** From any Google account (Zaflas's): the business on
   Google Search or Maps → "Sugerir uma edição" → "Alterar nome ou outros detalhes" → website
   (official site only, never a social profile), hours or phone → "Enviar". Google moderates it
   (pending, then accepted or not accepted) and the owner of the profile may reject it. Only
   true, factual corrections, one business at a time; the status is under "Suas contribuições"
   → "Edições".

Sources: Google Business Profile Help on
[owners and managers](https://support.google.com/business/answer/3403100),
[requesting ownership](https://support.google.com/business/answer/4566671) and
[suggesting edits](https://support.google.com/websearch/answer/9879130).

## Implementation contract (for the bot)

A new module `tools/ytbot/commercial/maps/` with a typed CLI, following the commercial runtime
model:

```bash
python3 -m tools.ytbot commercial maps login                       # visible, owner signs in
python3 -m tools.ytbot commercial maps status
python3 -m tools.ytbot commercial maps research --city "Lucas do Rio Verde" --state MT \
  [--group saude] [--limit 120]
python3 -m tools.ytbot commercial maps verify --run <id>            # confirmation searches
python3 -m tools.ytbot commercial maps export --run <id>            # candidatos.csv, report.md
python3 -m tools.ytbot commercial sales import --network whatsapp --csv <file> \
  --source google-maps-manual
```

- Selectors, classification, ignore lists and scoring are data (a versioned TOML next to the
  module), not code, so the owner tunes them like the sales rules.
- Every step writes its record before acting; a crash resumes without opening a business
  twice.
- Tests use saved HTML fixtures of listings and search pages; no live Google access in CI.
- The research never imports, never messages and never writes on Google.
