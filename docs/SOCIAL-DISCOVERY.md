# Discovery and contextual replies

The discovery module searches recent public X posts for real questions and conversations where
a project can add context. It does not auto-reply. It produces a curated list, a human reviews
the thread, and only then the reply command publishes one contextual comment.

## Scope

- Search window: at most 7 days.
- Products: Abastevo, SorriFit, Zaflas and the GitHub projects.
- Language: Brazilian Portuguese.
- One reply per target, recorded in a private journal.
- No mass replies, no automated engagement, no follow or like automation.
- One contextual link maximum, never a link-only reply.

## Search terms

| Product | Queries | Relevant terms | Contextual link |
| --- | --- | --- | --- |
| Abastevo | `etanol ou gasolina`, `consumo gasolina`, `preço gasolina posto`, `custo por km combustível`, `calculadora combustível` | etanol, gasolina, combustível, posto, consumo, preço, km | Price formation guide |
| SorriFit | `academia carga treino`, `progressão de carga`, `descanso treino academia`, `calistenia progressão`, `treino academia dúvida` | treino, academia, carga, série, descanso, calistenia, repetição | SorriFit Portuguese page |
| Zaflas | `produtor rural safra`, `gestão agrícola`, `agricultura de precisão`, `NDVI lavoura`, `talhão lavoura` | safra, talhão, lavoura, produtor, agrícola, NDVI, fazenda | Production module |
| GitHub | `validar CNPJ`, `validação CPF TypeScript`, `open source brasileiro`, `Rust jogo open source`, `yt-dlp app` | CNPJ, CPF, TypeScript, open source, Rust, yt-dlp, validação | Relevant repository or playground |

The terms live in `tools/ytbot/social/discovery.py`. Adding a product requires queries,
relevance terms, exclusions, a link and a campaign name.

## Curation rules

A candidate must:

- be public, in Portuguese and published within the last 7 days;
- be written by another account, never the owner's;
- contain at least one product relevance term;
- have enough text to understand the context, not just a link or media;
- not be about politics, elections, government disputes, war, violence, crime, profanity,
  giveaways, follow trains or engagement bait;
- not already have a reply from this account in the journal.

Scoring is a sorting aid, not an authorization:

- product-term matches;
- a real question;
- original post instead of a reply;
- recent publication, especially the last 48 hours;
- useful engagement;
- readable length.

Prefer personal questions and lived experience over news accounts. A news post can be
relevant, but a reply there is more likely to read as promotion. A personal post asking for
help is the best fit.

## Reply writing

Before writing:

1. Read the full post and the visible replies.
2. Identify the actual problem: a price without a source, a cost calculation, a training
   plateau, a missing farm record, an invalid document field.
3. Decide whether the project link genuinely helps answer that problem.
4. If the link does not help, do not reply.

The reply must:

- sound like a person joining the conversation, not a brand;
- add a fact, a method, a correction or a practical next step;
- use one contextual link at most, placed after the useful part;
- link only to abastevo.com.br, zaflas.com.br, sorrifit.com, github.com,
  open-data-brazil.github.io or tupibg.com;
- explain what the link contains;
- stay under 280 X characters, with each URL counted as 23;
- be respectful when disagreeing;
- avoid "confira", "descubra", "é importante destacar", "neste contexto" and generic closings.

The reply must not:

- be only a link;
- repeat the same text across posts;
- attack a person, a company or a group;
- give medical, legal or financial advice;
- promise savings, results or correctness;
- use engagement bait;
- reply to politics, violence or a sensitive personal crisis.

## Commands

```bash
python3 -m tools.ytbot social discover --network x --product abastevo --days 7 --limit 10
python3 -m tools.ytbot social reply --network x --url <status-url> --file <reply.txt> --dry-run
python3 -m tools.ytbot social reply --network x --url <status-url> --file <reply.txt>
```

`discover` runs in the hidden Xvfb browser, saves candidates to
`.local/social/x/discovery.json` and prints score, date, author, URL and a text preview.

`reply` validates the target status URL, requires a contextual link and at least ten words,
checks the X length, fills the inline reply in the hidden browser and stops before clicking
on `--dry-run`. A real reply writes `started` before the click and `posted` or `unconfirmed`
after it.

## First validated reply

- Target: <https://x.com/messsquita_/status/2121420107528413418>
- Reply: <https://x.com/AlexandreZanat/status/2121926973194973370>
- Context: a driver questioned a low gasoline price in Manaus.
- Comment: check the ANP weekly average before concluding the math does not add up; the
  Abastevo guide explains what goes into the price and where to verify the source.
- Link: Abastevo price formation guide with UTM.
- Result: posted and confirmed.

This is a manual validation of the path, not permission to scale. Every future reply still
needs a human read of the target thread.

## Error handling

| Situation | Bot action |
| --- | --- |
| Search page does not load | Stop; reopen the hidden browser and retry once |
| No candidate passes filters | Report zero; do not lower the relevance bar silently |
| Candidate is political or sensitive | Discard; never reply |
| Target already has a reply in the journal | Stop; inspect the target and journal |
| Reply has no link | Stop; the comment needs contextual value and a destination |
| Reply is too short | Stop; write a real comment with context |
| Reply over 280 | Stop; shorten and review |
| Reply button disabled | Stop before clicking; inspect target restrictions |
| Failure before the click | Safe to retry after checking the page |
| Failure after the click, no toast | Mark `unconfirmed`; inspect the thread; never retry |
| Rate limit or platform warning | Stop; wait for the platform window |
| Target deleted or protected | Stop; discard the candidate |

The reply journal is `.local/social/x/replies.json`. It is private and contains the target,
text hash, reply URL and state. `started` and `unconfirmed` records block another attempt
until a human checks the thread.

## Limits

Implemented: live search, 7-day filter, Portuguese filter, product relevance, exclusion list,
scoring, candidate file, inline text reply, contextual link requirement, dry run, confirmation
and idempotency.

Not implemented: automated comment generation, thread replies, likes, follows, DMs, mass
search, scheduling and engagement analytics. Those require a separate review.
