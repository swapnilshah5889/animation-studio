"""Procedural face: structure, tracks, attachment to the head bone, and renders."""

from pathlib import Path

import pytest
from PIL import Image

from studio_core.config import REPO_ROOT, load_config
from studio_core.face import (
    EXPRESSIONS,
    EYE_STATES,
    MOUTHS,
    FaceGeometry,
    blink_track,
    face_attachments,
    face_layers,
)
from studio_core.rig import RigError, build_character, load_rig, rotate
from studio_core.sif import (
    Angle,
    Animated,
    Canvas,
    Group,
    Interp,
    Space,
    Switch,
    Transform,
    Vec,
    Waypoint,
)
from studio_core.sif.bones import BoneLink
from studio_core.sif.render import render_frames

PIP = REPO_ROOT / "tests" / "fixtures" / "characters" / "pip" / "rig.json"
SPACE = Space(1920, 1080, 60)


def test_anchors_are_in_the_head_frame() -> None:
    g = FaceGeometry.from_view(load_rig(PIP).view(), SPACE)
    # Head pivot (110, 285); left eye at pixel (141, 196) -> 31 px right, 89 px up.
    assert g.eye_l == Vec(31 / 60, 89 / 60) and g.eye_r == Vec(-31 / 60, 89 / 60)
    assert g.mouth == Vec(0, 37 / 60) and g.mouth_w == 1.0


def test_switch_structure() -> None:
    layers = face_layers(load_rig(PIP).view(), SPACE)
    assert [layer.desc for layer in layers] == ["eye_l", "eye_r", "brows", "mouth"]
    eye, brows, mouth = layers[0], layers[2], layers[3]
    assert [c.desc for c in eye.children] == list(EYE_STATES)
    assert [c.desc for c in brows.children] == list(EXPRESSIONS)
    assert [c.desc for c in mouth.children] == list(MOUTHS)
    rest = mouth.children[-1]
    assert isinstance(rest, Switch) and [c.desc for c in rest.children] == list(EXPRESSIONS)


def test_unknown_states_are_rejected() -> None:
    view = load_rig(PIP).view()
    with pytest.raises(ValueError, match="unknown expression"):
        face_layers(view, SPACE, expression="angry")
    with pytest.raises(ValueError, match="unknown mouth shape"):
        face_layers(view, SPACE, mouth=Animated("string", (Waypoint(0, "Q", Interp.CONSTANT),)))


def test_blink_track() -> None:
    keys = [(w.frame, w.value) for w in blink_track([10, 40]).waypoints]
    assert keys[:5] == [(0, "open"), (10, "half"), (11, "closed"), (12, "half"), (13, "open")]
    assert keys[-1] == (43, "open")
    with pytest.raises(ValueError, match="overlaps"):
        blink_track([10, 12])


def test_attachments_follow_the_head_bone() -> None:
    rig = load_rig(PIP)
    view = rig.view()
    built = build_character(
        rig, None, SPACE, file_prefix=".", attachments=face_attachments(view, SPACE)
    )
    names = [c.desc for c in built.group.children]
    head_at = names.index("head")
    assert names[head_at + 1] == "head attachments"
    head_group, face_group = built.group.children[head_at], built.group.children[head_at + 1]
    assert (
        isinstance(face_group.transform, BoneLink) and face_group.transform == head_group.transform
    )
    with pytest.raises(RigError, match="attachments for unknown parts"):
        build_character(rig, None, SPACE, file_prefix=".", attachments={"tail": []})


MOUTH_RGB = (0x78, 0x28, 0x3A)


def dark_red(img: Image.Image) -> list[tuple[int, int]]:
    # A tight tolerance matters: antialiased edges of the dark line art elsewhere on the body
    # come within ~25 of this colour and would drag the centroid off the head.
    return [
        (x, y)
        for y in range(img.height)
        for x in range(img.width)
        if all(abs(a - b) < 10 for a, b in zip(img.getpixel((x, y)), MOUTH_RGB, strict=True))
    ]


@pytest.mark.render
@pytest.mark.skipif(not load_config().path("tools", "synfig").exists(), reason="no synfig CLI")
def test_rendered_face_turns_with_the_head_and_mouths_differ(tmp_path: Path) -> None:
    rig = load_rig(PIP)
    view = rig.view()
    folder = tmp_path / "pip"
    folder.mkdir()
    for f in rig.folder.glob("**/*.png"):
        (folder / f.relative_to(rig.folder)).parent.mkdir(parents=True, exist_ok=True)
        (folder / f.relative_to(rig.folder)).write_bytes(f.read_bytes())
    space = Space(500, 700, 60)  # 1 art px = 1 canvas px
    mouth = Animated(
        "string", (Waypoint(0, "D", Interp.CONSTANT), Waypoint(2, "A", Interp.CONSTANT))
    )
    head = Animated(
        "angle", (Waypoint(0, Angle(0), Interp.CONSTANT), Waypoint(1, Angle(20), Interp.CONSTANT))
    )
    built = build_character(
        rig,
        None,
        space,
        file_prefix="pip",
        offsets={"head": head},
        attachments=face_attachments(view, space, mouth=mouth),
    )
    hips = (250, 650)  # canvas pixels
    place = Group(
        "place",
        transform=Transform(offset=Vec((hips[0] - 250) / 60, (350 - hips[1]) / 60)),
        children=[built.group],
    )
    canvas = Canvas(
        width=500, height=700, fps=24, frames=3, ppu=60, layers=[place], bones=built.bones
    )
    frames = [
        Image.open(f).convert("RGB")
        for f in render_frames(canvas.save(tmp_path / "f.sif"), tmp_path / "out")
    ]

    wide, turned, closed = (dark_red(f) for f in frames)
    assert len(wide) > 400 and len(closed) < 0.1 * len(wide), (len(wide), len(closed))

    # The mouth is rigid on the head: rotating the head 20° about the neck rotates its centroid.
    neck = (hips[0] + 0, hips[1] - 242)
    c0 = (sum(p[0] for p in wide) / len(wide), sum(p[1] for p in wide) / len(wide))
    rel = rotate(Vec(c0[0] - neck[0], neck[1] - c0[1]), 20)  # y up for the rotation
    expect = (neck[0] + rel.x, neck[1] - rel.y)
    c1 = (sum(p[0] for p in turned) / len(turned), sum(p[1] for p in turned) / len(turned))
    assert abs(c1[0] - expect[0]) < 1.5 and abs(c1[1] - expect[1]) < 1.5, (c1, expect)
