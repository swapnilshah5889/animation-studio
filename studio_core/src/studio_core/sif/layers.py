"""Synfig layers and the canvas document.

Only what the CLI needs is written: no GUIDs, no GUI state. Layer lists are **bottom-first**
(painter's order): later layers draw on top, exactly like the file format.

Group transform semantics (measured by rendering, see docs/learning/synfig-format.md):

    point_in_parent = offset + R(angle) · scale · (point_in_group - origin)

So a part drawn with its pivot at the group's local (0, 0) and `origin = (0, 0)` rotates around
its pivot, and `offset` is where that pivot sits in the parent. That is the convention
`ImportLayer.with_pivot` and nested `Group`s use for cut-out rigs.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from studio_core.sif.units import Space
from studio_core.sif.values import Animated, Color, Transform, Vec, num, value_xml


@dataclass
class Layer:
    desc: str  # the layer's name; Switch layers select children by it
    TYPE = ""
    VERSION = ""

    def params(self) -> dict[str, object]:
        raise NotImplementedError

    def to_xml(self) -> ET.Element:
        el = ET.Element(
            "layer",
            type=self.TYPE,
            active="true",
            exclude_from_rendering="false",
            version=self.VERSION,
            desc=self.desc,
        )
        for name, value in self.params().items():
            param = ET.SubElement(el, "param", name=name)
            if isinstance(value, list):  # a group's inline canvas
                inline = ET.SubElement(param, "canvas")
                for child in value:
                    inline.append(child.to_xml())
            else:
                param.append(value_xml(value))
        return el


@dataclass
class ImportLayer(Layer):
    """A raster image (PNG) placed between its top-left and bottom-right corners, in units."""

    file: str = ""  # path relative to the .sif file
    tl: Vec | Animated = field(default_factory=lambda: Vec(-1, 1))
    br: Vec | Animated = field(default_factory=lambda: Vec(1, -1))
    opacity: float = 1.0
    TYPE = "import"
    VERSION = "0.1"

    @classmethod
    def with_pivot(
        cls,
        desc: str,
        file: str,
        size_px: tuple[int, int],
        pivot_px: tuple[float, float],
        space: Space,
    ) -> ImportLayer:
        """Place an image so its pivot pixel sits at local (0, 0): ready to rotate in a Group."""
        w, h = size_px
        px, py = pivot_px
        tl = Vec(space.length(-px), space.length(py))
        br = Vec(space.length(w - px), space.length(-(h - py)))
        return cls(desc=desc, file=file, tl=tl, br=br)

    def params(self) -> dict[str, object]:
        return {"amount": self.opacity, "tl": self.tl, "br": self.br, "filename": self.file}


@dataclass
class Rectangle(Layer):
    color: Color | Animated = field(default_factory=lambda: Color(1, 1, 1))
    point1: Vec | Animated = field(default_factory=lambda: Vec(-1, 1))
    point2: Vec | Animated = field(default_factory=lambda: Vec(1, -1))
    TYPE = "rectangle"
    VERSION = "0.2"

    def params(self) -> dict[str, object]:
        return {"color": self.color, "point1": self.point1, "point2": self.point2}


@dataclass
class Circle(Layer):
    color: Color | Animated = field(default_factory=lambda: Color(1, 1, 1))
    origin: Vec | Animated = field(default_factory=lambda: Vec(0, 0))
    radius: float | Animated = 1.0
    TYPE = "circle"
    VERSION = "0.2"

    def params(self) -> dict[str, object]:
        return {"color": self.color, "radius": self.radius, "origin": self.origin}


@dataclass
class Group(Layer):
    """Layers moved together: the building block of a cut-out rig (one group per joint)."""

    children: list[Layer] = field(default_factory=list)
    origin: Vec | Animated = field(default_factory=lambda: Vec(0, 0))  # the pivot, local units
    transform: Transform = field(default_factory=Transform)
    TYPE = "group"
    VERSION = "0.3"

    def params(self) -> dict[str, object]:
        return {"origin": self.origin, "transformation": self.transform, "canvas": self.children}


@dataclass
class Switch(Group):
    """Shows only the child whose `desc` equals `active` (e.g. mouth shapes A-H, X)."""

    active: str | Animated = ""
    TYPE = "switch"
    VERSION = "0.0"

    def params(self) -> dict[str, object]:
        return {**super().params(), "layer_name": self.active}


@dataclass
class Canvas:
    """A whole .sif document."""

    width: int
    height: int
    fps: int
    frames: int  # total frame count; frames are 0 .. frames-1
    ppu: float = 60.0
    bgcolor: Color = field(default_factory=lambda: Color(0.5, 0.5, 0.5))
    name: str = "Animation Studio scene"
    layers: list[Layer] = field(default_factory=list)

    @property
    def space(self) -> Space:
        return Space(self.width, self.height, self.ppu)

    def to_xml(self) -> ET.Element:
        if self.frames < 1:
            raise ValueError("a canvas needs at least one frame")
        left, top, right, bottom = self.space.view_box()
        bg = self.bgcolor
        root = ET.Element(
            "canvas",
            version="1.2",
            width=str(self.width),
            height=str(self.height),
            xres="2834.645669",  # 72 dpi in dots per metre; irrelevant for PNG output
            yres="2834.645669",
            **{"view-box": f"{num(left)} {num(top)} {num(right)} {num(bottom)}"},
            antialias="1",
            fps=str(self.fps),
            **{"begin-time": "0f", "end-time": f"{self.frames - 1}f"},
            bgcolor=f"{num(bg.r)} {num(bg.g)} {num(bg.b)} {num(bg.a)}",
        )
        ET.SubElement(root, "name").text = self.name
        for layer in self.layers:
            root.append(layer.to_xml())
        return root

    def to_string(self) -> str:
        root = self.to_xml()
        ET.indent(root, space="  ")
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            + ET.tostring(root, encoding="unicode")
            + "\n"
        )

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_string())
        return path
