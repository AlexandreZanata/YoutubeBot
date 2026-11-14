# Measured flow-profile evidence

Status: in progress. Default standard; fast remains qualification-gated. All numbers below are real measurements; incomplete references and projections are labeled.

| Scope | Quota | Stage / candidate | Input | Wall s | RTF / fps | Peak process RSS GiB | Size MiB | Quality / decision |
|---|---:|---|---:|---:|---:|---:|---:|---|
| . | 200% | asr / openvino-gpu | 1 | 2522.52 | RTF0.587 | 2.386 | 0.00 | WER0.2594%->0.1431%; CER0.1985%->0.0584%; estimated timing0.1585s |
| screening/quota-200-offset-900-seconds-300 | 200% | asr / openvino-gpu | 1 | 247.55 | RTF0.825 | 1.135 | 0.00 | Timing only; full qualification pending |
| screening/quota-200-offset-900-seconds-300 | 200% | asr / openvino-gpu | 2 | 236.66 | RTF0.789 | 1.162 | 0.00 | Timing only; full qualification pending |
| screening/quota-200-offset-900-seconds-300 | 200% | asr / turbo-b4-t2 | 1 | 355.77 | RTF1.186 | 2.724 | 0.00 | Timing only; full qualification pending |
| screening/quota-200-offset-900-seconds-300 | 200% | asr / turbo-b4-t2 | 2 | 330.57 | RTF1.102 | 2.724 | 0.00 | Timing only; full qualification pending |
| screening/quota-200-offset-900-seconds-300 | 200% | asr / turbo-t2 | 1 | 421.92 | RTF1.406 | 2.357 | 0.00 | Timing only; full qualification pending |
| screening/quota-200-offset-900-seconds-300 | 200% | asr / turbo-t2 | 2 | 351.38 | RTF1.171 | 2.177 | 0.00 | Timing only; full qualification pending |
| screening/quota-200-offset-900-seconds-300 | 200% | filters / ass | 1 | 34.14 | 26.36fps | 0.093 | 0.00 | Timing only; full qualification pending |
| screening/quota-200-offset-900-seconds-300 | 200% | filters / audio-volume-aac | 1 | 1.18 | 762.71fps | 0.051 | 0.00 | Timing only; full qualification pending |
| screening/quota-200-offset-900-seconds-300 | 200% | filters / decode-loop | 1 | 2.96 | 304.05fps | 0.068 | 0.00 | Timing only; full qualification pending |
| screening/quota-200-offset-900-seconds-300 | 200% | filters / scale-crop | 1 | 4.94 | 182.19fps | 0.079 | 0.00 | Timing only; full qualification pending |
| screening/quota-200-offset-900-seconds-300 | 200% | filters / x264-video-only | 1 | 38.22 | 23.55fps | 0.287 | 0.00 | Timing only; full qualification pending |
| screening/quota-200-offset-900-seconds-300 | 200% | render / standard | 1 | 407.57 | 22.45fps | 0.622 | 43.21 | Timing only; full qualification pending |
| screening/quota-200-offset-900-seconds-300 | 200% | render / standard | 2 | 391.60 | 23.37fps | 0.623 | 43.15 | Timing only; full qualification pending |
| screening/quota-200-offset-900-seconds-300/calibration/seconds-30 | 200% | render / cache-proof-vaapi22-ft1 | 1 | 13.12 | 68.60fps | 0.146 | 3.14 | VMAF95.247282; SSIM0.986084; PSNR43.773819; AAC equal=True |
| screening/quota-200-offset-900-seconds-300/calibration/seconds-30 | 200% | render / standard | 1 | 42.03 | 21.41fps | 0.560 | 4.19 | Timing only; full qualification pending |
| screening/quota-200-offset-900-seconds-300/calibration/seconds-30 | 200% | render / standard | 2 | 43.42 | 20.73fps | 0.560 | 4.13 | Timing only; full qualification pending |
| screening/quota-200-offset-900-seconds-300/calibration/seconds-30 | 200% | render / vaapi-qp20-cached-ass | 1 | 12.41 | 72.52fps | 0.160 | 4.17 | VMAF95.810857; SSIM0.988978; PSNR44.83453; AAC equal=True |

One trial per measured sample; run-to-run variation has not been established. Different inputs are not repeat trials.

The initial cached-ASS proof uses VAAPI QP22 / one filter thread. The final QP20 / two-thread candidate also passed the30-second numeric calibration on input1; full acceptance remains pending.

The existing complete standard ASR on input1 took7840s(RTF1.823),1164segments. Full standard render is unavailable: the owner-paused partial MP4 was excluded. The production render estimate4840–5340s is a projection, not a completed measurement.

Known rejects: unavailable NVIDIA/NVENC; VAAPI hardware-overlay processing profile unsupported. Invalid QSV flags and incompatible OpenVINO4.1 ABI are setup/command failures, not fair encoder or model quality results. Corrected QSV CQP and all unmeasured ASR candidates remain unqualified.

No browser, upload, scheduling or production state was changed. Benchmark units use200% by default; any400% test is separate. Do not promote fast until both complete videos and all objective/blind-review gates pass.
