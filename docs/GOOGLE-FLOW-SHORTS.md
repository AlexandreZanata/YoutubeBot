# Google AI Video Generation for YouTube Shorts Only

AI-generated video clips (`tools/ytbot/shorts_video/`) default to vertical **YouTube Shorts**
(`1080x1920`, `9:16`, `30 fps`). Long-form videos (`run`, `batch`, `distribute`,
`documentary`) never use AI video clips and enforce `ShortsOnlyViolationError` if invoked with
`visual_mode="ai-video"`.

A separate opt-in **mini movie** path (`shorts-video movie`) renders an existing run directory
(`narration.aac` plus `clips/`) as a horizontal **16:9** film (`1920x1080`, `30 fps`). It is
explicit, budgeted by the same credit settings, and never converts a regular batch into AI
video.

## Google AI Pro vs. Gemini Video API Billing

YoutubeBot distinguishes clearly between consumer subscription tools and billed APIs:

1. **Google Flow (`google-flow`, default provider)**: Consumer creative studio at
   `https://labs.google/fx/tools/flow` (`flow.google`), included with the **Google AI Pro**
   subscription and its monthly Flow credit allowance for Veo models. Google Flow has **no
   public developer API**. YoutubeBot uses an isolated private Chrome/Xvfb profile
   (`.local/video-providers/google-flow/profile`, CDP port `9345`, display `:94`) plus a
   compliant **Assisted Workflow** (`flow-prompts.md` + automatic import from `clips/` or
   `.local/video-providers/google-flow/imports/`).
2. **Gemini Video API (`gemini-api`, disabled by default)**: Official Google developer REST
   API (`generativelanguage.googleapis.com/v1beta/models/{model}:predictLongRunning`).
   Google AI Pro Flow credits do **not** pay for Gemini API calls (any Google Cloud/Developer
   Program perks must be claimed separately in Google AI Studio). YoutubeBot never switches
   to `gemini-api` silently: it requires explicit `allow_paid_api=True`, a positive spending
   limit, and a private `0600` API key in `.local/video-providers/gemini-api/config.json`.
3. **Manual Video Import (`manual-import`)**: Imports and validates locally downloaded `.mp4`
   clips from the Short's `clips/` directory or `.local/video-providers/manual-import/` at
   zero credit cost.

## Setup and Authentication

Open the dedicated Google Flow browser profile in a visible window and sign in manually:

```bash
python3 -m tools.ytbot shorts-video login
python3 -m tools.ytbot shorts-video status --probe
python3 -m tools.ytbot shorts-video stop
```

The Flow profile never touches ChatGPT (`9300`) or YouTube Studio (`9301..9320`) profiles.
When a session expires or presents a verification challenge, YoutubeBot records
`.local/ytbot/needs-login.json`, marks the Short `needs_login`, and pauses that job without
attempting CAPTCHA or challenge bypasses.

## CLI Examples

Dry-run storyboard planning and credit estimation (spends 0 credits):

```bash
python3 -m tools.ytbot shorts --channel zaflas --count 1 --visual-mode ai-video --dry-run
python3 -m tools.ytbot faith-shorts --channel whispers-from-heaven --count 1 --visual-mode ai-video --dry-run
python3 -m tools.ytbot shorts-video estimate --channel zaflas --topic "Solo e raiz"
```

Legacy static Shorts remain the default when `--visual-mode` is omitted or set to `static`:

```bash
python3 -m tools.ytbot shorts --channel zaflas --count 1 --visual-mode static
```

Mini movie (long-form 16:9) from a prepared run directory:

```bash
python3 -m tools.ytbot shorts-video movie --channel infinite-random-worlds \
  --run-dir .local/ytbot/channels/infinite-random-worlds/runs/<slug> --width 1920 --height 1080
```

Opt-in AI video Shorts generation & assisted import:

```bash
python3 -m tools.ytbot shorts --channel zaflas --count 1 --visual-mode ai-video --video-provider google-flow
python3 -m tools.ytbot shorts-video import --channel zaflas --topic "Calagem e gessagem: qual é a diferença?" --source-dir ~/Downloads/flow-clips
```

## Credit Controls and Channel Rules

- Settings live in `.local/ytbot-media/shorts-video-settings.json` (`0600`) and ledger
  totals in `.local/ytbot-media/shorts-credits-ledger.json` (`0600`).
- `max_credits_per_short` and `max_credits_per_batch` stop scene generation once reached.
- `fallback_to_static` (default `true`) fills remaining or failed scenes with the channel's
  still-image background so a valid Short is never lost.
- Original narration audio (`narration.aac`) is never sped up or cut to fit video clips;
  burned-in subtitles preserve the channel's `1080x1920` ASS layout; generated clip audio is
  always stripped (`-an`).
- **Documentary channels (`sepia-atlas`, `bathylora`)**: AI clip generation is disabled by
  default (`ChannelPolicyError`) to preserve archival/scientific authenticity rules.

## Troubleshooting

- **Provider unavailable / Assisted workflow**: Check `flow-prompts.md` in the Short's run
  directory, generate the 9:16 clips in Google Flow, save them as `clips/scene_01.mp4`,
  `clips/scene_02.mp4`, ..., and run `python3 -m tools.ytbot shorts-video import`.
- **Expired Google Flow session**: Run `python3 -m tools.ytbot shorts-video login`, sign in
  manually, then resume the job.
- **No NVIDIA GPU**: FFmpeg automatically falls back from `h264_nvenc` to `libx264` CRF 18
  while preserving `1080x1920`, `30 fps`, narration sync, and burned-in subtitles.
