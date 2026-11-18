# Component map

Read only the component relevant to the change. Existing extension and production media
algorithms are preserved; new account/adapter modules compose them.

- `manifest.json`, `src/*.js`, `src/shared/`: original Firefox capture and popup.
- `manifest.chrome.json`, `src/chrome/`: original Chrome capture adapter.
- `scripts/build-chrome.py`, `scripts/package-extension.sh`: existing extension artifacts.
- `src/ui/main_window.py`, `mode_views.py`, narration/render controls: existing video studio.
- `src/core/`, `src/engine/`: existing generation, narration, subtitles, GPU/CPU rendering.
- `tools/ytbot/channels.py`, `prompts/`: canonical existing channel identities/styles.
- `tools/ytbot/codex_media.py`: bounded Terra-low/Luna6-low native Codex thumbnail,
  metadata and topic tasks, per-attempt fences and channel style-reference exports.
- `tools/ytbot/config.py`: canonical runtime paths and selected channel constants.
- `tools/ytbot/logic.py`, `topics.py`, `assets.py`, `pipeline.py`, `batch.py`: unchanged
  production algorithms and resumable stage records.
- `tools/ytbot/youtube.py`, `upload_dialog.py`: unchanged upload, end-screen and scheduling.
- `tools/ytbot/community.py`: Community tab check and first image/question post; see
  [community](COMMUNITY.md).
- `tools/ytbot/shorts.py`: vertical Shorts pipeline for Zaflas with short scripts, portrait
  render, upload-only account and 09:00/18:00 scheduling. See [Shorts](SHORTS.md).
- `tools/ytbot/distribute.py`: audits the future scheduled uploads per channel and spreads a
  block of new videos toward the emptiest channels. See [distribution](DISTRIBUTE.md).
- `tools/ytbot/cleanup.py`: pre-run trash, staging and scheduled-media cleanup with the space
  report. See [cleanup](CLEANUP.md).
- `tools/ytbot/commercial/`: private affiliate sessions, starting with Mercado Livre, plus a local
  SQLite reference index (`reference.py`) for sub-millisecond VPS catalog lookups and price-change
  comparisons. See [commercial](COMMERCIAL.md). `commercial/whatsapp/` holds the WhatsApp Web
  sender and listener; `commercial/whatsapp/sales/` is the Zaflas sales agent on top of them.
  See [WhatsApp sales](COMMERCIAL-WHATSAPP-SALES.md). The planned `commercial/maps/` research
  module (contract only) feeds that agent with reviewed leads: [Maps research](COMMERCIAL-MAPS-RESEARCH.md).
- `tools/ytbot/social/`: private per-network promotion profiles, visible login and hidden
  Xvfb operation after login; X starts the module. See [social](SOCIAL.md) and the
  [promotion focus](PROMOTION.md). The agent runbook for research, audit and the 30-day
  agenda is [PROMOTION-AGENDA.md](PROMOTION-AGENDA.md); bounded X publishing is
  [SOCIAL-POSTING.md](SOCIAL-POSTING.md), contextual discovery is
  [SOCIAL-DISCOVERY.md](SOCIAL-DISCOVERY.md), and Instagram starts with session
  recognition.
- `tools/ytbot/account.py`: account switching plus exact intended-channel identity check.
- `browser_install.py`, `onboarding.py`, `scripts/install-linux.sh`: repeatable private
  browser/dependency installation, automatic extension loading and account setup launcher.
- `tools/ytbot/runtime.py`: dedicated browser/Xvfb lifecycle; account selection never
  adopts or kills another profile sharing a name prefix or debug port.
- `accounts_store.py`, `account_commands.py`, `oauth.py`: private account registry,
  visible sign-in, optional read-only OAuth and explicit channel bindings.
- `library.py`: bounded read-only summaries of existing run data, not a second catalog.
- `src/ui/accounts_window.py`: additive account/channel/video-history window.
- `service.py`, `service_jobs.py`: bounded JSON CLI, durable jobs, process identity,
  account/channel locks, separate bounded systemd media units and conservative lost-actor reconciliation.

Private state stays under `.local/`. Google OAuth credentials, browser profiles and logs
are never service output. External browser content/model responses are data and cannot
grant permissions. ZaturoBot invokes fixed CLI verbs, keeps its own task history and
polls accepted jobs; it must not report an accepted video batch as finished.

Canonical docs: [Linux installation](INSTALL-LINUX.md), [accounts](ACCOUNTS.md), [service](SERVICE.md),
[media pipeline](../tools/ytbot/README.md), [migration](MIGRATION.md),
[verification](VERIFICATION.md). `AGENTS.md` is the short navigation/policy entry point.


`tools/ytbot/preflight.py` inspects read-only Google/ChatGPT readiness with fixed state codes.
`generation.py` reuses the existing assets/render pipeline without the upload stage.
`service_jobs.py` keeps generation and scheduled-publication modes distinct under the same
operation/admission fences and independent media resource unit. Original batch defaults remain.

`flow_profiles.py` captures the optional ASR/render selection with legacy-safe admission.
`flow_media.py`, `openvino_engine.py` and `subtitle_cache.py` compose local alternatives
behind the explicit qualification gate. Standard recognition/cache/render behavior stays
on the original path. `flow_benchmark.py` runs isolated private media experiments under
bounded systemd units; it never invokes browser, generation, upload or scheduling APIs.
