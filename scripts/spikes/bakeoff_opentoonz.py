"""Engine bake-off: build and render a baked benchmark shot with OpenToonz (`tcomposer`).

    uv run --project studio_core python scripts/spikes/bakeoff_opentoonz.py BAKE.json OUT_DIR
        [--rigid] [--frames N] [--shrink 2]

OUT_DIR gets project/ (the generated OpenToonz project), frames/0000.png... and stats.json.
"""

from __future__ import annotations

import argparse
import json
import resource
import shutil
import time
from pathlib import Path

from studio_core.engines.opentoonz.build import build_project
from studio_core.engines.opentoonz.tnz import render

ap = argparse.ArgumentParser()
ap.add_argument("bake", type=Path)
ap.add_argument("out", type=Path)
ap.add_argument("--rigid", action="store_true")
ap.add_argument("--frames", type=int)
ap.add_argument("--shrink", type=int, default=2)
a = ap.parse_args()

bake = json.loads(a.bake.read_text())
n = a.frames or bake["n_frames"]
t0 = time.perf_counter()
scene, info = build_project(bake, a.out / "project", rigid=a.rigid)
build_s = time.perf_counter() - t0
raw = a.out / "raw"
shutil.rmtree(raw, ignore_errors=True)
res = render(scene, raw, n, shrink=a.shrink)
frames = a.out / "frames"
shutil.rmtree(frames, ignore_errors=True)
frames.mkdir()
for i, f in enumerate(sorted(raw.glob("f.*.png"))):
    shutil.move(f, frames / f"{i:04d}.png")
shutil.rmtree(raw)
stats = {
    "engine": "opentoonz-rigid" if a.rigid else "opentoonz-plastic",
    "frames": res["frames"],
    "build_s": round(build_s, 2),
    "render_total_s": res["wall_s"],
    "s_per_frame": round(res["wall_s"] / max(res["frames"], 1), 3),
    "wall_s": round(time.perf_counter() - t0, 2),
    "returncode": res["returncode"],
    "children_maxrss_mb": round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1e6),
    **info,
}
(a.out / "stats.json").write_text(json.dumps(stats))
print(json.dumps(stats))
if res["returncode"] or res["frames"] != n:
    print(res["stderr_tail"])
