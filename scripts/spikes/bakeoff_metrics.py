"""Engine bake-off, gate 2 numbers.

    uv run --project studio_core python scripts/spikes/bakeoff_metrics.py WORK_DIR

WORK_DIR (~/ai-studio/scratch/engine-bakeoff) holds bake_<shot>.json (the benchmark shots),
out/<engine>/<shot>/ renders and out/<engine>/probe_<shot>/ renders on the magenta probe backdrop.
Prints and writes WORK_DIR/metrics.json:

  motion   (the same for every engine: they all play one bake): foot slide per planted contact,
           the largest knee bend, jerk and acceleration of the joint angles
  defects  holes, seams, detached pieces on the probe renders (studio_core.preview.sweep)
  area     figure area when a knee bends most, relative to the same character standing (a rough
           volume-keeping measure: bending that pinches shows as a smaller number)
  frames   every frame of a render differs from a second run? (determinism, by file hash)
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from studio_core.mocap import metrics
from studio_core.preview.sweep import Thresholds, check_frame, figure_mask

W = Path(sys.argv[1]).expanduser()
ENGINES = sorted(p.name for p in (W / "out").iterdir() if p.is_dir())


def frame_files(d: Path) -> list[Path]:
    sub = d / "frames" if (d / "frames").is_dir() else d
    return sorted(sub.glob("*.png"))


def motion(shot: str) -> dict:
    bake = json.loads((W / f"bake_{shot}.json").read_text())
    ch = bake["characters"][0]
    frames = ch["frames"]
    bones = ch["bones"]
    legs = [
        (b, next(c for c, s in bones.items() if s["parent"] == b))
        for b, s in bones.items()
        if s["role"] == "thigh"
    ]
    leg = sum(bones[b]["length_px"] for b in (legs[0][0], legs[0][1])) if legs else 1.0
    feet = {}
    for thigh, shin in legs:
        xs, ys = [], []
        for fr in frames:
            x, y, d = fr["bones"][shin]
            xs.append(x + bones[shin]["length_px"] * math.cos(math.radians(d)))
            ys.append(y + bones[shin]["length_px"] * math.sin(math.radians(d)))
        feet[bones[thigh]["side"]] = metrics.FootTrack(xs, ys)
    walk_n = 46  # the walk-in is the first 1.9 s
    walk_feet = {s: metrics.FootTrack(t.x[:walk_n], t.y[:walk_n]) for s, t in feet.items()}
    out = {"foot_slide_walk": metrics.foot_slide(walk_feet, leg) if shot == "s01_sh01" else None}
    bend = []
    for fr in frames:
        for thigh, shin in legs:
            bend.append(
                abs(
                    fr["bones"][shin][2]
                    - fr["bones"][thigh][2]
                    - (ch["rest"][shin][2] - ch["rest"][thigh][2])
                )
            )
    out["max_knee_bend_deg"] = round(max(bend), 1) if bend else 0
    offs = [{b: fr["bones"][b][2] - ch["rest"][b][2] for b in bones} for fr in frames]
    names = list(bones)
    out["jerk_rms_deg_f3"] = round(metrics.jerk_rms(offs, names), 2)
    out["accel_peak_deg_f2"] = round(metrics.accel_peak(offs, names), 1)
    out["max_bend_frame"] = (
        int(
            np.argmax(
                [
                    max(
                        abs(
                            fr["bones"][s][2]
                            - fr["bones"][t][2]
                            - (ch["rest"][s][2] - ch["rest"][t][2])
                        )
                        for t, s in legs
                    )
                    for fr in frames
                ]
            )
        )
        if legs
        else 0
    )
    return out


def area(img: Path) -> int:
    rgb = np.asarray(Image.open(img).convert("RGB"))
    return int(figure_mask(rgb, Thresholds().magenta_tol).sum())


def defects(engine: str, probe_shot: str) -> dict:
    files = frame_files(W / "out" / engine / f"probe_{probe_shot}")
    kinds = {"hole": 0, "seam": 0, "detached": 0}
    bad = 0
    biggest = 0
    for f in files:
        found = check_frame(np.asarray(Image.open(f).convert("RGB").resize((960, 540))))
        bad += bool(found)
        for d in found:
            kinds[d.kind] = kinds.get(d.kind, 0) + 1
            biggest = max(biggest, d.area_px)
    return {"frames": len(files), "frames_with_defect": bad, **kinds, "largest_px": biggest}


def digest(d: Path) -> str:
    h = hashlib.sha256()
    for f in frame_files(d):  # decoded pixels: PNG files from some engines carry a changing header
        h.update(Image.open(f).convert("RGB").tobytes())
    return h.hexdigest()[:12]


report: dict = {"motion": {s: motion(s) for s in ("s01_sh01", "s02_sh01")}, "engines": {}}
for e in ENGINES:
    r: dict = {}
    for shot, probe in (("s01_sh01", "s03_sh01"), ("s02_sh01", "s04_sh01")):
        if (W / "out" / e / f"probe_{probe}").is_dir():
            r[f"defects_{shot}"] = defects(e, probe)
            files = frame_files(W / "out" / e / f"probe_{probe}")
            if shot == "s01_sh01" and files:
                mb = report["motion"][shot]["max_bend_frame"]
                r["area_max_bend_vs_first"] = round(area(files[mb]) / area(files[0]), 3)
    a, b = W / "out" / e / "s02_sh01", W / "out" / e / "rerun_s02_sh01"
    if a.is_dir() and b.is_dir():
        r["deterministic_shot_b"] = digest(a) == digest(b)
        r["frames_shot_a"] = len(frame_files(W / "out" / e / "s01_sh01"))
    report["engines"][e] = r
(W / "metrics.json").write_text(json.dumps(report, indent=1))
print(json.dumps(report, indent=1))
