"""Skinned-mesh spike (D-093): count defect frames of one continuous skinned mesh per character,
with the same probe-backdrop measure as the rigid cut (overlap_measure.measure).

    uv run --project studio_core python scripts/spikes/skinned_measure.py s03_sh01 [--blend 0.6]
        [--step 8] [--baseline] [--frames] [--attribute-sheet]

Prints one JSON line: frames, defect frames, holes, seams, per-joint tally, s/frame. `--baseline`
measures the cut (bendable limbs) the same way. Needs the bake-off work folder.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from overlap_measure import WORK, measure

from studio_core.engines.blender.skin import build_skin, distortion

ap = argparse.ArgumentParser()
ap.add_argument("shot")
ap.add_argument("--blend", type=float, default=0.6)
ap.add_argument("--band", type=float, default=1.0)
ap.add_argument("--step", type=int, default=8)
ap.add_argument("--baseline", action="store_true")
ap.add_argument("--frames", action="store_true")
ap.add_argument("--tag", default="")
a = ap.parse_args()

bake_path = WORK / f"bake_{a.shot}.json"
out = WORK / "out" / "skinned" / (a.shot + ("_base" if a.baseline else "") + a.tag)
out.mkdir(parents=True, exist_ok=True)
if not a.baseline:
    bake = json.loads(bake_path.read_text())
    for ch in bake["characters"]:
        ch["skin"] = build_skin(ch, out / "skin", step=a.step, blend=a.blend, band=a.band)
    bake_path = out / "bake_skin.json"
    bake_path.write_text(json.dumps(bake))
res = measure(bake_path, out / "render", per_frame=a.frames)
stats = json.loads((out / "render" / "stats.json").read_text())
res["s_per_frame"] = stats["s_per_frame"]
if not a.baseline:
    d = distortion(bake["characters"][0], bake["characters"][0]["skin"])
    res["distorted_frames"] = sum(x["bad"] > 0.02 for x in d)
    res["folded_frames"] = sum(x["folded"] > 0.002 for x in d)
    res["worst_bad_share"] = round(max(x["bad"] for x in d), 3)
    res["distorted_list"] = [i for i, x in enumerate(d) if x["bad"] > 0.02] if a.frames else None
    res["skin"] = {k: v for k, v in bake["characters"][0]["skin"].items() if k.startswith("n_")}
print(json.dumps(res))
