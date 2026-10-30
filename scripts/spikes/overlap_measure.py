# ruff: noqa: E501
"""Joint-overlap measuring tool: Kit's benchmark shot (probe backdrop), rendered headless in Blender,
and a count of the frames with holes or seams.

    uv run --project studio_core python scripts/spikes/overlap_measure.py [--shot s03_sh01] [--rigid]
        [--rig CHARACTER_DIR]   # a rebuilt character folder (scripts/spikes/overlap_rebuild.py)
        [--attribute]           # trace each defect to the cut parts around it (flat-colour render)
        [--frames]              # also list the defect frames

Needs the bake-off work folder (`bakeoff_all.py` makes it). Prints one JSON line: frames, defect
frames, holes, seams and a tally per joint (or, with --attribute, per pair of bordering parts).
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from studio_core.engines.blender.launch import render
from studio_core.engines.limbs import add_bendable_limbs
from studio_core.preview.sweep import check_frame

WORK = Path.home() / "ai-studio/scratch/engine-bakeoff"


def joint_positions(bake: dict, frame: int, size=(960, 540)) -> dict[str, tuple[float, float]]:
    """Joint (bone start) positions in the 960x540 frame, from the bake (stage px, y up)."""
    ch = bake["characters"][0]
    w, h = bake["size"]
    sx, sy = size[0] / w, size[1] / h
    return {b: (v[0] * sx, size[1] - v[1] * sy) for b, v in ch["frames"][frame]["bones"].items()}


def flat_copy(bake_path: Path, dest: Path) -> tuple[Path, dict[str, tuple[int, int, int]]]:
    """A copy of the bake whose parts are flat unique colours (alpha kept), so a defect can be
    traced to the parts around it. Returns the new bake path and {part: colour}."""
    bake = json.loads(bake_path.read_text())
    ch = bake["characters"][0]
    rig_dir = Path(ch["rig_dir"])
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(rig_dir, dest)
    rig = json.loads((dest / "rig.json").read_text())["views"][ch["view"]]
    colours = {}
    for i, (name, part) in enumerate(sorted(rig["parts"].items())):
        c = ((i * 67 + 40) % 200 + 30, (i * 113 + 90) % 200 + 30, (i * 29 + 150) % 200 + 30)
        colours[name] = c
        im = Image.open(dest / part["file"]).convert("RGBA")
        a = im.getchannel("A")
        Image.merge("RGBA", (*Image.new("RGB", im.size, c).split(), a)).save(dest / part["file"])
    add_bendable_limbs(dest, ch["view"])
    ch["rig_dir"] = str(dest)
    out = dest.parent / (bake_path.stem + "_flat.json")
    out.write_text(json.dumps(bake))
    return out, colours


def bordering(rgb: np.ndarray, box, colours: dict) -> list[str]:
    """Part names whose flat colour appears within 5 px of a defect box (most pixels first)."""
    x0, y0, x1, y1 = box
    crop = rgb[max(y0 - 5, 0) : y1 + 5, max(x0 - 5, 0) : x1 + 5].reshape(-1, 3).astype(int)
    keys = list(colours)
    pal = np.array([colours[k] for k in keys])
    d = np.abs(crop[:, None, :] - pal[None]).sum(-1)
    hit = d.argmin(1)[d.min(1) < 30]
    cnt = Counter(keys[i] for i in hit)
    return [k for k, n in cnt.most_common(3) if n >= 4]


def with_rig(bake_path: Path, rig_dir: Path) -> Path:
    """A copy of the bake that points at another character folder (its limb images are rebuilt)."""
    bake = json.loads(bake_path.read_text())
    ch = bake["characters"][0]
    add_bendable_limbs(rig_dir, ch["view"])
    ch["rig_dir"] = str(rig_dir)
    ch["limbs"] = json.loads((rig_dir / "rig.json").read_text())["views"][ch["view"]][
        "bendable_limbs"
    ]
    out = rig_dir.parent / f"{bake_path.stem}_rig.json"
    out.write_text(json.dumps(bake))
    return out


def measure(
    bake_path: Path,
    out: Path,
    rigid: bool = False,
    per_frame: bool = False,
    attribute: bool = False,
    rig: Path | None = None,
) -> dict:
    colours = None
    if rig:
        bake_path = with_rig(bake_path, rig)
    if attribute:
        bake_path, colours = flat_copy(bake_path, out.parent / "flat_rig")
    render(bake_path, out, engine="WORKBENCH", rigid=rigid)
    bake = json.loads(bake_path.read_text())
    files = sorted(
        (out / "frames").glob("*.png") if (out / "frames").is_dir() else out.glob("*.png")
    )
    kinds: Counter = Counter()
    joints: Counter = Counter()
    bad = 0
    frames_bad = []
    for i, f in enumerate(files):
        found = check_frame(np.asarray(Image.open(f).convert("RGB").resize((960, 540))))
        bad += bool(found)
        if found:
            frames_bad.append(i)
        jp = joint_positions(bake, min(i, len(bake["characters"][0]["frames"]) - 1))
        for d in found:
            kinds[d.kind] += 1
            if colours:
                rgb = np.asarray(Image.open(f).convert("RGB").resize((960, 540)))
                near = "|".join(sorted(bordering(rgb, d.box, colours)[:2])) or "?"
            else:
                near = min(jp, key=lambda b: math.dist(jp[b], d.center))
            joints[f"{near}:{d.kind}"] += 1
    res = {
        "frames": len(files),
        "defect_frames": bad,
        **kinds,
        "by_joint": dict(joints.most_common(16)),
    }
    if per_frame:
        res["bad_frames"] = frames_bad
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot", default="s03_sh01")
    ap.add_argument("--rigid", action="store_true")
    ap.add_argument("--frames", action="store_true")
    ap.add_argument("--rig", type=Path, help="a rebuilt character folder (overlap_rebuild.py)")
    ap.add_argument(
        "--attribute", action="store_true", help="trace defects to the parts around them"
    )
    a = ap.parse_args()
    out = WORK / "out" / "overlap" / a.shot
    print(
        json.dumps(
            measure(WORK / f"bake_{a.shot}.json", out, a.rigid, a.frames, a.attribute, a.rig)
        )
    )
