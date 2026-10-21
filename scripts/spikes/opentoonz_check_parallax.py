# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=10", "numpy>=1.26"]
# ///
"""Spike check: measure the parallax in frames rendered by opentoonz_scene.py.

    uv run scripts/spikes/opentoonz_check_parallax.py [frames_dir] [--a 30 --b 60]

For four horizontal bands (sky, hills, ground, foreground bushes) it finds the horizontal shift
between two frames that best aligns the band, then prints each band's shift relative to the
ground (Z = 0) band. Expected ratios from the scene's Z depths: sky 0.25, hills 0.5,
ground 1.0, bushes 1000/650 = 1.54. Pick frames inside the pan, before the final push-in,
and close enough together that the bushes move less than one pattern period (700 px).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

BANDS = {  # name: (y0, y1) in 1080p pixels, expected speed relative to the ground
    "sky (Z=-3000)": ((20, 120), 0.25),
    "hills (Z=-1000)": ((560, 660), 0.5),
    "ground (Z=0)": ((835, 870), 1.0),
    "bushes (Z=+350)": ((1000, 1075), 1000 / 650),
}


def best_shift(a: np.ndarray, b: np.ndarray, max_shift: int) -> int:
    """Shift s (pixels) such that b[x] ~ a[x + s]; content moving left gives s > 0.

    The camera only pans right, so only s in [-20, max_shift] is searched: the bush and flower
    patterns repeat, and a wider window can lock onto a shift one period away.
    """
    best, best_err = 0, float("inf")
    w = a.shape[1]
    for sft in range(-20, max_shift + 1):
        lo, hi = max(0, -sft), min(w, w - sft)
        if hi - lo < w // 3:
            continue
        err = np.abs(a[:, lo + sft : hi + sft] - b[:, lo:hi]).mean()
        if err < best_err:
            best, best_err = sft, err
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "frames_dir",
        nargs="?",
        type=Path,
        default=Path.home() / "ai-studio/scratch/opentoonz-spike/gen/outputs/frames",
    )
    ap.add_argument("--a", type=int, default=40)
    ap.add_argument("--b", type=int, default=50)
    ap.add_argument("--max-shift", type=int, default=400, help="pixels; keep below 700")
    args = ap.parse_args()

    def load(n: int) -> np.ndarray:
        img = Image.open(args.frames_dir / f"frame.{n:04d}.png").convert("L")
        return np.asarray(img, dtype=np.float32)

    fa, fb = load(args.a), load(args.b)
    shifts = {
        name: best_shift(fa[y0:y1], fb[y0:y1], args.max_shift)
        for name, ((y0, y1), _) in BANDS.items()
    }
    ground = shifts["ground (Z=0)"] or 1
    print(f"frames {args.a} -> {args.b}: horizontal shift per band")
    for name, (_, expected) in BANDS.items():
        print(
            f"  {name:18s} {shifts[name]:5d} px   ratio {shifts[name] / ground:5.2f}"
            f"   expected {expected:4.2f}"
        )


if __name__ == "__main__":
    main()
