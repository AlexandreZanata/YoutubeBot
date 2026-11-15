"""Local optional OpenVINO Whisper worker; dependencies stay in its private virtualenv."""

import argparse
import json
import math
from importlib.metadata import version
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("CPU", "GPU"), required=True)
    parser.add_argument("--threads", type=int, choices=(2, 4, 8), default=2)
    args = parser.parse_args()
    import numpy as np
    import openvino as ov
    import openvino_genai as genai

    start = time.monotonic()
    raw = subprocess.check_output(["ffmpeg", "-nostdin", "-v", "error", "-i", str(args.audio),
                                   "-ar", "16000", "-ac", "1", "-f", "f32le", "-"], stderr=subprocess.DEVNULL)
    waveform = np.frombuffer(raw, dtype="<f4")
    options = {"PERFORMANCE_HINT": "LATENCY"}
    if args.device == "CPU":
        options.update(INFERENCE_NUM_THREADS=args.threads, NUM_STREAMS=1)
    print(f"[OpenVINO] loading local model on {args.device}", flush=True)
    pipeline = genai.WhisperPipeline(str(args.model), args.device, **options)
    ready = time.monotonic()
    print(f"[OpenVINO] pipeline ready after {ready-start:.2f}s", flush=True)
    result = pipeline.generate(waveform, language="<|en|>", task="transcribe",
                               return_timestamps=True, num_beams=1)
    inference_seconds = time.monotonic() - ready
    segments = []
    for index, chunk in enumerate(result.chunks or []):
        begin, end = float(chunk.start_ts), float(chunk.end_ts)
        if not math.isfinite(begin) or not math.isfinite(end) or begin < 0 or end <= begin:
            raise ValueError("OpenVINO returned incomplete subtitle timestamps.")
        if chunk.text.strip():
            segments.append({"id": index, "start": round(begin, 2), "end": round(end, 2),
                             "text": chunk.text.strip(), "avg_logprob": None})
    if not segments:
        raise ValueError("OpenVINO returned no subtitle segments.")
    args.output.write_text(json.dumps(segments, indent=2) + "\n")
    args.output.with_name("engine-info.json").write_text(json.dumps({
        "openvino": ov.__version__, "device": args.device, "threads": args.threads,
        "openvino_genai": version("openvino-genai"), "numpy": np.__version__,
        "model_revision": "b568445dd5dc8c695bde596f8acbb4694fd6ba64",
        "beam_size": 1, "language": "en", "options": options,
        "elapsed_in_worker_seconds": time.monotonic() - start,
        "load_seconds": ready - start, "inference_seconds": inference_seconds,
        "duration_seconds": len(waveform) / 16000, "segments": len(segments),
    }, indent=2) + "\n")
    print(f"[OpenVINO] completed {len(segments)} segments", flush=True)


if __name__ == "__main__":
    main()
