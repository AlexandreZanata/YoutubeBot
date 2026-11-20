# Zaflas channel profile

## Identity

| Field | Value |
| --- | --- |
| Channel | Zaflas |
| Handle | `@zaflas` |
| Channel ID | `UCi2aftoK7vlS3A6OozMHXKg` |
| Language | Brazilian Portuguese only |
| Spoken brand | Zaflas Agro |
| Website | <https://zaflas.com.br/> |
| Visual identity | Photorealistic agribusiness with bold Portuguese typography |
| Background | Golden fields and slow warm pollen particles |

The public channel describes itself as a channel about agriculture, rural management and
technology in the field. It promises simple, objective content about soil management,
productivity, irrigation, machinery, precision agriculture and farm management. It also
presents Zaflas Agro as the system built to centralize the farm's information.

The article text is Brazilian Portuguese and the prompt enforces that language. The Read
aloud voice remains **Cove**, as selected by the owner; it is not changed by the channel
profile. Existing audio files are kept as recorded. Fallem Prince and Whispers From Heaven
remain English-only.

The channel description must keep the website link at the top:

```text
🌱 Conheça o Zaflas:  https://zaflas.com.br/
```

## Schedule profile

Audience: Brazilian farmers, agronomists and agro professionals, concentrated in
Center-South Brazil (Sao Paulo/Brasilia time, UTC-3). Cuiaba is one hour behind Brasilia, so
the slot is chosen in Cuiaba hours to land on the Brazilian lunch peak, when field work
pauses and phones come out. Metricool's 2026 study of 799,718 videos shows long-form
activity concentrated between 10:00 and 16:00 local, and the national engagement peak is the
12:00 to 13:00 lunch window.

| Slot (America/Cuiaba) | Brasilia/Sao Paulo | Why |
| --- | --- | --- |
| 11:00 | 12:00 | Publishes exactly at the start of the Brazilian lunch peak, the strongest midday engagement window for the agro audience |

One video per day, unchanged. Before 2026-11-20 the channel published at 12:00 America/Cuiaba
(13:00 Brasilia), one hour into the lunch window.

## Catalog snapshot

Analyzed from the public Videos tab on 15/11/2026. Shorts are excluded from the duration
sample.

- **39 long-form videos**
- Shortest: **23:08**
- Longest: **42:51**
- Average: **30:16**
- Median: **29:54**
- Latest 30 long-form videos average: **29:41**
- Production target: **4,000 to 4,800 words**, normally **25 to 35 minutes**, with about
  **30 minutes** as the regular shape. This was recalibrated after the current narration
  voice produced 70 to 77 minutes from roughly 10,000-word articles.

The channel header shows 86 videos because it includes Shorts and other content outside the
Videos tab. Do not use that number as the long-form sample size.

The Zaflas article generation targets **26,000 to 34,000 characters** (about 4,000 to 4,800
words). The hard ceiling follows the longest published video plus 30 minutes: the channel
longest is about 77 minutes, so a video up to about 107 minutes is accepted and the article
safety cap is **100,000 characters**. Above that the bot asks for one rewrite that must cut
at least 15 percent; a rewrite below 2,000 characters is rejected. This avoids discarding a
long article that would still fit the channel.

## Title patterns

The catalog uses practical questions about costs, trade-offs, technology and farm decisions:

- *Quanto a Logística Realmente Tira do Lucro de uma Fazenda?*
- *Quanto da Sua Produção Está Ficando no Chão Durante a Colheita?*
- *Uma Fazenda Pode Produzir Muito e Mesmo Assim Perder Dinheiro?*
- *Uma Máquina Agrícola Maior Realmente Reduz o Custo por Hectare?*
- *Vender a Safra Antes de Plantar: Proteção ou Risco para o Produtor?*
- *Por Que o Brasil Depende Tanto de Fertilizantes Estrangeiros?*

Titles are direct, specific and Portuguese. They promise a practical explanation, not a
miracle result.

## Article generation

The local instructions in `tools/ytbot/prompts/zaflas_agro/article_header.txt` are the
canonical source. The main rules:

- Write one complete Brazilian Portuguese audio article.
- Address Brazilian farmers, rural managers, agronomists and agricultural professionals.
- Use an authoritative, accessible and thoughtful technical voice.
- Explain technology, agronomy, management, costs, risks and productivity together.
- Target 4,000 to 4,800 words, normally 25 to 35 minutes.
- Open with a single question that expresses the episode topic.
- Use the fixed identification once:
  `Você está ouvindo Zaflas Agro, conhecimento para quem faz o campo acontecer.`
- End with the exact sign-off:
  `Zaflas Agro. Tecnologia, gestão e conhecimento para o campo.`
- Explain technical terms before relying on them.
- Separate technical possibility, economic viability and guaranteed on-farm outcome.
- Use hypothetical examples only when explicitly identified.
- Do not invent results, studies, quotations, statistics, regulations, subsidies or current
  prices.
- Prefer Embrapa, universities and competent Brazilian public bodies for factual claims.
- No blanket agronomic recommendations, pesticide recipes or universal payback promises.
- No em dashes or en dashes.
- Output only the narration that will be read aloud.

The existing energy article excerpt in the prompt is a style reference only. Hooks, examples,
reasoning and conclusions must change for each episode.

## Thumbnail profile

Six recent thumbnails were downloaded and measured privately. All are 1280x720.

### Layout

- Left **45 to 50%**: smooth black or near-black cinematic gradient with huge uppercase
  Portuguese typography.
- Right **50 to 55%**: one photorealistic Brazilian agribusiness scene.
- No visible dividing line, card, frame, logo or decorative clutter.
- The photograph must communicate the topic even without the text.
- Main keyword is the largest element; supporting words are smaller.
- White supporting text and one thematic keyword color.
- Text stays inside YouTube safe margins.

### Typography

- Extremely bold condensed sans-serif.
- Uppercase, clean solid characters, crisp edges.
- Reference feel: Anton, Bebas Neue, Oswald Heavy or premium editorial condensed type.
- One main keyword, one main message, supporting words.
- No thin, rounded, serif, handwritten, metallic, glowing or 3D text.

### Palette

| Role | Approximate color |
| --- | --- |
| Left gradient | `#0A0A0A` |
| Supporting text | `#FFFFFF` |
| Golden/yellow accent | `#F4C400` |
| Agricultural green accent | `#5DBB2A` |
| Deep crop green | `#2E5A1C` |
| Soil and grain brown | `#8A6A35` |

Mean RGB across the samples is approximately **103, 88, 50**. Luminance ranges from about
**65 to 103**, with a high standard deviation, so the images combine deep black areas with
bright sunset highlights. Saturation varies from restrained to strong depending on the
accent.

Accent color follows the topic: grain/harvest uses gold, crops and technology use
agricultural green, finance uses green, warnings and pests use red/orange, water uses blue,
soil uses terracotta, coffee uses deep brown or cherry red. Never use random colors.

The canonical prompt is `tools/ytbot/prompts/zaflas_agro/thumbnail.txt`. Do not attach the
reference thumbnails to generation; the prompt contains the style.

## Background

`assets/backgrounds/zaflas_agro.mp4` with the `agro` particle profile:

- golden fields and warm pollen;
- slow horizontal drift;
- warm particles `(255, 225, 160)`;
- low motion so narration remains the focus.

## Metadata and description

The video description is not the same as the channel About text. It follows a fixed brand
prefix:

1. `🌱 Conheça o Zaflas:  https://zaflas.com.br/`
2. Subscription link for channel `UCi2aftoK7vlS3A6OozMHXKg`.
3. `nossas redes:`
4. LinkedIn, Instagram, Facebook, YouTube and GitHub links.
5. One topic-specific paragraph of **120 to 170 Portuguese words**.
6. **Seven lowercase hashtags**.
7. `TAGS:` with comma-separated Portuguese tags within **425 characters**.

The metadata prompt replaces the source social-link em dashes with colons to obey the bot's
no-dash rule. The fixed website and social URLs must remain intact. Do not add a second sales
pitch, timestamps, references, a disclaimer block or unsupported facts.

Sample tag families:

- herbicide resistance, plants daninhas, manejo, lavoura
- logística, frete, armazenagem, escoamento, lucro
- custo por hectare, margem, fluxo de caixa, gestão rural
- dados agrícolas, telemetria, LGPD, segurança
- seguro rural, Proagro, Zarc, risco
- silagem, silo, grãos, perdas

## Sample videos

| Video | Duration | Theme |
| --- | --- | --- |
| `S67HAI5L66E` | 32:53 | Herbicide resistance |
| `mSFlmieZIr8` | 30:01 | Logistics and farm profit |
| `1P7V7ZMw_wY` | 42:48 | High production, low profit |
| `4SjwaLepRS0` | 30:22 | Ownership of machine data |
| `0-lvQHAwtDs` | 27:08 | Rural insurance |
| `3Rbk7ldNvpA` | 30:40 | On-farm grain storage |

## Account status

A dedicated `zaflas` browser profile was created under
`.local/accounts/browser/zaflas` with CDP port `9302`. The channel identity is bound and
verified. This is an **upload-only** profile: ChatGPT and the capture extension are not
required. Generation uses the main `legacy` profile; catalog, Community, upload and
scheduling use the Zaflas profile.

Zaflas publishes **one video per day at 11:00 America/Cuiaba**, which is **12:00 in
Sao Paulo/Brasilia**, the start of the Brazilian lunch peak. The channel profile uses
`slots=(11,)`, so a batch fills one slot per day.

## Limits

Public transcripts were not used for this analysis. The profile is based on the full catalog,
six thumbnails and sampled video descriptions. Refresh it when the visual or editorial
direction changes.
