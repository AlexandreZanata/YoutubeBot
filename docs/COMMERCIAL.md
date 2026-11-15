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

### Product result fields

The private JSON records position, title, product URL, image, raw card text, commission,
sponsored flag, share link, share ID and share text. Prices and availability must be
rechecked before publishing. The module does not buy, publish, or modify affiliate links.

## Privacy and limits

- Keep the commercial profile under `.local/`; never commit browser state.
- Require an explicit network.
- Do not bypass login, reCAPTCHA or account challenges.
- Do not use another account's affiliate links.
- Do not claim a product is affiliated until the hub returns its link for this account.
- Product prices and availability must be rechecked before publication.
