"""Joint overlap: draw the pixels that were never drawn, under the neighbour (Step 4B, D-091).

The sheet is one picture: where a thigh passes behind the coat, or an arm lies over the body, the
pixels of the part underneath were never painted. A cut part therefore stops at the edge of what
was visible, and when a joint moves the part behind slides out from under its neighbour and
leaves a hole or a hairline of background. Real mocap bends joints much further than the old
eased clips did, so those slivers block lifelike motion (docs/spikes/joint-overlap.md).

This module grows every part *under* the parts drawn in front of it, around its joints:

- `grow_under`: the hidden zone near a joint (covered at rest by a part in front, never by
  background) is painted from the part's own colours, over a reach that scales with the limb's
  width. At rest the part is hidden there, so the static render does not change; when the joint
  bends, the hidden pixels are what shows.
- `fill_notches`: a rectangular bite in a part's outline that other parts surround (a tail with a
  leg-shaped gap through it, the pixels the leg hid in the sheet) is closed.

Pure numpy; sheet pixel coordinates; no engine-specific data (D-030): the result is just larger
part masks and pixels that `_cut_view` crops into the usual part images.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

from studio_core.puppet.build import _disc, _grow, _shrink, paint_from
from studio_core.puppet.checks import components

REACH = (
    1.35  # of the limb radius: how far around a joint the part behind is drawn under its neighbour
)
NOTCH = 0.025  # of the figure's height: bites in the torso's outline up to this wide are closed
FRONT_MARGIN = (
    2  # px: the zone stays this far inside the front part's edge, so it is never seen at rest
)


def joint_reach(
    bone: str, other: str, bones: dict[str, dict], fits: dict[str, dict], height_px: float
) -> float:
    """Radius (px) around a joint within which the part behind is drawn under its neighbour.
    Scales with the thicker of the two limbs (a stick figure's joint needs less than a coat's)."""
    radii = [fits[b]["radius_px"] for b in (bone, other) if b in fits]
    return REACH * max(radii, default=0.05 * height_px)


def joints_of(bone: str, bones: dict[str, dict]) -> list[tuple[tuple[float, float], str]]:
    """(joint position, neighbouring bone) for each joint a part has: its own and its children's."""
    out = []
    if bones[bone]["parent"] is not None:
        out.append((tuple(bones[bone]["joint_px"]), bones[bone]["parent"]))
    for child, spec in bones.items():
        if spec["parent"] == bone:
            out.append((tuple(spec["joint_px"]), child))
    return out


def _turned(mask: np.ndarray, delta: float, centre: tuple[float, float]) -> np.ndarray:
    """`mask` rotated by `delta` degrees about `centre`, in PIL's sense (as `hang_arms` does)."""
    img = Image.fromarray(mask.astype("uint8") * 255)
    return np.asarray(img.rotate(delta, Image.Resampling.NEAREST, center=centre)) > 127


def _turn_point(at: tuple[float, float], delta: float, centre: tuple[float, float]):
    a = math.radians(delta)
    dx, dy = at[0] - centre[0], at[1] - centre[1]
    # PIL turns counter-clockwise on screen (y down)
    return (
        centre[0] + dx * math.cos(a) + dy * math.sin(a),
        centre[1] - dx * math.sin(a) + dy * math.cos(a),
    )


def grow_under(
    masks: dict[str, np.ndarray],
    pixels: dict[str, np.ndarray],
    bones: dict[str, dict],
    fits: dict[str, dict],
    order: tuple[str, ...],
    height_px: float,
    reach: float | None = None,
    notch: float | None = None,
    opaque: np.ndarray | None = None,
    turn: dict[str, tuple[float, tuple[float, float]]] | None = None,
) -> dict[str, np.ndarray]:
    """Grow each part's mask and pixels under the parts in front of it, around its joints (in
    place). Returns {part: the pixels added}.

    `opaque` (default: everywhere) marks the pixels that fully cover what lies behind them: the
    parts in front only hide a pixel where they are opaque (the figure's antialiased edge ring
    lets what is behind show through).

    `turn` is {part: (degrees, centre)} for parts the rig turns after the cut (`hang_arms`: the
    sheet's A-pose arms rest hanging). What hides what is judged in that turned, rest frame, and
    the growth is turned back into the sheet's."""
    reach = REACH if reach is None else reach
    notch = NOTCH if notch is None else notch
    turn = turn or {}

    def at_rest(name: str, mask: np.ndarray) -> np.ndarray:
        return _turned(mask, *turn[name]) if name in turn else mask

    solid = {n: m if opaque is None else m & opaque for n, m in masks.items()}
    rest_solid = {n: at_rest(n, m) for n, m in solid.items()}
    added: dict[str, np.ndarray] = {}
    for i, name in enumerate(order[:-1]):
        if name not in bones:
            continue
        # at each joint only the part across it hides this one: a shin grown under the other leg
        # would show as a phantom bump when the legs pass (Mia's sweep: holes made, not closed)
        zone = np.zeros_like(masks[name])
        for at, other in joints_of(name, bones):
            if order.index(other) < i:  # the neighbour is behind this part: it hides nothing
                continue
            r = reach / REACH * joint_reach(name, other, bones, fits, height_px)
            child = other if bones[other]["parent"] == name else name
            if bones[child]["parent"] in turn:  # a joint carried round by the turned arm
                at = _turn_point(at, *turn[bones[child]["parent"]])
            zone |= _disc(zone.shape, at, r) & _shrink(rest_solid[other], FRONT_MARGIN)
        zone &= ~at_rest(name, masks[name])
        if name in turn:
            zone = _turned(zone, -turn[name][0], turn[name][1])
        zone &= ~masks[name]
        if not zone.any():
            continue
        pixels[name] = paint_from(pixels[name], masks[name], zone)
        masks[name] = masks[name] | zone
        added[name] = zone
        rest_solid[name] = at_rest(name, solid[name] | zone)
    if "torso" in masks and notch > 0:
        others = np.zeros_like(masks["torso"])
        for other, m in masks.items():
            if other != "torso":
                others |= m
        bite = fill_notches(masks["torso"], others, round(notch * height_px))
        pixels["torso"] = paint_from(pixels["torso"], masks["torso"], bite)
        masks["torso"] = masks["torso"] | bite
        added["torso"] = added.get("torso", np.zeros_like(bite)) | bite
    return added


def fill_notches(mask: np.ndarray, others: np.ndarray, width_px: int) -> np.ndarray:
    """The pixels that close the bites of up to `width_px` in `mask`'s outline (a morphological
    closing, new pixels only) where another part touches the bite.

    The sheet's background key cut a rectangle out of Kit's tail where a leg lay over it: the leg
    hid those pixels in the sheet, so the bite always borders the part that hid it. A bite that
    borders nothing is the character's own shape (a gap in hair, between a tail and a body), and
    closing it would only turn an open gap into an enclosed hole (Mia's, in the first trial)."""
    r = max(width_px // 2, 1)
    bite = _shrink(_grow(mask, r), r) & ~mask
    touching = _grow(others, 2)
    keep = np.zeros_like(bite)
    for piece in components(bite):
        if (piece & touching).any():
            keep |= piece
    return keep
