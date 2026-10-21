"""Rig model: loading, forward kinematics, bone construction, and a render checked against FK."""

import json
import math
from pathlib import Path

import pytest
from PIL import Image

from studio_core.config import REPO_ROOT, load_config
from studio_core.rig import RigError, build_character, clamp_offset, load_rig, rotate, world_pose
from studio_core.sif import Angle, Animated, Canvas, Color, Interp, Space, Vec, Waypoint
from studio_core.sif.layers import Group, SkeletonLayer
from studio_core.sif.render import render_frames

PIP = REPO_ROOT / "tests" / "fixtures" / "characters" / "pip" / "rig.json"


def test_loads_the_placeholder_rig() -> None:
    rig = load_rig(PIP)
    view = rig.view()
    assert rig.id == "pip" and view["root"] == "torso" and len(view["bones"]) == 10
    with pytest.raises(RigError):
        rig.view("three_quarter")


def test_invalid_rig_and_missing_files_are_rejected(tmp_path: Path) -> None:
    data = json.loads(PIP.read_text())
    (tmp_path / "rig.json").write_text(json.dumps(data))
    with pytest.raises(RigError, match="part files not found"):
        load_rig(tmp_path / "rig.json")  # no parts/ folder next to it
    load_rig(tmp_path / "rig.json", check_files=False)
    data["views"]["front"]["draw_order"].pop()
    (tmp_path / "rig.json").write_text(json.dumps(data))
    with pytest.raises(RigError, match="draw_order"):
        load_rig(tmp_path / "rig.json", check_files=False)


def test_world_pose_rest_and_rotated() -> None:
    view = load_rig(PIP).view()
    rest = world_pose(view)
    assert rest["torso"] == (Vec(0, 0), 90)
    # Shoulder: torso pixel (178, 45) relative to the hips pivot (100, 260), y up.
    assert rest["upper_arm_l"][0] == Vec(78, 215) and rest["upper_arm_l"][1] == -90
    # Elbow hangs 112 px below the shoulder at rest.
    assert rest["forearm_l"][0] == Vec(78, 103)
    # Raise the upper arm 90° CCW: the elbow swings to the right of the shoulder.
    raised = world_pose(view, {"upper_arm_l": 90})
    elbow = raised["forearm_l"][0]
    assert math.isclose(elbow.x, 78 + 112) and math.isclose(elbow.y, 215, abs_tol=1e-9)
    assert raised["forearm_l"][1] == 0  # the forearm inherits the parent's rotation


def test_clamp_offset_uses_limits() -> None:
    view = load_rig(PIP).view()
    assert clamp_offset(view, "head", 40) == 25
    assert clamp_offset(view, "upper_arm_l", -90) == -30
    assert clamp_offset(view, "upper_arm_l", 150) == 150


def test_build_character_bones_and_draw_order() -> None:
    rig = load_rig(PIP)
    built = build_character(
        rig, "front", Space(1920, 1080, 120), file_prefix="../../characters/pip"
    )
    assert (
        len(built.bones) == 10 and built.by_name["forearm_l"].parent is built.by_name["upper_arm_l"]
    )
    # Forearm origin in the upper arm's frame: 112 px along the bone (+x) = 0.9333 units.
    origin = built.by_name["forearm_l"].origin
    assert math.isclose(origin.x, 112 / 120) and math.isclose(origin.y, 0, abs_tol=1e-9)
    names = [c.desc for c in built.group.children]
    assert names[:-1] == rig.view()["draw_order"] and isinstance(
        built.group.children[-1], SkeletonLayer
    )
    with pytest.raises(RigError, match="unknown bones"):
        build_character(rig, None, Space(1920, 1080, 120), file_prefix=".", offsets={"tail": 10.0})


# --------------------------------------------------------------------------- render vs FK

COLORS = {"body": (40, 80, 220), "upper": (220, 40, 40), "lower": (40, 180, 60)}


def synthetic_rig(folder: Path, draw_order: list[str]) -> Path:
    """Solid-colour parts so each part's rendered centroid can be measured."""
    (folder / "parts").mkdir(parents=True)
    sizes = {"body": (80, 160), "upper": (24, 100), "lower": (20, 90)}
    for name, size in sizes.items():
        Image.new("RGBA", size, (*COLORS[name], 255)).save(folder / "parts" / f"{name}.png")
    rig = {
        "schema_version": 1,
        "id": "synth",
        "name": "Synth",
        "default_view": "front",
        "views": {
            "front": {
                "root": "body",
                "bones": {
                    "body": {"parent": None, "direction_deg": 90},
                    "upper": {
                        "parent": "body",
                        "attach": {"part": "body", "at_px": [70, 20]},
                        "direction_deg": -90,
                    },
                    "lower": {
                        "parent": "upper",
                        "attach": {"part": "upper", "at_px": [12, 92]},
                        "direction_deg": -90,
                    },
                },
                "parts": {
                    "body": {
                        "file": "parts/body.png",
                        "size_px": [80, 160],
                        "pivot_px": [40, 150],
                        "bone": "body",
                    },
                    "upper": {
                        "file": "parts/upper.png",
                        "size_px": [24, 100],
                        "pivot_px": [12, 8],
                        "bone": "upper",
                    },
                    "lower": {
                        "file": "parts/lower.png",
                        "size_px": [20, 90],
                        "pivot_px": [10, 6],
                        "bone": "lower",
                    },
                },
                "draw_order": draw_order,
            }
        },
    }
    (folder / "rig.json").write_text(json.dumps(rig))
    return folder / "rig.json"


def centroid(img: Image.Image, rgb: tuple[int, int, int]) -> tuple[float, float]:
    pts = [
        (x, y)
        for y in range(img.height)
        for x in range(img.width)
        if all(abs(a - b) < 40 for a, b in zip(img.getpixel((x, y)), rgb, strict=True))
    ]
    assert pts, f"no {rgb} pixels"
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


@pytest.mark.render
@pytest.mark.skipif(not load_config().path("tools", "synfig").exists(), reason="no synfig CLI")
def test_rendered_parts_land_where_forward_kinematics_predicts(tmp_path: Path) -> None:
    # Overlapping parts would hide pixels and bias the centroid, so render twice and measure only
    # the part drawn on top each time.
    for top in ("upper", "lower"):
        other = "lower" if top == "upper" else "upper"
        rig = load_rig(synthetic_rig(tmp_path / top / "synth", ["body", other, top]))
        view = rig.view()
        poses = [{}, {"body": -10.0, "upper": 120.0, "lower": 45.0}]
        space = Space(500, 500, 1)  # 1 px per unit: art pixels map 1:1 to canvas pixels
        offsets = {
            b: Animated(
                "angle",
                (
                    Waypoint(0, Angle(poses[0].get(b, 0.0)), Interp.LINEAR),
                    Waypoint(1, Angle(poses[1].get(b, 0.0)), Interp.LINEAR),
                ),
            )
            for b in view["bones"]
        }
        built = build_character(rig, None, space, file_prefix="synth", offsets=offsets)
        canvas = Canvas(
            width=500,
            height=500,
            fps=24,
            frames=2,
            ppu=1,
            bgcolor=Color(1, 1, 1),
            layers=[Group("place", children=[built.group])],
            bones=built.bones,
        )
        frames = render_frames(canvas.save(tmp_path / top / "t.sif"), tmp_path / top / "f")
        for frame, pose in zip(frames, poses, strict=True):
            fk = world_pose(view, pose)
            spec = view["parts"][top]
            (w, h), (px, py) = spec["size_px"], spec["pivot_px"]
            joint, direction = fk[spec["bone"]]
            turned = direction - view["bones"][spec["bone"]]["direction_deg"]
            centre = rotate(Vec(w / 2 - px, py - h / 2), turned)  # image centre from the pivot
            expect = (
                250 + joint.x + centre.x,
                250 - (joint.y + centre.y),
            )  # canvas centre (250, 250)
            got = centroid(Image.open(frame).convert("RGB"), COLORS[top])
            assert abs(got[0] - expect[0]) < 1.5 and abs(got[1] - expect[1]) < 1.5, (
                frame.name,
                top,
                got,
                expect,
            )
