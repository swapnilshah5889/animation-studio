"""Step 1 demo: build a .sif from scratch in Python and render it to MP4.

    uv run scripts/sif_demo.py                # both rigs → films/step1-demo/shots/s01_sh01_*/
    uv run scripts/sif_demo.py --rig bones    # just one: groups | bones | both

A bunny puppet made of PNG parts (tests/fixtures/handmade/parts) waves in front of a panning
background, and its mouth follows the real Rhubarb cues of a Kokoro voice line from Step 0, with
that line as the soundtrack. The output follows the film project folder layout (ARCHITECTURE.md),
under films/ (git-ignored). Safe to re-run.

The same puppet and timeline are rigged two ways, and the renders are compared pixel by pixel:

- groups: nested groups (forward kinematics). Each part is drawn with its pivot at its group's
  local origin; each child group's offset is the joint position in the parent's space.
- bones: a Synfig skeleton (torso → head, torso → upper arm → forearm). Each part is a flat group
  whose transformation is a bone_link; `base` turns the art so it lies along the bone's +x.
  Scene-level placement (where the puppet stands, the background pan) stays groups.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from studio_core.config import REPO_ROOT, load_config
from studio_core.sif import (
    Angle,
    Animated,
    Bone,
    BoneLink,
    Canvas,
    Color,
    Group,
    ImportLayer,
    Interp,
    Layer,
    SkeletonLayer,
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
SHOTS = FILM / "shots"

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


# The animation, as angles relative to the parent part (identical for both rigs).
HEAD_NOD = [(0, 0), (24, 4), (48, -3), (72, 3), (96, 0)]
ARM_RAISE = [(0, 15), (18, 15), (36, 150), (108, 150), (132, 15)]  # 0 = hanging straight down
FOREARM_WAVE = [
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
PUPPET_SCALE = 1.5
HIPS_PX = (960, 1010)


def rotate(v: Vec, degrees: float) -> Vec:
    r = math.radians(degrees)
    return Vec(v.x * math.cos(r) - v.y * math.sin(r), v.x * math.sin(r) + v.y * math.cos(r))


class Puppet:
    """Shared helpers: part layers and joint offsets in each part's image frame (units, y up)."""

    def __init__(self, parts: dict, space: Space) -> None:
        self.parts, self.space = parts, space

    def layer(self, name: str, desc: str | None = None) -> ImportLayer:
        meta = self.parts[name]
        rel = f"../../characters/pip/parts/{meta['file']}"  # relative to the .sif
        return ImportLayer.with_pivot(
            desc or name, rel, tuple(meta["size"]), meta["pivot"], self.space
        )

    def joint(self, child: str) -> Vec:
        """The child's pivot relative to its parent's pivot, in the parent's image frame."""
        parent, (ax, ay) = ATTACH[child]
        px, py = self.parts[parent]["pivot"]
        return Vec(self.space.length(ax - px), self.space.length(py - ay))

    def mouth_parts(self) -> list[Layer]:
        return [self.layer(f"mouth_{s}", desc=s) for s in ("A", "E", "X")]


def build_groups(pup: Puppet) -> Layer:
    mouth = Switch(
        "mouth",
        transform=Transform(offset=pup.joint("mouth")),
        active=mouth_track(load_cues(CUES), FPS, shape_map=MOUTH_MAP),
        children=pup.mouth_parts(),
    )
    head = Group(
        "head",
        transform=Transform(offset=pup.joint("head"), angle=angles(HEAD_NOD)),
        children=[pup.layer("head"), mouth],
    )
    forearm = Group(
        "forearm",
        transform=Transform(offset=pup.joint("forearm"), angle=angles(FOREARM_WAVE)),
        children=[pup.layer("forearm")],
    )
    arm = Group(
        "arm",
        transform=Transform(offset=pup.joint("upper_arm"), angle=angles(ARM_RAISE)),
        children=[pup.layer("upper_arm"), forearm],
    )
    return Group("pip-rig", children=[pup.layer("torso"), head, arm])  # arm draws on top


# How each part's art is turned to lie along its bone's +x: torso, head and mouth art point up
# from their pivot (-90°), arm art hangs down (+90°). `base` rotates image frame -> bone frame.
ART_TO_BONE = {"torso": -90.0, "head": -90.0, "mouth": -90.0, "upper_arm": 90.0, "forearm": 90.0}


def build_bones(pup: Puppet) -> tuple[Layer, list[Bone]]:
    def origin(child: str) -> Vec:
        """Joint offset expressed in the parent bone's frame."""
        parent = ATTACH[child][0]
        return rotate(pup.joint(child), ART_TO_BONE[parent])

    def rel(keys: list[tuple[int, float]], offset: float) -> Animated:
        return angles([(f, a + offset) for f, a in keys])

    # Bone world angle = parent's + relative angle. Torso points up (90°). The upper arm's world
    # direction is the art's hanging direction rotated by the animation (-90 + a), so relative to
    # the torso it is a - 180. Head and forearm share their parent's art orientation: offset 0.
    torso = Bone("torso", angle=Angle(90), length=pup.space.length(260), namespace="pip")
    head = Bone(
        "head",
        parent=torso,
        origin=origin("head"),
        angle=rel(HEAD_NOD, 0),
        length=pup.space.length(285),
        namespace="pip",
    )
    upper = Bone(
        "upper_arm",
        parent=torso,
        origin=origin("upper_arm"),
        angle=rel(ARM_RAISE, -180),
        length=pup.space.length(112),
        namespace="pip",
    )
    fore = Bone(
        "forearm",
        parent=upper,
        origin=origin("forearm"),
        angle=rel(FOREARM_WAVE, 0),
        length=pup.space.length(132),
        namespace="pip",
    )

    def linked(name: str, bone: Bone, children: list[Layer], offset: Vec | None = None) -> Group:
        base = Transform(offset=offset or Vec(0, 0), angle=Angle(ART_TO_BONE[name]))
        return Group(name, transform=BoneLink(bone, base), children=children)

    mouth = Switch(
        "mouth",
        transform=BoneLink(
            head, Transform(offset=origin("mouth"), angle=Angle(ART_TO_BONE["mouth"]))
        ),
        active=mouth_track(load_cues(CUES), FPS, shape_map=MOUTH_MAP),
        children=pup.mouth_parts(),
    )
    bones = [torso, head, upper, fore]
    rig = Group(
        "pip-rig",
        # Flat siblings: draw order is free, independent of the bone hierarchy.
        children=[
            linked("torso", torso, [pup.layer("torso")]),
            linked("head", head, [pup.layer("head")]),
            mouth,
            linked("upper_arm", upper, [pup.layer("upper_arm")]),
            linked("forearm", fore, [pup.layer("forearm")]),
            SkeletonLayer("pip skeleton", bones=bones),  # GUI handles only, not rendered
        ],
    )
    return rig, bones


def build(parts: dict, n_frames: int, space: Space, rig_kind: str) -> Canvas:
    pup = Puppet(parts, space)
    bones: list[Bone] = []
    if rig_kind == "groups":
        rig = build_groups(pup)
    else:
        rig, bones = build_bones(pup)
    hips_x, hips_y = space.to_units(*HIPS_PX)
    puppet = Group(  # scene-level placement stays a plain group in both variants
        "pip",
        transform=Transform(offset=Vec(hips_x, hips_y), scale=Vec(PUPPET_SCALE, PUPPET_SCALE)),
        children=[rig],
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
        name=f"Step 1 demo: Pip waves ({rig_kind} rig)",
        layers=[background, puppet],
        bones=bones,
    )


def psnr(a: Path, b: Path) -> float:
    """Peak signal-to-noise ratio between two frames (inf = identical, >40 dB = invisible)."""
    diff = ImageChops.difference(Image.open(a).convert("RGB"), Image.open(b).convert("RGB"))
    mse = sum(v**2 for v in ImageStat.Stat(diff).rms) / 3
    return math.inf if mse == 0 else 10 * math.log10(255**2 / mse)


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rig", choices=["groups", "bones", "both"], default="both")
    args = parser.parse_args()
    kinds = ["groups", "bones"] if args.rig == "both" else [args.rig]

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
    renders: dict[str, list[Path]] = {}
    for kind in kinds:
        shot = SHOTS / f"s01_sh01_{kind}"
        sif = build(parts, n_frames, Space(1920, 1080, PPU), kind).save(shot / "scene.sif")
        renders[kind] = render_frames(sif, shot / "frames")
        mp4 = encode_mp4(shot / "frames", shot / "shot.mp4", FPS, audio=AUDIO)

        info = probe(mp4)
        streams = {s["codec_type"]: s for s in info["streams"]}
        video = streams["video"]
        assert len(renders[kind]) == n_frames, (len(renders[kind]), n_frames)
        assert int(video["nb_read_frames"]) == n_frames and video["width"] == 1920, video
        assert "audio" in streams, "no audio track"
        assert abs(float(info["format"]["duration"]) - n_frames / FPS) < 0.1, info["format"]
        size_kb = sif.stat().st_size / 1024
        print(
            f"OK {kind:6s} {mp4.relative_to(REPO_ROOT)}: {n_frames} frames, 1920x1080, audio; "
            f"scene.sif {size_kb:.0f} KB"
        )

    if len(renders) == 2:
        scores = [psnr(renders["groups"][f], renders["bones"][f]) for f in range(0, n_frames, 12)]
        worst = min(scores)
        print(
            f"groups vs bones, every 12th frame: worst PSNR {worst:.1f} dB "
            f"({sum(math.isinf(x) for x in scores)}/{len(scores)} frames pixel-identical)"
        )
        assert worst > 40, "the two rigs should render the same animation"
    return 0


if __name__ == "__main__":
    sys.exit(main())
