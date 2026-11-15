# Promotion agenda runbook

This is the agent runbook for researching, auditing and building the owner's promotion
agenda. It is the only promotion artifact that belongs in Git. Research notes, the filled
calendar, article drafts and copy libraries are private working files under
`docs/promotion/` (ignored) or `.local/promotion/`; never commit them.

The agenda is a review calendar, not a publishing schedule. Every row is a proposal that the
owner must approve. The agent never posts, schedules, sends messages, follows accounts or
changes a profile while producing it.

All network modules use the YouTube runtime model: a visible browser only for owner login and
challenges; agenda validation, status and publishing run hidden in Xvfb with the same private
profile. Each network gets its own display and CDP port.

Discovery is a separate review step. It searches public conversations from the last 7 days,
filters out politics, violence and engagement bait, and proposes contextual replies. A human
reads the thread before a reply is written. Aim for five contextual replies per original post,
tracked with `social quota`; report a gap instead of forcing a reply. See
[discovery](SOCIAL-DISCOVERY.md).

## Inputs

Read these before researching:

- [Promotion focus](PROMOTION.md): priorities, destinations, claims and rules.
- [Social sessions](SOCIAL.md): private profiles and X connection.
- `AGENTS.md`: repository policy.
- The live sites: <https://abastevo.com.br/>, <https://zaflas.com.br/> and
  <https://sorrifit.com/?idioma=pt>. The English SorriFit page is `/en`; do not mix language
  destinations.
- The GitHub repositories: br-validators, Abastevo, TBG and OpenYT.
- The current product documentation, pricing, release notes and known limitations.
- Previous cycle data, if it exists. If there is no measured data, write "baseline unknown";
  never write zero.

Private working output for a cycle:

```
docs/promotion/<YYYY-MM>/
  00-sources.md      source log and confidence
  01-audit.md        product, link, language and risk audit
  02-agenda.md       the filled 30-day review calendar
  03-experiments.md  measurement plan and experiments
  04-drafts/         optional copy or article drafts, never committed
```

## Research protocol

1. Read the product source of truth before writing a claim. A landing page proves what it
   advertises, not that the feature works after login. A README proves what the repository
   documents, not production availability.
2. Record every source with URL, date, type, finding, confidence and limitation. Separate
   primary sources, observational studies and opinion.
3. Classify each statement:
   - **Fact:** directly observed in a primary source.
   - **Interpretation:** editorial reading of the evidence.
   - **Hypothesis:** needs a test, a measurement or owner confirmation.
4. Prefer primary and recent sources: official product docs, platform help and policy,
   the X algorithm repository, Google Search Central, NN/g, GitHub Blog, academic papers and
   Brazilian official data sources. Use secondary studies only as directional evidence.
5. Do not turn one study into a universal rule. "Best time", "best format" and "best hook"
   are hypotheses until the owner's own audience confirms them.
6. Listen to 10 to 20 public communities, creators or forums per product. Record why each is
   relevant and how to participate without spam. Do not scrape private profiles or groups.
7. For each product, collect the audience's words, objections, triggers and current
   alternatives. Do not invent personas from demographics alone.
8. Write only what can be sourced. If a number, quote, feature or result is missing, mark it
   as unknown or hypothesis. Never create a testimonial, benchmark or user count.

## Audit protocol

Build a truth table per product:

| Field | What to record |
| --- | --- |
| Claim | The exact promise or feature |
| Source | URL and date |
| State | shipped, beta, planned or unknown |
| Allowed wording | Conservative Portuguese phrasing |
| Forbidden wording | What would overpromise |
| Proof | Screenshot, doc, release note or demo needed |

Audit checklist:

- [ ] Every product claim matches the live site or repository.
- [ ] Planned, beta and unpublished states are explicit.
- [ ] Prices, plans and trial conditions are current and dated.
- [ ] The main CTA exists and reaches the correct language and page.
- [ ] Links return the expected page; no broken or redirected destination.
- [ ] Functional query parameters survive UTM addition, for example SorriFit `?idioma=pt`.
- [ ] No personal data, precise location, CNPJ, health data or credentials appear in a URL.
- [ ] The landing page promise, proof and CTA agree with the proposed post.
- [ ] The product's privacy statement is respected. Abastevo states no cookies or trackers;
      do not add tracking without an explicit decision.
- [ ] Health, fiscal, legal and price claims have the required qualification.
- [ ] The X profile, bio, pinned post and link are consistent with the current campaign.
- [ ] Platform rules on spam, automation, authenticity and manipulation are respected.
- [ ] The calendar fits the owner's routine, not an imaginary content team.

Audit the language:

- Brazilian Portuguese, natural and specific.
- Write like a person talking to a friend, not like a press release or a language model.
- Short sentences, active voice, one idea per paragraph. Vary the rhythm.
- Explain jargon before using it.
- Cut "É importante destacar", "Neste contexto", "Além disso", "Vale ressaltar", "Descubra",
  forced triads and generic closing lines.
- Read the copy aloud. If it sounds polished in a generic way, rewrite it.
- No "você sabia", "revolucionário", "disruptivo", "segredo", "hack" or "última chance".
- No em dash in published copy. Use commas, periods or parentheses.
- No engagement bait, no "comente SIM", no "siga para mais", no "marque 3 amigos".
- One clear CTA per row.
- Facts, opinions and hypotheses are visibly separated.
- The text passes a read-aloud test and does not promise income, weight loss, savings,
  performance or legal outcome.

## Building the agenda

Default cycle: 30 days in `America/Cuiaba`, starting on the next review day.

Default mix, unless the owner changes the priority:

- 15 Abastevo pieces, 50%.
- 7 Zaflas pieces, 23.3%.
- 5 SorriFit pieces, 16.7%.
- 3 GitHub pieces, 10%.

Default capacity:

- 1 main post per day.
- 15 to 20 minutes of human conversation per day.
- 4 threads, 4 polls and 8 visual briefs in the cycle.
- Remaining days use short text posts or a prepared reserve.
- Sunday: low activity, no forced replies.
- Keep a buffer. Do not fill every slot if the week is already at five to six hours.

Each calendar row must contain:

| Field | Requirement |
| --- | --- |
| Date and ID | Stable ID such as P01 or T01 |
| Product | Abastevo, Zaflas, SorriFit or one GitHub project |
| Format | text, image, video, thread, poll or article distribution |
| Hook | One specific tension, number, question or observation |
| Audience | One primary segment |
| Objective | awareness, consideration, activation or learning |
| CTA | One action, matching the destination |
| Destination | Exact URL with UTM |
| Metric | One measurable event or learning |
| Conversation task | A specific 15 to 20 minute human task |
| Risk note | Claim, privacy or platform risk |
| Status | draft, reviewed or approved |

Rules for the rows:

- One product, one audience and one CTA per row.
- No duplicate hooks or near-duplicate copy across the cycle.
- Native value first. The post must make sense before the click.
- Test link placement, in the post versus the first reply, instead of assuming a rule.
- Visual briefs must use real screenshots or diagrams, no invented interface and no private
  data.
- Seasonal or commemorative dates only when they have a verified link to the audience.
- The agenda is a proposal. Do not create scheduled posts or Studio entries.

## Measurement plan

Define a qualified visit as a visit to the correct destination that includes an action tied
to the problem, such as completing a calculation or opening a query result. A pageview is not
a conversion. A store click is not an install. A GitHub star is not adoption.

Use a stable UTM convention:

- `utm_source`: x, linkedin, instagram, tiktok, youtube, reddit, github.
- `utm_medium`: organic_social, community, referral.
- `utm_campaign`: product, theme and cycle.
- `utm_content`: stable post ID, format, variant and placement.

Propose events per product, but do not claim they exist:

- Abastevo: query completed, calculator completed, guide used.
- Zaflas: demo requested, trial started, first workflow completed.
- SorriFit: store opened, first open, workout saved, only with consented aggregate data.
- br-validators: playground example completed, release asset opened.
- TBG: practice started, practice completed.
- OpenYT: release asset opened, activation only if consented measurement exists.
- All repositories: stars and useful issues, aggregated and manually classified.

For each experiment, write the hypothesis, metric, duration, success threshold and stop rule.
Run an experiment for at least two weeks before judging a format. Keep baselines marked
unknown until measured.

## Acceptance criteria

The cycle is ready for owner review only when:

- [ ] Every product claim has a source or is marked as hypothesis.
- [ ] Every number has a source and a date.
- [ ] Every row has audience, objective, CTA, destination and metric.
- [ ] Every link is correct, reachable and language-consistent.
- [ ] The 30 rows fit the declared weekly capacity.
- [ ] The mix respects the current priority.
- [ ] The language audit passes.
- [ ] Planned, beta and unpublished states are visible.
- [ ] No private data, credentials or tracking surprises exist.
- [ ] No post was published, scheduled or sent.
- [ ] The working drafts remain outside Git.

## Change control

- Update this runbook only when the process changes.
- Keep the filled calendar, sources, audit and drafts private.
- When a product, price, link or platform policy changes, update the truth table first.
- Use a branch and pull request for runbook changes, with the normal CI gate.
- At the end of a cycle, record what was learned and what the next cycle should test.
