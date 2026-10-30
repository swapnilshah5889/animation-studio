# ruff: noqa: B023
"""Engine bake-off: how far can a knee or an elbow bend before the cut shows a hole or seam?

    uv run --project studio_core python scripts/spikes/bakeoff_bend.py [--render]

Kit stands on the magenta probe backdrop; frames 0-12 bend the right knee 0..120 degrees in steps
of 10, frames 13-27 bend the right elbow 0..140. Every engine plays the same baked transforms
(Synfig plays the same bends through `poses`, which the rig clamps to its limits: shin 60, forearm
140). For each frame it counts holes + seams (studio_core.preview.sweep) beyond the straight pose.
Writes ~/ai-studio/scratch/engine-bakeoff/bend.json and bend_sheet.png (a crop per engine).
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from studio_core.engines import bake as bk
from studio_core.engines.face_sprite import write_sprites
from studio_core.preview.sweep import check_frame, figure_mask

HERE = Path(__file__).parent
WORK = Path.home() / "ai-studio/scratch/engine-bakeoff"
FILM = WORK / "film"
KNEE = [(f, -10.0 * f) for f in range(13)]  # frame, shin offset
ELBOW = [(13 + i, -10.0 * i) for i in range(15)]  # frame, forearm offset
N = 28
ENGINES = [
    ("synfig-bend", "synfig", []),
    ("synfig-rigid", "synfig", ["--rigid"]),
    ("blender-workbench", "blender", ["--engine", "WORKBENCH"]),
    ("blender-rigid", "blender", ["--engine", "WORKBENCH", "--rigid"]),
    ("opentoonz-plastic", "opentoonz", []),
    ("opentoonz-rigid", "opentoonz", ["--rigid"]),
]


def spec() -> dict:
    poses = []
    for f, a in KNEE:
        poses.append({"time_s": f / 24, "bones": {"shin_r": a}})
    for f, a in ELBOW:
        poses.append({"time_s": f / 24, "bones": {"forearm_r": a, "shin_r": 0}})
    return {
        "schema_version": 1,
        "id": "s05_sh01",
        "duration_s": N / 24,
        "background": "probe",
        "characters": [
            {
                "id": "kit",
                "position": [0.5, 0.92],
                "facing": "right",
                "poses": poses,
                "expressions": [{"expr": "neutral", "start_s": 0.0}],
            }
        ],
        "camera": {"move": "static", "zoom": 1.0},
    }


def run(script: str, *args: str) -> None:
    out = subprocess.run(
        ["uv", "run", "--project", "studio_core", "python", str(HERE / script), *args],
        capture_output=True,
        text=True,
        cwd=HERE.parents[1],
    )
    print("  ", script, (out.stdout.strip().splitlines() or ["?"])[-1][:120], flush=True)


def count(img: Path) -> tuple[int, int]:
    found = check_frame(np.asarray(Image.open(img).convert("RGB").resize((960, 540))))
    return sum(d.kind == "hole" for d in found), sum(d.kind == "seam" for d in found)


def frame_files(d: Path) -> list[Path]:
    return sorted((d / "frames" if (d / "frames").is_dir() else d).glob("*.png"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", action="store_true")
    a = ap.parse_args()
    s = spec()
    shot_dir = FILM / "shots" / "s05_sh01"
    shot_dir.mkdir(exist_ok=True)
    (shot_dir / "shot.json").write_text(json.dumps(s))
    bake = bk.bake_shot(FILM, s)
    ch = bake["characters"][0]
    view = bk.load_rig(Path(ch["rig_dir"]) / "rig.json").view("front")
    for f in range(N):  # unclamped transforms for the engines that take the bake
        off = {"shin_r": dict(KNEE).get(f, 0.0), "forearm_r": dict(ELBOW).get(f, 0.0)}
        root = bk.Vec(*ch["frames"][f]["bones"]["torso"][:2])
        ch["frames"][f]["bones"] = bk._fk(view, off, {}, root, 1.0)
    write_sprites(bake, WORK / "sprites")
    (WORK / "bake_s05_sh01.json").write_text(json.dumps(bake))
    if a.render:
        for name, kind, flags in ENGINES:
            out = str(WORK / "out" / name / "bend_s05_sh01")
            if kind == "synfig":
                run("bakeoff_synfig.py", str(FILM), "s05_sh01", out, *flags)
            else:
                run(f"bakeoff_{kind}.py", str(WORK / "bake_s05_sh01.json"), out, *flags)
    result = {}
    sheet_rows = []
    for name, _, _ in ENGINES:
        files = frame_files(WORK / "out" / name / "bend_s05_sh01")
        if len(files) < N:
            continue
        counts = [count(f) for f in files]
        base = counts[0]

        def first_bad(rng: list[tuple[int, float]]) -> int | None:
            for f, ang in rng[1:]:
                if (counts[f][0] > base[0]) or (counts[f][1] > base[1]):
                    return int(-ang)
            return None

        area0 = int(figure_mask(np.asarray(Image.open(files[0]).convert("RGB")), 60).sum())
        areas = [
            int(figure_mask(np.asarray(Image.open(f).convert("RGB")), 60).sum()) / area0
            for f in files
        ]
        result[name] = {
            "base_holes_seams": base,
            "knee_first_new_defect_deg": first_bad(KNEE),
            "elbow_first_new_defect_deg": first_bad(ELBOW),
            "knee_120_vs_straight": [counts[12][0] - base[0], counts[12][1] - base[1]],
            "elbow_140_vs_straight": [counts[27][0] - base[0], counts[27][1] - base[1]],
            "area_ratio_knee_60": round(areas[6], 3),
            "area_ratio_knee_120": round(areas[12], 3),
            "area_ratio_elbow_90": round(areas[13 + 9], 3),
            "area_ratio_elbow_140": round(areas[27], 3),
        }
        row = Image.new("RGB", (4 * 300, 300), (232, 232, 228))
        for k, f in enumerate((0, 6, 12, 27)):  # straight, knee 60, knee 120, elbow 140
            im = Image.open(files[f]).convert("RGB")
            crop = im.crop(
                (
                    int(im.width * 0.28),
                    int(im.height * 0.25),
                    int(im.width * 0.72),
                    int(im.height * 1.0),
                )
            ).resize((300, 300))
            row.paste(crop, (k * 300, 0))
        ImageDraw.Draw(row).rectangle([0, 0, 170, 18], fill=(0, 0, 0))
        ImageDraw.Draw(row).text((4, 3), name, fill=(255, 255, 255))
        sheet_rows.append(row)
    (WORK / "bend.json").write_text(json.dumps(result, indent=1))
    if sheet_rows:
        sheet = Image.new("RGB", (1200, 300 * len(sheet_rows)))
        for i, r in enumerate(sheet_rows):
            sheet.paste(r, (0, i * 300))
        sheet.save(WORK / "bend_sheet.png")
    print(json.dumps(result, indent=1))


main()
