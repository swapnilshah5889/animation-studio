"""Swappable hand poses, drawn in code (spike docs/spikes/hand-poses.md, approach C).

A rig view may carry `hands` (rig.schema.json): per forearm bone, the poses it has, the wrist, the
hand's width and the fill/outline colours. Each drawn pose is a mitten-like cartoon hand of
vector shapes (the same Region/Outline helpers the face uses), drawn in the forearm part's local
frame and linked to the forearm bone, so it follows the arm. The poses are one switch per hand,
driven over time like the mouth:

- `rest`: the hand as cut (nothing is drawn: the end of the forearm image shows)
- `fist`, `point`, `open`, `wave`: drawn over the end of the forearm image

The cut hand's pixels are part of the forearm image and cannot be taken out of it, so a drawn
pose is drawn on top. A pose is narrower than the cut hand (a fist, a point's wrist), so the rig
stores the cut hand's outline (`cover_px`, a convex hull measured from the image) and every pose
is drawn on a backing of it, in the hand's fill and outline: no cut-hand pixel peeks out.

Shapes are built in a canonical hand frame (origin at the wrist, +x along the arm outward, +y
toward the thumb, units of the hand width `s`) and then turned into the part frame by the bone's
rest direction. The thumb sits on the side of the body.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

from studio_core.rig import Rig, rotate, world_pose
from studio_core.sif import (
    Animated,
    Color,
    Group,
    Interp,
    Layer,
    Outline,
    Region,
    Space,
    Switch,
    Vec,
    Waypoint,
    smooth,
)

HAND_POSES = ("rest", "fist", "point", "open", "wave")
DRAWN = tuple(p for p in HAND_POSES if p != "rest")
WAVE_TILT_DEG = 14.0  # the waving hand is the open hand tipped about the wrist
OUTLINE = 0.06  # outline width, in hand widths
DEFAULT_LINE = "#463430"  # the face's default line colour (face.DEFAULT_COLORS)

Pt = tuple[float, float]


@dataclass(frozen=True)
class Blob:
    cx: float
    cy: float
    rx: float
    ry: float


@dataclass(frozen=True)
class Stroke:
    a: Pt
    b: Pt
    w: float


@dataclass(frozen=True)
class Shape:
    """A pose: a silhouette (blobs and thick strokes drawn as one outlined shape) plus creases,
    all in hand widths in the canonical frame."""

    body: tuple[Blob | Stroke, ...]
    creases: tuple[Stroke, ...] = ()
    tilt_deg: float = 0.0


def _finger(base: Pt, angle_deg: float, length: float, w: float) -> Stroke:
    a = math.radians(angle_deg)
    return Stroke(base, (base[0] + length * math.cos(a), base[1] + length * math.sin(a)), w)


def _open_body() -> tuple[Blob | Stroke, ...]:
    fingers = [(-0.33, -28, 0.55), (-0.11, -9, 0.68), (0.11, 9, 0.66), (0.33, 26, 0.5)]
    return (
        Blob(0.5, 0.0, 0.5, 0.5),
        *(_finger((0.85, y), ang, ln, 0.2) for y, ang, ln in fingers),
        _finger((0.4, 0.4), 62, 0.5, 0.22),  # the thumb
    )


SHAPES: dict[str, Shape] = {
    "fist": Shape(
        body=(
            Blob(0.5, 0.0, 0.58, 0.5),
            Stroke((0.3, 0.4), (0.85, 0.34), 0.26),  # the thumb folded across
        ),
        creases=(  # finger lines on the knuckle side
            Stroke((0.6, -0.22), (1.02, -0.22), 0.05),
            Stroke((0.6, -0.02), (1.05, -0.02), 0.05),
            Stroke((0.6, 0.17), (1.0, 0.17), 0.05),
        ),
    ),
    "point": Shape(
        body=(
            Blob(0.4, 0.0, 0.45, 0.42),
            Stroke((0.7, -0.04), (1.7, 0.0), 0.24),  # the index finger
            Stroke((0.3, 0.38), (0.7, 0.3), 0.22),  # the thumb, along the palm
        ),
        creases=(
            Stroke((0.6, -0.22), (0.92, -0.22), 0.05),
            Stroke((0.6, -0.34), (0.86, -0.34), 0.05),
        ),
    ),
    "open": Shape(body=_open_body()),
    "wave": Shape(body=_open_body(), tilt_deg=WAVE_TILT_DEG),
}


@dataclass(frozen=True)
class HandGeometry:
    """One hand in the forearm part's local frame (units, pivot at 0,0, y up)."""

    wrist: Vec
    size: float  # hand width, units
    direction_deg: float  # the forearm bone's rest direction: where the fingers point at rest
    mirror: bool  # thumb on the other side (the arm on the character's other side)
    poses: tuple[str, ...]
    fill: Color
    outline: Color
    cover: tuple[Vec, ...] = ()  # the cut hand's outline in the part's frame (units)

    @classmethod
    def from_view(cls, view: dict[str, Any], bone: str, space: Space) -> HandGeometry:
        hand = view.get("hands", {}).get(bone)
        if hand is None:
            raise ValueError(
                f"forearm {bone!r} has no hands; it has {sorted(view.get('hands', {}))}"
            )
        part = view["parts"][hand["part"]]
        px, py = part["pivot_px"]
        wx, wy = hand["wrist_px"]
        direction = float(view["bones"][bone]["direction_deg"])
        # The thumb goes toward the body: compare the wrist with the root, in the rest pose.
        rest = world_pose(view)
        wrist_world = rest[bone][0]
        inward_x = -math.copysign(1.0, wrist_world.x - rest[view["root"]][0].x or 1.0)
        thumb_x = rotate(Vec(0, 1), direction).x
        mirror = thumb_x * inward_x < -1e-6
        colors = view.get("face", {}).get("colors", {})
        return cls(
            wrist=Vec(space.length(wx - px), space.length(py - wy)),
            size=space.length(hand["size_px"]),
            direction_deg=direction,
            mirror=mirror,
            poses=tuple(hand["poses"]),
            fill=Color.hex(hand["fill"]),
            outline=Color.hex(hand.get("outline") or colors.get("line", DEFAULT_LINE)),
            cover=tuple(
                Vec(space.length(cx - px), space.length(py - cy))
                for cx, cy in hand.get("cover_px", [])
            ),
        )

    def to_part(self, p: Pt, tilt_deg: float = 0.0) -> Vec:
        """A canonical point (hand widths) → the part's local frame (units)."""
        x, y = p[0] * self.size, p[1] * self.size
        if self.mirror:
            y = -y
        turn = self.direction_deg + (-tilt_deg if self.mirror else tilt_deg)
        v = rotate(Vec(x, y), turn)
        return Vec(self.wrist.x + v.x, self.wrist.y + v.y)


def _ring(g: HandGeometry, b: Blob, grow: float, tilt: float, n: int = 14) -> list[Vec]:
    return [
        g.to_part(
            (
                b.cx + (b.rx + grow) * math.cos(2 * math.pi * i / n),
                b.cy + (b.ry + grow) * math.sin(2 * math.pi * i / n),
            ),
            tilt,
        )
        for i in range(n)
    ]


def _body_layers(g: HandGeometry, shape: Shape, color: Color, grow: float, tag: str) -> list[Layer]:
    out: list[Layer] = []
    for item in shape.body:
        if isinstance(item, Blob):
            out.append(
                Region(
                    tag,
                    color=color,
                    spline=smooth(_ring(g, item, grow, shape.tilt_deg), closed=True),
                )
            )
        else:
            pts = [g.to_part(item.a, shape.tilt_deg), g.to_part(item.b, shape.tilt_deg)]
            width = (item.w + 2 * grow) * g.size
            out.append(Outline(tag, color=color, width=width, spline=smooth(pts, closed=False)))
    return out


def _backing(g: HandGeometry, color: Color, grow: float, tag: str) -> list[Layer]:
    """The cut hand's outline as a flat-sided shape, `grow` hand widths bigger all round: it
    hides the cut hand under any pose."""
    if not g.cover:
        return []
    cx = sum(p.x for p in g.cover) / len(g.cover)
    cy = sum(p.y for p in g.cover) / len(g.cover)
    pts = []
    for p in g.cover:
        dx, dy = p.x - cx, p.y - cy
        d = math.hypot(dx, dy) or 1.0
        k = 1 + grow * g.size / d
        pts.append(Vec(cx + dx * k, cy + dy * k))
    return [Region(tag, color=color, spline=smooth(pts, closed=True, tension=0.0))]


def pose_layers(g: HandGeometry, pose: str) -> list[Layer]:
    """The vector shapes of one drawn pose: an outline pass, a fill pass over it (so fingers
    merge into one outlined silhouette), then the finger lines."""
    shape = SHAPES[pose]
    layers = _backing(g, g.outline, OUTLINE, "outline")
    layers += _body_layers(g, shape, g.outline, OUTLINE, "outline")
    layers += _backing(g, g.fill, 0.0, "fill")
    layers += _body_layers(g, shape, g.fill, 0.0, "fill")
    for c in shape.creases:
        pts = [g.to_part(c.a, shape.tilt_deg), g.to_part(c.b, shape.tilt_deg)]
        layers.append(
            Outline("crease", color=g.outline, width=c.w * g.size, spline=smooth(pts, closed=False))
        )
    return layers


def hand_switch(g: HandGeometry, bone: str, active: str | Animated) -> Switch:
    """The switch for one hand: a child per pose it has (`rest` is empty)."""
    states = [active] if isinstance(active, str) else [w.value for w in active.waypoints]
    bad = sorted({s for s in states if s not in g.poses})
    if bad:
        raise ValueError(f"{bone} has no hand pose {bad}; it has {list(g.poses)}")
    children = [
        Group(p, children=[] if p == "rest" else pose_layers(g, p))
        for p in HAND_POSES
        if p in g.poses
    ]
    return Switch(f"hand {bone}", active=active, children=children)


def hand_track(keys: list[tuple[int, str]]) -> str | Animated:
    """Hand-pose changes as a constant-key switch track ('rest' from frame 0 until the first)."""
    by_frame = {0: "rest"}
    by_frame.update(dict(keys))
    waypoints: list[Waypoint] = []
    for f in sorted(by_frame):
        if waypoints and waypoints[-1].value == by_frame[f]:
            continue
        waypoints.append(Waypoint(f, by_frame[f], Interp.CONSTANT))
    if len(waypoints) == 1:
        return waypoints[0].value  # type: ignore[return-value]
    return Animated("string", tuple(waypoints))


def hand_attachments(
    view: dict[str, Any], space: Space, tracks: dict[str, str | Animated] | None = None
) -> dict[str, list[Layer]]:
    """`{forearm part: [hand switch]}` for `build_character(attachments=...)`; `tracks` maps a
    forearm bone to its pose track (a hand without one stays `rest`). {} when the view has no
    hands, or when no hand ever leaves `rest` (the render is then exactly the plain one)."""
    tracks = tracks or {}
    out: dict[str, list[Layer]] = {}
    for bone, hand in view.get("hands", {}).items():
        track = tracks.get(bone, "rest")
        if track == "rest":
            continue
        g = HandGeometry.from_view(view, bone, space)
        out.setdefault(hand["part"], []).append(hand_switch(g, bone, track))
    return out


def merge_attachments(*sets: dict[str, list[Layer]] | None) -> dict[str, list[Layer]] | None:
    """Combine attachment dicts (face, hands) part by part; None when there are none."""
    merged: dict[str, list[Layer]] = {}
    for one in sets:
        for part, layers in (one or {}).items():
            merged.setdefault(part, []).extend(layers)
    return merged or None


def hand_bone(view: dict[str, Any], side: str) -> str | None:
    """The forearm bone with hands on the character's `side`, or None."""
    for bone in view.get("hands", {}):
        if view["bones"][bone].get("side") == side:
            return bone
    return None


# --------------------------------------------------------------------------- adding hands


@dataclass(frozen=True)
class CutHand:
    wrist: Pt  # pixels
    width: float  # pixels
    fill: str  # hex: the median of the hand's interior (no outline or edge pixels)
    edge: str | None  # hex: the darkest of the hand's edge pixels (its own outline), if it has one
    cover: tuple[Pt, ...]  # pixels: a flat-sided shape that contains every pixel of the hand


def _hex(rgb: np.ndarray) -> str:
    r, g, b = (int(v) for v in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _hull(points: np.ndarray) -> list[Pt]:
    """Convex hull (monotone chain) of an (n, 2) array."""
    pts = sorted({(float(x), float(y)) for x, y in points})
    if len(pts) < 3:
        return pts

    def half(seq: list[Pt]) -> list[Pt]:
        out: list[Pt] = []
        for q in seq:
            while len(out) >= 2 and (
                (out[-1][0] - out[-2][0]) * (q[1] - out[-2][1])
                - (out[-1][1] - out[-2][1]) * (q[0] - out[-2][0])
                <= 0
            ):
                out.pop()
            out.append(q)
        return out[:-1]

    return half(pts) + half(pts[::-1])


def measure_cut_hand(path: Path, direction_deg: float) -> CutHand:
    """Wrist, width, colours and outline of the cut hand at the far end of a forearm image, whose
    bone points along `direction_deg`. The hand is the last 12% of the opaque pixels along that
    axis; its width is their mean width. Its fill is the median colour of the pixels that are not
    near the edge (so the outline does not darken it); its `edge` is the darkest 30% of the edge
    pixels; `cover` is the hull of every opaque pixel beyond the wrist, grown to a coarse grid."""
    rgba = np.array(Image.open(path).convert("RGBA"))
    opaque = rgba[..., 3] > 20
    ys, xs = np.nonzero(opaque)
    if len(xs) == 0:
        raise ValueError(f"{path} has no opaque pixels")
    d = np.array([math.cos(math.radians(direction_deg)), -math.sin(math.radians(direction_deg))])
    t = xs * d[0] + ys * d[1]
    lo, tip = float(t.min()), float(np.percentile(t, 99.8))
    band = (t >= tip - 0.12 * (tip - lo)) & (t <= tip)
    thickness = max(1.0, float(t[band].max() - t[band].min()) + 1.0)
    width = float(band.sum()) / thickness
    centre = np.array([xs[band].mean(), ys[band].mean()])
    wrist_t = tip - 0.95 * width
    wrist = centre + d * (wrist_t - float(t[band].mean()))
    h, w = rgba.shape[:2]
    wrist = (float(np.clip(wrist[0], 0, w)), float(np.clip(wrist[1], 0, h)))

    mask = Image.fromarray(opaque.astype(np.uint8) * 255)

    def eroded(radius: int) -> np.ndarray:
        return np.array(mask.filter(ImageFilter.MinFilter(2 * radius + 1))) > 0

    in_band = np.zeros_like(opaque)
    in_band[ys[band], xs[band]] = True
    inner = in_band & eroded(max(1, round(0.2 * width)))
    if inner.sum() < 30:  # a tiny hand: the whole band
        inner = in_band
    fill = _hex(np.median(rgba[inner][..., :3], axis=0))
    ring = in_band & ~eroded(max(1, round(0.08 * width))) & (rgba[..., 3] > 200)
    edge = None
    if ring.sum() >= 20:
        px = rgba[ring][..., :3].astype(float)
        dark = px[np.argsort(px @ [0.3, 0.59, 0.11])[: max(10, int(0.3 * len(px)))]]
        edge = _hex(np.median(dark, axis=0))

    beyond = t >= wrist_t
    cell = max(1.0, width / 10)
    cells = np.unique(np.stack([xs[beyond] // cell, ys[beyond] // cell], axis=1), axis=0)
    corners = [
        ((cx + dx) * cell, (cy + dy) * cell) for cx, cy in cells for dx in (0, 1) for dy in (0, 1)
    ]
    cover = tuple(_hull(np.array(corners))) if len(cells) else ()
    return CutHand(wrist, width, fill, edge, cover)


def measure_hand(path: Path, direction_deg: float) -> tuple[Pt, float, str]:
    """Wrist (pixels), hand width (pixels) and fill colour (hex) of the cut hand."""
    c = measure_cut_hand(path, direction_deg)
    return c.wrist, c.width, c.fill


def colour_distance(a: str, b: str) -> float:
    """Euclidean distance between two hex colours, in 0-255 RGB steps."""
    return math.dist(
        tuple(int(a[i : i + 2], 16) for i in (1, 3, 5)),
        tuple(int(b[i : i + 2], 16) for i in (1, 3, 5)),
    )


OUTLINE_SWAP = 60.0  # the cut hand's own edge replaces the face line colour when this far from it


def hand_outline(edge: str | None, line: str, fill: str) -> str | None:
    """The outline colour to store for a hand, or None to use the face's line colour: the cut
    hand's own dark edge when it is far from the line colour (the line would show as a halo on
    it) and visibly different from the fill (otherwise the hand has no outline to match)."""
    if edge is None or colour_distance(edge, fill) < 25:
        return None
    return edge if colour_distance(edge, line) > OUTLINE_SWAP else None


def add_hands(rig: Rig, poses: tuple[str, ...] = HAND_POSES) -> dict[str, Any]:
    """A copy of the rig's data with `hands` on every view's forearms (opt-in: build_puppet does
    not call this). Wrist, width, colours and the cut hand's outline come from the forearm image's
    hand end; the outline colour is the face's line colour unless the cut hand's own edge is far
    from it (`hand_outline`). Returns the data; validating and writing it is the caller's."""
    data = copy.deepcopy(rig.data)
    for view in data["views"].values():
        hands = {}
        for bone, spec in view["bones"].items():
            if spec.get("role", bone[:-2] if bone.endswith(("_l", "_r")) else bone) != "forearm":
                continue
            part_name = next((n for n, p in view["parts"].items() if p["bone"] == bone), None)
            if part_name is None:
                continue
            part = view["parts"][part_name]
            cut = measure_cut_hand(rig.folder / part["file"], spec["direction_deg"])
            hands[bone] = {
                "part": part_name,
                "wrist_px": [round(cut.wrist[0], 1), round(cut.wrist[1], 1)],
                "size_px": round(cut.width, 1),
                "poses": list(poses),
                "fill": cut.fill,
            }
            if cut.cover:
                hands[bone]["cover_px"] = [[round(x, 1), round(y, 1)] for x, y in cut.cover]
            line = view.get("face", {}).get("colors", {}).get("line", DEFAULT_LINE)
            outline = hand_outline(cut.edge, line, cut.fill)
            if outline:
                hands[bone]["outline"] = outline
        if hands:
            view["hands"] = hands
    return data
