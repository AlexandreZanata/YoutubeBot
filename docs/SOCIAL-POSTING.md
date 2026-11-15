# X publishing

The X publisher posts one reviewed item from the private promotion agenda. It is deliberately
small: text or one image, one account, one post at a time, no threads, polls, replies,
scheduling, follows or engagement automation.

Runtime rule: a visible Chrome window is used only for login and platform challenges. After
login, agenda validation, status and publishing run in hidden Xvfb on display `:90` with the
same private profile and CDP port `9322`. Every future network module must follow the same
model with its own display and port.

## Inputs

| Path | Purpose | Git |
| --- | --- | --- |
| `.local/promotion/agenda.json` | 30-day agenda imported from the research cycle | ignored |
| `.local/social/x/posts.json` | idempotency journal, states and post URLs | ignored |
| `.local/social/x/profile` | Chrome session | ignored |
| `.local/social/x/account.json` | handle, display name and verification time | ignored |

The agenda is private because it contains unreviewed copy, sources and campaign decisions.
Only this runbook and the code are versioned.

## Agenda schema

```json
{
  "schema": 1,
  "cycle": "2026-11",
  "timezone": "America/Cuiaba",
  "items": [
    {
      "id": "P01",
      "date": "2026-11-16",
      "product": "Abastevo",
      "format": "text",
      "text": "O litro mais barato nem sempre é o que economiza mais. Depende do consumo do seu carro. Coloca os seus números na calculadora e compara: {url}",
      "destination": "https://abastevo.com.br/ferramentas/etanol-ou-gasolina/",
      "campaign": "abastevo_utilidade_202611",
      "content": "p01_text",
      "audience": "Motorista de carro flex",
      "objective": "Entender custo por quilometro",
      "cta": "Veja a calculadora",
      "metric": "Calculo concluido",
      "conversation": "Ler uma duvida sobre consumo",
      "image": null,
      "alt_text": "",
      "status": "approved"
    }
  ]
}
```

Rules enforced by `load_agenda`:

- `schema` must be `1` and every id must be unique.
- `format` must be `text`, `image`, `thread`, `poll` or `video`.
- `status` must be `draft`, `reviewed` or `approved`. Only `approved` can be posted.
- Text and image items must contain the `{url}` placeholder.
- `destination` must be HTTP or HTTPS.
- The publisher currently accepts only `text` and `image`. Threads, polls and videos are
  rejected with a clear error instead of being flattened into a single post.

The tracked URL keeps existing query parameters, for example SorriFit `?idioma=pt`, and adds
`utm_source=x`, `utm_medium=organic_social`, `utm_campaign` and `utm_content`.

## First post

The first item, P01, was published on 15/11/2026. The original wording was deleted with owner
approval and republished with the conversational revision:

- Current URL: <https://x.com/AlexandreZanat/status/2121924243122171996>
- Previous URL: <https://x.com/AlexandreZanat/status/2121920819635130591> (`P01-old` in the
  journal, state `deleted`)
- Format: text
- Image: none
- Destination: Abastevo ethanol/gasoline calculator with UTM
- Journal: `posted`

The agenda marks P01 as text. A generic image would repeat the sentence, and a generated
fake calculator screen would damage trust. The post therefore uses the real link card that X
builds from the Abastevo page. A real screenshot is allowed in a future image item only after
review, with no private data and with alt text.

X editing requires a paid Plus/Premium entitlement; the account showed the upgrade prompt
instead of an editor. The owner authorized deletion and replacement, so the old post is
preserved only as a journal audit record and the new post uses the conversational copy.

## Editing a published post

Do not silently delete and repost when a copy revision is needed.

- X editing requires the account entitlement. If the Editar menu shows an upgrade prompt, the
  bot cannot edit.
- Update the private agenda copy first.
- Ask the owner before deleting a published post. Deletion is irreversible and removes the
  existing link.
- If the owner approves a replacement, delete the post in X, update the private journal entry
  explicitly, then publish the revised item as a new post.
- Never bypass the journal to force a repost.

## Image policy

Use an image only when it adds evidence or a concrete visual step:

- Prefer a real, reviewed screenshot of the product.
- Do not invent UI, charts, testimonials or numbers.
- Do not show personal data, precise location, CNPJ, health data or credentials.
- PNG, JPG or WEBP, at most 5 MB, under `.local/`.
- Add alt text when the platform exposes the field.
- If the agenda item is `text`, do not attach an image just to fill space.
- If the agenda item is `image` and the file is missing, stop; do not publish a text-only
  substitute without changing the agenda and reviewing it.

The publisher does not call an image model. A generated illustration is a separate editorial
decision and must be reviewed before it is attached.

## Commands

```bash
python3 -m tools.ytbot social open --network x      # visible login only
python3 -m tools.ytbot social status --network x    # hidden
python3 -m tools.ytbot social stop --network x
python3 -m tools.ytbot social agenda --network x
python3 -m tools.ytbot social post --network x --id P01 --dry-run
python3 -m tools.ytbot social post --network x --id P01
```

`--dry-run` fills the composer in the hidden browser, waits for the Post button, then closes
without clicking. It does not write the journal. The agenda command is the validation gate: a
missing or invalid file stops the post before any browser interaction.

## Publish path

1. Load the agenda and find the exact id.
2. Reject draft or reviewed items.
3. Render the text with the tracked URL and check the X weighted length, with each URL counted
   as 23 characters.
4. Refuse a duplicate id or a text hash already present in the journal.
5. Validate the optional image path, type and size.
6. Ensure the hidden Xvfb browser on display `:90`; if a visible bot window is open, stop it
   and relaunch the same private profile in the background.
7. Confirm the browser is logged in. If not, stop and ask the owner to finish login.
8. Open `https://x.com/compose/post` and target the visible composer dialog.
9. Fill `data-testid="tweetTextarea_0"`.
10. Attach `input[data-testid="fileInput"]` and wait for the attachment preview when an image
    is present.
11. Wait for `data-testid="tweetButton"` to become enabled.
12. Write `state: started` with the text hash before clicking.
13. Click Post once.
14. Confirm the toast or the closed composer.
15. Read the status URL from the toast link when available.
16. Write `state: posted` or `state: unconfirmed`; never retry automatically.

## Error handling

| Situation | Bot action |
| --- | --- |
| Browser closed | Start the hidden Xvfb browser automatically |
| Visible login window open | Stop it, then relaunch the same profile in the background |
| Xvfb display busy | Use the next free display and update the network constant |
| Login required or challenge | Stop; the owner finishes it in the visible window and reruns |
| Agenda missing or invalid | Stop; fix the private JSON or its schema |
| Item not approved | Stop; review and set `status: approved` |
| Item already started, posted or unconfirmed | Stop; inspect the journal and the profile |
| Same text hash under another id | Stop; possible duplicate |
| Text over 280 weighted characters | Stop; shorten and review |
| Image missing, outside `.local`, wrong type or over 5 MB | Stop; fix the file or agenda |
| Post button does not enable | Stop before clicking; inspect text and link |
| Failure before the click | Safe to retry after checking the composer and journal |
| Failure after the click, no toast | Mark `unconfirmed`; inspect the profile manually; never retry |
| Rate limit or platform warning | Stop; wait for the platform window; do not loop |
| Account mismatch | Stop; the visible profile is not the expected account |

The journal is the source of truth. A `started` or `unconfirmed` record blocks another publish
until a human checks the profile and edits the private state deliberately.

## Scope

Implemented: text, one image, UTM, dry run, idempotency, login check, confirmation and error
fences. Not implemented: threads, polls, video, replies, quotes, scheduling, analytics
collection and multi-account posting. Those require separate review and tests.
