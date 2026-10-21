"""Scene layout: camera presets, parallax rates, zoom, backdrop and placement (rendered)."""

import json
from pathlib import Path

import pytest
from PIL import Image
from test_rig import COLORS, synthetic_rig

from studio_core.config import REPO_ROOT, load_config
from studio_core.rig import build_character, ground_offset_px, load_rig
from studio_core.scene import (
    DESIGN,
    PAN_PX,
    PUSH,
    PlacedCharacter,
    SceneError,
    build_scene,
    camera_tracks,
    load_background,
)
from studio_core.sif.render import render_frames

MEADOW = REPO_ROOT / "tests" / "fixtures" / "backgrounds" / "meadow" / "layers.json"
needs_synfig = [
    pytest.mark.render,
    pytest.mark.skipif(not load_config().path("tools", "synfig").exists(), reason="no synfig CLI"),
]


def test_meadow_fixture_loads() -> None:
    bg = load_background(MEADOW)
    assert [l["parallax"] for l in bg.data["layers"]] == [0.05, 0.35, 1.0, 1.4]  # noqa: E741


def test_camera_presets() -> None:
    assert camera_tracks(None, 24, 48).pan is None and camera_tracks(None, 24, 48).zoom == 1.0
    pan = camera_tracks({"move": "slow_pan_right"}, 24, 48).pan
    assert [(w.frame, w.value) for w in pan.waypoints] == [(0, 0.0), (47, float(PAN_PX))]
    left = camera_tracks({"move": "slow_pan_left", "start_s": 1, "duration_s": 1}, 24, 96).pan
    assert [(w.frame, w.value) for w in left.waypoints] == [
        (0, 0.0),
        (24, 0.0),
        (48, -float(PAN_PX)),
    ]
    zoom = camera_tracks({"move": "push_in", "zoom": 1.2}, 24, 48).zoom
    assert [w.value for w in zoom.waypoints] == [1.2, pytest.approx(1.2 * PUSH)]
    with pytest.raises(SceneError, match="unknown camera move"):
        camera_tracks({"move": "dolly_zoom"}, 24, 48)


def stripe_background(folder: Path) -> Path:
    """Transparent layers with one 40 px vertical stripe at the centre, one colour each."""
    (folder / "layers").mkdir(parents=True)
    layers = []
    for name, rgb, factor, front in (
        ("far", (255, 0, 0), 0.0, False),
        ("mid", (0, 0, 255), 0.5, False),
        ("ground", (0, 160, 0), 1.0, False),
        ("near", (255, 0, 255), 1.5, True),
    ):
        img = Image.new("RGBA", (2880, 1080), (0, 0, 0, 0))
        y = {"far": 0, "mid": 270, "ground": 540, "near": 810}[name]
        img.paste((*rgb, 255), (1420, y, 1460, y + 270))  # each in its own band of rows
        img.save(folder / "layers" / f"{name}.png")
        layers.append(
            {"name": name, "file": f"layers/{name}.png", "parallax": factor, "in_front": front}
        )
    data = {
        "schema_version": 1,
        "id": "stripes",
        "size_px": [2880, 1080],
        "backdrop": "#ffffff",
        "layers": layers,
    }
    (folder / "layers.json").write_text(json.dumps(data))
    return folder / "layers.json"


def centroid_x(img: Image.Image, rgb: tuple[int, int, int]) -> float:
    xs = [
        x
        for y in range(img.height)
        for x in range(img.width)
        if all(abs(a - b) < 40 for a, b in zip(img.getpixel((x, y)), rgb, strict=True))
    ]
    assert xs, rgb
    return sum(xs) / len(xs)


@pytest.mark.parametrize("_", [None], ids=["render"])
@pytest.mark.render
@pytest.mark.skipif(not load_config().path("tools", "synfig").exists(), reason="no synfig CLI")
def test_layers_slide_at_their_parallax_rate(tmp_path: Path, _: None) -> None:
    bg = load_background(stripe_background(tmp_path / "bg"))
    canvas = build_scene(
        fps=24,
        n_frames=12,
        background=bg,
        background_prefix="bg",
        characters=[],
        camera={"move": "slow_pan_right"},
    )
    size, scale = (480, 270), 480 / DESIGN.width
    frames = render_frames(canvas.save(tmp_path / "s.sif"), tmp_path / "f", size=size)
    first, last = (Image.open(frames[i]).convert("RGB") for i in (0, -1))
    for rgb, factor in (
        ((255, 0, 0), 0.0),
        ((0, 0, 255), 0.5),
        ((0, 160, 0), 1.0),
        ((255, 0, 255), 1.5),
    ):
        moved = centroid_x(last, rgb) - centroid_x(first, rgb)
        assert abs(moved - (-PAN_PX * factor * scale)) < 1.0, (rgb, moved)


@pytest.mark.render
@pytest.mark.skipif(not load_config().path("tools", "synfig").exists(), reason="no synfig CLI")
def test_push_in_zooms_and_backdrop_fills_the_frame(tmp_path: Path) -> None:
    bg = load_background(stripe_background(tmp_path / "bg"))
    canvas = build_scene(
        fps=24,
        n_frames=12,
        background=bg,
        background_prefix="bg",
        characters=[],
        camera={"move": "push_in"},
    )
    frames = render_frames(canvas.save(tmp_path / "s.sif"), tmp_path / "f", size=(480, 270))

    def width(img: Image.Image) -> int:
        return sum(1 for x in range(img.width) if img.getpixel((x, 100))[:3] == (0, 0, 255))

    first, last = (Image.open(frames[i]).convert("RGB") for i in (0, -1))
    assert abs(width(last) / width(first) - PUSH) < 0.15, (width(first), width(last))

    zoomed_out = build_scene(
        fps=24,
        n_frames=1,
        background=bg,
        background_prefix="bg",
        characters=[],
        camera={"move": "static", "zoom": 0.5},
    )
    frame = render_frames(zoomed_out.save(tmp_path / "z.sif"), tmp_path / "z", size=(240, 135))[0]
    assert Image.open(frame).getchannel("A").getextrema() == (255, 255)  # no transparent pixel


@pytest.mark.render
@pytest.mark.skipif(not load_config().path("tools", "synfig").exists(), reason="no synfig CLI")
def test_characters_stand_at_their_frame_position(tmp_path: Path) -> None:
    bg = load_background(stripe_background(tmp_path / "bg"))
    rig = load_rig(synthetic_rig(tmp_path / "synth", ["upper", "lower", "body"]))  # body on top
    built = build_character(rig, None, DESIGN, file_prefix="synth")
    ground = ground_offset_px(rig.view())
    assert ground == 38  # the hanging forearm reaches 38 px below the root (body bottom: 10 px)
    canvas = build_scene(
        fps=24,
        n_frames=1,
        background=bg,
        background_prefix="bg",
        characters=[PlacedCharacter(built, (0.25, 0.75), scale=2.0, ground_px=ground)],
    )
    img = Image.open(
        render_frames(canvas.save(tmp_path / "c.sif"), tmp_path / "f", size=(480, 270))[0]
    ).convert("RGB")
    # The body part is 80 px wide around the root, scaled 2x then to 480 px: 40 px.
    body_x = centroid_x(img, COLORS["body"])
    assert abs(body_x - 0.25 * 480) < 1.5, body_x
    # The feet (here the lowest part, the forearm) touch the position's y.
    rows = [
        y
        for y in range(img.height)
        for x in range(img.width // 2)  # the character's half, away from the centre stripes
        if all(abs(a - b) < 40 for a, b in zip(img.getpixel((x, y)), COLORS["lower"], strict=True))
    ]
    assert abs(max(rows) + 1 - 0.75 * 270) < 1.5, max(rows)
