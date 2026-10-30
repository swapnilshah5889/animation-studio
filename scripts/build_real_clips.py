"""Build the real-motion clips (walk, run, wave, jump, shrug) from the CMU mocap files.

    uv run scripts/fetch_mocap.py           # once: the raw trials, outside the repo
    uv run scripts/build_real_clips.py      # writes studio_core/.../motions/real_clips/*.json

Deterministic: the same files give the same JSON. The JSON (a few KB each) is committed; the raw
mocap is not (docs/MODELS.md lists the source and its terms).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from studio_core.config import REPO_ROOT
from studio_core.mocap import acclaim
from studio_core.mocap.retarget import (
    RealClip,
    best_yaw,
    build_gait,
    build_oneshot,
    gaussian_smooth,
    project,
)

RAW = Path.home() / "ai-studio" / "mocap" / "cmu"
OUT = REPO_ROOT / "studio_core" / "src" / "studio_core" / "motions" / "real_clips"
FPS = 24
MAX_YAW = 45.0  # a puppet's gestures are drawn facing the viewer: never turn the plane beyond this


def load(trial: str) -> acclaim.Mocap:
    subject = trial.split("_")[0]
    return acclaim.load(RAW / f"{subject}.asf", RAW / f"{trial}.amc")


def active_window(m: acclaim.Mocap, joints: list[str], pad: float = 0.35) -> tuple[float, float]:
    """The seconds in which `joints` move at more than 15% of their top speed, padded."""
    p = project(m, 0.0)
    speed = sum(np.linalg.norm(np.gradient(p[j], axis=0), axis=1) for j in joints)
    speed = gaussian_smooth(speed, 6)
    on = np.where(speed > 0.15 * speed.max())[0]
    return max(0.0, on[0] / m.fps - pad), min((m.frames - 1) / m.fps, on[-1] / m.fps + pad)


def waving_side(m: acclaim.Mocap) -> str:
    left = np.ptp(m.joints["lradius_end"][:, 1])
    right = np.ptp(m.joints["rradius_end"][:, 1])
    return "left" if left > right else "right"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    clips: list[RealClip] = []
    clips.append(build_gait(load("35_01"), "walk", "35_01", FPS))
    clips.append(build_gait(load("35_17"), "run", "35_17", FPS))

    m = load("141_16")
    side = waving_side(m)
    c = "l" if side == "left" else "r"
    yaw = min(MAX_YAW, best_yaw(m, [(f"{c}radius_end", f"{c}humerus")]))
    clips.append(
        build_oneshot(m, "wave", "141_16", FPS, yaw, arms=(side,), gesture_side=side, legs=False)
    )

    m = load("141_21")
    window = active_window(m, ["lhumerus_end", "rhumerus_end", "lradius_end", "rradius_end"])
    clips.append(build_oneshot(m, "shrug", "141_21", FPS, 0.0, window, legs=False))

    m = load("13_39")
    clips.append(build_oneshot(m, "jump", "13_39", FPS, 0.0, active_window(m, ["root"], 0.15)))

    for clip in clips:
        path = OUT / f"{clip.name}.json"
        path.write_text(json.dumps(clip.to_json(), separators=(",", ":")) + "\n")
        print(
            f"{clip.name}: {clip.frames} frames at {clip.fps} fps, yaw {clip.yaw_deg:.0f}, "
            f"{path.stat().st_size / 1024:.0f} KB"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
