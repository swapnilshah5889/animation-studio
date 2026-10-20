"""A minimal, typed builder for Synfig `.sif` files (Step 1).

    from studio_core.sif import Canvas, Group, ImportLayer, Transform, Vec, Angle, Animated, ...

    canvas = Canvas(width=1920, height=1080, fps=24, frames=240, ppu=120)
    canvas.layers.append(Group("arm", children=[...], transform=Transform(angle=Animated(...))))
    canvas.save(Path("scene.sif"))     # then: synfig scene.sif -t png -o frames/f.png

Format notes: docs/learning/synfig-format.md. Rendering: studio_core.sif.render.
"""

from studio_core.sif.layers import Canvas, Circle, Group, ImportLayer, Layer, Rectangle, Switch
from studio_core.sif.units import Space, frame_time, frames
from studio_core.sif.values import (
    Angle,
    Animated,
    Color,
    Interp,
    Transform,
    Vec,
    Waypoint,
    value_xml,
)

__all__ = [
    "Angle",
    "Animated",
    "Canvas",
    "Circle",
    "Color",
    "Group",
    "ImportLayer",
    "Interp",
    "Layer",
    "Rectangle",
    "Space",
    "Switch",
    "Transform",
    "Vec",
    "Waypoint",
    "frame_time",
    "frames",
    "value_xml",
]
