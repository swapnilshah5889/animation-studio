"""Draw the Step 2 placeholder character "Pip" and its rig.json (no AI; Step 4 replaces the art).

    uv run scripts/make_placeholder_character.py     # → tests/fixtures/characters/pip/

Compared with the Step 1 parts: the head has **no painted face** (the face is procedural vector
art, D-007, task 2.4), and the puppet has both arms and two-segment legs, so every motion in the
library has the bones it needs. rig.json follows schemas/rig.schema.json and is validated here.
Safe to re-run: the output is identical every time.
"""

from __future__ import annotations

import json
import sys

from make_placeholder_parts import FUR, LINE, PANTS, WIDTH, limb, part, torso
from PIL import ImageDraw

from studio_core.config import REPO_ROOT
from studio_core.schema import validate

OUT = REPO_ROOT / "tests" / "fixtures" / "characters" / "pip"
EAR_PINK = (244, 176, 180, 255)
SHOE = (90, 70, 64, 255)


def head_blank(d: ImageDraw.ImageDraw, w: int, h: int) -> None:
    """Ears and a face disc; eyes, brows and mouth are drawn by studio_core.face."""
    ear_w, ear_h = int(w * 0.24), int(h * 0.5)
    for cx in (int(w * 0.32), int(w * 0.68)):
        d.ellipse(
            [cx - ear_w // 2, WIDTH, cx + ear_w // 2, ear_h], fill=FUR, outline=LINE, width=WIDTH
        )
        d.ellipse([cx - ear_w // 4, ear_h // 6, cx + ear_w // 4, ear_h - ear_h // 6], fill=EAR_PINK)
    d.ellipse([WIDTH, int(h * 0.38), w - WIDTH, h - WIDTH], fill=FUR, outline=LINE, width=WIDTH)


def thigh(d: ImageDraw.ImageDraw, w: int, h: int) -> None:
    limb(d, w, h, PANTS, False)


def shin(d: ImageDraw.ImageDraw, w: int, h: int) -> None:
    d.rounded_rectangle(
        [WIDTH, WIDTH, w - WIDTH, h - WIDTH - h // 6],
        radius=w // 2,
        fill=FUR,
        outline=LINE,
        width=WIDTH,
    )
    d.ellipse([0, h - h // 4, w, h - WIDTH], fill=SHOE, outline=LINE, width=WIDTH)  # shoe


IMAGES = {  # file: (size, drawing)
    "torso": ((200, 280), torso),
    "head": ((220, 300), head_blank),
    "upper_arm": ((56, 150), lambda d, w, h: limb(d, w, h, (64, 170, 160, 255), False)),
    "forearm": ((52, 150), lambda d, w, h: limb(d, w, h, FUR, True)),
    "thigh": ((64, 130), thigh),
    "shin": ((64, 150), shin),
}

# Bones: parent, joint (part + pixel), rest direction, length, side, limits. The character's left
# is on the viewer's right in the front view.
BONES = {
    "torso": (None, None, 90, 240, "center", (-15, 15)),
    "head": ("torso", ("torso", [100, 18]), 90, 280, "center", (-25, 25)),
    "upper_arm_l": ("torso", ("torso", [178, 45]), -90, 112, "left", (-30, 170)),
    "forearm_l": ("upper_arm_l", ("upper_arm_l", [28, 132]), -90, 132, "left", (-20, 140)),
    "upper_arm_r": ("torso", ("torso", [22, 45]), -90, 112, "right", (-170, 30)),
    "forearm_r": ("upper_arm_r", ("upper_arm_r", [28, 132]), -90, 132, "right", (-140, 20)),
    "thigh_l": ("torso", ("torso", [132, 262]), -90, 100, "left", (-35, 35)),
    "shin_l": ("thigh_l", ("thigh_l", [32, 118]), -90, 130, "left", (-10, 60)),
    "thigh_r": ("torso", ("torso", [68, 262]), -90, 100, "right", (-35, 35)),
    "shin_r": ("thigh_r", ("thigh_r", [32, 118]), -90, 130, "right", (-60, 10)),
}
PIVOTS = {
    "torso": [100, 260],
    "head": [110, 285],
    "upper_arm": [28, 20],
    "forearm": [26, 18],
    "thigh": [32, 16],
    "shin": [32, 14],
}
# part name: (image, bone). Both sides share an image.
PARTS = {
    "torso": ("torso", "torso"),
    "head": ("head", "head"),
    **{
        f"{img}_{s}": (img, f"{img}_{s}")
        for img in ("upper_arm", "forearm", "thigh", "shin")
        for s in "lr"
    },
}
DRAW_ORDER = [
    "thigh_r",
    "shin_r",
    "thigh_l",
    "shin_l",
    "torso",
    "upper_arm_r",
    "forearm_r",
    "upper_arm_l",
    "forearm_l",
    "head",
]


def rig_json() -> dict:
    bones = {}
    for name, (parent, attach, direction, length, side, (lo, hi)) in BONES.items():
        spec = {
            "role": name.rsplit("_", 1)[0] if name.endswith(("_l", "_r")) else name,
            "parent": parent,
            "direction_deg": direction,
            "length_px": length,
            "side": side,
            "limits_deg": {"min": lo, "max": hi},
        }
        if attach:
            spec["attach"] = {"part": attach[0], "at_px": attach[1]}
        bones[name] = spec
    parts = {
        name: {
            "file": f"parts/{img}.png",
            "size_px": list(IMAGES[img][0]),
            "pivot_px": PIVOTS[img],
            "bone": bone,
        }
        for name, (img, bone) in PARTS.items()
    }
    face = {
        "part": "head",
        "eyes": {"left_px": [141, 196], "right_px": [79, 196], "size_px": 30},
        "brows": {"left_px": [141, 164], "right_px": [79, 164], "width_px": 34},
        "mouth": {"at_px": [110, 248], "width_px": 60},
        "colors": {
            "line": "#463430",
            "eye_white": "#ffffff",
            "iris": "#463430",
            "mouth": "#78283a",
            "tongue": "#e88a96",
        },
    }
    return {
        "schema_version": 1,
        "id": "pip",
        "name": "Pip",
        "style": "storybook",
        "default_view": "front",
        "views": {
            "front": {
                "root": "torso",
                "bones": bones,
                "parts": parts,
                "draw_order": DRAW_ORDER,
                "face": face,
            }
        },
    }


def main() -> int:
    (OUT / "parts").mkdir(parents=True, exist_ok=True)
    for name, (size, draw) in IMAGES.items():
        part(size, draw).save(OUT / "parts" / f"{name}.png", optimize=True)
    data = rig_json()
    issues = validate("rig", data)
    if issues:
        sys.exit("rig.json is invalid: " + "; ".join(map(str, issues)))
    (OUT / "rig.json").write_text(json.dumps(data, indent=2) + "\n")
    print(
        f"wrote {OUT.relative_to(REPO_ROOT)}: {len(IMAGES)} images, {len(BONES)} bones, "
        f"{len(PARTS)} parts; rig.json valid"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
