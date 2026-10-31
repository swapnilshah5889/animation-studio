# ruff: noqa: E501
"""Spike D-097: a head turn moves the whole head. A 3 s test: Mia stands, looks left, right, back.

    uv run --project studio_core python scripts/spikes/rigged_turn_test.py WORK_DIR

Writes WORK_DIR/turn_test.mp4 (silent, 1080p) and turn_sheet.png (12 frames of the head and
shoulders). Reuses the plate and compositor of rigged_character_test.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import rigged_character_test as rct  # noqa: E402

from studio_core.engines.bake import FPS, bake_shot  # noqa: E402
from studio_core.engines.blender.launch import render  # noqa: E402
from studio_core.engines.face_sprite import write_sprites  # noqa: E402

SECONDS = 3.0
N = round(SECONDS * FPS)
CAM = {"move": "track", "keys": [{"time_s": 0.0, "zoom": 1.3, "cx": 806, "cy": 640}]}


def spec() -> dict:
    s = rct.shot_spec(CAM)
    s["duration_s"] = SECONDS
    ch = s["characters"][0]
    ch["position"] = [0.42, 0.92]
    ch.pop("path")
    ch["actions"] = [
        {"motion": "blink", "start_s": 0.0, "duration_s": SECONDS},
        {"motion": "idle_breathe", "start_s": 0.0},
    ]
    ch["expressions"] = [{"expr": "happy", "start_s": 0.0}]
    ch["look"] = [
        {"time_s": 0.0, "yaw": 0.0},
        {"time_s": 0.2, "yaw": 0.0},
        {"time_s": 0.8, "yaw": -0.9},
        {"time_s": 1.2, "yaw": -0.9},
        {"time_s": 2.0, "yaw": 0.9},
        {"time_s": 2.35, "yaw": 0.9},
        {"time_s": 2.9, "yaw": 0.0},
    ]
    ch["poses"] = [{"time_s": 0.0, "bones": {"head": 0}}, {"time_s": 2.9, "bones": {"head": 0}}]
    s["dialogue"] = []
    return s


def main() -> None:
    work = (
        Path(sys.argv[1]).expanduser()
        if len(sys.argv) > 1
        else Path.home() / "ai-studio/scratch/rigged-character-test"
    )
    work.mkdir(parents=True, exist_ok=True)
    film = rct.setup_film(work)
    bake = bake_shot(film, spec())
    base = work / "turn"
    base.mkdir(exist_ok=True)
    write_sprites(bake, base / "sprites")
    (base / "bake.json").write_text(json.dumps(bake))
    print(
        render(
            base / "bake.json", base / "frames", engine="EEVEE", size=f"{rct.W}x{rct.H}", samples=8
        )
    )
    layers = rct.make_layers()
    out = base / "final"
    out.mkdir(exist_ok=True)
    for f in range(N):
        rct.composite(
            layers,
            base / "frames" / f"{f:04d}.png",
            tuple(bake["camera_track"][f]),
            rct.foot_px(bake, f),
        ).save(out / f"{f:04d}.png")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(FPS),
            "-i",
            str(out / "%04d.png"),
            "-c:v",
            "libx264",
            "-crf",
            "17",
            "-pix_fmt",
            "yuv420p",
            str(work / "turn_test.mp4"),
        ],
        check=True,
    )
    yaws = [fr["face"]["yaw"] for fr in bake["characters"][0]["frames"]]
    picks = [round(i * (N - 1) / 11) for i in range(12)]
    tw, th = 480, 540
    sheet = Image.new("RGB", (tw * 6, th * 2), "white")
    for i, f in enumerate(picks):
        im = Image.open(out / f"{f:04d}.png")
        crop = im.crop((420, 80, 420 + 960, 80 + 1080)).resize((tw, th), Image.LANCZOS)
        sheet.paste(crop, ((i % 6) * tw, (i // 6) * th))
    sheet.save(work / "turn_sheet.png")
    (work / "turn_sheet_times.txt").write_text(
        "\n".join(f"frame {i + 1}: {f / FPS:.2f}s yaw {yaws[f]:+.2f}" for i, f in enumerate(picks))
    )


if __name__ == "__main__":
    main()
