# ASR and render execution profiles

`standard` is the default and preserves the existing recognition, cache keys, language,
render path, resolution, frame rate, audio mix and encoder fallback. Execution profiles
are independent of the existing channel and browser profiles.

`fast` is explicit opt-in. **It is not qualified yet and currently resolves to standard.**
The quality latch in `tools/ytbot/flow_profiles.py` cannot be bypassed by environment or
hardware discovery. A reviewed change with complete measured evidence must promote it.
Selecting fast while qualification is pending records `quality_validation_pending` and
uses the existing standard implementation. This is not a claim of a speed improvement.

## Selecting and reverting

Add `--flow-profile fast` to a future owner-authorized `ytbot run`, service `submit`, or
service `generate` invocation. These normal commands retain their existing publication
permissions and behavior. No production command is needed to benchmark existing files.
`YTBOT_FLOW_PROFILE=fast` supplies the admission/CLI default; an explicit CLI flag wins.
Revert with `--flow-profile standard`, or unset the environment variable. Never resubmit
an existing operation with a different profile.

For a new, independently authorized generation-only operation, the exact syntax is:

```bash
.venv/bin/python -m tools.ytbot.service generate \
  --operation-id NEW_UUID --channel fallem-prince --count 1 \
  --approved-generation --flow-profile fast
```

Replace `NEW_UUID` with a fresh UUID. This example is documentation only: while qualification
is pending it still runs standard, and it must not be used to restart the paused operation.

The service captures the requested profile in its durable request; the actor does not
read a later caller environment. Omitted and explicit standard keep the old request
fingerprint. Older records default to standard. A changed fast request with the same
operation UUID is a collision. Schema version remains 1 with additive `flow_profile`
and `flow_selection` status fields. Run records and the existing journal include the
requested/effective profile, revision and fallback reasons.

Only ASR/render parameters may vary. Article, narration, voice, English/Portuguese channel
rules, prompts, models/providers for content creation, metadata, thumbnails, accounts,
browser lifecycle, channels and schedule slots retain their original code and settings.
The service remains at CPUQuota=200%, MemoryHigh=12G, MemoryMax=16G and RuntimeMaxSec=12h.
No GUI editor is integrated.

Candidate ASR caches include thread, batch and timestamp settings and never replace or
reuse the standard namespace. Failed/empty inference falls back to standard. Candidate
renders write a private temporary MP4 and replace the intended output only on success.
An encoder failure retries the existing standard renderer with the same audio and ASS;
subtitle recognition does not need to run again. Successful prior work is retained.

## Reproducing the private benchmark

Use the project virtualenv (av stays at **18.1.0**, faster-whisper **1.2.1**). Run from the
isolated branch checkout. Set `BENCH` to a new private directory outside the production
checkout, and `PRODUCTION` to the installed checkout. These are shell placeholders only.

```bash
.venv/bin/python -m tools.ytbot.flow_benchmark diagnose --root "$BENCH" --production-root "$PRODUCTION"
.venv/bin/python -m tools.ytbot.flow_benchmark snapshot --root "$BENCH" --production-root "$PRODUCTION"
```

Snapshotting copies only existing article/audio/ASS/metadata/thumbnail files, without hard
links. It excludes `video.mp4`, `upload.json`, `record.json`, locks, operations and provider
state. The unfinished production MP4 is never a valid reference. No browser or upload
module is invoked. Input and intermediate media, transcripts, command logs and hashes
remain private. Commit only reviewed, aggregated numbers.

Heavy work fails closed while any production unit or admitted actor is active. The
owner's explicitly authorized stopped-render exception requires `permit-pause` with the
exact existing operation, stopped PID and an absolute deadline within three hours. It
records process-start identity and partial-video size. It never signals production.
Every two seconds, experiments recheck the permit, stopped state, identity and size;
resumption, another active job or the deadline stops only the benchmark unit. An existing
permit cannot be overwritten to extend the pause.

```bash
# Only after the owner has independently stopped the renderer:
.venv/bin/python -m tools.ytbot.flow_benchmark permit-pause \
  --root "$BENCH" --production-root "$PRODUCTION" \
  --operation-id OWNER_AUTHORIZED_UUID --pid OWNER_STOPPED_PID \
  --deadline 'YYYY-MM-DDTHH:MM:SS-04:00'
```

Each heavy child gets its own `flowbench-UUID` systemd unit with CPUQuota 200%, 12G/16G
memory and a 12-hour maximum, additionally bounded by the pause deadline. The production
unit is never reconfigured. `--cpu-quota 400` uses a separate result namespace and never
changes the production quota. Full runs use the two complete copied audios. Screening
uses lossless float PCM extracted at 900 seconds for 300 or 600 seconds, identically for
all candidates. Startup, model loading and complete generator iteration are timed.

```bash
# Pinned private Intel runtime and standalone VMAF; no apt install or production pip:
.venv/bin/python scripts/prepare-flow-benchmark-tools.py --root "$BENCH" --production-root "$PRODUCTION"

# Example screening; repeat for the bounded candidate IDs listed by --help:
.venv/bin/python -m tools.ytbot.flow_benchmark asr --root "$BENCH" --production-root "$PRODUCTION" \
  --candidate standard --sample-seconds 300
.venv/bin/python -m tools.ytbot.flow_benchmark asr --root "$BENCH" --production-root "$PRODUCTION" \
  --candidate turbo-b4-t2 --sample-seconds 300
.venv/bin/python -m tools.ytbot.flow_benchmark render --root "$BENCH" --production-root "$PRODUCTION" \
  --candidate standard --sample-seconds 300
.venv/bin/python -m tools.ytbot.flow_benchmark render --root "$BENCH" --production-root "$PRODUCTION" \
  --candidate veryfast-crf18-t2 --sample-seconds 300
```

Omit `--sample-seconds` for the full final validation; `--repeat 2` measures variation
when the authorized window permits. `--input-index 1` can screen an obviously bad
candidate before spending time on input 2. `--asr-candidate NAME` chooses the fixed ASS
source for encoder comparisons; use the same source for every encoder. For the final
combined flow also render the finalist's own captions. Outputs never overwrite a
production path or an existing failed trial.

`compare-asr`, `compare-video`, `filters` and `report` use the same root/production flags.
Quality comparisons accept the same screening/quota selectors. `filters` isolates 30
seconds of background decode/loop, scale/crop, ASS, video encoding and audio processing;
these are isolated costs, not full-video timing claims. The report records medians,
range, CPU time/utilization, peak process RSS, effective fps, file size and RTF. Execution
logs record exact commands, versions, load, temperature and clock samples. Hardware
candidates log real initialization/encode failures; presence in `ffmpeg -encoders` alone
is not evidence of availability.

ASR word/character distance uses the existing article, normalized consistently. The
article is not an audited spoken transcript. Interpolated matched-token timing is a
screening estimate, not forced alignment. Missing/duplicated blocks, English correctness
and timestamp coherence still require checking the actual audio and captions. No metric
or timing report automatically qualifies fast.

Video comparisons measure full matched frames using FFmpeg SSIM/PSNR and either libvmaf
or the privately built Netflix VMAF CLI. Standalone VMAF decodes into named pipes, avoiding
raw-video files hundreds of GB in size. AAC packet hashes verify identical encoded audio.
Use actual frame counts and FFmpeg duplication/drop counters as well as visual review.
Do not compare a candidate's captions against different captions when calibrating its
encoder; separately assess the combined final flow.

## Acceptance and evidence

Required: ASR WER/CER no more than baseline +1.0 percentage point; median timestamp
error <=0.5s; complete speech coverage without lost/duplicated blocks; correct English.
Video must remain 1920x1080/30fps at the same frame-exact duration with unchanged audio,
VMAF >=95 (or measured delta <=1), SSIM >=0.985, PSNR >=40dB, no lost/duplicated frames,
and 10 blind A/B frames plus 10 subtitle windows reviewed per complete video. Files over
2x baseline need separate owner approval. Combined measured ASR+render speedup must be
>=1.5x. Missing evidence does not pass.

The current run's aggregated evidence and candidate dispositions are maintained in
`docs/performance/flow-profile-results.json` and its Markdown companion. Measurements
from 200% and 400% must remain separate. Screening projections must be labeled as such;
they cannot substitute for full two-video acceptance.

The official [faster-whisper 1.2.1 documentation](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/README.md)
supports batched inference. Its default timestamp behavior differs from sequential
inference; the candidate explicitly requests timestamp tokens. Benchmarks from another
CPU/model cannot predict this PC's speed.
[CTranslate2's CPU backend documentation](https://opennmt.net/CTranslate2/hardware_support.html)
explains that its prebuilt wheel already includes MKL/oneDNN; the oneDNN experiment uses
an isolated child environment rather than replacing production packages.
[whisper.cpp OpenVINO support](https://github.com/ggml-org/whisper.cpp#openvino-support)
accelerates the encoder and requires its own clean build/model conversion. It is not an
installed equivalent of the existing faster-whisper path. Report build/conversion cost
and actual accuracy before selecting it. Never install av19 into the working environment.

Kdenlive, Shotcut and OpenShot provide editing interfaces around media engines such as
FFmpeg. An editor does not accelerate Whisper recognition, and using the same x264 preset
inside a GUI does not remove its encoding cost. They add integration work without a
measured benefit for these two bottlenecks, so they are not integrated.

## Current candidate implementation

The gated candidate uses the pinned official OpenVINO large-v3-turbo W8 model on Intel
GPU. It remains local and uses a separate private virtualenv. Other languages retain
standard ASR. Missing dependencies, unavailable GPU or failed inference use the existing
standard recognition/cache. Candidate cache keys include the pinned OpenVINO package
versions and model revision.

After production is positively inactive, the owner can prepare the optional runtime:

```bash
.venv/bin/python scripts/prepare-flow-benchmark-tools.py \
  --root "$PRODUCTION/.local/flow-tools" --production-root "$PRODUCTION" \
  --runtime-tools --openvino
```

This is an explicit tool installation, not qualification or activation. The locked package
manifest pins OpenVINO core **2026.4.0** with GenAI **2026.4.0.0**: selecting core 2026.4.1
through a broad transitive dependency caused an incompatible SONAME in the real experiment.
Neither the production virtualenv nor system packages are updated. Intel VAAPI, Media SDK
and OpenCL libraries are extracted privately and passed only to the child process.

The render candidate caches static ASS at every actual display change. Centisecond event
boundaries are mapped to the first applicable 30-fps frame. The original ASS font, text,
placement, outline and shadow are rasterized by the same libass. A variable-rate lossless
ARGB track retains those frame-exact timestamps; alpha is unpremultiplied once per state
and composited before encoding. Animated/custom ASS effects fall back to standard.
This addresses the measured serial ASS cost. VAAPI hardware overlay was rejected on this
installed stack (unsupported processing profile); the tested cache uses software overlay
and hardware H.264 encoding. The complete fast gate remains pending.

QSV CQP uses video-scoped `-q:v`; ICQ uses `-global_quality:v`. An early unscoped quality
probe changed the AAC bitstream and used incorrect CQP units. Its files are retained as
invalid private diagnostics and excluded from valid speed/quality comparisons. The AAC
hash gate caught this before any production activation.

Short ASR cuts can also create artificial boundary failures: sequential recognition on
input 1 emitted text and timestamps after its 300-second end. Initial disagreement against
that transcript was not evidence of missing speech in batched/OpenVINO recognition.
The original full-audio standard cache confirmed the actual final words. Keep cut-boundary
artifacts distinct from real full-audio coverage and do not use that proxy as ground truth.

Conceptual GUI evaluation: [Kdenlive](https://docs.kdenlive.org/en/troubleshooting/faq.html),
[Shotcut](https://www.shotcut.org/stockmedia/Shotcut%20User%20Guide.pdf) and
[OpenShot](https://www.openshot.org/libopenshot/) use FFmpeg-related media libraries.
Changing the editing interface does not remove the measured Whisper or ASS work. This is
an architectural assessment, not a measured GUI speed comparison.

## Measured checkpoint (200% quota)

| Stage / condition | Reference | Candidate | Gain | Quality / qualification |
|---|---:|---:|---:|---|
| ASR, 300s input1, CPU2 versus OpenVINO GPU | 421.92s | 247.55s | 1.70x versus CPU2 | Cut-boundary caveat; not a full standard/fast comparison |
| ASR, 300s input2, CPU2 versus OpenVINO GPU | 351.38s | 236.66s | 1.48x versus CPU2 | Full-corpus quality pending |
| Render-only, 30s input1, same ASS | Standard x264 42.03s | Cached ASS + VAAPI QP22/one filter thread 13.12s including preparation | 3.20x | VMAF95.247; SSIM0.986084; PSNR43.774dB; identical AAC; full qualification pending |
| Render-only, 30s input1, final candidate | Standard x264 42.03s | Cached ASS + VAAPI QP20/two filter threads 12.41s including preparation | 3.39x | VMAF95.811; SSIM0.988978; PSNR44.835dB; identical AAC; size0.994x; numeric sample gate passed |
| Render-only, 30s input2, final candidate | Standard x264 43.42s | Cached ASS + VAAPI QP20/two filter threads 12.40s including preparation | 3.50x | VMAF95.819; SSIM0.988996; PSNR44.746dB; identical AAC; size0.999x; numeric sample gate passed |
| ASR, full input1 | Original standard 7840s | OpenVINO GPU 2522.52s | 3.11x | WER0.2594% ->0.1431%; CER0.1985% ->0.0584%; estimated median token timing0.159s; whole-profile qualification pending |
| Render, full input1, final candidate | Complete standard reference unavailable | 1583.87s including 122.32s caption preparation and 1461.55s encoding | Not measured against a complete reference | 129155 frames, no duplicates/drops; full video/audio metrics pending |
| ASR + render, full input1 | Standard ASR observed; standard render projected only | 4106.39s (68min26.39s), sum of measured stages | Full paired gain not established | Complete input2 and remaining full quality gates pending |
| Complete standard/fast videos, both inputs | Not complete | Not complete | Not established | Fast stays disabled |

The CPU2 screening reference is an explicitly threaded candidate, not the unmodified
standard ASR setting. The full standard render is unavailable: the stopped production
MP4 is unfinished and was excluded. QP20/two-filter-thread calibration is separate from
the QP22/one-thread proof; neither short test qualifies the full profile. Detailed tables and updates:
[measured evidence](performance/flow-profile-results.md),
[aggregated JSON](performance/flow-profile-results.json).

## Bounded-window outcome

The owner-authorized pause ends at 18:00 America/Cuiaba on 2026-11-14. Experiments stop
within that window. This is a partial qualification result: both existing inputs were
screened, and the complete first finalist ASR/render finished. The second full finalist
and complete standard render references remain pending. The proposed fast profile stays
disabled; this branch is a draft PR, not an installed production change.

Input1 candidate processing took 68min26.39s for ASR plus render. Applying its measured
stage rates to input2 suggests approximately 54 minutes, but that is a projection, not a
completed input2 measurement. The observed standard ASR plus unfinished-render projection
would imply roughly 3.09–3.21x for input1; this is also a projection and does not pass the
measured end-to-end gate. Content creation and optional tool installation are excluded.

Resume the remaining private experiments only in a new independently authorized idle
window. First complete input2, then obtain complete standard render references and full
video/audio metrics, review temporal subtitle windows and confirm combined gain on both
inputs. A reviewed qualification change is required before fast can actually activate.
The paused production operation remains under the owner's/OpenCode's control.

A separate 400% quota test on the same 30-second input1 render took 12.31s versus 12.41s
at 200%. The 0.10-second difference is not an established improvement: each condition has
one trial, and the complete MP4 bytes match. Keep 200% as the default. No full-video or ASR
400% measurement was completed, and the production service quota was never changed.

The complete input1 artifact received a static blind comparison of ten sampled frames
and ten caption-window centers. Text remained within the image and no obvious major
background damage was visible in those samples. Segmentation and blank/nonblank caption
differences require temporal/audio review; static centers do not satisfy ten temporal
subtitle windows. The whole-profile gate remains pending. Review images and mapping stay
private and are not committed.

The final input2 render screening covered 305 seconds (300s speech plus 5s outro):
standard CPU render took 391.60s; the cached-ASS/VAAPI candidate took 109.49s
including preparation, a measured render-only gain of 3.58x. All 9150
frames were emitted with no duplicates/drops. Objective quality was measured on its
30-second calibration, not all 305 seconds. Neither is a complete input2 validation.
