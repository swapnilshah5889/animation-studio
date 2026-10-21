"""Render a labelled sheet of the procedural face: every expression x every mouth, plus blinks.

    uv run scripts/preview_face.py      # → ~/ai-studio/scratch/face-preview/face_preview.png

One Synfig render: frame k shows one (expression, mouth) pair, then the blink states. Generated
media, so it stays outside the repo. Safe to re-run.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from studio_core.config import REPO_ROOT
from studio_core.face import EXPRESSIONS, MOUTHS, face_attachments
from studio_core.rig import build_character, load_rig
from studio_core.sif import (
    Animated,
    Canvas,
    Color,
    Group,
    Interp,
    Rectangle,
    Space,
    Transform,
    Vec,
    Waypoint,
)
from studio_core.sif.render import render_frames

RIG = REPO_ROOT / "tests" / "fixtures" / "characters" / "pip" / "rig.json"
OUT = Path.home() / "ai-studio" / "scratch" / "face-preview"
W, H, PPU = 300, 340, 60


def track(values: list[str]) -> Animated:
    """One value per frame, collapsing repeats (switch states step)."""
    keys: list[Waypoint] = []
    for frame, value in enumerate(values):
        if not keys or keys[-1].value != value:
            keys.append(Waypoint(frame, value, Interp.CONSTANT))
    return Animated("string", tuple(keys))


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    rig = load_rig(RIG)
    shutil.copytree(rig.folder, OUT / "pip")
    view = rig.view()
    space = Space(W, H, PPU)

    combos = [(e, m) for e in EXPRESSIONS for m in MOUTHS]
    blinks = ["open", "half", "closed"]
    exprs = [e for e, _ in combos] + ["neutral"] * len(blinks)
    mouths = [m for _, m in combos] + ["X"] * len(blinks)
    eyes = ["open"] * len(combos) + blinks

    attachments = face_attachments(
        view, space, expression=track(exprs), eyes=track(eyes), mouth=track(mouths)
    )
    built = build_character(rig, None, space, file_prefix="pip", attachments=attachments)
    # Frame the head: the neck sits 242 px above the hips; the head centre ~150 px above that.
    place = Group(
        "place", transform=Transform(offset=Vec(0, -(242 + 150) / PPU)), children=[built.group]
    )
    canvas = Canvas(
        width=W,
        height=H,
        fps=24,
        frames=len(exprs),
        ppu=PPU,
        bgcolor=Color(1, 1, 1),
        layers=[
            Rectangle("bg", color=Color(0.93, 0.95, 0.98), point1=Vec(-5, 5), point2=Vec(5, -5)),
            place,
        ],
        bones=built.bones,
    )
    frames = render_frames(canvas.save(OUT / "face.sif"), OUT / "frames")

    thumb = 150
    font = ImageFont.load_default(size=16)
    label_w, head_h = 110, 26
    cols = len(MOUTHS)
    rows = len(EXPRESSIONS) + 1
    sheet = Image.new("RGB", (label_w + cols * thumb, head_h + rows * (thumb + 6)), "white")
    draw = ImageDraw.Draw(sheet)
    for j, m in enumerate(MOUTHS):
        draw.text((label_w + j * thumb + thumb // 2 - 6, 4), m, fill="black", font=font)
    for k, frame in enumerate(frames):
        if k < len(combos):
            r, c = divmod(k, cols)
            label = EXPRESSIONS[r]
        else:
            r, c = len(EXPRESSIONS), k - len(combos)
            label = "blink"
        img = Image.open(frame).convert("RGB")
        face = img.crop((40, 90, 260, 310)).resize((thumb, thumb))  # eyes-to-mouth region
        y = head_h + r * (thumb + 6)
        sheet.paste(face, (label_w + c * thumb, y))
        if c == 0:
            draw.text((8, y + thumb // 2 - 8), label, fill="black", font=font)
        if r == len(EXPRESSIONS):
            draw.text((label_w + c * thumb + 6, y + thumb - 22), blinks[c], fill="black", font=font)
    out = OUT / "face_preview.png"
    sheet.save(out)
    print(f"wrote {out} ({len(frames)} faces)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
