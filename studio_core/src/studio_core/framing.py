"""Head room and foot room, checked on the bake (engine-neutral, D-098).

The first push-in of Mia cropped her hair and her boots from 4.25 s: the camera keys were chosen
by eye, and no rule looked at the character's bounds. Here the bounds are computed per frame from
the bake (the joint positions every engine receives) and pushed through the camera of that frame,
so a shot that crops the head or the feet fails a test instead of a review.

Boxes are in stage px with y DOWN (the camera's frame); the bake keeps y up, so we flip.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Margins:
    """Free space the character must keep inside the frame, as a share of the frame size."""

    top: float = 0.05  # head room
    bottom: float = 0.04  # foot room
    side: float = 0.03


Box = tuple[float, float, float, float]  # x0, y0, x1, y1 (y down)


def figure_boxes(
    char: dict[str, Any], hair_above_px: float = 24.0, half_w_px: float = 170.0
) -> list[Box]:
    """The character's box in each frame, in stage px: the top of the hair (the head joint plus
    the head bone's length along its direction, plus the curls above it), the lowest sole, and
    the head's width either side of the torso. Arms are left out on purpose: a hand that swings
    past the edge is not a crop."""
    scale = char["scale"]
    heads = [b for b, sp in char["bones"].items() if sp["role"] == "head"]
    from studio_core.motions.gait import foot_bones

    shins = foot_bones(char)
    root = next(b for b, sp in char["bones"].items() if sp["parent"] is None)
    head = heads[0]
    reach = (char["bones"][head]["length_px"] + hair_above_px) * scale
    boxes: list[Box] = []
    for fr in char["frames"]:
        bones = fr["bones"]
        _hx, hy, deg = bones[head]
        top = hy + reach * math.sin(math.radians(deg))  # y up
        soles = [
            bones[s][1]
            + char["bones"][s]["length_px"] * scale * math.sin(math.radians(bones[s][2]))
            for s in shins
        ]
        x = bones[root][0]
        boxes.append(
            (x - half_w_px * scale, top, x + half_w_px * scale, min(soles))
        )  # y up for now
    return boxes


def screen_box(box: Box, cam: tuple[float, float, float], size: tuple[int, int]) -> Box:
    """A stage box (y up, as `figure_boxes` returns it) on screen (px, y down) under the camera
    (zoom, cx, cy) with cx, cy in stage px, y down."""
    zoom, cx, cy = cam
    w, h = size
    x0, ytop, x1, ybot = box
    top, bot = h - ytop, h - ybot  # to y down
    return (
        (x0 - cx) * zoom + w / 2,
        (top - cy) * zoom + h / 2,
        (x1 - cx) * zoom + w / 2,
        (bot - cy) * zoom + h / 2,
    )


def check_framing(
    char: dict[str, Any],
    camera_track: list[list[float]],
    size: tuple[int, int],
    margins: Margins = Margins(),  # noqa: B008
    half_w_px: float = 170.0,
) -> list[dict[str, Any]]:
    """Every frame where the head, the feet or a side of the character is closer to the frame
    edge than the margin (or outside it). [] means the framing holds for the whole shot."""
    w, h = size
    bad = []
    for f, box in enumerate(figure_boxes(char, half_w_px=half_w_px)):
        x0, y0, x1, y1 = screen_box(box, tuple(camera_track[f]), size)  # type: ignore[arg-type]
        problems = []
        if y0 < margins.top * h:
            problems.append(f"head room {y0:.0f} px < {margins.top * h:.0f}")
        if y1 > h - margins.bottom * h:
            problems.append(f"foot room {h - y1:.0f} px < {margins.bottom * h:.0f}")
        if x0 < margins.side * w or x1 > w - margins.side * w:
            problems.append(f"side room {min(x0, w - x1):.0f} px < {margins.side * w:.0f}")
        if problems:
            bad.append({"frame": f, "problems": problems})
    return bad
