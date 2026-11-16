# Commercial affiliates

The commercial module keeps separate private browser sessions for affiliate networks.
Mercado Livre is the first network.

## Mercado Livre

- Hub: <https://www.mercadolivre.com.br/afiliados/hub>
- Visible login profile: `.local/commercial/mercadolivre/profile`
- Remote debugging: `127.0.0.1:9324`
- Hidden Xvfb display: `:92`
- Account record: `.local/commercial/mercadolivre/account.json` with mode 0600

The owner signs in manually in the visible browser. The bot never reads or stores the
password, cookies or tokens in Git. After login, `commercial status` switches the same
profile to the hidden runtime and confirms the affiliate hub session.

```bash
python3 -m tools.ytbot commercial open --network mercadolivre
python3 -m tools.ytbot commercial status --network mercadolivre
python3 -m tools.ytbot commercial stop --network mercadolivre
```

The logged-in affiliate hub is the source for the product search. The bot reads products and
affiliate links shown to this account; it never invents products, prices, commission values or
links.

## Product search and share link

```bash
python3 -m tools.ytbot commercial products --network mercadolivre \
  --query "cafeteira" --limit 5
```

The command runs in the hidden profile, searches the affiliate hub and opens each product's
share dialog. Results are saved privately in
`.local/commercial/mercadolivre/products.json`.

### Page map

| Element | Selector / evidence |
| --- | --- |
| Product search | `input[placeholder="Busque produtos"]` |
| Result card | `li.poly-card` |
| Product title | first `a[href*="/p/"]` in the card |
| Product image | first `img` in the card |
| Product URL | the card's `/p/` href |
| Commission | card text containing `GANHOS` or `GANHOS EXTRAS` |
| Share action | `Compartilhar` inside the card |
| Share dialog | `role=dialog` with title `Compartilhe para ganhar dinheiro` |
| Copy link | dialog button `Copiar link` |
| Copy ID | dialog button `Copiar ID` |
| Copy information | dialog button `Copiar informação` |

The hub also exposes filters `Ganhos extras`, `Mais vendidos`, `Categorias` and ordering
`Mais relevantes`. The product cards can be tagged `MAIS VENDIDO`, `MAIS BUSCADO` or
`OFERTA IMPERDÍVEL`, and some are marked `Patrocinado por`.

### Correct affiliate link

Always use **Copiar link**, not the raw product URL. The returned link is a short
`https://meli.la/...` affiliate link. Copiar ID returns the share ID; Copiar informação
returns a ready-to-paste text with the ID and link.

Example from a live account:

```text
Copiar link  -> https://meli.la/2vCmtKw
Copiar ID    -> 1PBCGF-FBQR
Copiar info  -> 🔍 Cole este texto no buscador do Mercado Livre: 1PBCGF-FBQR

                🔗 Ou acesse o link:
                https://meli.la/2vCmtKw
```

The command rejects any share response that is not a `meli.la` link. The raw `/p/` URL, the
product ID and the affiliate short link are different things; never substitute one for
another. Links are account-specific and must not be reused from another affiliate account.

### Product detail extraction

For each result the command also opens the product page and reads the JSON-LD
`ProductGroup`/`Product` data plus the visible page:

| Field | Source |
| --- | --- |
| `product_id` | `/p/MLB...` in the product URL |
| `canonical_url` | JSON-LD variant URL |
| `brand`, `model` | JSON-LD |
| `price`, `currency`, `availability` | JSON-LD `offers` |
| `meta_price` | visible `itemprop=price` |
| `seller` | visible seller block |
| `long_description` | visible product description |
| `specs` | JSON-LD `additionalProperty` |
| `variants` | JSON-LD `hasVariant` |
| `gallery` | large `mlstatic.com` images on the product page |
| `photos` | downloaded private copies under `.local/commercial/mercadolivre/images/` |

The photos are private working files with mode 0600. When the static site is fed, copy the
selected images into the site's own asset directory; never publish a `.local/...` path.

The private JSON now carries everything needed for the static-site ingestion: product ID,
title, canonical URL, brand/model, price and reference price, availability, seller,
description, specs, variants, gallery, local photos, commission, sponsored flag, affiliate
link, share ID and share text. Prices and availability must be rechecked before publishing.

### Telegram offers group

The owner created the Telegram offers group (`@procurali`) and paired it with the remote
Procurali VPS (`procurali.com.br`). Keep bot tokens, SSH keys and VPS origin addresses out of
this repository; delivery runs through the companion ZaturoBot pipeline described below.

## Local-to-VPS physical-key delivery

Once `.local/commercial/mercadolivre/products.json` and its downloaded images are ready on this
workstation, deliver them to the remote Procurali VPS through the sibling ZaturoBot sync runner:

```bash
# 1. Confirm affiliate session and capture products locally
python3 -m tools.ytbot commercial status --network mercadolivre
python3 -m tools.ytbot commercial products --network mercadolivre \
  --query "<search terms>" --limit 4

# 2. Send once over the physical-key SSH tunnel (or pass --watch for continuous monitoring)
bash ../ZaturoBot/scripts/procurali-local-sync.sh --once \
  --category hardware-e-perifericos
```

Rules for the local bot agent and operator:

1. **Physical-key tunnel only:** `procurali-local-sync.sh` authenticates solely with this
   workstation's private Ed25519 key and device token in `../ZaturoBot/.secrets/procurali-local-bot/`
   against the VPS `procurali-link` (`nologin`, port-forwarding-only) account, forwarding only local
   loopback ports for MinIO object storage and the ZaturoBot Hub HTTP API.
2. **Never bypass or leak secrets:** Never open a direct server shell, never copy `.secrets/` files
   into this repository, and never commit VPS origin IP addresses, SSH keys, tokens or `.local/`
   files. Keep Telegram/WhatsApp credentials outside YoutubeBot.
3. **Automatic downstream fan-out:** A successful ingest to the VPS Hub (`worker_id =
   procurali-local-pc`) triggers:
   - Static image upload to MinIO (9:16 vertical reel frames filtered out, `.local/` paths stripped),
   - Persistent storage + 30-day price history tracking in the Hub SQLite database,
   - Automatic static site rebuild (`procurali-site-sync.service`) serving <https://procurali.com.br/>,
   - Queueing into the VPS `procurali-telegram-poll.service` (paced 1–3 minutes between posts),
   - Updated human-assisted WhatsApp Web drafts written locally to
     `../ZaturoBot/.secrets/procurali-local-bot/whatsapp-assisted-drafts.json`.
4. **Change detection:** `zaturo-worker commerce watch-ml` hashes `products.json` with SHA-256 and
   skips re-uploading when the file digest has not changed (`"status": "unchanged"`). When testing
   with new items, pick SKUs that have not already been published unless an updated price observation
   is intended.

## Privacy and limits

- Keep the commercial profile under `.local/`; never commit browser state.
- Require an explicit network.
- Do not bypass login, reCAPTCHA or account challenges.
- Do not use another account's affiliate links.
- Do not claim a product is affiliated until the hub returns its link for this account.
- Product prices and availability must be rechecked before publication.
- Never automate WhatsApp Web or call WhatsApp Meta APIs from YoutubeBot; use the generated
  human-assisted drafts only.
