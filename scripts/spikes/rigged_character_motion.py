# ruff: noqa: E501
"""Spike D-093: smoothness numbers, with the smoothing layer off and on (same shot, same motion).

    uv run --project studio_core python scripts/spikes/rigged_character_motion.py WORK_DIR

Per bone, from the baked world directions: pops (one-frame jumps above 9 deg), the largest step in
degrees per frame, and the jerk (RMS of the third difference). For the face: the largest one-frame
change of eye openness and mouth openness (a switch is 1.0; a blend is far smaller), and expression changes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from rigged_character_test import CAM_WIDE, setup_film, shot_spec

from studio_core.engines.bake import bake_shot
from studio_core.motions import smooth

work = Path(sys.argv[1]).expanduser()
film = setup_film(work)
report = {}
for mode in ("off", "on"):
    spec = shot_spec(CAM_WIDE)
    if mode == "off":
        spec.pop("smooth")
    bake = bake_shot(film, spec)
    ch = bake["characters"][0]
    dirs = {b: np.array([f["bones"][b][2] for f in ch["frames"]]) for b in ch["bones"]}
    # offsets from the parent: the same measure the motions use (a child's world angle includes its parent's)
    rel = {}
    for b, s in ch["bones"].items():
        rel[b] = dirs[b] - (dirs[s["parent"]] if s["parent"] else 0)
    step = {b: float(np.abs(np.diff(v)).max()) for b, v in rel.items()}
    pops = {b: int((np.abs(np.diff(v)) > smooth.DEFAULT_POP_DEG).sum()) for b, v in rel.items()}
    jerk = {b: float(np.sqrt(np.mean(np.diff(v, 3) ** 2))) for b, v in rel.items() if b != "torso"}
    out = {
        "pops_total": sum(pops.values()),
        "pops_by_bone": {b: n for b, n in pops.items() if n},
        "max_step_deg_per_frame": round(max(step.values()), 2),
        "jerk_rms_mean": round(float(np.mean(list(jerk.values()))), 3),
        "jerk_rms_max": round(max(jerk.values()), 3),
    }
    if mode == "on":
        eo = np.array([f["face"]["eye_open"] for f in ch["frames"]])
        mo = np.array([f["face"]["mouth"]["open"] for f in ch["frames"]])
        sm = np.array([f["face"]["smile"] for f in ch["frames"]])
        out["face"] = {
            "max_eye_open_step": round(float(np.abs(np.diff(eo)).max()), 3),
            "max_mouth_open_step": round(float(np.abs(np.diff(mo)).max()), 3),
            "max_smile_step": round(float(np.abs(np.diff(sm)).max()), 3),
            "blink_frames_to_close": int(((eo < 0.95) & (eo > 0.05)).sum()),
        }
    else:
        from studio_core.engines.bake import _track_value  # noqa: F401

        modes = [f["eyes"] for f in ch["frames"]]
        letters = [f["mouth"] for f in ch["frames"]]
        eo = np.array([smooth.EYE_VALUE.get(e, 1.0) for e in modes])
        mo = np.array([smooth.VISEME_PARAMS[m]["open"] for m in letters])
        out["face_switch"] = {
            "max_eye_open_step": round(float(np.abs(np.diff(eo)).max()), 3),
            "max_mouth_open_step": round(float(np.abs(np.diff(mo)).max()), 3),
            "eye_changes": int((np.diff(eo) != 0).sum()),
            "mouth_changes": int((np.diff(mo) != 0).sum()),
        }
    report[mode] = out
(work / "motion_report.json").write_text(json.dumps(report, indent=1))
print(json.dumps(report, indent=1))
