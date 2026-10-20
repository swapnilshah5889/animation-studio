"""Render tests: run the real Synfig CLI and measure pixels. Marked `render` (a few seconds)."""

import shutil
from pathlib import Path

import pytest
from PIL import Image

from studio_core.config import load_config
from studio_core.sif import (
    Angle,
    Animated,
    Canvas,
    Circle,
    Color,
    Group,
    Interp,
    Rectangle,
    Switch,
    Transform,
    Vec,
    Waypoint,
)
from studio_core.sif.render import render_frames

pytestmark = [
    pytest.mark.render,
    pytest.mark.skipif(not load_config().path("tools", "synfig").exists(), reason="no synfig CLI"),
]
RED, BLUE, GREEN = Color(1, 0, 0), Color(0, 0, 1), Color(0, 1, 0)


def centroid(path: Path, color: tuple[int, int, int]) -> tuple[float, float]:
    im = Image.open(path).convert("RGB")
    pts = [
        (x, y)
        for y in range(im.height)
        for x in range(im.width)
        if all(abs(a - b) < 60 for a, b in zip(im.getpixel((x, y)), color, strict=True))
    ]
    assert pts, f"no pixels of {color} in {path.name}"
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def test_group_rotates_around_its_pivot_and_switch_changes(tmp_path: Path) -> None:
    c = Canvas(width=320, height=180, fps=24, frames=24, ppu=40, bgcolor=Color(1, 1, 1))
    angle = Animated("angle", (Waypoint(0, Angle(0), Interp.EASE), Waypoint(23, Angle(90))))
    c.layers.append(
        Group(
            "arm",
            transform=Transform(offset=Vec(-1, 0), angle=angle),
            children=[Rectangle("bone", color=RED, point1=Vec(1.8, 0.1), point2=Vec(2.2, -0.1))],
        )
    )
    active = Animated(
        "string", (Waypoint(0, "A", Interp.CONSTANT), Waypoint(12, "B", Interp.CONSTANT))
    )
    c.layers.append(
        Switch(
            "mouth",
            active=active,
            children=[
                Circle("A", color=BLUE, origin=Vec(2.5, 1.5), radius=0.3),
                Circle("B", color=GREEN, origin=Vec(2.5, 1.5), radius=0.3),
            ],
        )
    )
    frames = render_frames(c.save(tmp_path / "t.sif"), tmp_path / "frames")
    assert len(frames) == 24
    # Frame 0: the red block sits 2 units right of the pivot (-1, 0) -> unit (1, 0) -> px (200, 90).
    x0, y0 = centroid(frames[0], (255, 0, 0))
    assert abs(x0 - 200) < 2 and abs(y0 - 90) < 2
    # Last frame: rotated 90° counter-clockwise around the pivot -> unit (-1, 2) -> px (120, 10).
    x1, y1 = centroid(frames[23], (255, 0, 0))
    assert abs(x1 - 120) < 2 and abs(y1 - 10) < 2
    # The switch shows A before frame 12 and B from frame 12 on.
    centroid(frames[11], (0, 0, 255))
    centroid(frames[12], (0, 255, 0))
    shutil.rmtree(tmp_path / "frames")
