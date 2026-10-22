"""Batch text-to-speech with Indic Parler-TTS (AI4Bharat), for `speak` (task 3.2b, D-042).
Runs in envs/parler:

    envs/parler/.venv/bin/python scripts/audio/parler_batch.py < job.json

The job (JSON on stdin):

    {"out_dir": "/abs/dir", "device": "mps",
     "lines": [{"key": "l001", "text": "Hi Bunny!", "seed": 1234,
                "description": "Mary's voice is high-pitched and slightly expressive, ..."}]}

The description (written by studio_core.audio.voices, never by the LLM) names the speaker and
asks for pitch, pace and expressiveness. Parler samples randomly, so each line carries a seed.
Writes <out_dir>/<key>.wav at the model's sample rate (44.1 kHz) and prints one JSON line:

    {"model": "indic-parler-tts (parler-tts d108732)", "sample_rate": 44100, "device": "mps",
     "files": {"l001": "/abs/dir/l001.wav"}, "load_s": 9.1, "synth_s": 4.2, "audio_s": 3.0}

The weights are gated: the first run downloads them, which needs the owner to have accepted the
model's terms on Hugging Face and run `hf auth login`. After that, everything is offline.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Before torch is imported: ops MPS lacks fall back to the CPU instead of erroring.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

REPO_ID = "ai4bharat/indic-parler-tts"
MODEL_DIR = Path.home() / "ai-studio" / "models" / "indic-parler-tts"
TOKENIZER_DIR = MODEL_DIR / "description-tokenizer"
MODEL_NAME = "indic-parler-tts (parler-tts d108732)"
TOKENIZER_FILES = ["*.json", "*.model", "*.txt"]


def ensure_model() -> None:
    """Download the weights (gated) and the description tokenizer once; then stay offline."""
    from huggingface_hub import snapshot_download

    if not (MODEL_DIR / "model.safetensors").is_file():
        snapshot_download(REPO_ID, local_dir=MODEL_DIR)
    if not (TOKENIZER_DIR / "tokenizer_config.json").is_file():
        config = json.loads((MODEL_DIR / "config.json").read_text())
        name = config["text_encoder"]["_name_or_path"]  # the description encoder (flan-t5)
        snapshot_download(name, local_dir=TOKENIZER_DIR, allow_patterns=TOKENIZER_FILES)
    os.environ["HF_HUB_OFFLINE"] = "1"


def main() -> int:
    job = json.load(sys.stdin)
    ensure_model()

    import soundfile as sf
    import torch
    from parler_tts import ParlerTTSForConditionalGeneration
    from transformers import AutoTokenizer

    device = job.get("device") or "mps"
    if device == "mps" and not torch.backends.mps.is_available():
        device = "cpu"
    t0 = time.perf_counter()
    model = ParlerTTSForConditionalGeneration.from_pretrained(MODEL_DIR).to(device).eval()
    prompt_tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
    description_tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_DIR)
    rate = model.config.sampling_rate
    load_s = time.perf_counter() - t0

    out_dir = Path(job["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    files, synth_s, audio_s = {}, 0.0, 0.0
    for line in job["lines"]:
        description = description_tokenizer(line["description"], return_tensors="pt").to(device)
        prompt = prompt_tokenizer(line["text"], return_tensors="pt").to(device)
        torch.manual_seed(int(line["seed"]))
        t1 = time.perf_counter()
        with torch.no_grad():
            audio = model.generate(
                input_ids=description.input_ids,
                attention_mask=description.attention_mask,
                prompt_input_ids=prompt.input_ids,
                prompt_attention_mask=prompt.attention_mask,
            )
        synth_s += time.perf_counter() - t1
        samples = audio.cpu().float().numpy().squeeze()
        audio_s += len(samples) / rate
        path = out_dir / f"{line['key']}.wav"
        sf.write(path, samples, rate)
        files[line["key"]] = str(path)

    print(
        json.dumps(
            {
                "model": MODEL_NAME,
                "sample_rate": rate,
                "device": device,
                "files": files,
                "load_s": round(load_s, 2),
                "synth_s": round(synth_s, 2),
                "audio_s": round(audio_s, 2),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
