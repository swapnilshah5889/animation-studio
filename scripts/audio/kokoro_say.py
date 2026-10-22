"""Voice lines with Kokoro-82M. Runs in the isolated Kokoro env (envs/kokoro), not the workspace:

    envs/kokoro/.venv/bin/python scripts/audio/kokoro_say.py --out-dir OUT "Hello!" "Second line."

Weights live in ~/ai-studio/models/kokoro-82m (downloaded once on first run, then fully offline).
Prints one JSON line at the end: device, load time, audio seconds, synthesis seconds, files written.
Used by the Step 0 smoke test and `scripts/benchmark.py tts`; audio_mcp (Step 3) will build on it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Must be set before torch is imported: ops MPS lacks fall back to the CPU instead of erroring.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

REPO_ID = "hexgrad/Kokoro-82M"
MODEL_DIR = Path.home() / "ai-studio" / "models" / "kokoro-82m"
SAMPLE_RATE = 24_000
VOICES = [
    "af_heart",
    "af_bella",
    "am_michael",
    "am_puck",
    "bf_emma",
    "bm_george",
    # voice casting (Step 3, task 3.2)
    "af_nicole",
    "af_sky",
    "af_aoede",
    "af_kore",
    # Hindi (Step 3 task 3.2b, D-042)
    "hf_alpha",
    "hf_beta",
    "hm_omega",
    "hm_psi",
]


def ensure_model(model_dir: Path) -> None:
    """Download weights + a few voices once; afterwards force offline mode."""
    needed = [model_dir / "config.json", model_dir / "kokoro-v1_0.pth"]
    needed += [model_dir / "voices" / f"{v}.pt" for v in VOICES]
    if all(p.exists() for p in needed):
        os.environ["HF_HUB_OFFLINE"] = "1"
        return
    from huggingface_hub import snapshot_download

    snapshot_download(
        REPO_ID,
        local_dir=model_dir,
        allow_patterns=["config.json", "kokoro-v1_0.pth", "LICENSE*", "README.md"]
        + [f"voices/{v}.pt" for v in VOICES],
    )
    os.environ["HF_HUB_OFFLINE"] = "1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lines", nargs="+", help="text lines to voice, one WAV each")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--voice", default="af_heart")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--device", choices=["mps", "cpu"], default=None)
    parser.add_argument("--repeat", type=int, default=1, help="timed passes (benchmarking)")
    parser.add_argument("--model-dir", type=Path, default=MODEL_DIR)
    args = parser.parse_args()

    ensure_model(args.model_dir)

    import soundfile as sf
    import torch
    from kokoro import KModel, KPipeline

    device = args.device or ("mps" if torch.backends.mps.is_available() else "cpu")
    start = time.perf_counter()
    model = KModel(
        repo_id=REPO_ID,
        config=str(args.model_dir / "config.json"),
        model=str(args.model_dir / "kokoro-v1_0.pth"),
    )
    model = model.to(device).eval()
    lang = "b" if args.voice.startswith("b") else "a"  # voice prefix: a = US English, b = UK
    pipeline = KPipeline(lang_code=lang, repo_id=REPO_ID, model=model)
    voice = str(args.model_dir / "voices" / f"{args.voice}.pt")

    def synth(text: str) -> torch.Tensor:
        results = pipeline(text, voice=voice, speed=args.speed)
        chunks = [r.audio for r in results if r.audio is not None]
        return torch.cat(chunks).cpu()

    synth("Warm up.")  # first call compiles Metal kernels and loads G2P; not timed
    load_s = time.perf_counter() - start

    args.out_dir.mkdir(parents=True, exist_ok=True)
    files, audio_s, synth_s = [], 0.0, 0.0
    for _ in range(args.repeat):
        for i, line in enumerate(args.lines, 1):
            t0 = time.perf_counter()
            audio = synth(line)
            synth_s += time.perf_counter() - t0
            audio_s += len(audio) / SAMPLE_RATE
            path = args.out_dir / f"line_{i:02d}.wav"
            sf.write(path, audio.numpy(), SAMPLE_RATE)
            if str(path) not in files:
                files.append(str(path))

    print(
        json.dumps(
            {
                "device": device,
                "voice": args.voice,
                "load_s": round(load_s, 2),
                "audio_s": round(audio_s, 2),
                "synth_s": round(synth_s, 2),
                "rtf": round(synth_s / audio_s, 4) if audio_s else None,
                "sample_rate": SAMPLE_RATE,
                "files": files,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
