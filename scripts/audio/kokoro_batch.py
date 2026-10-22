"""Batch text-to-speech with Kokoro-82M, for audio_mcp's `speak` (task 3.2). Runs in envs/kokoro:

    envs/kokoro/.venv/bin/python scripts/audio/kokoro_batch.py < job.json

The job (JSON on stdin):

    {"out_dir": "/abs/dir", "device": "cpu",
     "voices": [{"id": "af_heart", "weight": 0.7}, {"id": "af_sky", "weight": 0.3}],
     "speed": 1.0,
     "lines": [{"key": "l001", "text": "Hi Bunny!"},
               {"key": "x", "text": "...", "voices": [{"id": "am_puck"}], "speed": 1.1}]}

Each line may override the job's voices and speed. Voices are blended by weight (a weighted
average of the voice packs). The model loads once per job. Writes <out_dir>/<key>.wav (24 kHz
mono, float) for each line and prints one JSON line:

    {"model": "kokoro-82m v1.0 (kokoro 0.9.4)", "sample_rate": 24000, "device": "cpu",
     "files": {"l001": "/abs/dir/l001.wav"}, "load_s": 1.4, "synth_s": 0.9}

No network after the first run: missing voices are fetched once (ensure_model), then
HF_HUB_OFFLINE is set. Postprocessing (trim, pitch, loudness) happens in studio_core.audio.
"""

from __future__ import annotations

import json
import sys
import time
from importlib.metadata import version
from pathlib import Path

from kokoro_say import MODEL_DIR, REPO_ID, SAMPLE_RATE, ensure_model


def main() -> int:
    job = json.load(sys.stdin)
    ensure_model(MODEL_DIR)

    import soundfile as sf
    import torch
    from kokoro import KModel, KPipeline

    device = job.get("device") or "cpu"
    t0 = time.perf_counter()
    model = KModel(
        repo_id=REPO_ID,
        config=str(MODEL_DIR / "config.json"),
        model=str(MODEL_DIR / "kokoro-v1_0.pth"),
    )
    model = model.to(device).eval()
    pipelines: dict[str, KPipeline] = {}
    packs: dict[str, torch.Tensor] = {}

    def blend(voices: list[dict]) -> tuple[str, torch.Tensor]:
        for v in voices:
            if v["id"] not in packs:
                path = MODEL_DIR / "voices" / f"{v['id']}.pt"
                if not path.is_file():
                    raise SystemExit(f"voice {v['id']!r} is not downloaded ({path})")
                packs[v["id"]] = torch.load(path, weights_only=True)
        total = sum(float(v.get("weight", 1)) for v in voices)
        mixed = sum(packs[v["id"]] * (float(v.get("weight", 1)) / total) for v in voices)
        lang = voices[0]["id"][0]  # a = US English, b = UK English
        return lang, mixed.float()

    def pipeline(lang: str) -> KPipeline:
        if lang not in pipelines:
            pipelines[lang] = KPipeline(lang_code=lang, repo_id=REPO_ID, model=model)
        return pipelines[lang]

    out_dir = Path(job["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    pipeline("a")("Warm up.", voice=blend([{"id": "af_heart"}])[1])  # loads G2P; not timed
    load_s = time.perf_counter() - t0

    files, synth_s = {}, 0.0
    for line in job["lines"]:
        lang, pack = blend(line.get("voices") or job["voices"])
        t1 = time.perf_counter()
        results = pipeline(lang)(line["text"], voice=pack, speed=line.get("speed", job["speed"]))
        audio = torch.cat([r.audio for r in results if r.audio is not None]).cpu()
        synth_s += time.perf_counter() - t1
        path = out_dir / f"{line['key']}.wav"
        sf.write(path, audio.numpy(), SAMPLE_RATE)
        files[line["key"]] = str(path)

    print(
        json.dumps(
            {
                "model": f"kokoro-82m v1.0 (kokoro {version('kokoro')})",
                "sample_rate": SAMPLE_RATE,
                "device": device,
                "files": files,
                "load_s": round(load_s, 2),
                "synth_s": round(synth_s, 2),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
