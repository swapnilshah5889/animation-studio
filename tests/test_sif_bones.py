"""The builder's bone output: XML structure, determinism, and a real render checked against FK."""

from pathlib import Path

import pytest
from test_sif_examples import KEYS, predicted_marker_px, white_centroid

from studio_core.config import load_config
from studio_core.sif import (
    Angle,
    Animated,
    Bone,
    BoneLink,
    Canvas,
    Color,
    Group,
    Interp,
    Rectangle,
    SkeletonLayer,
    Vec,
    Waypoint,
)
from studio_core.sif.bones import ROOT_GUID, ordered
from studio_core.sif.render import render_frames


def angles(*keys: tuple[int, float]) -> Animated:
    return Animated("angle", tuple(Waypoint(f, Angle(a), Interp.LINEAR) for f, a in keys))


def arm_canvas() -> Canvas:
    """The same rig as tests/fixtures/sif_examples/bones_arm_minimal.sif, built in Python."""
    upper = Bone(
        "upper_arm",
        origin=Vec(-3, 1),
        angle=angles(*[(f, a) for f, (a, _) in KEYS.items()]),
        length=3,
    )
    fore = Bone(
        "forearm",
        parent=upper,
        origin=Vec(3, 0),
        angle=angles(*[(f, b) for f, (_, b) in KEYS.items()]),
        length=2.5,
    )
    c = Canvas(width=640, height=360, fps=24, frames=48, ppu=40, bgcolor=Color(0.9, 0.9, 0.85))
    c.bones = [fore, upper]  # deliberately out of order: the writer sorts parents first
    c.layers = [
        Group(
            "upper",
            transform=BoneLink(upper),
            children=[
                Rectangle("u", color=Color(1, 0.6, 0), point1=Vec(-0.1, 0.2), point2=Vec(3.1, -0.2))
            ],
        ),
        Group(
            "fore",
            transform=BoneLink(fore),
            children=[
                Rectangle(
                    "f", color=Color(0.1, 0.5, 1), point1=Vec(-0.1, 0.15), point2=Vec(2.5, -0.15)
                ),
                Rectangle(
                    "marker", color=Color(1, 1, 1), point1=Vec(2.5, 0.15), point2=Vec(2.7, -0.15)
                ),
            ],
        ),
        SkeletonLayer("skeleton", bones=[upper, fore]),
    ]
    return c


def test_bones_block_structure_and_determinism() -> None:
    text = arm_canvas().to_string()
    assert text.index("<bones>") < text.index("<layer")  # bones before any layer
    assert f'<bone_root type="bone_object" guid="{ROOT_GUID}" />' in text
    assert text.index("<string>upper_arm</string>") < text.index("<string>forearm</string>")
    assert '<bone_link type="transformation">' in text
    assert 'type="skeleton" active="true" exclude_from_rendering="true"' in text
    assert text == arm_canvas().to_string()


def test_bone_ordering_rejects_foreign_parents() -> None:
    a = Bone("a")
    b = Bone("b", parent=a)
    assert [x.name for x in ordered([b, a])] == ["a", "b"]
    with pytest.raises(ValueError):
        ordered([b])


def test_guids_are_namespaced() -> None:
    assert Bone("arm", namespace="pip").guid != Bone("arm", namespace="bunny").guid
    assert Bone("arm", namespace="pip").guid == Bone("arm", namespace="pip").guid


@pytest.mark.render
@pytest.mark.skipif(not load_config().path("tools", "synfig").exists(), reason="no synfig CLI")
def test_builder_bone_rig_matches_forward_kinematics(tmp_path: Path) -> None:
    frames = render_frames(arm_canvas().save(tmp_path / "arm.sif"), tmp_path / "f")
    for frame in KEYS:
        mx, my = white_centroid(frames[frame])
        px, py = predicted_marker_px(frame)
        assert abs(mx - px) < 1.5 and abs(my - py) < 1.5, (frame, (mx, my), (px, py))
