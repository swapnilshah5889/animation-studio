"""Procedural vector face (D-007): eyes that blink, brows per expression, Rhubarb mouths.

Everything is drawn in code from the rig's face anchors (rig.json `face`), in the head part's
local frame (pivot at 0,0, y up, units), and handed to `build_character(attachments=...)`, which
links it to the head bone so the face turns with the head.

Three switches drive it:
- `eye_l` / `eye_r`: open, half, closed (blinks: `blink_track`)
- `brows`: one brow pair per expression
- `mouth`: Rhubarb shapes A-H and X. X (rest) is itself a switch on the expression, so a sad
  character frowns between lines instead of smiling.

Shapes follow Rhubarb's mouth guide: A closed (M, B, P), B slightly open with clenched teeth
(K, S, T, EE), C open (EH, AE), D wide open (AA), E slightly rounded (AO, ER), F puckered (UW, OW,
W), G upper teeth on the lower lip (F, V), H tongue raised (L), X rest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from studio_core.sif import (
    Animated,
    Circle,
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
    arc,
    ellipse,
    smooth,
)

EXPRESSIONS = ("neutral", "happy", "sad", "surprised", "grumpy", "worried")
EYE_STATES = ("open", "half", "closed")
MOUTHS = ("A", "B", "C", "D", "E", "F", "G", "H", "X")

# Brow shape per expression, in eye heights: (raise, inner_drop, arch). inner_drop > 0 lowers the
# inner ends (grumpy V), < 0 raises them (sad, worried).
BROWS = {
    "neutral": (0.0, 0.0, 0.12),
    "happy": (0.12, -0.05, 0.22),
    "sad": (0.05, -0.35, 0.05),
    "surprised": (0.45, 0.0, 0.3),
    "grumpy": (-0.1, 0.35, 0.0),
    "worried": (0.2, -0.3, 0.1),
}
DEFAULT_COLORS = {
    "line": "#463430",
    "eye_white": "#ffffff",
    "iris": "#463430",
    "mouth": "#78283a",
    "tongue": "#e88a96",
}


@dataclass(frozen=True)
class FaceGeometry:
    """Face anchors in the head part's local frame (units, pivot origin, y up)."""

    eye_l: Vec
    eye_r: Vec
    eye_h: float
    brow_l: Vec
    brow_r: Vec
    brow_w: float
    mouth: Vec
    mouth_w: float
    colors: dict[str, Color]

    @classmethod
    def from_view(cls, view: dict[str, Any], space: Space) -> FaceGeometry:
        face = view.get("face")
        if not face:
            raise ValueError("this rig view has no `face` section")
        px, py = view["parts"][face["part"]]["pivot_px"]

        def local(p: list[float]) -> Vec:
            return Vec(space.length(p[0] - px), space.length(py - p[1]))

        eyes, mouth = face["eyes"], face["mouth"]
        eye_h = space.length(eyes["size_px"])
        brows = face.get("brows") or {
            # Default: brows a little above the eyes, as wide as an eye.
            "left_px": [eyes["left_px"][0], eyes["left_px"][1] - eyes["size_px"]],
            "right_px": [eyes["right_px"][0], eyes["right_px"][1] - eyes["size_px"]],
            "width_px": eyes["size_px"],
        }
        colors = {**DEFAULT_COLORS, **face.get("colors", {})}
        return cls(
            eye_l=local(eyes["left_px"]),
            eye_r=local(eyes["right_px"]),
            eye_h=eye_h,
            brow_l=local(brows["left_px"]),
            brow_r=local(brows["right_px"]),
            brow_w=space.length(brows["width_px"]),
            mouth=local(mouth["at_px"]),
            mouth_w=space.length(mouth["width_px"]),
            colors={k: Color.hex(v) for k, v in colors.items()},
        )


# --------------------------------------------------------------------------- eyes


def _eye_states(g: FaceGeometry, c: Vec, side: str) -> list[Layer]:
    h, w = g.eye_h, g.eye_h * 0.8
    line, white, iris = g.colors["line"], g.colors["eye_white"], g.colors["iris"]
    lw = h * 0.08
    pupil = Vec(c.x, c.y - h * 0.05)
    open_eye = Group(
        "open",
        children=[
            Region("white", color=white, spline=ellipse(c, w / 2, h / 2)),
            Circle("pupil", color=iris, origin=pupil, radius=h * 0.28),
            Circle(
                "shine",
                color=white,
                origin=Vec(pupil.x + h * 0.08, pupil.y + h * 0.1),
                radius=h * 0.09,
            ),
            Outline("rim", color=line, spline=ellipse(c, w / 2, h / 2), width=lw),
        ],
    )
    half_c = Vec(c.x, c.y - h * 0.15)
    half_eye = Group(
        "half",
        children=[
            Region("white", color=white, spline=ellipse(half_c, w / 2, h * 0.22)),
            Circle("pupil", color=iris, origin=Vec(c.x, c.y - h * 0.17), radius=h * 0.17),
            Outline("rim", color=line, spline=ellipse(half_c, w / 2, h * 0.22), width=lw),
        ],
    )
    closed_eye = Group(
        "closed",
        children=[
            Outline(
                "lid",
                color=line,
                width=lw * 1.2,
                spline=arc(Vec(c.x - w / 2, c.y), Vec(c.x, c.y - h * 0.15), Vec(c.x + w / 2, c.y)),
            ),
        ],
    )
    return [open_eye, half_eye, closed_eye]


def blink_track(blink_frames: list[int], *, start_state: str = "open") -> Animated:
    """Eye-state waypoints: each blink is half → closed → half → open over 4 frames."""
    keys: dict[int, str] = {0: start_state}
    last_end = -1
    for f in sorted(blink_frames):
        if f <= last_end:
            raise ValueError(f"blink at frame {f} overlaps the previous blink (ends {last_end})")
        for i, state in enumerate(("half", "closed", "half", "open")):
            keys[f + i] = state
        last_end = f + 3
    return Animated(
        "string", tuple(Waypoint(f, s, Interp.CONSTANT) for f, s in sorted(keys.items()))
    )


# --------------------------------------------------------------------------- brows


def _brow(g: FaceGeometry, anchor: Vec, inner_dir: float, expr: str) -> Outline:
    """One brow; inner_dir is -1 if the face centre is to the left of this brow, +1 if right."""
    raise_, drop, arch = BROWS[expr]
    h, half = g.eye_h, g.brow_w / 2
    y = anchor.y + raise_ * h
    inner = Vec(anchor.x + inner_dir * half, y - drop * h)
    outer = Vec(anchor.x - inner_dir * half, y + drop * h * 0.3)
    mid = Vec((inner.x + outer.x) / 2, (inner.y + outer.y) / 2 + arch * h)
    return Outline("brow", color=g.colors["line"], spline=arc(inner, mid, outer), width=h * 0.13)


# --------------------------------------------------------------------------- mouths


def _mouth_shapes(g: FaceGeometry) -> dict[str, list[Layer]]:
    m, u = g.mouth, g.mouth_w / 2
    line, inside, tongue, teeth = (g.colors[k] for k in ("line", "mouth", "tongue", "eye_white"))
    lw = g.mouth_w * 0.06

    def at(x: float, y: float) -> Vec:
        return Vec(m.x + x * u, m.y + y * u)

    def stroke(name: str, *pts: tuple[float, float], width: float = lw) -> Outline:
        return Outline(
            name, color=line, width=width, spline=smooth([at(*p) for p in pts], closed=False)
        )

    def hole(rx: float, ry: float, dy: float = 0.0) -> list[Layer]:
        c = at(0, dy)
        return [Region("inside", color=inside, spline=ellipse(c, rx * u, ry * u))]

    def rim(rx: float, ry: float, dy: float = 0.0, width: float = lw) -> Outline:
        return Outline("rim", color=line, width=width, spline=ellipse(at(0, dy), rx * u, ry * u))

    def blob(name: str, color: Color, cx: float, cy: float, rx: float, ry: float) -> Region:
        return Region(name, color=color, spline=ellipse(at(cx, cy), rx * u, ry * u))

    return {
        "A": [stroke("lips", (-0.55, 0), (0, -0.03), (0.55, 0), width=lw * 1.4)],
        "B": [*hole(0.6, 0.18), blob("teeth", teeth, 0, 0, 0.5, 0.09), rim(0.6, 0.18)],
        "C": [
            *hole(0.55, 0.35, -0.05),
            blob("teeth", teeth, 0, 0.17, 0.4, 0.08),
            blob("tongue", tongue, 0, -0.25, 0.3, 0.12),
            rim(0.55, 0.35, -0.05),
        ],
        "D": [
            *hole(0.65, 0.6, -0.2),
            blob("teeth", teeth, 0, 0.28, 0.45, 0.08),
            blob("tongue", tongue, 0, -0.55, 0.4, 0.18),
            rim(0.65, 0.6, -0.2),
        ],
        "E": [
            *hole(0.38, 0.32, -0.05),
            blob("tongue", tongue, 0, -0.22, 0.22, 0.09),
            rim(0.38, 0.32, -0.05),
        ],
        "F": [*hole(0.18, 0.2), rim(0.18, 0.2, width=lw * 1.6)],
        "G": [*hole(0.5, 0.2), blob("teeth", teeth, 0, 0.06, 0.45, 0.1), rim(0.5, 0.2)],
        "H": [
            *hole(0.5, 0.35, -0.05),
            blob("tongue", tongue, 0, 0.1, 0.28, 0.13),
            rim(0.5, 0.35, -0.05),
        ],
    }


def _rest_mouths(g: FaceGeometry) -> dict[str, list[Layer]]:
    """Mouth X (rest) per expression."""
    m, u = g.mouth, g.mouth_w / 2
    line, inside = g.colors["line"], g.colors["mouth"]
    lw = g.mouth_w * 0.06

    def at(x: float, y: float) -> Vec:
        return Vec(m.x + x * u, m.y + y * u)

    def curve(*pts: tuple[float, float]) -> list[Layer]:
        return [
            Outline(
                "rest", color=line, width=lw, spline=smooth([at(*p) for p in pts], closed=False)
            )
        ]

    return {
        "neutral": curve((-0.6, 0.05), (0, -0.12), (0.6, 0.05)),
        "happy": curve((-0.8, 0.15), (0, -0.3), (0.8, 0.15)),
        "sad": curve((-0.6, -0.12), (0, 0.08), (0.6, -0.12)),
        "surprised": [
            Region("o", color=inside, spline=ellipse(at(0, 0), 0.18 * u, 0.22 * u)),
            Outline("rim", color=line, width=lw, spline=ellipse(at(0, 0), 0.18 * u, 0.22 * u)),
        ],
        "grumpy": curve((-0.5, -0.05), (0, 0), (0.5, -0.08)),
        "worried": curve((-0.55, 0), (-0.2, 0.06), (0.2, -0.06), (0.55, 0)),
    }


# --------------------------------------------------------------------------- assembly


def face_layers(
    view: dict[str, Any],
    space: Space,
    *,
    expression: str | Animated = "neutral",
    eyes: str | Animated = "open",
    mouth: str | Animated = "X",
) -> list[Layer]:
    """The face, in the head part's local frame. Values are switch states; Animated string
    tracks change them over time (constant interpolation)."""
    for value, allowed, what in (
        (expression, EXPRESSIONS, "expression"),
        (eyes, EYE_STATES, "eye state"),
        (mouth, MOUTHS, "mouth shape"),
    ):
        states = [w.value for w in value.waypoints] if isinstance(value, Animated) else [value]
        bad = sorted({s for s in states if s not in allowed})
        if bad:
            raise ValueError(f"unknown {what} {bad}; known: {list(allowed)}")
    g = FaceGeometry.from_view(view, space)
    # The character's left eye is on the viewer's right (larger x); its face centre is to the left.
    left_is_right_of_centre = g.eye_l.x > g.eye_r.x
    sign = -1.0 if left_is_right_of_centre else 1.0
    brows = Switch(
        "brows",
        active=expression,
        children=[
            Group(expr, children=[_brow(g, g.brow_l, sign, expr), _brow(g, g.brow_r, -sign, expr)])
            for expr in EXPRESSIONS
        ],
    )
    shapes = _mouth_shapes(g)
    rest = Switch(
        "X",
        active=expression,
        children=[Group(expr, children=layers) for expr, layers in _rest_mouths(g).items()],
    )
    mouth_switch = Switch(
        "mouth",
        active=mouth,
        children=[
            *(Group(name, children=layers) for name, layers in shapes.items()),
            rest,
        ],
    )
    return [
        Switch("eye_l", active=eyes, children=_eye_states(g, g.eye_l, "left")),
        Switch("eye_r", active=eyes, children=_eye_states(g, g.eye_r, "right")),
        brows,
        mouth_switch,
    ]


def face_attachments(view: dict[str, Any], space: Space, **tracks: Any) -> dict[str, list[Layer]]:
    """`{head part: face layers}`, ready for `build_character(attachments=...)`."""
    return {view["face"]["part"]: face_layers(view, space, **tracks)}
