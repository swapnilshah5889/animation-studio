# ruff: noqa: E501
"""Engine bake-off driver: bake the benchmark shots and render them with every engine.

    uv run --project studio_core python scripts/spikes/bakeoff_all.py [--only synfig,blender,opentoonz]
        [--rerun]       # also re-render shot B into out/<engine>/rerun_s02_sh01 (determinism)

Work folder: ~/ai-studio/scratch/engine-bakeoff (film/, bake_<shot>.json, sprites/, out/<engine>/<shot>/).
Shots: s01_sh01 = shot A (Kit), s02_sh01 = shot B (Mia); s03/s04 = the same two on a magenta probe
backdrop (for the defect counts). Run `bakeoff_metrics.py` afterwards.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from studio_core.engines.bake import bake_shot
from studio_core.engines.face_sprite import write_sprites

HERE = Path(__file__).parent
WORK = Path.home() / "ai-studio/scratch/engine-bakeoff"
FILM = WORK / "film"
SHOTS = ("s01_sh01", "s02_sh01", "s03_sh01", "s04_sh01")
BLENDER = (
    ("blender-workbench", "WORKBENCH", False),
    ("blender-eevee", "EEVEE", False),
    ("blender-cycles", "CYCLES", False),
    ("blender-rigid", "WORKBENCH", True),
)


def run(script: str, *args: str) -> None:
    out = subprocess.run(
        ["uv", "run", "--project", "studio_core", "python", str(HERE / script), *args],
        capture_output=True,
        text=True,
        cwd=HERE.parents[1],
    )
    line = (out.stdout.strip().splitlines() or ["(no output)"])[-1]
    print(f"  {script} {' '.join(args[-3:])[:60]} -> {line[:200]}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="synfig,blender,opentoonz")
    ap.add_argument("--rerun", action="store_true")
    a = ap.parse_args()
    only = a.only.split(",")
    for shot in SHOTS:
        spec = json.loads((FILM / "shots" / shot / "shot.json").read_text())
        bake = bake_shot(FILM, spec)
        write_sprites(bake, WORK / "sprites")
        (WORK / f"bake_{shot}.json").write_text(json.dumps(bake))
    jobs = [(s, "") for s in SHOTS] + ([("s02_sh01", "rerun_")] if a.rerun else [])
    for shot, prefix in jobs:
        name = f"{prefix}{shot}" if prefix else (f"probe_{shot}" if shot in SHOTS[2:] else shot)
        bake = str(WORK / f"bake_{shot}.json")
        if "synfig" in only:
            for eng, flag in (("synfig-bend", []), ("synfig-rigid", ["--rigid"])):
                run("bakeoff_synfig.py", str(FILM), shot, str(WORK / "out" / eng / name), *flag)
        if "blender" in only:
            for eng, kind, rigid in BLENDER:
                run(
                    "bakeoff_blender.py",
                    bake,
                    str(WORK / "out" / eng / name),
                    "--engine",
                    kind,
                    *(["--rigid"] if rigid else []),
                )
        if "opentoonz" in only:
            for eng, flag in (("opentoonz-plastic", []), ("opentoonz-rigid", ["--rigid"])):
                run("bakeoff_opentoonz.py", bake, str(WORK / "out" / eng / name), *flag)


main()
