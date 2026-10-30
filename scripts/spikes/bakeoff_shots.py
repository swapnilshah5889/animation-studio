"""Engine bake-off: the two benchmark shot specs, written into a scratch film folder.

    uv run --project studio_core python scripts/spikes/bakeoff_shots.py [FILM_DIR]

FILM_DIR (default ~/ai-studio/scratch/engine-bakeoff/film) must hold characters/kit and
characters/mia (with `bendable_limbs`, see `studio_core.engines.limbs`), the `orchard`
background and `audio` (linked from films/real-15s). Shot A: Kit walks in, waves, jumps (5 s,
real mocap clips). Shot B: Mia says one line in a close-up, blinks and turns her head (3 s).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SECONDS_A, SECONDS_B = 5.0, 3.0


def shot_a() -> dict:
    return {
        "schema_version": 1,
        "id": "s01_sh01",
        "duration_s": SECONDS_A,
        "background": "orchard",
        "characters": [
            {
                "id": "kit",
                "position": [0.12, 0.9],
                "facing": "right",
                "path": [{"time_s": 1.9, "position": [0.6, 0.9], "ease": "ease_in_out"}],
                "actions": [
                    {"motion": "blink", "start_s": 0.0, "duration_s": SECONDS_A},
                    {"motion": "idle_breathe", "start_s": 0.0},
                    {
                        "motion": "walk_real",
                        "start_s": 0.0,
                        "duration_s": 1.9,
                        "params": {"energy": 0.6},
                    },
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
                ],
                "expressions": [{"expr": "happy", "start_s": 0.0}],
            }
        ],
        "camera": {"move": "static", "zoom": 1.0},
    }


def shot_b() -> dict:
    return {
        "schema_version": 1,
        "id": "s02_sh01",
        "duration_s": SECONDS_B,
        "background": "orchard",
        "characters": [
            {
                "id": "mia",
                "position": [0.5, 0.97],
                "facing": "right",
                "actions": [
                    {"motion": "blink", "start_s": 0.0, "duration_s": SECONDS_B},
                    {"motion": "idle_breathe", "start_s": 0.0},
                    {"motion": "talk_gesture", "start_s": 0.5, "params": {"energy": 0.5}},
                ],
                # the head turn: eased in to the right, held, eased back
                "poses": [
                    {"time_s": 0.0, "bones": {"head": 0}},
                    {"time_s": 0.9, "bones": {"head": 14}},
                    {"time_s": 1.8, "bones": {"head": 14}},
                    {"time_s": 2.6, "bones": {"head": -6}},
                ],
                "expressions": [{"expr": "happy", "start_s": 0.0}],
            }
        ],
        "dialogue": [
            {
                "character": "mia",
                "line_id": "l002",
                "text": "Let's send it back to the sky!",
                "start_s": 0.5,
            }
        ],
        "camera": {"move": "static", "zoom": 1.7},
    }


def probe_background(film: Path) -> None:
    """A flat magenta background (the pose sweep's probe) so defects can be counted per engine."""
    from PIL import Image

    bg = film / "backgrounds" / "probe"
    (bg / "layers").mkdir(parents=True, exist_ok=True)
    for path in (bg / "layers" / "probe.png", bg / "plate.png"):
        Image.new("RGB", (1920, 1080), (255, 0, 255)).save(path)
    (bg / "layers.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "probe",
                "name": "Probe",
                "size_px": [1920, 1080],
                "backdrop": "#ff00ff",
                "layers": [{"name": "probe", "file": "layers/probe.png", "parallax": 1.0}],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    film = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path.home() / "ai-studio/scratch/engine-bakeoff/film"
    )
    probe_background(film)
    specs = [shot_a(), shot_b()]
    for spec, new_id in ((shot_a(), "s03_sh01"), (shot_b(), "s04_sh01")):  # same shots, magenta
        specs.append({**spec, "id": new_id, "background": "probe"})
    for spec in specs:
        d = film / "shots" / spec["id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "shot.json").write_text(json.dumps(spec, indent=2) + "\n")
        print(d / "shot.json")
