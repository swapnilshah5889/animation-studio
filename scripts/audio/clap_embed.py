"""CLAP embeddings for sound-effect search (task 3.5, D-036). Runs in envs/clap:

    envs/clap/.venv/bin/python scripts/audio/clap_embed.py < job.json

Two kinds of job (JSON on stdin):

    {"mode": "text", "texts": ["a soft cartoon pop", "birds singing at dawn"]}
    {"mode": "audio", "files": ["/abs/a.wav", ...], "out": "/abs/vectors.npy"}

Text vectors are printed in the JSON result. Audio vectors go to `out` (float32, one row per
file, in order), because a library has thousands. Every vector is L2-normalized, so cosine
similarity is a dot product. Audio must be 48 kHz mono WAV (the library is converted on import).

CLAP (laion/larger_clap_general, Apache-2.0) maps sounds and descriptions into one 512-d space:
"a dog barking" lands near recordings of dogs barking. Its feature extractor takes random crops
of clips longer than 10 s, so the RNG is re-seeded per clip: the same file always gets the same
vector. Weights download once to ~/ai-studio/models/clap/, then offline.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ID = "laion/larger_clap_general"
MODEL_DIR = Path.home() / "ai-studio" / "models" / "clap" / "larger_clap_general"
SAMPLE_RATE = 48_000
BATCH = 16


def ensure_model() -> None:
    import os

    if not (MODEL_DIR / "config.json").is_file():
        from huggingface_hub import snapshot_download

        snapshot_download(
            REPO_ID,
            local_dir=MODEL_DIR,
            allow_patterns=["*.json", "*.txt", "pytorch_model.bin", "*.md"],
        )
    os.environ["HF_HUB_OFFLINE"] = "1"


def main() -> int:
    job = json.load(sys.stdin)
    ensure_model()

    import numpy as np
    import soundfile as sf
    import torch
    from transformers import ClapModel, ClapProcessor

    t0 = time.perf_counter()
    model = ClapModel.from_pretrained(MODEL_DIR).eval()
    processor = ClapProcessor.from_pretrained(MODEL_DIR)
    load_s = time.perf_counter() - t0

    def normalized(x: torch.Tensor) -> np.ndarray:
        x = x if isinstance(x, torch.Tensor) else x.pooler_output
        return torch.nn.functional.normalize(x, dim=-1).numpy().astype("float32")

    t1 = time.perf_counter()
    result: dict = {"model": REPO_ID, "load_s": round(load_s, 2)}
    with torch.no_grad():
        if job["mode"] == "text":
            inputs = processor(text=job["texts"], return_tensors="pt", padding=True)
            vectors = normalized(model.get_text_features(**inputs))
            result["vectors"] = vectors.tolist()
        else:
            rows = []
            for i in range(0, len(job["files"]), BATCH):
                clips = []
                for path in job["files"][i : i + BATCH]:
                    audio, rate = sf.read(path, dtype="float32", always_2d=True)
                    if rate != SAMPLE_RATE:
                        raise SystemExit(f"{path}: {rate} Hz, expected {SAMPLE_RATE}")
                    clips.append(audio.mean(axis=1))
                np.random.seed(0)  # the extractor's random crops: same file, same vector
                inputs = processor(audio=clips, sampling_rate=SAMPLE_RATE, return_tensors="pt")
                rows.append(normalized(model.get_audio_features(**inputs)))
            vectors = np.concatenate(rows) if rows else np.zeros((0, 512), "float32")
            np.save(job["out"], vectors)
            result["out"] = job["out"]
            result["count"] = len(vectors)
        result["dim"] = int(vectors.shape[1]) if len(vectors) else 512
    result["embed_s"] = round(time.perf_counter() - t1, 2)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
