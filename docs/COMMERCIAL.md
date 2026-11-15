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

The logged-in affiliate hub is the source for the product search. The bot must read the
products and affiliate links shown to this account; it must not invent products, prices,
commission values or links. Product discovery and content generation will be added after
the live hub structure is inspected. No purchase, publication or affiliate link change is
performed by the session commands.

## Privacy and limits

- Keep the commercial profile under `.local/`; never commit browser state.
- Require an explicit network.
- Do not bypass login, reCAPTCHA or account challenges.
- Do not use another account's affiliate links.
- Do not claim a product is affiliated until the hub returns its link for this account.
- Product prices and availability must be rechecked before publication.
