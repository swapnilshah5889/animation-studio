"""Typed Synfig parameter values and their XML.

Every parameter in a .sif file is either a static value (`<real value="1.5"/>`) or an
`<animated>` node holding waypoints. Python types map to Synfig types:

    float → <real>      int → <integer>    bool → <bool>     str → <string>
    Vec   → <vector>    Color → <color>    Angle → <angle>
    Transform → <composite type="transformation">       Animated → <animated type="...">
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import StrEnum

from studio_core.sif.units import frame_time


class Interp(StrEnum):
    """Interpolation names as written in the file (the GUI shows different labels)."""

    EASE = "halt"  # GUI: "Ease In/Out"
    LINEAR = "linear"
    CLAMPED = "clamped"  # GUI default: smooth, no overshoot
    CONSTANT = "constant"  # step; the only one valid for strings and bools
    TCB = "auto"  # GUI: "TCB" smooth spline


def num(value: float) -> str:
    """Deterministic float text: fixed 6 decimals, no negative zero."""
    text = f"{value:.6f}"
    return "0.000000" if text == "-0.000000" else text


@dataclass(frozen=True)
class Vec:
    x: float
    y: float


@dataclass(frozen=True)
class Color:
    r: float
    g: float
    b: float
    a: float = 1.0

    @classmethod
    def hex(cls, value: str) -> Color:
        """'#88c8f0' → Color. Synfig colors are linear 0..1 floats."""
        h = value.lstrip("#")
        r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
        return cls(r, g, b)


@dataclass(frozen=True)
class Angle:
    degrees: float  # counter-clockwise, y up


@dataclass(frozen=True)
class Waypoint:
    frame: int
    value: object
    interp: Interp = Interp.CLAMPED  # used for both "before" and "after"


@dataclass(frozen=True)
class Animated:
    """A parameter that changes over time. `kind` is the Synfig type name (vector, angle, ...)."""

    kind: str
    waypoints: tuple[Waypoint, ...]

    def __post_init__(self) -> None:
        frames_ = [w.frame for w in self.waypoints]
        if not frames_:
            raise ValueError("an animated value needs at least one waypoint")
        if frames_ != sorted(set(frames_)):
            raise ValueError(f"waypoint frames must be strictly increasing: {frames_}")
        if self.kind in ("string", "bool") and any(
            w.interp is not Interp.CONSTANT for w in self.waypoints
        ):
            raise ValueError(f"{self.kind} values can only use constant interpolation")


@dataclass(frozen=True)
class Transform:
    """A group's transformation: where its origin lands in the parent, rotation, skew, scale."""

    offset: Vec | Animated = field(default_factory=lambda: Vec(0, 0))
    angle: Angle | Animated = field(default_factory=lambda: Angle(0))
    skew: Angle | Animated = field(default_factory=lambda: Angle(0))
    scale: Vec | Animated = field(default_factory=lambda: Vec(1, 1))


def value_xml(value: object) -> ET.Element:
    """Build the XML element for one value (static or animated)."""
    if isinstance(value, Animated):
        el = ET.Element("animated", type=value.kind)
        for wp in value.waypoints:
            w = ET.SubElement(
                el, "waypoint", time=frame_time(wp.frame), before=wp.interp, after=wp.interp
            )
            w.append(value_xml(wp.value))
        return el
    if isinstance(value, bool):  # before int: bool is an int subclass
        return ET.Element("bool", value="true" if value else "false")
    if isinstance(value, int):
        return ET.Element("integer", value=str(value))
    if isinstance(value, float):
        return ET.Element("real", value=num(value))
    if isinstance(value, str):
        el = ET.Element("string")
        el.text = value
        return el
    if isinstance(value, Vec):
        el = ET.Element("vector")
        ET.SubElement(el, "x").text = num(value.x)
        ET.SubElement(el, "y").text = num(value.y)
        return el
    if isinstance(value, Color):
        el = ET.Element("color")
        for channel in ("r", "g", "b", "a"):
            ET.SubElement(el, channel).text = num(getattr(value, channel))
        return el
    if isinstance(value, Angle):
        return ET.Element("angle", value=num(value.degrees))
    if isinstance(value, Transform):
        el = ET.Element("composite", type="transformation")
        for name, part in (
            ("offset", value.offset),
            ("angle", value.angle),
            ("skew_angle", value.skew),
            ("scale", value.scale),
        ):
            ET.SubElement(el, name).append(value_xml(part))
        return el
    raise TypeError(f"no Synfig type for {type(value).__name__}: {value!r}")
