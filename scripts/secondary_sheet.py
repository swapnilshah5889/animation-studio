"""Task 4B: a contact sheet of the ears' and tail's follow-through, with and without.

    uv run scripts/secondary_sheet.py --film <film with secondary=True builds> kit bo

For each character (a rig with ear or tail bones) it poses the puppet (forward kinematics, PIL:
no Synfig) at frames of a head tilt and a nod, once with the follow-through layer and once
without it, and writes renders/secondary/sheet.png (renders/ is git-ignored). Rows: tilt with,
tilt without, nod with, nod without. Columns: three frames of the motion, per character.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

from studio_core.config import REPO_ROOT
from studio_core.motions import Key, animate
from studio_core.motions.timeline import sample
from studio_core.rig import load_rig, world_pose
from studio_core.sif import Interp

FPS = 24
N = 72
CELL = (330, 300)
MOTIONS = {
    "tilt": ([{"motion": "head_tilt", "start_s": 0.25, "params": {"side": "left", "energy": 1}}],
              (0.40, 0.60, 1.40)),
    "nod": ([{"motion": "nod", "start_s": 0.25, "params": {"energy": 1.0}}], (0.40, 0.55, 0.80)),
}  # fmt: skip


def value_at(track, frame: int):
    return sample([Key(w.frame, w.value, Interp.LINEAR) for w in track.waypoints], frame)


def pose(view, folder: Path, anim, frame: int) -> Image.Image:
    angles = {b: value_at(t, frame).degrees for b, t in anim.angles.items()}
    shifts = {b: value_at(t, frame) for b, t in anim.shifts.items()}
    world = world_pose(view, angles)
    size = (1000, 1000)
    root = (500, 640)
    out = Image.new("RGBA", size, (250, 248, 244, 255))
    for name in view["draw_order"]:
        part = view["parts"][name]
        joint, direction = world[part["bone"]]
        dx = dy = 0.0
        bone = part["bone"]
        while bone is not None:  # a shift moves the bone's joint, and what hangs from it
            if bone in shifts:
                dx, dy = dx + shifts[bone].x, dy + shifts[bone].y
            bone = view["bones"][bone]["parent"]
        turn = direction - view["bones"][part["bone"]]["direction_deg"]
        jx, jy = root[0] + joint.x + dx, root[1] - joint.y - dy
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        px, py = part["pivot_px"]
        layer.paste(
            Image.open(folder / part["file"]).convert("RGBA"), (round(jx - px), round(jy - py))
        )
        out.alpha_composite(layer.rotate(turn, Image.Resampling.BICUBIC, center=(jx, jy)))
    return out.crop((140, 20, 860, 660)).resize(CELL)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--film", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "renders" / "secondary")
    ap.add_argument("--view", default="front")
    ap.add_argument("characters", nargs="+")
    args = ap.parse_args()
    rows = [(m, on) for m in MOTIONS for on in (True, False)]
    sheet = Image.new(
        "RGB", (CELL[0] * 3 * len(args.characters), (CELL[1] + 4) * len(rows)), (255, 255, 255)
    )
    draw = ImageDraw.Draw(sheet)
    for ci, cid in enumerate(args.characters):
        folder = args.film / "characters" / cid
        view = load_rig(folder / "rig.json").view(args.view)
        for ri, (motion, on) in enumerate(rows):
            actions, times = MOTIONS[motion]
            anim = animate(view, actions, fps=FPS, n_frames=N, secondary=on)
            for k, t in enumerate(times):
                x, y = (ci * 3 + k) * CELL[0], ri * (CELL[1] + 4)
                sheet.paste(pose(view, folder, anim, round(t * FPS)).convert("RGB"), (x, y))
                label = f"{cid} {motion} {'with' if on else 'without'} follow-through, {t:.2f}s"
                draw.text((x + 6, y + 4), label, fill=(0, 0, 0))
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "sheet.png"
    sheet.save(path)
    print(path)


if __name__ == "__main__":
    main()
