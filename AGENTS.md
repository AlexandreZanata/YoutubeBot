# YoutubeBot agent guide

This is YoutubeBot: a Firefox/Chrome audio-capture extension, Python/PySide6 video
studio, and resumable Playwright YouTube production/scheduled-upload pipeline.
Read [the component map](docs/ARCHITECTURE.md), then only the relevant module and tests.
English in code, comments, documentation and commits; user-facing UI may use Portuguese.

## Preserve existing behavior

- Extension capture, filename templates and download behavior stay unchanged.
- Keep the existing generation modes, narration, voices, subtitles, backgrounds and rendering.
  Never speed up or alter the owner's narration audio in new videos; existing uploads keep
  their audio. A long video may run up to 20 minutes past the channel's longest published
  video (Vocal Pages: about 124 minutes) instead.
- Every channel is English-only except Zaflas. Infinite Random Worlds, Vocal Pages, Fallem
  Prince and Whispers From Heaven use English narration, subtitles, metadata and thumbnail
  text. Zaflas is Brazilian Portuguese in every long video and every Short: script,
  narration, titles, descriptions, tags and thumbnail text. Reject any English output on
  Zaflas before audio, render or upload. The Read aloud voice remains Cove as selected by
  the owner. Operator/browser interface language never changes content language.
- `tools/ytbot` keeps channel prompts, deduplication, resumable stage records and sequential
  upload/scheduling. Existing profiles are `fallem-prince`, `whispers-from-heaven`, `zaflas`,
  `infinite-random-worlds`, `vocal-pages`, `zanata`, `reflection`, `midnight-tales`,
  `sepia-atlas` and `bathylora`.
  Whispers uses 2,400 to 2,800 words (15 to 17 minutes), Sacred Brown Engraving thumbnails,
  brown stippling background and the metadata/tag patterns in
  [its channel profile](docs/channels/whispers-from-heaven.md). Zaflas uses Brazilian
  Portuguese, 4,000 to 4,800 words (25 to 35 minutes), photorealistic agribusiness
  thumbnails, the fixed site/social description prefix and
  [its channel profile](docs/channels/zaflas.md). Zaflas publishes one video per day at
  11:00 America/Cuiaba (12:00 in Sao Paulo/Brasilia, the Brazilian lunch peak). Its dedicated
  profile is upload-only; generation stays in legacy.
  Zaflas articles target 4,000 to 4,800 words (26,000 to 34,000 characters) with one bounded
  rewrite above the ceiling.
- Sepia Atlas is English-only, American English, premium historical documentaries built on
  authentic archival photography: 15 to 25 minutes average (1,900 to 3,200 words, tolerance up
  to 40 minutes / ~5,100 words), one video every two days at 21:00, mandatory `0.9x` narration
  speed (`slow_narration(..., factor=0.9)`), mandatory broadcast documentary voice filter
  (`DOCUMENTARY_VOICE_FILTER`) with subtle filtered analog room-tone, smooth 1.2s optical
  cross-dissolves, mandatory narration-to-image synchronization, Cinematic Archival Minimalism
  (Archival Black, Aged Gold, Antique Ivory) and a photographer's eye for the Atlas Frame emblem.
  Never fabricate a historical photograph or present a generated image as documentary evidence.
  The first episode stays private for owner review and is never auto-published. See
  [its channel profile](docs/channels/sepia-atlas.md).
- Bathylora (`@Bathylora`, `UCxuhkOi4CDDStvQFpRGsoXA`) is English-only, American English,
  premium deep-ocean science documentaries built on authentic oceanographic photography (NOAA
  Ocean Exploration priority, USGS and verified open scientific archives): 15 to 25 minutes
  average (1,900 to 3,200 words, tolerance up to 40 minutes / ~5,100 words), one video every two days
  at 21:00, mandatory `0.9x` narration speed (`slow_narration(..., factor=0.9)`), mandatory
  broadcast documentary voice filter (`DOCUMENTARY_VOICE_FILTER`) with subtle filtered analog
  room-tone, smooth 1.2s optical cross-dissolves, mandatory narration-to-image synchronization,
  **Abyssal Cinema** visual identity (Abyssal Black `#030B12`, Deep Ocean `#071F2C`,
  Bioluminescent Cyan `#55D9D0`, Ocean Mist `#B5D2D7`, Arctic White `#EDF7F5`, Submersed Teal
  `#164958`) and **The Depth Mark** emblem. Never reuse Sepia Atlas aesthetics, never fabricate
  species or discoveries, never present AI imagery as scientific evidence, and keep the first
  episode private for owner review. See [its channel profile](docs/channels/bathylora.md) and
  [its exact step-by-step production pipeline](docs/channels/bathylora-pipeline.md)
  (`python3 -m tools.ytbot documentary init|collect|audit|narrate|render|qc`).
- Midnight Tales is English-only long-form sleep stories for adults, 6,500 to 9,000 words
  (45 to 65 minutes), one video every two days at 21:00 and one Short every two days at 09:00.
  Thumbnails are painterly cinematic scenes with no text, and the thumbnail is the still video
  background. See [its channel profile](docs/channels/midnight-tales.md).
- the word of reflection is English-only biblical stories at 08:00 and 21:00 daily, 14 to 16
  minutes, full-bleed cinematic thumbnails with a two or three word white title. It shares the
  Google account with Vocal Pages. See
  [its channel profile](docs/channels/the-word-of-reflection.md).
- zanata is English-only book summaries at 10:00 daily, 50 to 55 minutes, with the yellow
  BOOK SUMMARY thumbnail formula in [its channel profile](docs/channels/zanata.md). It shares
  the Google account with Fallem Prince: switch the brand channel in Studio, never sign out.
- Infinite Random Worlds is English-only and has no background video: the episode thumbnail
  is the still background under the burned-in subtitles. It keeps no music, the five-second
  quick finish and a free per-episode thumbnail style. Stories target 4,500 to 6,000 words
  (32 to 43 minutes) with a unique world each. See
  [its channel profile](docs/channels/infinite-random-worlds.md).
- Require an explicit channel. Verify its YouTube channel ID before mutating Studio.
  When the owner names a channel by theme ("fundo do mar", "canal de documentário"), resolve it
  through [channel nicknames](docs/CHANNEL-ALIAS.md) and never guess between two channels.
- Schedule only: up to 2 videos/day for fallem prince at 10:00 and 21:00 in
  America/Cuiaba (09:00/20:00 US Eastern), at least 60 minutes ahead, not made for kids, custom
  thumbnail and Subscribe + Best for viewer end screen.
- The owner reduced fallem prince to 2/day on 2026-11-20. Days with four scheduled videos
  are rebalanced: the extras move to future days at 10:00/21:00 until
  every day holds at most two. Use `--start-date YYYY-MM-DD` for a specific first day.
- Posting hours are America/Cuiaba slots chosen per channel audience: US Eastern for every
  English channel, Brasilia for Zaflas. The rationale and the Cuiabá-to-audience equivalence
  live in each [channel profile](docs/channels/) under "Schedule profile". Two slots per day
  are always at least six hours apart, and the frequency never changes when hours are tuned.
  `python3 -m tools.ytbot reschedule --channel <slug>` moves already-scheduled future videos
  to the current slots without touching generation.
- Preserve channel-specific title/description/tags rules and media quality.
- Never blindly retry an uncertain upload or start the same service operation twice.

## Boundaries

Accounts, browser profiles, OAuth tokens, generated media, model caches and run history
are private `.local/` state. Never log tokens/cookies or put them in Git. Google sign-in
uses the owner's visible browser and consent; do not bypass challenges or copy another
profile while in use. Browser automation remains the upload path; optional OAuth only
helps discover and verify account/channel identity. Never silently switch channels.
Every entry point follows the [session contract](docs/SESSION-CONTRACT.md): a signed-out
profile records `needs-login.json`, opens one visible window and stops; it never clicks the
avatar blindly or retries.

When a session actually expires, the bot records `.local/ytbot/needs-login.json`, notifies the
desktop, opens the profile in a visible window on the sign-in page and stops the batch. The
owner completes the login or two-step verification by hand; the marker clears after the next
successful channel check. Never reopen a profile that is merely idle and never retry the
expired step in a loop. See [accounts](docs/ACCOUNTS.md).

The service CLI is typed and bounded. Never expose a general shell, arbitrary subprocess
arguments or account secrets to ZaturoBot. Real generation/upload/Google consent tests
are opt-in; CI uses fixtures. Read [accounts](docs/ACCOUNTS.md), [service](docs/SERVICE.md)
and [migration](docs/MIGRATION.md) for those operations.

## Autonomous operation (owner decision 2026-11-20)

When the owner leaves a batch running unattended, monitor it and act on errors instead of
waiting for instructions:

- A single failed video or Short (expired session, Studio timeout, schedule not confirmed) is
  logged to `.local/ytbot/incidents.log` and the queue continues with the next item. Never
  regenerate or re-upload a video that already has a `videoId`; retry only its details/schedule.
- An expired account is handled by the session contract: record, open the visible window once,
  and continue with every other channel that does not depend on it.
- Never stop the whole run for one channel. Stop only when no remaining item can proceed at all,
  and then report why.
- At the end, report every incident, what was recovered and what still needs the owner. Files
  already uploaded stay as drafts; nothing is published twice.

## Verify and hand off

Use `npm ci`, then `npm run verify` (extension lint/build/package + Node/Python tests).
Keep tests behavioral. Run the smallest useful command during development and the complete
gate before publication. Report actual checks and remaining physical-account/GPU limits.
No harness, dynamic rule resolver or hook framework is required. Keep docs concise and
canonical: README for commands, architecture for ownership, topic docs for contracts.
Never delete the owner's original local media, browser state, credentials or unrelated repos.


The owner's bounded native-chat extension also authorizes generation-only service jobs.
Preserve scheduled-submit defaults; `generate` must never upload. `preflight.py` reports
actual positive/login-required/unknown browser evidence without raw credential output.
`generation.py` reuses the existing assets/render core sequentially. Uncertain operations
remain fenced; only verified ready video artifacts count as completion. No live account,
media generation or paid action belongs in CI fixtures.

## Codex media on work PCs

When Codex is installed, use `codex_media.py` for thumbnails, metadata and automatic topic suggestions; ChatGPT keeps
article generation and Read aloud only. The coordinator must be `gpt-6.1-terra` with low
reasoning effort, or owner-selected `gpt-6-luna` with low effort. The native image tool
renders the thumbnail. An empty or invalid Codex image path is retried once automatically; if it persists,
stop. Never silently use a more expensive coordinator or API-key fallback.
The only ChatGPT image fallback is the owner-authorized one after Codex reports its usage
limit: log the reset time, record it privately and resume Codex when credits return. Preserve media-attempt fences and existing
artifacts. See [Codex media setup](docs/CODEX-MEDIA.md).

Only fallem prince alternates dense and classic thumbnail prompts. Whispers and Zaflas use
their single channel prompt; a stale classic style falls back to dense.

Fallem Prince thumbnails follow the owner's dense, dark monochrome narrative
engravings. The style is written into `tools/ytbot/prompts/fallem_prince/thumbnail.txt`;
never attach the two style-reference images, because they override the subject and make
every thumbnail reuse the same character. Keep the etched midtones and full-scene depth,
but invent a unique subject and metaphor for each article. The earlier large white
void/two-color poster interpretation is superseded. Alternate the dense prompt with
`thumbnail-classic.txt`: six dense and six classic in a twelve-video batch.

## Shorts

Every channel now publishes Vertical Shorts through the `faith-shorts` protocol: 1080x1920,
35 to 55 seconds, one generated image per Short as its background, burned-in subtitles and no
custom thumbnail. Every Short must have its own image tied to its story; never reuse a scene from
another Short, and a near-duplicate background is replaced once. Each channel keeps its own art
style, topic queue and slot hours: Zaflas
09:00/18:00, reflection 08:00/20:00, Whispers 09:00/21:00, zanata 09:00, Fallem Prince 21:00,
Infinite Random Worlds 09:00, Vocal Pages 21:00, Midnight Tales one every two days at 09:00,
Sepia Atlas 21:00 and Bathylora 21:00.
The Zaflas `shorts` command remains for legacy batches; new Shorts go through `faith-shorts`.
Generation uses the legacy ChatGPT profile and only the upload touches the channel profile. Do
not route Shorts through the long-form batch. See [Shorts](docs/SHORTS.md).

## Commercial affiliates

Mercado Livre affiliate products live in the `commercial` module. Each network has a private
profile under `.local/commercial/<network>/`; login is manual in the visible browser and
status/publishing work runs hidden. Read products and links only from the logged-in affiliate
hub, never invent prices, commissions or links, and never commit browser state.

WhatsApp Web in the commercial module is owner-operated: manual QR login in the visible
browser, hidden sending, one chat at a time, human intervals, a `--live` gate and a journal
that blocks repeats. It never broadcasts and never feeds the Procurali pipeline. The
DOM map, state machine and troubleshooting are in
[WhatsApp Web](docs/COMMERCIAL-WHATSAPP.md).

The Zaflas Inova Simples sales agent is the only list use (owner decision 2026-11-17): it opens
one-to-one conversations only with businesses from the owner's reviewed Google Maps CSV (never
scraped), at most 50 first contacts per day in business hours, never repeats an opening and
sends at most one follow-up. It answers funnel leads by
`tools/ytbot/commercial/whatsapp/sales/sales_rules.toml`, through OpenCode Go: free models
first (zero price in the live catalog, rotating, paused on timeout or no credits), then only
`deepseek-v4.1-flash` and `muse-spark-1.3-contributor` as paid fallback; a price, deadline, link
or promise outside that file falls back to
its fixed text or goes to the owner. A refusal sends the owner's five-bubble indication ask and then the chat goes to the owner
(owner decision 2026-11-19); a true opt-out ("para de me mandar", "spam", "me remove") is the
permanent do-not-contact entry. The robot
question gets an honest answer, the OpenCode key stays in `.local/`, and `--live` stays
required. Imported numbers start with replies active: the agent answers a lead that writes even before
an opening, `sales activate|pause` toggles that per lead, and `run --live --prospect --limit`
opens one number at a time up to 50/day. `sales queue list|send` is a view of `leads.json`
(Maps leads in CSV order, no second store) whose `send --live --limit 1` opens exactly one
number through the same path and run lock; the opening names the business as on Google Maps. The rules' values are of the static institutional
site only; apps and systems are always quoted by the owner and the bot must never tie the site
price to them. Closing the
institutional site sends only the Pix keys written in the rules file; closing an app or system,
a payment message and a refusal after interest go to the owner, but an app or system first gets a
gentle requirements interview (restating what the client said, then a summary the client
confirms) so the owner receives the complete ficha. A staff member is asked for the
decision maker's contact; a number they send becomes a referral lead with its own opening and
its own daily limit. See [sales agent](docs/COMMERCIAL-WHATSAPP-SALES.md).

The separate Brasa & Pão ordering agent inherits the same WhatsApp sender, listener, journal,
store, pacing and free-first model router, but keeps its own rules, state machine, menu and
private root under `.local/commercial/whatsapp/lanchonete/`. It only replies to customers who
wrote first, confirms every order item, extra, fee, payment and change before writing the
kitchen ficha, and never invents a price or sends a Pix key. Run it with
`python3 -m tools.ytbot commercial lanchonete ... --network whatsapp`; `--live` is required to
send. See [ordering agent](docs/COMMERCIAL-WHATSAPP-LANCHONETE.md).

Google Maps lead research runs with `python3 -m tools.ytbot commercial maps
login|status|research|verify|export`: one tab, a person's pace, the owner's manual Google login,
hidden Chrome after login, a stop at any challenge, read-only on Google, a confirmation search
before a business counts as having no site, and an owner-reviewed CSV as the only output.
Selectors, category catalog, exclusions and score are the versioned
`tools/ytbot/commercial/maps/maps_rules.toml`; runs are resumable under
`.local/commercial/maps/runs/`; `commercial sales import --source google-maps-manual` adds the
reviewed rows. Tests use saved HTML only. Its filters, score and the "Ajuste do Google Maps"
access steps are in [Maps research](docs/COMMERCIAL-MAPS-RESEARCH.md).

When delivering captured products from this workstation to the remote Procurali VPS (database,
site, Telegram offers group queue, and WhatsApp Web assisted drafts), never copy VPS origin IPs,
SSH private keys or device tokens into this repository and never post to Telegram/WhatsApp directly
from YoutubeBot. Instead run the sibling ZaturoBot physical-key sync launcher
(`bash ../ZaturoBot/scripts/procurali-local-sync.sh --once` or `--watch`), which opens a
port-forwarding-only `nologin` SSH tunnel (`procurali-link`), checks SHA-256 changes, uploads static
product photos to MinIO, and ingests validated batches to the VPS Hub as `procurali-local-pc`. For
sub-millisecond local queries of prior VPS offers and price history (plus automatic comparison
during `commercial products`), use `commercial reference --network mercadolivre` (with `--refresh`
when a fresh ETag snapshot from the VPS is needed). See [commercial](docs/COMMERCIAL.md).

## Social promotion

The promotion module publishes the owner's GitHub projects in Brazilian Portuguese. The
primary destinations are abastevo.com.br, zaflas.com.br and sorrifit.com, with Abastevo first;
the GitHub repositories support credibility and developer reach. Keep one code folder and one
private browser profile per network under `tools/ytbot/social/` and `.local/social/`. Require
an explicit network. X sign-in is manual in the visible browser; never automate passwords,
two-factor or challenges, and never commit cookies, tokens, screenshots with account data or
private paths. `social status` saves only the handle, display name and verification time. Do
not publish or change a profile until the owner gives explicit copy and action instructions.
See [social](docs/SOCIAL.md), [promotion focus](docs/PROMOTION.md) and the
[agenda runbook](docs/PROMOTION-AGENDA.md). X publishing is limited to one approved agenda
item, text or one reviewed image, with UTM and the private idempotency journal. Never retry an
item marked started or unconfirmed, and never delete a published post without owner approval.
Instagram currently supports session and account recognition only; its publishing and
discovery modules are not implemented. Every social-network module follows the YouTube runtime
model: a visible Chrome window is
used only for owner login and platform challenges. After login, catalog or agenda checks,
status and publishing run in a hidden Chrome/Xvfb runtime on a dedicated display, with the
same private profile and a separate CDP port. No publishing path may require a visible
window.
See [X publishing](docs/SOCIAL-POSTING.md).

Discovery searches public X posts from the last 7 days for fuel, fitness, agro and developer
conversations. Filter politics, violence, profanity and engagement bait. A human reads the
target thread before any reply. A reply must add context or a method, may carry one relevant
link, and never consists only of a link. One reply per target, recorded in the private reply
journal; never retry a started or unconfirmed reply. The target is ten contextual replies for
each original post published; track it with `social quota` and report gaps instead of forcing
irrelevant comments. See [discovery](docs/SOCIAL-DISCOVERY.md).

On X only, every day also carries fifteen polemic comments on public posts under 24 hours with
large reach. The comment defends a contrarian but defensible thesis that invites disagreement,
never a personal attack, a false claim, politics, violence or a bait phrase. One project link
maximum, after the argument, with no invented number. If fewer than fifteen pass the bar,
report the gap. Drafts stay local until the owner gives the publish command. The daily cap is 25 replies
(ten contextual plus fifteen polemic). Publishing follows the pacing protocol in
[X publishing](docs/SOCIAL-POSTING.md): one action at a time, 2 to 5 minutes apart, never two
at the same time, and stop on unconfirmed or rate limit. Simulating keystrokes or rotating
identities to evade platform detection is forbidden. This rule never applies to YouTube or
to Community posts.

## Intelligent distribution

"Distribuição inteligente" or "distribui" is the mode that chooses the channels by itself.
Audit the future scheduled uploads of every registered channel, then give each new video to
the channel with the fewest scheduled ones, water-filling until the requested count is
allocated. Channels with a large queue may receive zero. Never ask which channel to use.

Run it with `python3 -m tools.ytbot distribute --count N` (add `--dry-run` to only print the
plan). Each channel keeps its own prompts, language, article length, background, thumbnail
style, upload profile, slot hours and `interval_days`; the distribution only decides the
quantity. See [distribution](docs/DISTRIBUTE.md).

## Community

After the asset stage of every batch, check the selected channel's Community tab. The rule
is one post per rolling 24 hours. If the newest post is younger than 24 hours, do nothing;
otherwise publish one question post that carries a dedicated square art generated for that
post in the channel's visual style (never a plain crop of a video thumbnail), a link to the
related video and, on Zaflas, the site https://zaflas.com.br/. Community text follows the
channel language: English everywhere except Zaflas, which is Brazilian Portuguese. Never
retry an unconfirmed publish blindly. See [community](docs/COMMUNITY.md).

## Desktop manager

`desktop/` is a Rust + Slint manager that lists every profile and logged network from the
private registries and exposes only open/stop actions through the typed CLI. Its home page,
the Central, reads the sales agent's `central.json` (interventions, messages and client
fichas) and may only hand a validated `https://wa.me/<digits>` link or a re-checked path
inside that client's folder under `sales/clientes/` (the folder, its `ficha.md`, or a media
file of a known type) to `xdg-open`. Keep the domain crate free of UI types. See [desktop](docs/DESKTOP.md) and
[desktop/README.md](desktop/README.md).

## Generation and upload profiles

Generation always uses the main profile with the ChatGPT login and audio-capture extension.
Additional profiles are upload-only: they require the YouTube Studio login and channel
binding, not ChatGPT or the capture extension. Use `--account legacy --upload-account <id>`
to keep generation in the main profile and send only catalog, Community, upload and schedule
work to the upload profile. Verify the channel identity in the upload profile before use.

## Upload failure handling

Every upload wait is bounded and logged. `upload_guard` blocks before Studio when the
video, metadata title/description or a valid thumbnail is missing. After upload,
`video_details` applies title, description, tags and thumbnail on the edit page, waits for the
`studiothumbnail` 200 and verifies title, description and tags before checks and the end
screen. The tags field is behind "Mostrar mais" in YouTube Studio.
An end-screen verification warning does not block scheduling; the final audit fixes it.

Never re-upload a video that already has an `upload.json` video ID: schedule the existing
draft. If checks do not finish, leave the draft, record the video ID and slot, and report;
never retry an uncertain upload or wait 30 minutes silently. Use
[Upload recovery](docs/UPLOAD-RECOVERY.md) for the full catalog and manual fallbacks.

## Performance and reliability changes

Every performance or reliability fix must be documented in README,
`docs/UPLOAD-RECOVERY.md` or the relevant contract, covered by `npm run verify`, and
pushed to GitHub through a branch and PR after CI passes. Never keep a silent local
optimization.

Disk exhaustion is a media failure, not a retry problem. Keep batch, audio, render and capture
space guards; fail early with the available and required gigabytes. Upload files are staged in
`.local/ytbot/upload-tmp`. Large runs may live on `/data` through the `.local/ytbot/runs`
symlink.

Cleanup runs before every `run` and `shorts`: empty the trash, clear the upload staging and
remove `video.mp4`, `narration.wav`, `thumbnail.frame.png` and `upload-*.mp4` from runs whose
`upload.json` is already scheduled with a video ID. Keep the article, `narration.aac`,
subtitles, metadata, thumbnail and every record. Never prune an unscheduled or uncertain run,
and never delete browser state, credentials or another repository. See
[cleanup](docs/CLEANUP.md).
