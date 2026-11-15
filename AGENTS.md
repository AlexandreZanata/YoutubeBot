# YoutubeBot agent guide

This is YoutubeBot: a Firefox/Chrome audio-capture extension, Python/PySide6 video
studio, and resumable Playwright YouTube production/scheduled-upload pipeline.
Read [the component map](docs/ARCHITECTURE.md), then only the relevant module and tests.
English in code, comments, documentation and commits; user-facing UI may use Portuguese.

## Preserve existing behavior

- Extension capture, filename templates and download behavior stay unchanged.
- Keep the existing generation modes, narration, voices, subtitles, backgrounds and rendering.
- Fallem Prince and Whispers From Heaven use English narration, subtitles and metadata.
  Only Zaflas uses Brazilian Portuguese. Operator/browser interface language never changes content language.
- `tools/ytbot` keeps channel prompts, deduplication, resumable stage records and sequential
  upload/scheduling. Existing profiles are `fallem-prince`, `whispers-from-heaven`, `zaflas`.
  Whispers uses 2,400 to 2,800 words (15 to 17 minutes), Sacred Brown Engraving thumbnails,
  brown stippling background and the metadata/tag patterns in
  [its channel profile](docs/channels/whispers-from-heaven.md). Zaflas uses Brazilian
  Portuguese, 6,000 to 7,200 words (25 to 35 minutes), photorealistic agribusiness
  thumbnails, the fixed site/social description prefix and
  [its channel profile](docs/channels/zaflas.md). Zaflas publishes one video per day at
  12:00 America/Cuiaba. Its dedicated profile is upload-only; generation stays in legacy.
- Require an explicit channel. Verify its YouTube channel ID before mutating Studio.
- Schedule only: up to 4 videos/day for fallem prince at 00:00, 06:00, 12:00 and
  18:00 in America/Cuiaba, at least 60 minutes ahead, not made for kids, custom
  thumbnail and Subscribe + Best for viewer end screen.
- The 4/day expansion starts on 2026-11-15. Days that already have 00:00/12:00 keep
  them; the new videos fill the exact middle slots 06:00/18:00 (2/day), completing
  4/day. Use `--start-date YYYY-MM-DD` when a batch must start on a specific day.
- Preserve channel-specific title/description/tags rules and media quality.
- Never blindly retry an uncertain upload or start the same service operation twice.

## Boundaries

Accounts, browser profiles, OAuth tokens, generated media, model caches and run history
are private `.local/` state. Never log tokens/cookies or put them in Git. Google sign-in
uses the owner's visible browser and consent; do not bypass challenges or copy another
profile while in use. Browser automation remains the upload path; optional OAuth only
helps discover and verify account/channel identity. Never silently switch channels.

The service CLI is typed and bounded. Never expose a general shell, arbitrary subprocess
arguments or account secrets to ZaturoBot. Real generation/upload/Google consent tests
are opt-in; CI uses fixtures. Read [accounts](docs/ACCOUNTS.md), [service](docs/SERVICE.md)
and [migration](docs/MIGRATION.md) for those operations.

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
stop. Never silently use a more expensive coordinator, API-key fallback,
or ChatGPT image fallback after a Codex failure. Preserve media-attempt fences and existing
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

## Community

After the asset stage of every batch, check the selected channel's Community tab. The rule
is one post per calendar day after 00:00 in the channel timezone. If today already has a
post, do nothing; otherwise publish one question post with the first topic, a short text and
a square crop of that video's thumbnail. Never retry an unconfirmed publish blindly. See
[community](docs/COMMUNITY.md).

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
space guards; fail early with the available and required gigabytes. Upload files are hard
links to `video.mp4`. Large runs may live on `/data` through the `.local/ytbot/runs` symlink;
never delete recorded media to free space.
