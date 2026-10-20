"""Compose instrumental music with ACE-Step 1.5 (turbo). Runs in the ACE-Step env:

    ~/ai-studio/ace-step/.venv/bin/python scripts/audio/acestep_compose.py --out-dir OUT

Weights live in ~/ai-studio/models/ace-step-1.5 (ACESTEP_CHECKPOINTS_DIR): turbo DiT, VAE and text
encoder. The optional 1.7B "thinking" language model is not installed (D-020), so thinking and
all chain-of-thought rewrites are off: the director writes the caption itself.
Prints one JSON line at the end: device, load and generation seconds, output file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ACE_ROOT = Path.home() / "ai-studio" / "ace-step"
MODEL_DIR = Path.home() / "ai-studio" / "models" / "ace-step-1.5"
DEFAULT_CAPTION = (
    "gentle, playful background music for a preschool cartoon, ukulele, glockenspiel, "
    "soft hand percussion, bright and happy, major key"
)

REPO_ID = "ACE-Step/Ace-Step1.5"
# Turbo DiT + VAE + text encoder. Not "acestep-5Hz-lm-1.7B" (3.8 GB, optional, D-020).
PARTS = ["acestep-v15-turbo", "vae", "Qwen3-Embedding-0.6B"]

# Must be set before acestep is imported.
os.environ.setdefault("ACESTEP_CHECKPOINTS_DIR", str(MODEL_DIR))
os.environ.setdefault("ACESTEP_PROJECT_ROOT", str(ACE_ROOT))
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def ensure_model() -> None:
    """Download the weights once; afterwards run fully offline."""
    if all((MODEL_DIR / part).is_dir() and any((MODEL_DIR / part).iterdir()) for part in PARTS):
        os.environ["HF_HUB_OFFLINE"] = "1"
        return
    from huggingface_hub import snapshot_download

    snapshot_download(
        REPO_ID, local_dir=MODEL_DIR, allow_patterns=[f"{p}/*" for p in PARTS] + ["*.md", "*.json"]
    )
    os.environ["HF_HUB_OFFLINE"] = "1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--caption", default=DEFAULT_CAPTION)
    parser.add_argument("--bpm", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--steps", type=int, default=8, help="turbo model: 8")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--format", default="wav", choices=["wav", "flac", "mp3"])
    parser.add_argument(
        "--no-mlx-dit",
        action="store_true",
        help="run the DiT in PyTorch/MPS only (the MLX path keeps a second copy of the weights)",
    )
    args = parser.parse_args()

    ensure_model()
    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music
    from acestep.llm_inference import LLMHandler

    start = time.perf_counter()
    dit = AceStepHandler()
    status, ok = dit.initialize_service(
        project_root=str(ACE_ROOT),
        config_path="acestep-v15-turbo",
        device=args.device,
        use_mlx_dit=not args.no_mlx_dit,
    )
    if not ok:
        print(json.dumps({"error": f"initialize_service failed: {status}"}))
        return 1
    load_s = time.perf_counter() - start
    llm = LLMHandler()  # never initialized: no LM installed (D-020)

    params = GenerationParams(
        caption=args.caption,
        lyrics="[Instrumental]",
        instrumental=True,
        bpm=args.bpm,
        duration=args.duration,
        inference_steps=args.steps,
        seed=args.seed,
        thinking=False,
        use_cot_metas=False,
        use_cot_caption=False,
        use_cot_language=False,
    )
    config = GenerationConfig(
        batch_size=1, use_random_seed=False, seeds=[args.seed], audio_format=args.format
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    result = generate_music(dit, llm, params, config, save_dir=str(args.out_dir))
    gen_s = time.perf_counter() - t0
    if not result.success:
        print(json.dumps({"error": result.error}))
        return 1

    files = [a["path"] for a in result.audios]
    print(
        json.dumps(
            {
                "device": str(getattr(dit, "device", args.device)),
                "load_s": round(load_s, 1),
                "gen_s": round(gen_s, 1),
                "duration_s": args.duration,
                "files": files,
                "notes": [
                    f"turbo DiT ({'PyTorch/MPS' if args.no_mlx_dit else 'MLX'}), {args.steps} "
                    f"steps, LM off, seed {args.seed}",
                    f"caption: {args.caption}",
                ],
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
