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

from dataclasses import dataclass, field
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

EXPRESSIONS = (
    "neutral",
    "happy",
    "sad",
    "surprised",
    "grumpy",
    "worried",
    "excited",
    "shy",
    "sleepy",
    "proud",
    "determined",
)
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
    "excited": (0.38, -0.05, 0.28),  # high and round, brighter than happy
    "shy": (0.1, -0.22, 0.08),  # a little raised, inner ends up: tentative, with a sideways smile
    "sleepy": (-0.14, -0.12, 0.02),  # low and flat, outer ends drooping (pair with half eyes)
    "proud": (0.18, 0.06, 0.2),  # lifted, inner ends a touch down: chin-up confidence
    "determined": (-0.05, 0.2, 0.0),  # low, a shallow V (half as steep as grumpy) over a firm mouth
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
    # Solid-eye style, and the view's turn (0 = front-on; the signed measured turn fraction,
    # positive faces screen-right). Defaults draw the face exactly as before they existed.
    style: str = "sclera"
    eye_w: float = 0.0  # solid eye width (0: 0.8 of the height)
    highlight: Vec | None = None  # solid eye highlight, offset from the eye centre (y up)
    highlight_r: float = 0.0
    brow_weight: float = 0.13
    turn: float = 0.0
    skin: Color | None = field(default=None)

    @property
    def facing(self) -> float:
        """+1 when the face turns toward screen-right (larger x), -1 toward screen-left."""
        return 1.0 if self.turn >= 0 else -1.0

    @property
    def squeeze(self) -> float:
        """How far the turn is, 0 to 1 (a turn past 'as asked' foreshortens no further)."""
        return min(abs(self.turn), 1.0)

    @property
    def far_eye_scale(self) -> float:
        """The far eye and brow are this wide next to the near ones: 0.75 for a slight turn, 0.55
        for a full one."""
        return 0.75 - 0.2 * self.squeeze if self.turn else 1.0

    @property
    def mouth_scale(self) -> float:
        return 1.0 - 0.3 * self.squeeze

    @property
    def mouth_dx(self) -> float:
        """The mouth sits toward the snout, the side the face turns to."""
        return self.facing * 0.12 * self.mouth_w * self.squeeze

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
        skin = colors.pop("skin", None)
        solid = eyes.get("style") == "solid"
        if solid:
            colors["iris"] = eyes.get("color", colors["iris"])
        highlight = eyes.get("highlight_px")
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
            style="solid" if solid else "sclera",
            eye_w=space.length(eyes["width_px"]) if solid and "width_px" in eyes else 0.0,
            highlight=(
                Vec(space.length(highlight[0]), -space.length(highlight[1]))
                if solid and highlight
                else None
            ),
            highlight_r=space.length(eyes.get("highlight_r_px", 0.0)) if solid else 0.0,
            brow_weight=brows.get("weight", 0.13),
            turn=float(face.get("turn", 0.0)),
            skin=Color.hex(skin) if skin and solid else None,
        )


# --------------------------------------------------------------------------- eyes


def _eye_states(g: FaceGeometry, c: Vec, side: str, far: bool = False) -> list[Layer]:
    """The three eye states. On a turned head (`g.turn`) the far eye is narrower (`far`) and
    both pupils or highlights look toward the side the face turns to."""
    if g.style == "solid":
        return _solid_eye_states(g, c, far)
    if g.turn:
        return _turned_eye_states(g, c, far)
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


def _eye_width(g: FaceGeometry, far: bool) -> float:
    w = g.eye_w or g.eye_h * 0.8
    return w * (g.far_eye_scale if far and g.turn else 1.0)


def _turned_eye_states(g: FaceGeometry, c: Vec, far: bool) -> list[Layer]:
    """A sclera eye on a turned head: the same eye, narrower when far, the pupil (squeezed to
    match) shifted toward the side the face turns to."""
    h, w = g.eye_h, _eye_width(g, far)
    sx = w / (g.eye_h * 0.8)
    line, white, iris = g.colors["line"], g.colors["eye_white"], g.colors["iris"]
    lw = h * 0.08
    look = g.facing * 0.1 * w
    pupil = Vec(c.x + look, c.y - h * 0.05)
    open_eye = Group(
        "open",
        children=[
            Region("white", color=white, spline=ellipse(c, w / 2, h / 2)),
            Region("pupil", color=iris, spline=ellipse(pupil, h * 0.28 * sx, h * 0.28)),
            Region(
                "shine",
                color=white,
                spline=ellipse(
                    Vec(pupil.x + h * 0.08 * sx, pupil.y + h * 0.1), h * 0.09 * sx, h * 0.09
                ),
            ),
            Outline("rim", color=line, spline=ellipse(c, w / 2, h / 2), width=lw),
        ],
    )
    half_c = Vec(c.x, c.y - h * 0.15)
    half_eye = Group(
        "half",
        children=[
            Region("white", color=white, spline=ellipse(half_c, w / 2, h * 0.22)),
            Region(
                "pupil",
                color=iris,
                spline=ellipse(Vec(c.x + look, c.y - h * 0.17), h * 0.17 * sx, h * 0.17),
            ),
            Outline("rim", color=line, spline=ellipse(half_c, w / 2, h * 0.22), width=lw),
        ],
    )
    return [open_eye, half_eye, _closed_eye(g, c, w)]


def _closed_eye(g: FaceGeometry, c: Vec, w: float) -> Group:
    h, lw = g.eye_h, g.eye_h * 0.08
    return Group(
        "closed",
        children=[
            Outline(
                "lid",
                color=g.colors["line"],
                width=lw * 1.2,
                spline=arc(Vec(c.x - w / 2, c.y), Vec(c.x, c.y - h * 0.15), Vec(c.x + w / 2, c.y)),
            ),
        ],
    )


def _solid_eye_states(g: FaceGeometry, c: Vec, far: bool) -> list[Layer]:
    """A solid eye: a dark oval with a small highlight and no white. Half-closed is the oval
    with a lid over its top (the face's skin colour when known, else the oval squashed);
    closed is the lid line."""
    h, w = g.eye_h, _eye_width(g, far)
    sx = w / (g.eye_w or g.eye_h * 0.8)
    dark, white = g.colors["iris"], g.colors["eye_white"]
    hl = g.highlight or Vec(h * 0.12, h * 0.16)
    hr = g.highlight_r or h * 0.09
    shine = Vec(c.x + hl.x * sx + g.facing * 0.06 * w * bool(g.turn), c.y + hl.y)
    open_eye = Group(
        "open",
        children=[
            Region("eye", color=dark, spline=ellipse(c, w / 2, h / 2)),
            Region("shine", color=white, spline=ellipse(shine, hr * sx, hr)),
        ],
    )
    if g.skin is not None:
        half_children: list[Layer] = [
            Region("eye", color=dark, spline=ellipse(c, w / 2, h / 2)),
            Region(  # the lid: a skin-coloured ellipse whose low edge cuts the oval at its middle
                "lid",
                color=g.skin,
                spline=ellipse(Vec(c.x, c.y - 0.1 * h / 2 + h * 0.6), w * 0.62, h * 0.6),
            ),
        ]
    else:
        half_c = Vec(c.x, c.y - h * 0.15)
        half_children = [Region("eye", color=dark, spline=ellipse(half_c, w / 2, h * 0.22))]
    return [open_eye, Group("half", children=half_children), _closed_eye(g, c, w)]


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


def _brow(g: FaceGeometry, anchor: Vec, inner_dir: float, expr: str, far: bool = False) -> Outline:
    """One brow; inner_dir is -1 if the face centre is to the left of this brow, +1 if right.
    The far brow of a turned head is shorter."""
    raise_, drop, arch = BROWS[expr]
    h, half = g.eye_h, g.brow_w / 2 * (g.far_eye_scale if far and g.turn else 1.0)
    y = anchor.y + raise_ * h
    inner = Vec(anchor.x + inner_dir * half, y - drop * h)
    outer = Vec(anchor.x - inner_dir * half, y + drop * h * 0.3)
    mid = Vec((inner.x + outer.x) / 2, (inner.y + outer.y) / 2 + arch * h)
    return Outline(
        "brow", color=g.colors["line"], spline=arc(inner, mid, outer), width=h * g.brow_weight
    )


# --------------------------------------------------------------------------- mouths


def _mouth_shapes(g: FaceGeometry) -> dict[str, list[Layer]]:
    m, u = g.mouth, g.mouth_w / 2
    sx, dx = g.mouth_scale, g.mouth_dx  # a turned head's mouth is shorter, toward the snout
    line, inside, tongue, teeth = (g.colors[k] for k in ("line", "mouth", "tongue", "eye_white"))
    lw = g.mouth_w * 0.06

    def at(x: float, y: float) -> Vec:
        return Vec(m.x + dx + x * u * sx, m.y + y * u)

    def stroke(name: str, *pts: tuple[float, float], width: float = lw) -> Outline:
        return Outline(
            name, color=line, width=width, spline=smooth([at(*p) for p in pts], closed=False)
        )

    def hole(rx: float, ry: float, dy: float = 0.0) -> list[Layer]:
        c = at(0, dy)
        return [Region("inside", color=inside, spline=ellipse(c, rx * u * sx, ry * u))]

    def rim(rx: float, ry: float, dy: float = 0.0, width: float = lw) -> Outline:
        return Outline(
            "rim", color=line, width=width, spline=ellipse(at(0, dy), rx * u * sx, ry * u)
        )

    def blob(name: str, color: Color, cx: float, cy: float, rx: float, ry: float) -> Region:
        return Region(name, color=color, spline=ellipse(at(cx, cy), rx * u * sx, ry * u))

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
    sx, dx = g.mouth_scale, g.mouth_dx
    line, inside = g.colors["line"], g.colors["mouth"]
    lw = g.mouth_w * 0.06

    def at(x: float, y: float) -> Vec:
        return Vec(m.x + dx + x * u * sx, m.y + y * u)

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
            Region("o", color=inside, spline=ellipse(at(0, 0), 0.18 * u * sx, 0.22 * u)),
            Outline("rim", color=line, width=lw, spline=ellipse(at(0, 0), 0.18 * u * sx, 0.22 * u)),
        ],
        "grumpy": curve((-0.5, -0.05), (0, 0), (0.5, -0.08)),
        "worried": curve((-0.55, 0), (-0.2, 0.06), (0.2, -0.06), (0.55, 0)),
        # An open grin: the mouth is a D-shaped bowl with a row of teeth, brighter than happy.
        "excited": [
            Region("inside", color=inside, spline=ellipse(at(0, -0.12), 0.7 * u * sx, 0.42 * u)),
            Region(
                "teeth",
                color=g.colors["eye_white"],
                spline=ellipse(at(0, 0.14), 0.5 * u * sx, 0.1 * u),
            ),
            Outline(
                "rim", color=line, width=lw, spline=ellipse(at(0, -0.12), 0.7 * u * sx, 0.42 * u)
            ),
        ],
        # A small smile pulled to one side (the viewer's right end sits higher).
        "shy": curve((-0.4, 0.0), (-0.05, -0.1), (0.4, 0.12)),
        "sleepy": curve((-0.3, 0.0), (0, -0.05), (0.3, 0.0)),
        # A broad closed smile whose one corner is higher: a smirk of pride.
        "proud": curve((-0.7, 0.04), (-0.3, -0.2), (0.3, -0.22), (0.72, 0.18)),
        "determined": curve((-0.5, 0.0), (0, -0.04), (0.5, 0.05)),
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
    # The far eye is on the side the face turns to (larger x when facing screen-right).
    left_far = bool(g.turn) and (g.eye_l.x - g.eye_r.x) * g.facing > 0
    brows = Switch(
        "brows",
        active=expression,
        children=[
            Group(
                expr,
                children=[
                    _brow(g, g.brow_l, sign, expr, left_far),
                    _brow(g, g.brow_r, -sign, expr, not left_far and bool(g.turn)),
                ],
            )
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
        Switch("eye_l", active=eyes, children=_eye_states(g, g.eye_l, "left", left_far)),
        Switch(
            "eye_r",
            active=eyes,
            children=_eye_states(g, g.eye_r, "right", not left_far and bool(g.turn)),
        ),
        brows,
        mouth_switch,
    ]


def face_attachments(view: dict[str, Any], space: Space, **tracks: Any) -> dict[str, list[Layer]]:
    """`{head part: face layers}`, ready for `build_character(attachments=...)`."""
    return {view["face"]["part"]: face_layers(view, space, **tracks)}
