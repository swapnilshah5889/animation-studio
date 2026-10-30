"""Run the Blender back end headless from Python: `render(bake_json, out_dir, ...)`."""

from __future__ import annotations

import json
import resource
import subprocess
import time
from pathlib import Path

BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")
SCRIPT = Path(__file__).with_name("build_render.py")


def render(
    bake_json: Path,
    out_dir: Path,
    *,
    engine: str = "EEVEE",
    size: str = "960x540",
    rigid: bool = False,
    frames: str | None = None,
    samples: int = 8,
) -> dict:
    cmd = [
        str(BLENDER),
        "--background",
        "--factory-startup",
        "--python",
        str(SCRIPT),
        "--",
        str(bake_json),
        str(out_dir),
        "--engine",
        engine,
        "--size",
        size,
        "--samples",
        str(samples),
    ]
    if rigid:
        cmd.append("--rigid")
    if frames:
        cmd += ["--frames", frames]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    wall = time.perf_counter() - t0
    log = proc.stdout + proc.stderr
    stats_path = out_dir / "stats.json"
    stats = json.loads(stats_path.read_text()) if stats_path.exists() else {}
    stats.update(
        engine=f"blender-{engine.lower()}",
        wall_s=round(wall, 2),
        returncode=proc.returncode,
        children_maxrss_mb=round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1e6),
    )
    (out_dir / "blender.log").write_text(log)
    return stats
