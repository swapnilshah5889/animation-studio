"""Vector shapes: splines (Synfig "blines"), filled regions, stroked outlines, polygons.

A Synfig spline is a list of points, each with two tangents: `t1` arriving and `t2` leaving
(Hermite tangents, in units). Between two points the curve is the cubic Hermite segment, i.e. a
Bezier with control points p0 + t2/3 and p1 - t1/3. Zero tangents give straight lines and sharp
corners. Verified by rendering (synfig-format.md, "Vector shapes").

Helpers build splines so callers rarely touch tangents:
- `smooth(points, closed=...)`: a Catmull-Rom curve through the points (tangent = (next - prev) / 2)
- `ellipse(center, rx, ry)`: 4 points with the quarter-circle tangent 3 · 0.5523 · r ≈ 1.6568 · r
- `arc(start, mid, end)`: an open 3-point curve (brows, closed eyes, mouth lines)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass, field

from studio_core.sif.layers import Layer
from studio_core.sif.values import Animated, Color, Vec, value_xml

CIRCLE_K = 1.6568542  # Hermite tangent for a quarter circle: 3 * 0.5522847 (Bezier kappa)


@dataclass(frozen=True)
class SplinePoint:
    point: Vec
    t_in: Vec = field(default_factory=lambda: Vec(0, 0))  # Synfig t1
    t_out: Vec = field(default_factory=lambda: Vec(0, 0))  # Synfig t2
    width: float = 1.0  # outline width multiplier at this point


@dataclass(frozen=True)
class Spline:
    points: tuple[SplinePoint, ...]
    closed: bool

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError("a spline needs at least 2 points")

    def to_xml(self) -> ET.Element:
        el = ET.Element("bline", type="bline_point", loop="true" if self.closed else "false")
        for p in self.points:
            comp = ET.SubElement(ET.SubElement(el, "entry"), "composite", type="bline_point")
            ET.SubElement(comp, "point").append(value_xml(p.point))
            ET.SubElement(comp, "width").append(value_xml(float(p.width)))
            ET.SubElement(comp, "origin").append(value_xml(0.5))
            ET.SubElement(comp, "split").append(value_xml(True))
            ET.SubElement(comp, "t1").append(value_xml(p.t_in))
            ET.SubElement(comp, "t2").append(value_xml(p.t_out))
            ET.SubElement(comp, "split_radius").append(value_xml(True))
            ET.SubElement(comp, "split_angle").append(value_xml(True))
        return el

    def moved(self, dx: float, dy: float, sx: float = 1.0, sy: float = 1.0) -> Spline:
        """Scale around the origin, then translate (tangents scale too)."""
        return Spline(
            tuple(
                SplinePoint(
                    Vec(p.point.x * sx + dx, p.point.y * sy + dy),
                    Vec(p.t_in.x * sx, p.t_in.y * sy),
                    Vec(p.t_out.x * sx, p.t_out.y * sy),
                    p.width,
                )
                for p in self.points
            ),
            self.closed,
        )


def smooth(points: Sequence[Vec], *, closed: bool, tension: float = 1.0) -> Spline:
    """A Catmull-Rom curve through `points`. tension 0 = straight segments, 1 = Catmull-Rom."""
    n = len(points)
    if n < 2:
        raise ValueError("a spline needs at least 2 points")
    out = []
    for i, p in enumerate(points):
        if closed:
            prev, nxt = points[i - 1], points[(i + 1) % n]
            t = Vec((nxt.x - prev.x) / 2 * tension, (nxt.y - prev.y) / 2 * tension)
        elif i == 0:
            t = Vec((points[1].x - p.x) * tension, (points[1].y - p.y) * tension)
        elif i == n - 1:
            t = Vec((p.x - points[i - 1].x) * tension, (p.y - points[i - 1].y) * tension)
        else:
            prev, nxt = points[i - 1], points[i + 1]
            t = Vec((nxt.x - prev.x) / 2 * tension, (nxt.y - prev.y) / 2 * tension)
        out.append(SplinePoint(p, t, t))
    return Spline(tuple(out), closed)


def ellipse(center: Vec, rx: float, ry: float) -> Spline:
    cx, cy = center.x, center.y
    k = CIRCLE_K
    pts = (
        SplinePoint(Vec(cx + rx, cy), Vec(0, k * ry), Vec(0, k * ry)),
        SplinePoint(Vec(cx, cy + ry), Vec(-k * rx, 0), Vec(-k * rx, 0)),
        SplinePoint(Vec(cx - rx, cy), Vec(0, -k * ry), Vec(0, -k * ry)),
        SplinePoint(Vec(cx, cy - ry), Vec(k * rx, 0), Vec(k * rx, 0)),
    )
    return Spline(pts, closed=True)


def arc(start: Vec, mid: Vec, end: Vec) -> Spline:
    """An open curve from start through mid to end (Catmull-Rom)."""
    return smooth([start, mid, end], closed=False)


@dataclass
class Region(Layer):
    """A filled closed spline."""

    color: Color | Animated = field(default_factory=lambda: Color(0, 0, 0))
    spline: Spline | None = None
    TYPE = "region"
    VERSION = "0.1"

    def params(self) -> dict[str, object]:
        if self.spline is None or not self.spline.closed:
            raise ValueError(f"region {self.desc!r} needs a closed spline")
        return {"color": self.color, "bline": self.spline}


@dataclass
class Outline(Layer):
    """A stroked spline (open or closed) with round tips."""

    color: Color | Animated = field(default_factory=lambda: Color(0, 0, 0))
    spline: Spline | None = None
    width: float = 0.05  # units
    TYPE = "outline"
    VERSION = "0.3"

    def params(self) -> dict[str, object]:
        if self.spline is None:
            raise ValueError(f"outline {self.desc!r} needs a spline")
        return {
            "color": self.color,
            "bline": self.spline,
            "width": float(self.width),
            "sharp_cusps": True,
            "round_tip[0]": True,
            "round_tip[1]": True,
            "homogeneous_width": True,
        }


@dataclass(frozen=True)
class _VectorList:
    points: tuple[Vec, ...]

    def to_xml(self) -> ET.Element:
        el = ET.Element("dynamic_list", type="vector")
        for p in self.points:
            ET.SubElement(el, "entry").append(value_xml(p))
        return el


@dataclass
class Polygon(Layer):
    """A filled polygon with straight edges."""

    color: Color | Animated = field(default_factory=lambda: Color(0, 0, 0))
    points: list[Vec] = field(default_factory=list)
    TYPE = "polygon"
    VERSION = "0.1"

    def params(self) -> dict[str, object]:
        if len(self.points) < 3:
            raise ValueError(f"polygon {self.desc!r} needs at least 3 points")
        return {"color": self.color, "vector_list": _VectorList(tuple(self.points))}
