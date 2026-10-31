"""A parametric face: where the eyes, brows, nose and mouth go on a head, with hard limits.

Rules live in code, not in the LLM or the artist's guess (D-093). The old face anchors were *found*
in the painted head (puppet/build.py `clean_face`): whatever marks were nearest the skeleton's
guess. On Mia that put the eyes 165 px apart on a 212 px wide face (78% of it, at the cheek edges),
the mouth 49 px left of the eyes' midpoint, and gave the turned view no relation to the front one.
Here every feature is **computed** from the head's bounding box and a few proportions, then
clamped to limits a child's face keeps:

    box    = FaceBox.from_head_bbox(x0, y0, x1, y1)        # the skin area, hair margins removed
    layout = layout_face(box, FaceStyle(), yaw=0.0)         # clamped; layout.corrections says what
    layout.eye_l, layout.eye_r, layout.mouth, layout.nose   # (x, y) in head-image pixels

All distances are shares of the face box (width `w`, height `h`, measured from the top of the
visible skin), so the face scales with the head. The numbers in LIMITS are the contract; the tests
sweep the whole range of styles and yaws and assert they hold.

**Head turn (yaw, -1 = looking to the viewer's left, +1 = to the right).** A 2.5D cheat that
needs no extra art: the features slide toward the side the head turns to, the far eye narrows,
and the nose slides further than the eyes (it sits in front of the face plane), all within
limits so nothing leaves the skin. Beyond ~0.6 a turned head set should be used instead
(`YAW_SWAP`), which this module only reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

Point = tuple[float, float]

# (min, max) of each proportion, as a share of the face box width (x, w) or height (y, h)
LIMITS: dict[str, tuple[float, float]] = {
    "eye_gap": (0.30, 0.46),  # centre to centre, of w
    "eye_w": (0.10, 0.20),  # one eye's width, of w
    "eye_aspect": (1.0, 1.5),  # eye height / width (kids' eyes are tall ovals)
    "eye_y": (0.42, 0.62),  # of h, from the top of the face box
    "brow_gap": (0.08, 0.22),  # eye centre to brow, of h
    "nose_y": (0.60, 0.76),  # of h
    "mouth_y": (0.72, 0.90),  # of h
    "mouth_w": (0.12, 0.30),  # closed width, of w
}
MIN_MOUTH_DROP = 0.14  # of h: the mouth is at least this far below the eye line
MAX_EYE_SPAN = 0.78  # of w: both eyes' outer edges stay inside this share of the face width
MOUTH_TO_GAP = 0.80  # the mouth is at most this share of the eye gap wide (open mouths scale up
# to MOUTH_OPEN_SCALE of it; see `mouth_half_width`)
MOUTH_OPEN_SCALE = 1.25
MARGIN = 0.10  # of w: nothing's centre goes closer than this to the face box's side
MOUTH_OFF_CENTRE = 0.06  # of w: the mouth is under the eyes' midpoint, within this
MAX_YAW = 1.0
YAW_SWAP = 0.6  # above this, show a turned head set rather than slide the face
YAW_SHIFT = 0.15  # of w: features slide by this much at yaw 1
NOSE_SHIFT = 1.35  # the nose slides this many times further than the eyes
FAR_EYE_SQUASH = 0.30  # the far eye is this much narrower at yaw 1
NEAR_EYE_GROW = 0.06
FACE_SQUASH = 0.14  # features' horizontal spread shrinks by this much at yaw 1


@dataclass(frozen=True)
class FaceBox:
    """The visible skin of a head, in head-image pixels (y down): where a face can go."""

    cx: float
    top: float
    w: float
    h: float

    @property
    def bottom(self) -> float:
        return self.top + self.h

    @classmethod
    def from_head_bbox(
        cls,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        *,
        hair_top: float = 0.30,
        hair_side: float = 0.13,
        chin: float = 0.0,
    ) -> FaceBox:
        """The skin area of a head whose bounding box (hair included) is x0..x1, y0..y1: the
        fringe takes `hair_top` of the height, the side hair `hair_side` of the width each, and
        `chin` of the height is lost at the bottom. A bald or short-haired head passes 0."""
        W, H = x1 - x0, y1 - y0
        w = W * (1 - 2 * hair_side)
        top = y0 + H * hair_top
        return cls(cx=(x0 + x1) / 2, top=top, w=w, h=(y1 - H * chin) - top)


@dataclass(frozen=True)
class FaceStyle:
    """The face's proportions (what makes it Mia's rather than Kit's). Out-of-range values are
    clamped by `layout_face`, never trusted."""

    eye_gap: float = 0.40
    eye_w: float = 0.165
    eye_aspect: float = 1.2
    eye_y: float = 0.52
    brow_gap: float = 0.15
    nose_y: float = 0.68
    mouth_y: float = 0.80
    mouth_w: float = 0.20


@dataclass(frozen=True)
class FaceLayout:
    box: FaceBox
    yaw: float
    eye_l: Point  # the character's left eye = the viewer's right one in a front view
    eye_r: Point
    eye_w_l: float  # widths in px (the far eye is narrower when turned)
    eye_w_r: float
    eye_h: float
    brow_l: Point
    brow_r: Point
    brow_w: float
    nose: Point
    mouth: Point
    mouth_w: float  # closed width in px
    needs_turned_set: bool
    corrections: dict[str, tuple[float, float]] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            k: (list(v) if isinstance(v, tuple) else v)
            for k, v in self.__dict__.items()
            if k not in ("box", "corrections")
        }


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def clamp_style(style: FaceStyle) -> tuple[FaceStyle, dict[str, tuple[float, float]]]:
    """The style with every proportion inside LIMITS, and {name: (asked, used)} for each change."""
    fixed, notes = {}, {}
    for name, (lo, hi) in LIMITS.items():
        asked = getattr(style, name)
        used = clamp(asked, lo, hi)
        fixed[name] = used
        if used != asked:
            notes[name] = (asked, used)
    out = replace(style, **fixed)
    # the mouth sits clearly below the eyes
    if out.mouth_y - out.eye_y < MIN_MOUTH_DROP:
        used = min(LIMITS["mouth_y"][1], out.eye_y + MIN_MOUTH_DROP)
        notes["mouth_y"] = (out.mouth_y, used)
        out = replace(out, mouth_y=used)
        if out.mouth_y - out.eye_y < MIN_MOUTH_DROP:  # eyes too low for any legal mouth
            used = out.mouth_y - MIN_MOUTH_DROP
            notes["eye_y"] = (out.eye_y, used)
            out = replace(out, eye_y=used)
    # both eyes stay inside the face
    span = out.eye_gap + out.eye_w
    if span > MAX_EYE_SPAN:
        used = MAX_EYE_SPAN - out.eye_w
        notes["eye_gap"] = (out.eye_gap, used)
        out = replace(out, eye_gap=used)
    # the mouth is narrower than the eyes are apart
    cap = out.eye_gap * MOUTH_TO_GAP
    if out.mouth_w > cap:
        notes["mouth_w"] = (out.mouth_w, cap)
        out = replace(out, mouth_w=cap)
    return out, notes


def mouth_half_width(layout: FaceLayout, width_scale: float = 1.0) -> float:
    """Half the mouth's drawn width in px: its closed width times the shape's width scale, but
    never wider than the eyes are apart (MOUTH_OPEN_SCALE of the closed limit)."""
    cap = (layout.eye_l[0] - layout.eye_r[0]) * MOUTH_TO_GAP * MOUTH_OPEN_SCALE
    return min(layout.mouth_w * width_scale, cap) / 2


def layout_face(box: FaceBox, style: FaceStyle | None = None, yaw: float = 0.0) -> FaceLayout:
    """All features of the face for a head turned by `yaw` (see the module docstring)."""
    st, notes = clamp_style(style or FaceStyle())
    t = clamp(yaw, -MAX_YAW, MAX_YAW)
    if t != yaw:
        notes["yaw"] = (yaw, t)
    a = abs(t)
    squash = 1 - FACE_SQUASH * a
    lo, hi = box.cx - box.w / 2 + MARGIN * box.w, box.cx + box.w / 2 - MARGIN * box.w
    slide = t * YAW_SHIFT * box.w
    gap = st.eye_gap * box.w * squash

    eye_y = box.top + st.eye_y * box.h
    ew = st.eye_w * box.w
    # t > 0: the head turns to the viewer's right, so the viewer's-left eye (the character's
    # right) is the far one
    w_r = ew * (1 - FAR_EYE_SQUASH * a) if t > 0 else ew * (1 + NEAR_EYE_GROW * a)
    w_l = ew * (1 - FAR_EYE_SQUASH * a) if t < 0 else ew * (1 + NEAR_EYE_GROW * a)

    def x_in(x: float, half_width: float = 0.0) -> float:
        return clamp(x, lo + half_width, hi - half_width)

    ex_r = x_in(box.cx + slide - gap / 2, w_r / 2)
    ex_l = x_in(box.cx + slide + gap / 2, w_l / 2)
    nose_x = x_in(box.cx + slide * NOSE_SHIFT)
    mouth_x = x_in(box.cx + slide)
    eh = ew * st.eye_aspect
    brow_y = eye_y - st.brow_gap * box.h
    return FaceLayout(
        box=box,
        yaw=t,
        eye_l=(ex_l, eye_y),
        eye_r=(ex_r, eye_y),
        eye_w_l=w_l,
        eye_w_r=w_r,
        eye_h=eh,
        brow_l=(ex_l, brow_y),
        brow_r=(ex_r, brow_y),
        brow_w=ew * 1.25,
        nose=(nose_x, box.top + st.nose_y * box.h),
        mouth=(mouth_x, box.top + st.mouth_y * box.h),
        mouth_w=st.mouth_w * box.w,
        needs_turned_set=a > YAW_SWAP,
        corrections=notes,
    )


def check_layout(layout: FaceLayout) -> list[str]:
    """Every rule a layout must keep; an empty list means it is a legal face. Used by the tests
    and by the build to refuse an illegal face loudly instead of drawing it."""
    b, problems = layout.box, []
    left, right = b.cx - b.w / 2, b.cx + b.w / 2
    for name, (x, y) in (
        ("eye_l", layout.eye_l),
        ("eye_r", layout.eye_r),
        ("nose", layout.nose),
        ("mouth", layout.mouth),
    ):
        if not (left + MARGIN * b.w - 1e-6 <= x <= right - MARGIN * b.w + 1e-6):
            problems.append(f"{name} x {x:.1f} is outside the face's side margins")
        if not (b.top <= y <= b.bottom):
            problems.append(f"{name} y {y:.1f} is outside the face box")
    gap = layout.eye_l[0] - layout.eye_r[0]
    if gap <= 0:
        problems.append("the eyes are crossed")
    outer = (layout.eye_l[0] + layout.eye_w_l / 2) - (layout.eye_r[0] - layout.eye_w_r / 2)
    if outer > MAX_EYE_SPAN * b.w + 1e-6:
        problems.append(f"eyes span {outer / b.w:.2f} of the face width (max {MAX_EYE_SPAN})")
    if abs(layout.mouth[0] - (layout.eye_l[0] + layout.eye_r[0]) / 2) > MOUTH_OFF_CENTRE * b.w:
        problems.append("the mouth is not under the middle of the eyes")
    if layout.eye_l[1] != layout.eye_r[1]:
        problems.append("the eyes are not level")
    if (layout.mouth[1] - layout.eye_l[1]) / b.h < MIN_MOUTH_DROP - 1e-6:
        problems.append("the mouth is too close to the eyes")
    if layout.nose[1] <= layout.eye_l[1] or layout.nose[1] >= layout.mouth[1]:
        problems.append("the nose is not between the eyes and the mouth")
    if layout.mouth_w > gap * MOUTH_TO_GAP + 1e-6:
        problems.append("the mouth is wider than the eyes are apart")
    if max(layout.eye_w_l, layout.eye_w_r) > LIMITS["eye_w"][1] * b.w * (1 + NEAR_EYE_GROW) + 1e-6:
        problems.append("an eye is too wide")
    return problems


def face_box_of_rig_face(face: dict) -> FaceBox:
    """The FaceBox a rig view's `face.layout` stores (see schemas/rig.schema.json)."""
    cx, top, w, h = face["layout"]["box"]
    return FaceBox(cx=cx, top=top, w=w, h=h)


def style_of_rig_face(face: dict) -> FaceStyle:
    return FaceStyle(**face["layout"].get("style", {}))


# ----------------------------------------------------------------------------- whole-head turn
# A turn moves the WHOLE head (skin, hair, fringe, locks) about a vertical axis, and the face
# features move on top of it by more (parallax; the nose most). Before D-097 only the features
# slid, so the face moved like a sticker on a fixed head.
HEAD_SHIFT = 0.08  # of the head width: the head's outline centre moves this far at yaw 1
NEAR_SQUASH = 0.04  # the side the head turns toward narrows this much at yaw 1
FAR_SQUASH = 0.22  # the far side narrows this much (it tucks behind the near side)
MIN_HEAD_SHARE = 0.40  # the head moves at least this share of the face's total shift
HAIR_LAG_S = 0.12  # the hair lobes trail the head by about this long (overlap)


@dataclass(frozen=True)
class HeadWarp:
    """The horizontal map of a turned head: x is measured from the head's vertical axis (px),
    positive toward the viewer's right. Piecewise linear, continuous at the axis."""

    shift: float
    near: float  # scale of the side the head turns toward
    far: float
    toward: int  # +1 / -1: which side is near (0 when not turned)

    def map_x(self, x: float) -> float:
        if self.toward == 0:
            return x
        near_side = (x > 0) == (self.toward > 0)
        return self.shift + x * (self.near if near_side else self.far)


def head_warp(yaw: float, head_w: float) -> HeadWarp:
    """The turn's map for a head `head_w` px wide (hair included)."""
    t = clamp(yaw, -MAX_YAW, MAX_YAW)
    a = abs(t)
    if a < 1e-9:
        return HeadWarp(0.0, 1.0, 1.0, 0)
    return HeadWarp(
        t * HEAD_SHIFT * head_w, 1 - NEAR_SQUASH * a, 1 - FAR_SQUASH * a, 1 if t > 0 else -1
    )


def face_total_shift(layout_yaw_slide: float, warp: HeadWarp) -> float:
    """How far a feature at the face centre moves on screen: the head's shift plus its slide
    within the head (signed, px)."""
    return warp.shift + layout_yaw_slide


def smooth_lag(yaws: list[float], fps: int, lag_s: float = HAIR_LAG_S) -> list[float]:
    """The yaw the hair lobes follow: the head's yaw through two cascaded one-pole filters, so
    they trail by about `lag_s` and settle (overlap and follow-through on a turn)."""
    import math

    a = 1 - math.exp(-1 / fps / (lag_s / 2))
    out, y1, y2 = [], yaws[0] if yaws else 0.0, yaws[0] if yaws else 0.0
    for v in yaws:
        y1 += (v - y1) * a
        y2 += (y1 - y2) * a
        out.append(y2)
    return out
