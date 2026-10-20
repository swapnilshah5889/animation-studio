"""Draw simple flat placeholder puppet parts for Step 1 (no AI): a bunny cut into parts.

    uv run scripts/make_placeholder_parts.py            # writes tests/fixtures/handmade/parts/

Each part is a transparent PNG drawn 4x larger and downsampled (smooth edges). parts.json records
every part's size and **pivot** (the joint it rotates around, in pixels from the top-left), the
same information a real rig needs (Step 2's rig.json). Safe to re-run: same output every time.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable

from PIL import Image, ImageDraw

from studio_core.config import REPO_ROOT

OUT = REPO_ROOT / "tests" / "fixtures" / "handmade" / "parts"
SS = 4  # supersampling factor

FUR = (246, 240, 232, 255)
FUR_SHADE = (226, 214, 202, 255)
EAR_PINK = (244, 176, 180, 255)
JACKET = (64, 170, 160, 255)
PANTS = (214, 132, 64, 255)
LINE = (70, 52, 46, 255)
MOUTH = (120, 40, 50, 255)
WIDTH = 3 * SS  # outline width at supersampled scale

Draw = Callable[[ImageDraw.ImageDraw, int, int], None]


def part(size: tuple[int, int], draw: Draw) -> Image.Image:
    w, h = size
    big = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    draw(ImageDraw.Draw(big), w * SS, h * SS)
    return big.resize((w, h), Image.Resampling.LANCZOS)


def torso(d: ImageDraw.ImageDraw, w: int, h: int) -> None:
    box = [WIDTH, WIDTH, w - WIDTH, h - WIDTH]
    d.rounded_rectangle(box, radius=w // 3, fill=PANTS)  # trousers: the whole shape first
    jacket = [WIDTH, WIDTH, w - WIDTH, int(h * 0.72)]
    d.rounded_rectangle(jacket, radius=w // 3, fill=JACKET, corners=(True, True, False, False))
    d.rounded_rectangle(box, radius=w // 3, outline=LINE, width=WIDTH)


def head(d: ImageDraw.ImageDraw, w: int, h: int) -> None:
    ear_w, ear_h = int(w * 0.24), int(h * 0.5)
    for cx in (int(w * 0.32), int(w * 0.68)):
        d.ellipse(
            [cx - ear_w // 2, WIDTH, cx + ear_w // 2, ear_h], fill=FUR, outline=LINE, width=WIDTH
        )
        d.ellipse([cx - ear_w // 4, ear_h // 6, cx + ear_w // 4, ear_h - ear_h // 6], fill=EAR_PINK)
    d.ellipse([WIDTH, int(h * 0.38), w - WIDTH, h - WIDTH], fill=FUR, outline=LINE, width=WIDTH)
    # Eyes are part of the head art for now; Step 2 replaces them with procedural vector eyes.
    for cx in (int(w * 0.36), int(w * 0.64)):
        d.ellipse([cx - w // 20, int(h * 0.6), cx + w // 20, int(h * 0.68)], fill=LINE)


def limb(d: ImageDraw.ImageDraw, w: int, h: int, color: tuple[int, ...], hand: bool) -> None:
    d.rounded_rectangle(
        [WIDTH, WIDTH, w - WIDTH, h - WIDTH], radius=w // 2, fill=color, outline=LINE, width=WIDTH
    )
    if hand:
        d.ellipse([WIDTH, h - w - WIDTH, w - WIDTH, h - WIDTH], fill=FUR, outline=LINE, width=WIDTH)


def mouth(shape: str) -> Draw:
    """Three of Rhubarb's mouth shapes: A (closed: M/B/P), E (rounded: AO/ER), X (rest)."""

    def draw(d: ImageDraw.ImageDraw, w: int, h: int) -> None:
        if shape == "A":
            d.line([w * 0.2, h * 0.5, w * 0.8, h * 0.5], fill=LINE, width=WIDTH * 2)
        elif shape == "E":
            d.ellipse(
                [w * 0.32, h * 0.15, w * 0.68, h * 0.85], fill=MOUTH, outline=LINE, width=WIDTH
            )
        else:  # X: relaxed, slight smile
            d.arc([w * 0.2, -h * 0.4, w * 0.8, h * 0.7], 30, 150, fill=LINE, width=WIDTH * 2)

    return draw


def background(d: ImageDraw.ImageDraw, w: int, h: int) -> None:
    """Wider than the 1920 frame (2880) so it can pan; flat sky, sun and hills."""
    d.rectangle([0, 0, w, h], fill=(150, 205, 245, 255))
    d.ellipse([w * 0.1, h * 0.08, w * 0.1 + h * 0.18, h * 0.26], fill=(255, 222, 110, 255))
    hills = [(0.15, 0.95, 0.55), (0.45, 1.05, 0.6), (0.8, 0.95, 0.5), (1.05, 1.0, 0.55)]
    for cx, cy, r in hills:
        d.ellipse(
            [w * cx - h * r, h * cy - h * r * 0.7, w * cx + h * r, h * cy + h * r * 0.7],
            fill=(110, 185, 95, 255),
        )
    d.rectangle([0, h * 0.86, w, h], fill=(95, 165, 80, 255))


# name: (size, drawing, pivot in pixels or None)
PARTS: dict[str, tuple[tuple[int, int], Draw, tuple[int, int] | None]] = {
    "background": ((2880, 1080), background, None),
    "torso": ((200, 280), torso, (100, 260)),  # pivot: hips (the root of the rig)
    "head": ((220, 300), head, (110, 285)),  # pivot: neck
    "upper_arm": ((56, 150), lambda d, w, h: limb(d, w, h, JACKET, False), (28, 20)),  # shoulder
    "forearm": ((52, 150), lambda d, w, h: limb(d, w, h, FUR, True), (26, 18)),  # elbow
    "mouth_A": ((90, 50), mouth("A"), (45, 25)),
    "mouth_E": ((90, 50), mouth("E"), (45, 25)),
    "mouth_X": ((90, 50), mouth("X"), (45, 25)),
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {}
    for name, (size, draw, pivot) in PARTS.items():
        part(size, draw).save(OUT / f"{name}.png", optimize=True)
        meta[name] = {
            "file": f"{name}.png",
            "size": list(size),
            "pivot": list(pivot) if pivot else None,
        }
    (OUT / "parts.json").write_text(json.dumps(meta, indent=2) + "\n")
    total = sum(p.stat().st_size for p in OUT.glob("*.png"))
    print(f"wrote {len(PARTS)} parts to {OUT.relative_to(REPO_ROOT)} ({total / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
