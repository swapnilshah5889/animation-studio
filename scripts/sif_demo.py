"""Step 1 demo: build a .sif from scratch in Python and render it to MP4.

    uv run scripts/sif_demo.py                # → films/step1-demo/shots/s01_sh01/shot.mp4

A bunny puppet made of PNG parts (tests/fixtures/handmade/parts) waves in front of a panning
background, and its mouth follows the real Rhubarb cues of a Kokoro voice line from Step 0, with
that line as the soundtrack. The output follows the film project folder layout (ARCHITECTURE.md),
under films/ (git-ignored). Safe to re-run.

The rig is nested groups (forward kinematics): each part is drawn with its pivot at its group's
local origin, and each child group's offset is the joint position in the parent's space.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from studio_core.config import REPO_ROOT, load_config
from studio_core.sif import (
    Angle,
    Animated,
    Canvas,
    Color,
    Group,
    ImportLayer,
    Interp,
    Space,
    Switch,
    Transform,
    Vec,
    Waypoint,
    frames,
)
from studio_core.sif.lipsync import load_cues, mouth_track
from studio_core.sif.render import encode_mp4, render_frames

PARTS = REPO_ROOT / "tests" / "fixtures" / "handmade" / "parts"
AUDIO = REPO_ROOT / "tests" / "fixtures" / "audio" / "pip_line_01.wav"
CUES = REPO_ROOT / "tests" / "fixtures" / "audio" / "pip_line_01.rhubarb.json"
FILM = REPO_ROOT / "films" / "step1-demo"
SHOT = FILM / "shots" / "s01_sh01"

FPS, PPU = 24, 120  # 1920x1080 → 16 x 9 units
# Where each part attaches, in its parent's image pixels (rig data; Step 2 moves it to rig.json).
ATTACH = {
    "head": ("torso", (100, 18)),  # neck on top of the torso
    "mouth": ("head", (110, 246)),
    "upper_arm": ("torso", (178, 45)),  # right shoulder
    "forearm": ("upper_arm", (28, 132)),  # elbow
}
# Our placeholder puppet has 3 mouths; every other Rhubarb shape shows the open "E" mouth.
MOUTH_MAP = {"A": "A", "X": "X", **{s: "E" for s in "BCDEFGH"}}


def eased(kind: str, keys: list[tuple[int, object]]) -> Animated:
    return Animated(kind, tuple(Waypoint(f, v, Interp.EASE) for f, v in keys))


def angles(keys: list[tuple[int, float]]) -> Animated:
    return eased("angle", [(f, Angle(a)) for f, a in keys])


def build(parts: dict, n_frames: int, space: Space) -> Canvas:
    def part_layer(name: str, desc: str | None = None) -> ImportLayer:
        meta = parts[name]
        rel = f"../../characters/pip/parts/{meta['file']}"  # relative to the .sif
        return ImportLayer.with_pivot(desc or name, rel, tuple(meta["size"]), meta["pivot"], space)

    def joint(child: str) -> Vec:
        """Child's pivot position in the parent group's units (parent pivot at 0,0; y up)."""
        parent, (ax, ay) = ATTACH[child]
        px, py = parts[parent]["pivot"]
        return Vec(space.length(ax - px), space.length(py - ay))

    mouth = Switch(
        "mouth",
        transform=Transform(offset=joint("mouth")),
        active=mouth_track(load_cues(CUES), FPS, shape_map=MOUTH_MAP),
        children=[part_layer(f"mouth_{s}", desc=s) for s in ("A", "E", "X")],
    )
    head = Group(
        "head",
        transform=Transform(
            offset=joint("head"), angle=angles([(0, 0), (24, 4), (48, -3), (72, 3), (96, 0)])
        ),
        children=[part_layer("head"), mouth],
    )
    forearm = Group(
        "forearm",
        transform=Transform(
            offset=joint("forearm"),
            angle=angles(
                [
                    (0, 0),
                    (36, 0),
                    (44, 30),
                    (52, -20),
                    (60, 30),
                    (68, -20),
                    (76, 30),
                    (84, -20),
                    (92, 30),
                    (108, 0),
                ]
            ),
        ),
        children=[part_layer("forearm")],
    )
    arm = Group(
        "arm",
        transform=Transform(
            offset=joint("upper_arm"),
            angle=angles([(0, 15), (18, 15), (36, 150), (108, 150), (132, 15)]),  # raise, lower
        ),
        children=[part_layer("upper_arm"), forearm],
    )
    hips_x, hips_y = space.to_units(960, 1010)
    puppet = Group(
        "pip",
        transform=Transform(offset=Vec(hips_x, hips_y), scale=Vec(1.5, 1.5)),
        children=[part_layer("torso"), head, arm],  # bottom-first: the arm draws on top
    )

    bg_meta = parts["background"]
    bg_w, bg_h = (space.length(v) for v in bg_meta["size"])
    background = Group(
        "background",
        # 2880 px wide image: slide it from left-aligned to right-aligned over the shot.
        transform=Transform(offset=eased("vector", [(0, Vec(4, 0)), (n_frames - 1, Vec(-4, 0))])),
        children=[
            ImportLayer(
                "background",
                file=f"../../backgrounds/meadow/{bg_meta['file']}",
                tl=Vec(-bg_w / 2, bg_h / 2),
                br=Vec(bg_w / 2, -bg_h / 2),
            )
        ],
    )
    return Canvas(
        width=1920,
        height=1080,
        fps=FPS,
        frames=n_frames,
        ppu=PPU,
        bgcolor=Color(1, 1, 1),
        name="Step 1 demo: Pip waves",
        layers=[background, puppet],
    )


def probe(mp4: Path) -> dict:
    ffprobe = str(load_config().path("tools", "ffprobe"))
    out = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-count_frames",
            "-show_entries",
            "stream=codec_type,width,height,nb_read_frames:format=duration",
            "-of",
            "json",
            str(mp4),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)


def main() -> int:
    parts = json.loads((PARTS / "parts.json").read_text())
    # Film folder layout: characters/<id>/parts, backgrounds/<id>, shots/<id>/scene.sif.
    shutil.rmtree(FILM, ignore_errors=True)
    (FILM / "characters" / "pip" / "parts").mkdir(parents=True)
    (FILM / "backgrounds" / "meadow").mkdir(parents=True)
    for name, meta in parts.items():
        dest = "backgrounds/meadow" if name == "background" else "characters/pip/parts"
        shutil.copy(PARTS / meta["file"], FILM / dest / meta["file"])

    audio_s = 5.6  # pip_line_01.wav; the shot runs 1.4 s longer for the arm to come down
    n_frames = frames(audio_s + 1.4, FPS)
    canvas = build(parts, n_frames, Space(1920, 1080, PPU))
    sif = canvas.save(SHOT / "scene.sif")
    rendered = render_frames(sif, SHOT / "frames")
    mp4 = encode_mp4(SHOT / "frames", SHOT / "shot.mp4", FPS, audio=AUDIO)

    info = probe(mp4)
    streams = {s["codec_type"]: s for s in info["streams"]}
    video = streams["video"]
    assert len(rendered) == n_frames, (len(rendered), n_frames)
    assert int(video["nb_read_frames"]) == n_frames and video["width"] == 1920, video
    assert "audio" in streams, "no audio track"
    assert abs(float(info["format"]["duration"]) - n_frames / FPS) < 0.1, info["format"]
    print(f"OK {mp4.relative_to(REPO_ROOT)}: {n_frames} frames at {FPS} fps, 1920x1080, with audio")
    print(f"   scene: {sif.relative_to(REPO_ROOT)} ({sif.stat().st_size / 1024:.0f} KB of XML)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
