"""Render the motion library for review: one labelled cell per motion, tiled into a 3x3 video.

    uv run scripts/preview_motions.py              # energy 0.6
    uv run scripts/preview_motions.py --energy 1   # big versions

Output: ~/ai-studio/scratch/motion-preview/motions_e<energy>.mp4 (1920x1080, 24 fps, ~4 s).
Each cell is a full Synfig render of Pip (bone rig + procedural face) doing one motion, built
through studio_core.motions.animate exactly as synfig_mcp will. Generated media, kept outside
the repo. Safe to re-run.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from studio_core.config import REPO_ROOT, load_config
from studio_core.face import face_attachments
from studio_core.motions import MOTIONS, animate
from studio_core.rig import build_character, load_rig
from studio_core.sif import (
    Canvas,
    Color,
    Group,
    ImportLayer,
    Rectangle,
    Space,
    Transform,
    Vec,
)
from studio_core.sif.render import encode_mp4, render_frames

RIG = REPO_ROOT / "tests" / "fixtures" / "characters" / "pip" / "rig.json"
OUT = Path.home() / "ai-studio" / "scratch" / "motion-preview"
W, H, PPU, FPS, SECONDS = 640, 360, 60, 24, 4.0
SCALE, HIPS = 0.34, (320, 250)  # Pip at 34% size, hips at this cell pixel
ORDER = [
    "idle_breathe",
    "blink",
    "wave",
    "nod",
    "head_tilt",
    "talk_gesture",
    "point",
    "walk_cycle",
    "jump",
]


def label_png(path: Path, text: str) -> None:
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 22)
    img = Image.new("RGBA", (300, 34), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, 299, 33], radius=8, fill=(255, 255, 255, 220))
    ImageDraw.Draw(img).text((10, 5), text, font=font, fill=(40, 40, 60, 255))
    img.save(path)


def cell(motion: str, energy: float, work: Path) -> Path:
    rig = load_rig(RIG)
    view = rig.view()
    n = round(SECONDS * FPS)
    params: dict = {"energy": energy}
    if motion == "point":
        params["target"] = [600, 40]  # top-right of the cell
    anim = animate(
        view,
        [{"motion": motion, "start_s": 0.4, "params": params}],
        fps=FPS,
        n_frames=n,
        root_px=Vec(*HIPS),
        scale=SCALE,
        seed="pip",
    )
    space = Space(W, H, PPU)
    face = face_attachments(view, space, expression="happy", eyes=anim.eyes or "open")
    built = build_character(
        rig,
        None,
        space,
        file_prefix="pip",
        offsets=anim.angles,
        shifts=anim.shifts,
        attachments=face,
    )
    hx, hy = space.to_units(*HIPS)
    pip = Group(
        "pip",
        transform=Transform(offset=Vec(hx, hy), scale=Vec(SCALE, SCALE)),
        children=[built.group],
    )
    label_png(work / "label.png", f"{motion}  (energy {energy:g})")
    label = ImportLayer(
        "label", file="label.png", tl=Vec(*space.to_units(10, 8)), br=Vec(*space.to_units(310, 42))
    )
    canvas = Canvas(
        width=W,
        height=H,
        fps=FPS,
        frames=n,
        ppu=PPU,
        bgcolor=Color(1, 1, 1),
        bones=built.bones,
        layers=[
            Rectangle("sky", color=Color.hex("#dcecf8"), point1=Vec(-6, 4), point2=Vec(6, -4)),
            Rectangle(
                "ground",
                color=Color.hex("#a8d59a"),
                point1=Vec(-6, space.to_units(0, 330)[1]),
                point2=Vec(6, -4),
            ),
            pip,
            label,
        ],
    )
    render_frames(canvas.save(work / "cell.sif"), work / "frames")
    return encode_mp4(work / "frames", work / "cell.mp4", FPS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--energy", type=float, default=0.6)
    args = parser.parse_args()
    assert set(ORDER) == set(MOTIONS), "preview must show every motion"

    OUT.mkdir(parents=True, exist_ok=True)
    cells = []
    for motion in ORDER:
        work = OUT / f"e{args.energy:g}" / motion
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        shutil.copytree(RIG.parent, work / "pip")
        cells.append(cell(motion, args.energy, work))
        print(f"rendered {motion}")

    ffmpeg = str(load_config().path("tools", "ffmpeg"))
    layout = "|".join(f"{(i % 3) * W}_{(i // 3) * H}" for i in range(9))
    out = OUT / f"motions_e{args.energy:g}.mp4"
    cmd = [ffmpeg, "-y", "-v", "error"]
    for c in cells:
        cmd += ["-i", str(c)]
    cmd += [
        "-filter_complex",
        f"xstack=inputs=9:layout={layout}",
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        str(out),
    ]
    subprocess.run(cmd, check=True)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
