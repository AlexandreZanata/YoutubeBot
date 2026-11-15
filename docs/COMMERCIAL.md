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

The owner created the Telegram offers group. Delivery is **not configured in this repository**
yet: it needs the group username/ID and a bot token stored privately. Do not guess a group,
token or chat ID, and never commit them. Until that configuration exists, the commercial
module only produces the private product JSON and affiliate links.

## Privacy and limits

- Keep the commercial profile under `.local/`; never commit browser state.
- Require an explicit network.
- Do not bypass login, reCAPTCHA or account challenges.
- Do not use another account's affiliate links.
- Do not claim a product is affiliated until the hub returns its link for this account.
- Product prices and availability must be rechecked before publication.
