"""Engine bake-off: render a baked benchmark shot with Blender (headless).

uv run --project studio_core python scripts/spikes/bakeoff_blender.py BAKE.json OUT_DIR
    [--engine EEVEE|WORKBENCH|CYCLES] [--frames 60-60] [--rigid] [--samples 8]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from studio_core.engines.blender.launch import render

ap = argparse.ArgumentParser()
ap.add_argument("bake", type=Path)
ap.add_argument("out", type=Path)
ap.add_argument("--engine", default="EEVEE")
ap.add_argument("--frames")
ap.add_argument("--rigid", action="store_true")
ap.add_argument("--samples", type=int, default=8)
ap.add_argument("--size", default="960x540")
a = ap.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
stats = render(
    a.bake, a.out, engine=a.engine, frames=a.frames, rigid=a.rigid, samples=a.samples, size=a.size
)
print(json.dumps(stats))
if stats["returncode"]:
    print((a.out / "blender.log").read_text()[-1500:])
