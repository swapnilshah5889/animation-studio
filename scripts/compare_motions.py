"""Render the same 5 s shot with the old hand-keyed and the new real motions, side by side.

    uv run scripts/compare_motions.py                  # Kit, film: ~/ai-studio/scratch/real-motion
    uv run scripts/compare_motions.py --character bo --film films/real-15s

The shot: the character walks in (a path across the frame), waves, then jumps. Two shots, same
timing, same path, same camera; only the motions differ. Writes, next to the film folder's shots:

    <film>/compare.mp4     old (left) | new (right), labelled, 960x540 each
    <film>/compare.json    the numbers: foot slide per contact, acceleration peaks, range of motion

Nothing is written into the character folders (they are linked into a scratch film).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from studio_core import placement
from studio_core.config import REPO_ROOT, load_config
from studio_core.mocap import metrics
from studio_core.motions import animate
from studio_core.motions.real import load_clip
from studio_core.rig import load_rig
from studio_core.scene import DESIGN
from studio_core.shot import render_shot
from studio_core.sif import Vec

FPS = 24
SECONDS = 5.0
PATH = [{"time_s": 1.9, "position": [0.6, 0.9], "ease": "ease_in_out"}]
START = [0.12, 0.9]


def actions(new: bool) -> list[dict[str, Any]]:
    common = [
        {"motion": "blink", "start_s": 0.0, "duration_s": SECONDS},
        {"motion": "idle_breathe", "start_s": 0.0},
    ]
    if new:
        return [
            *common,
            {"motion": "walk_real", "start_s": 0.0, "duration_s": 1.9, "params": {"energy": 0.6}},
            {
                "motion": "wave_real",
                "start_s": 1.9,
                "params": {"energy": 0.6, "speed": 1.8, "side": "right", "principles": 0.4},
            },
            {
                "motion": "jump_real",
                "start_s": 3.5,
                "params": {"energy": 0.6, "speed": 1.7, "principles": 0.4},
            },
        ]
    return [
        *common,
        {"motion": "walk_cycle", "start_s": 0.0, "duration_s": 1.9, "params": {"energy": 0.6}},
        {"motion": "wave", "start_s": 1.9, "params": {"energy": 0.6, "side": "right", "cycles": 2}},
        {"motion": "jump", "start_s": 3.5, "params": {"energy": 0.6}},
    ]


def shot_spec(shot_id: str, character: str, background: str, new: bool) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": shot_id,
        "duration_s": SECONDS,
        "background": background,
        "characters": [
            {
                "id": character,
                "position": START,
                "facing": "right",
                "path": PATH,
                "actions": actions(new),
                "expressions": [{"expr": "happy", "start_s": 0.0}],
            }
        ],
        "camera": {"move": "static", "zoom": 1.0},
    }


def measure(view: dict[str, Any], new: bool, character: str) -> dict[str, Any]:
    """The numbers for one version of the shot, from the keyed tracks (no rendering)."""
    n = round(SECONDS * FPS)
    track = placement.frame_positions(START, PATH, FPS, n)
    acts = actions(new)
    walking = placement.walking_frames(acts, FPS, n)
    facings = placement.facing_frames("right", track, walking)
    travel = placement.forward_travel(
        track, facings, width_px=DESIGN.width, height_px=DESIGN.height, scale=1.0
    )
    anim = animate(
        view, acts, fps=FPS, n_frames=n, travel=travel, root_px=Vec(0, 0), seed=character
    )
    bones = [b for b in view["bones"] if b != "torso"] + ["torso"]
    offsets = metrics.frame_offsets(view, anim.clips, n)
    leg = sum(view["bones"][b]["length_px"] for b in ("thigh_l", "shin_l"))
    walk_n = round(PATH[-1]["time_s"] * FPS) + 1
    feet = metrics.foot_tracks(view, anim.clips, n, travel)
    walk_feet = {s: metrics.FootTrack(t.x[:walk_n], t.y[:walk_n]) for s, t in feet.items()}
    retained = {}
    if new:  # how much of the actor's range of motion the puppet kept (1 = all of it)
        for clip_name, track, bone, frames in (
            ("wave", "upper_arm:right", "upper_arm_r", range(46, 80)),
            ("wave", "forearm:right", "forearm_r", range(46, 80)),
        ):
            src = load_clip(clip_name).tracks[track]
            got = [offsets[f][bone] for f in frames]
            retained[f"{clip_name}:{bone}"] = round(
                (max(got) - min(got)) / (max(src) - min(src)), 2
            )
    return {
        "range_kept_vs_source": retained,
        "foot_slide_walk": metrics.foot_slide(walk_feet, leg),
        "accel_peak_deg_per_frame2": round(metrics.accel_peak(offsets, bones), 2),
        "jerk_rms": round(metrics.jerk_rms(offsets, bones), 2),
        "range_deg": {b: round(r) for b, r in metrics.range_of_motion(offsets, bones).items()},
    }


def label(src: Path, text: str, out: Path) -> None:
    """Burn a caption into the corner (this ffmpeg has no drawtext, so overlay a PNG)."""
    png = out.with_suffix(".png")
    img = Image.new("RGBA", (330, 44), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, 329, 43], radius=10, fill=(0, 0, 0, 150))
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 26)
    ImageDraw.Draw(img).text((14, 7), text, font=font, fill=(255, 255, 255, 255))
    img.save(png)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-i",
            str(png),
            "-filter_complex",
            "overlay=20:20",
            "-an",
            str(out),
        ],
        check=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--character", default="kit")
    ap.add_argument("--source", type=Path, default=REPO_ROOT / "films" / "real-15s")
    ap.add_argument("--film", type=Path, default=Path.home() / "ai-studio/scratch/real-motion")
    ap.add_argument("--no-render", action="store_true", help="only print the numbers")
    args = ap.parse_args()

    char_dir = args.source / "characters" / args.character
    view = load_rig(char_dir / "rig.json").view()
    numbers = {
        "old": measure(view, False, args.character),
        "new": measure(view, True, args.character),
    }
    for name, vals in numbers.items():
        print(name, json.dumps(vals))
    clip = load_clip("walk")
    numbers["source_walk"] = {"stride_cycle_U": clip.stride_cycle, **clip.stats}
    args.film.mkdir(parents=True, exist_ok=True)
    (args.film / "compare.json").write_text(json.dumps(numbers, indent=2))
    if args.no_render:
        return 0

    film = args.film / "film"
    shutil.rmtree(film, ignore_errors=True)
    (film / "characters").mkdir(parents=True)
    (film / "characters" / args.character).symlink_to(char_dir.resolve(), target_is_directory=True)
    bg = next((args.source / "backgrounds").iterdir())
    (film / "backgrounds").mkdir()
    (film / "backgrounds" / bg.name).symlink_to(bg.resolve(), target_is_directory=True)
    cfg = load_config()
    clips = {}
    for shot_id, new in (("s01_sh01", False), ("s01_sh02", True)):
        folder = film / "shots" / shot_id
        folder.mkdir(parents=True)
        (folder / "shot.json").write_text(
            json.dumps(shot_spec(shot_id, args.character, bg.name, new), indent=2)
        )
        clips[new] = render_shot(film, shot_id, size=(960, 540), audio=False, cfg=cfg).mp4
        print(f"rendered {shot_id}: {clips[new]}")
    tmp = args.film / "labelled"
    tmp.mkdir(exist_ok=True)
    label(clips[False], "old: hand-keyed", tmp / "old.mp4")
    label(clips[True], "new: real motion", tmp / "new.mp4")
    out = args.film / "compare.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(tmp / "old.mp4"),
            "-i",
            str(tmp / "new.mp4"),
            "-filter_complex",
            "hstack=inputs=2",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],
        check=True,
    )
    shutil.rmtree(tmp)
    print(f"compare: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
