"""Draw a placeholder parallax background "meadow" (no AI; Step 4 generates real ones).

    uv run scripts/make_placeholder_background.py   # → tests/fixtures/backgrounds/meadow/

Four flat-colour layers at 2880x1080 (the 1920x1080 frame plus room to pan): sky (barely moves),
far hills, the meadow the characters stand on, and foreground grass in front of them.
layers.json follows schemas/background.schema.json. Deterministic: same output every run.
"""

from __future__ import annotations

import json
import random
import sys

from PIL import Image, ImageDraw

from studio_core.config import REPO_ROOT
from studio_core.schema import validate

OUT = REPO_ROOT / "tests" / "fixtures" / "backgrounds" / "meadow"
W, H, SS = 2880, 1080, 2  # supersample for smooth edges


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def finish(img: Image.Image, name: str) -> None:
    img.resize((W, H), Image.Resampling.LANCZOS).save(OUT / "layers" / f"{name}.png", optimize=True)


def sky() -> None:
    img, d = canvas()
    for i in range(12):  # banded gradient
        y0, y1 = i * H * SS // 12, (i + 1) * H * SS // 12 + SS
        t = i / 11
        d.rectangle(
            [0, y0, W * SS, y1], fill=(int(150 + 60 * t), int(205 + 30 * t), int(245 + 8 * t), 255)
        )
    d.ellipse([400 * SS, 120 * SS, 560 * SS, 280 * SS], fill=(255, 222, 110, 255))
    rnd = random.Random(7)
    for _ in range(9):
        cx, cy = rnd.randint(0, W) * SS, rnd.randint(80, 360) * SS
        for dx, r in ((-70, 45), (0, 65), (70, 45)):
            d.ellipse(
                [cx + dx * SS - r * SS, cy - r * SS, cx + dx * SS + r * SS, cy + r * SS // 2],
                fill=(255, 255, 255, 235),
            )
    finish(img, "sky")


def hills() -> None:
    img, d = canvas()
    rnd = random.Random(3)
    x = -200
    while x < W + 200:
        r = rnd.randint(260, 420)
        d.ellipse(
            [(x - r) * SS, (720 - r * 0.6) * SS, (x + r) * SS, (720 + r * 0.6) * SS],
            fill=(120, 190, 120, 255),
        )
        x += rnd.randint(300, 480)
    d.rectangle([0, 720 * SS, W * SS, H * SS], fill=(120, 190, 120, 255))
    finish(img, "hills")


def meadow() -> None:
    img, d = canvas()
    d.rectangle([0, 820 * SS, W * SS, H * SS], fill=(108, 182, 92, 255))
    d.ellipse([-400 * SS, 760 * SS, (W + 400) * SS, 900 * SS], fill=(108, 182, 92, 255))
    d.polygon(
        [(1340 * SS, 830 * SS), (1540 * SS, 830 * SS), (1800 * SS, H * SS), (1080 * SS, H * SS)],
        fill=(222, 196, 140, 255),
    )
    rnd = random.Random(11)
    for _ in range(40):
        cx, cy = rnd.randint(0, W), rnd.randint(850, 1060)
        color = rnd.choice([(255, 255, 255, 255), (255, 220, 90, 255), (240, 140, 170, 255)])
        d.ellipse([(cx - 9) * SS, (cy - 9) * SS, (cx + 9) * SS, (cy + 9) * SS], fill=color)
    finish(img, "meadow")


def foreground() -> None:
    img, d = canvas()
    rnd = random.Random(5)
    for x in range(-40, W + 40, 34):
        h = rnd.randint(50, 130)
        lean = rnd.randint(-25, 25)
        d.polygon(
            [((x - 14) * SS, H * SS), ((x + lean) * SS, (H - h) * SS), ((x + 14) * SS, H * SS)],
            fill=(70, 150, 72, 255),
        )
    finish(img, "foreground")


LAYERS = [
    {"name": "sky", "file": "layers/sky.png", "parallax": 0.05},
    {"name": "hills", "file": "layers/hills.png", "parallax": 0.35},
    {"name": "meadow", "file": "layers/meadow.png", "parallax": 1.0},
    {"name": "foreground", "file": "layers/foreground.png", "parallax": 1.4, "in_front": True},
]


def main() -> int:
    (OUT / "layers").mkdir(parents=True, exist_ok=True)
    for draw in (sky, hills, meadow, foreground):
        draw()
    data = {
        "schema_version": 1,
        "id": "meadow",
        "name": "Sunny meadow",
        "size_px": [W, H],
        "backdrop": "#9fd2f2",
        "layers": LAYERS,
    }
    issues = validate("background", data)
    if issues:
        sys.exit("layers.json is invalid: " + "; ".join(map(str, issues)))
    (OUT / "layers.json").write_text(json.dumps(data, indent=2) + "\n")
    size = sum(p.stat().st_size for p in (OUT / "layers").glob("*.png")) / 1024
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {len(LAYERS)} layers, {size:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
