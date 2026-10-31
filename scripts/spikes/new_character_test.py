"""The same 6 s shot on a ready-made cast (D-100): Kenney "Toon Characters 1", through Blender.

    DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run --project studio_core --with cairosvg \
        python scripts/spikes/new_character_test.py [work_dir] [--character "Female person"] [--tag blender]

Builds the rig from the SVG (puppet/kenney.py), bakes a walk-in, a stop and a wave, a talking
pose and a push-in (the camera must pass framing.py), swaps the head (expression heads) and the
lifted leg (`legBend`) per frame, renders with the Blender harness and composites the 2.5D plate
(reused from rigged_character_test.py, Mia's spike) and a soft shadow. Re-run safe.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import rigged_character_test as rct  # noqa: E402  (the plate, shadow, compositor, mux)

from studio_core.engines.bake import bake_shot  # noqa: E402
from studio_core.engines.blender.launch import render  # noqa: E402
from studio_core.framing import check_framing  # noqa: E402
from studio_core.motions.gait import foot_report  # noqa: E402
from studio_core.puppet.kenney import build_kenney_puppet  # noqa: E402

SRC = Path(os.path.expanduser("~/ai-studio/assets/kenney-toon-characters-1/src"))
W, H, N, FPS = rct.W, rct.H, rct.N, rct.FPS
SCALE = 0.6  # the figure is 94 units high at 12 px per unit: 0.6 gives about 675 px
HALF_W = 330.0  # the head's half width in rig px (53 units wide at 12 px per unit)

CAM = {
    "move": "track",
    "keys": [
        {"time_s": 0.0, "zoom": 1.0, "cx": 860, "cy": 540},
        {"time_s": 2.4, "zoom": 1.08, "cx": 830, "cy": 600},
        {"time_s": 3.8, "zoom": 1.25, "cx": 806, "cy": 625},
        {"time_s": 6.0, "zoom": 1.28, "cx": 806, "cy": 628},
    ],
}
HEADS = [  # (from s, head image): the expression heads are drawn art, swapped per frame
    (0.0, "head"),
    (1.7, "headShock"),  # a surprised hello as the wave starts
    (2.4, "head"),
    # (the 'headFocus' head read as grumpy while talking in the first review: the default head)
]


def shot_spec(cid: str) -> dict:
    return {
        "schema_version": 1,
        "id": "new_character_test",
        "duration_s": rct.SECONDS,
        "background": "plate",
        "transparent": True,
        "smooth": {},
        "characters": [
            {
                "id": cid,
                "scale": SCALE,
                "position": [0.10, 0.92],
                "facing": "right",
                "path": [{"time_s": 1.7, "position": [0.42, 0.92], "ease": "ease_in_out"}],
                "actions": [
                    {"motion": "idle_breathe", "start_s": 0.0},
                    {
                        "motion": "walk_step",
                        "start_s": 0.0,
                        "duration_s": 1.7,
                        "params": {"energy": 0.9, "lift": 1.5},
                    },
                    {
                        "motion": "wave",
                        "start_s": 1.8,
                        "params": {"energy": 0.6, "side": "right"},
                    },
                    {"motion": "talk_gesture", "start_s": 3.6, "params": {"energy": 0.45}},
                    {"motion": "head_tilt", "start_s": 4.4, "params": {"energy": 0.4}},
                ],
            }
        ],
        "dialogue": [],
        "camera": CAM,
    }


def swap_variants(bake: dict, rig_dir: Path) -> None:
    """Per-frame texture swaps: the expression head, and the bent leg while a foot is lifted."""
    ch = bake["characters"][0]
    variants = json.loads((rig_dir / "variants.json").read_text())
    base = rig_dir
    rest = ch["rest"]
    for f, fr in enumerate(ch["frames"]):
        t = f / FPS
        head = [h for s, h in HEADS if s <= t][-1]
        swaps = {}
        if head != "head":
            swaps["head"] = str(base / variants[head])
        if 2.0 <= t < 3.4:  # the waving hand is open (drawn by code), not the mitten
            swaps["hand_r"] = str(base / variants["handOpen_mirror"])
        root = fr["bones"]["torso"]
        for tag, mirror in (("l", ""), ("r", "_mirror")):
            b = f"thigh_{tag}"
            lift = (fr["bones"][b][1] - root[1]) - (rest[b][1] - rest["torso"][1]) * ch["scale"]
            if lift > 8:  # the lifted leg bends (the drawn knee), not a straight tube
                swaps[b] = str(base / variants["legBend" + mirror])
        if swaps:
            fr["part_images"] = swaps


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "work", type=Path, nargs="?", default=Path.home() / "ai-studio/scratch/new-character-test"
    )
    ap.add_argument("--character", default="Female person")
    ap.add_argument("--tag", default="blender")
    ap.add_argument("--skip-render", action="store_true")
    a = ap.parse_args()
    work = a.work.expanduser()
    cid = a.character.lower().replace(" ", "_")
    film = work / "film"
    rig_dir = film / "characters" / cid
    build_kenney_puppet(SRC / a.character, rig_dir, name=cid)
    audio = film / "audio"
    if not audio.exists():
        audio.symlink_to(rct.REPO_ROOT / "films/real-15s/audio", target_is_directory=True)
    bake = bake_shot(film, shot_spec(cid))
    swap_variants(bake, rig_dir)
    ch = bake["characters"][0]
    print(
        "framing problems:", check_framing(ch, bake["camera_track"], (W, H), half_w_px=HALF_W)[:3]
    )
    print("feet:", foot_report(ch, H - 0.92 * H))
    (work / f"bake_{a.tag}.json").write_text(json.dumps(bake))
    frames = work / f"frames_{a.tag}"
    if not a.skip_render:
        print(
            render(work / f"bake_{a.tag}.json", frames, engine="EEVEE", size=f"{W}x{H}", samples=8)
        )
    rct.SCALE = 0.95  # the shadow's width
    layers = rct.make_layers()
    out = work / f"final_{a.tag}"
    out.mkdir(exist_ok=True)
    for f in range(N):
        cam = tuple(bake["camera_track"][f])
        rct.composite(layers, frames / f"{f:04d}.png", cam, rct.foot_px(bake, f)).save(
            out / f"{f:04d}.png"
        )
    rct.mux(work, out, a.tag)
    print("wrote", work / f"clip_{a.tag}.mp4")


if __name__ == "__main__":
    main()
