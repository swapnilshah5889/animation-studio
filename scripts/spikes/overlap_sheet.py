"""Before/after contact sheet for the joint-overlap work: Kit's benchmark shot on the magenta probe
backdrop, Blender Workbench, old parts (the film's) above and the rebuilt parts below.

    uv run --project studio_core python scripts/spikes/overlap_sheet.py NEW_CHARACTER_DIR OUT.png
        [--frames 13,15,44,85,100,116]

Rows: before, after. A frame is cropped to the figure. Needs the bake-off work folder.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
from overlap_measure import WORK, with_rig

from studio_core.engines.blender.launch import render


def crops(frames_dir: Path, wanted: list[int], boxes: list | None = None) -> tuple[list, list]:
    files = sorted(frames_dir.glob("*.png"))
    out, used = [], []
    for k, i in enumerate(wanted):
        im = Image.open(files[i]).convert("RGB")
        if boxes is None:
            a = np.asarray(im).astype(int)
            fig = np.abs(a - [255, 0, 255]).max(-1) > 60
            ys, xs = np.nonzero(fig)
            box = (xs.min() - 8, ys.min() - 8, xs.max() + 8, ys.max() + 8)
        else:
            box = boxes[k]
        used.append(box)
        out.append(im.crop(box))
    return out, used


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("rig", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--frames", default="13,15,44,85,100,116")
    a = ap.parse_args()
    wanted = [int(f) for f in a.frames.split(",")]
    base = WORK / "bake_s03_sh01.json"
    scratch = WORK / "out" / "overlap" / "sheet"
    render(base, scratch / "before", engine="WORKBENCH")
    render(with_rig(base, a.rig), scratch / "after", engine="WORKBENCH")
    before, boxes = crops(scratch / "before", wanted)
    after, _ = crops(scratch / "after", wanted, boxes)
    h = 300
    tiles = [
        [im.resize((round(im.width * h / im.height), h), Image.LANCZOS) for im in row]
        for row in (before, after)
    ]
    w = sum(t.width for t in tiles[0])
    sheet = Image.new("RGB", (w, 2 * h + 24), (30, 30, 30))
    for r, row in enumerate(tiles):
        x = 0
        for t in row:
            sheet.paste(t, (x, 24 + r * h))
            x += t.width
    d = ImageDraw.Draw(sheet)
    d.text((6, 6), f"before (row 1) / after (row 2); frames {a.frames}", fill=(255, 255, 255))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(a.out)
    print(a.out, sheet.size)
