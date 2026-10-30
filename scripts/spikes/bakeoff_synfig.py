"""Engine bake-off, baseline: render a benchmark shot through the production Synfig back end.

    uv run --project studio_core python scripts/spikes/bakeoff_synfig.py FILM SHOT OUT_DIR [--rigid]

Writes OUT_DIR/frames/0000.png... (960x540) and OUT_DIR/stats.json (wall time, per frame).
`--rigid` draws two rigid parts per limb; the default bends limbs (Skeleton Deformation).
"""

from __future__ import annotations

import argparse
import json
import resource
import shutil
import time
from pathlib import Path

from studio_core.shot import render_shot

ap = argparse.ArgumentParser()
ap.add_argument("film", type=Path)
ap.add_argument("shot")
ap.add_argument("out", type=Path)
ap.add_argument("--rigid", action="store_true")
args = ap.parse_args()

t0 = time.perf_counter()
rendered = render_shot(args.film, args.shot, size=(960, 540), audio=False, bend=not args.rigid)
wall = time.perf_counter() - t0
out = args.out / "frames"
shutil.rmtree(out, ignore_errors=True)
out.mkdir(parents=True)
for i, f in enumerate(sorted(rendered.frames)):
    shutil.copy(f, out / f"{i:04d}.png")
n = len(rendered.frames)
stats = {
    "engine": "synfig-rigid" if args.rigid else "synfig-bend",
    "frames": n,
    "wall_s": round(wall, 2),
    "s_per_frame": round(wall / n, 3),
    "children_maxrss_mb": round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1e6),
}
(args.out / "stats.json").write_text(json.dumps(stats))
print(stats)
