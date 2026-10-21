"""Vector shapes: spline XML and tangent maths, and renders measured in pixels."""

import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image

from studio_core.config import load_config
from studio_core.sif import (
    Canvas,
    Color,
    Outline,
    Polygon,
    Region,
    Vec,
    arc,
    ellipse,
    smooth,
)
from studio_core.sif.render import render_frames
from studio_core.sif.shapes import CIRCLE_K


def test_smooth_tangents_are_catmull_rom() -> None:
    s = smooth([Vec(0, 0), Vec(1, 1), Vec(2, 0)], closed=False)
    assert [p.t_out for p in s.points] == [Vec(1, 1), Vec(1, 0), Vec(1, -1)]
    flat = smooth([Vec(0, 0), Vec(1, 1), Vec(2, 0)], closed=False, tension=0)
    assert all(p.t_in == Vec(0, 0) for p in flat.points)  # straight segments
    loop = smooth([Vec(1, 0), Vec(0, 1), Vec(-1, 0), Vec(0, -1)], closed=True)
    assert loop.points[0].t_out == Vec(0, 1)  # (next - prev) / 2, wrapping around


def test_ellipse_points_and_tangents() -> None:
    e = ellipse(Vec(2, 1), 3, 1)
    assert [p.point for p in e.points] == [Vec(5, 1), Vec(2, 2), Vec(-1, 1), Vec(2, 0)]
    assert e.points[0].t_out == Vec(0, CIRCLE_K * 1) and e.points[1].t_out == Vec(-CIRCLE_K * 3, 0)
    assert e.closed


def test_spline_xml() -> None:
    xml = ET.tostring(arc(Vec(-1, 0), Vec(0, 1), Vec(1, 0)).to_xml(), encoding="unicode")
    assert xml.startswith(
        '<bline type="bline_point" loop="false"><entry><composite type="bline_point">'
    )
    assert xml.count("<entry>") == 3 and "<t1><vector>" in xml and "<split_angle><bool" in xml


def test_shape_layers_validate_their_input() -> None:
    with pytest.raises(ValueError):
        Region("r", spline=arc(Vec(0, 0), Vec(1, 1), Vec(2, 0))).to_xml()  # open spline
    with pytest.raises(ValueError):
        Polygon("p", points=[Vec(0, 0), Vec(1, 0)]).to_xml()
    with pytest.raises(ValueError):
        smooth([Vec(0, 0)], closed=False)


def coverage(img: Image.Image, box: tuple[int, int, int, int]) -> float:
    """Exact covered area in pixels inside `box`. Synfig renders the canvas background as
    transparent (bgcolor does not paint the PNG), so alpha = antialiased coverage."""
    x0, y0, x1, y1 = box
    alpha = img.getchannel("A")
    return sum(alpha.getpixel((x, y)) / 255 for y in range(y0, y1) for x in range(x0, x1))


def count(img: Image.Image, rgb: tuple[int, int, int]) -> list[tuple[int, int]]:
    return [
        (x, y)
        for y in range(img.height)
        for x in range(img.width)
        if all(abs(a - b) < 60 for a, b in zip(img.getpixel((x, y)), rgb, strict=True))
    ]


@pytest.mark.render
@pytest.mark.skipif(not load_config().path("tools", "synfig").exists(), reason="no synfig CLI")
def test_rendered_shapes_have_the_right_size_and_place(tmp_path: Path) -> None:
    ppu = 40  # 400x300 canvas, view -5..5 x 3.75..-3.75
    c = Canvas(width=400, height=300, fps=24, frames=1, ppu=ppu, bgcolor=Color(1, 1, 1))
    c.layers = [
        Region("ellipse", color=Color(1, 0, 0), spline=ellipse(Vec(-2, 0), 1.5, 1.0)),
        Polygon("triangle", color=Color(0, 0, 1), points=[Vec(1, -1), Vec(4, -1), Vec(1, 2)]),
        Outline(
            "arc",
            color=Color(0, 0.6, 0),
            spline=arc(Vec(-3, -2.5), Vec(-2, -1.5), Vec(-1, -2.5)),
            width=0.1,
        ),
    ]
    rgba = Image.open(render_frames(c.save(tmp_path / "s.sif"), tmp_path / "f")[0]).convert("RGBA")
    img = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba).convert("RGB")

    # Ellipse: centre unit (-2, 0), radii 1.5 x 1 -> px box x 60..180, y 110..190.
    area = coverage(rgba, (50, 100, 190, 200))
    expected = math.pi * 1.5 * 1.0 * ppu**2
    assert abs(area - expected) / expected < 0.01, (area, expected)
    red = count(img, (255, 0, 0))
    cx = sum(p[0] for p in red) / len(red)
    assert abs(cx - (200 - 2 * ppu - 0.5)) < 1  # centred at unit x = -2

    # Triangle (1,-1) (4,-1) (1,2) -> px x 240..360, y 70..190.
    tri_area = coverage(rgba, (230, 60, 370, 200))
    tri = 0.5 * 3 * 3 * ppu**2
    assert abs(tri_area - tri) / tri < 0.01, (tri_area, tri)

    green = count(img, (0, 153, 0))
    top = min(p[1] for p in green)  # the arc's highest point passes through unit y = -1.5
    assert abs(top - (150 + 1.5 * ppu - 0.05 * ppu)) < 2.5, top
