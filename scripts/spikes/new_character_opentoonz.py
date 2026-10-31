"""Render the new-character bake (new_character_test.py) with OpenToonz: tcomposer on a generated project.

    uv run --project studio_core python scripts/spikes/new_character_opentoonz.py [work_dir]

The character is rendered on a transparent plate; the plate, shadow and mux are the same Python
compositor as the Blender clip, so the two clips differ only in how the engine drew the puppet.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import new_character_test as nct  # noqa: E402
import rigged_character_test as rct  # noqa: E402
from PIL import Image  # noqa: E402

from studio_core.engines.opentoonz.build import build_project  # noqa: E402
from studio_core.engines.opentoonz.tnz import render  # noqa: E402

work = Path(
    sys.argv[1] if len(sys.argv) > 1 else "~/ai-studio/scratch/new-character-test"
).expanduser()
bake = json.loads((work / "bake_blender.json").read_text())
clear = work / "clear.png"
Image.new("RGBA", (nct.W, nct.H), (0, 0, 0, 0)).save(clear)
bake["transparent"] = True
t0 = time.perf_counter()
scene, info = build_project(bake, work / "ot_project", rigid=True)
print("project", info, round(time.perf_counter() - t0, 2), "s")
raw = work / "ot_raw"
shutil.rmtree(raw, ignore_errors=True)
res = render(scene, raw, bake["n_frames"], shrink=1)
print("render", res)
frames = work / "frames_opentoonz"
shutil.rmtree(frames, ignore_errors=True)
frames.mkdir()
for i, f in enumerate(sorted(raw.glob("f.*.png"))):
    shutil.copyfile(f, frames / f"{i:04d}.png")
rct.SCALE = 0.95
layers = rct.make_layers()
out = work / "final_opentoonz"
out.mkdir(exist_ok=True)
for f in range(nct.N):
    cam = tuple(bake["camera_track"][f])
    rct.composite(layers, frames / f"{f:04d}.png", cam, rct.foot_px(bake, f)).save(
        out / f"{f:04d}.png"
    )
rct.mux(work, out, "opentoonz")
print("wrote", work / "clip_opentoonz.mp4")
