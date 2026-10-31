"""A puppet designed for rigging, drawn by code in a clean flat style (D-093).

The painted-still route (cut a finished illustration into parts) can never reach the production bar:
no art exists for the hidden part of an arm or a leg, shading is baked in, and there is one pose.
Here the figure is **drawn as parts**, so every part is a complete shape:

- every limb is a full capsule with round ends (the shoulder, elbow, knee and hip are circles that
  hide under the parent, so any rotation shows no gap and no cut edge)
- colours are a small palette of solid fills; each part has ONE light shade, a crescent on its
  right edge, so a rotated part keeps the same look (no baked soft shadow, no gradient)
- the head is three layers (skin, face, fringe) so the parametric face (`face_layout.py`) is drawn
  between skin and hair, and brows can slide under the fringe
- the hair locks are bones of role `ear`, so the follow-through layer (motions/follow.py) swings
  them after the head for free

`build_flat_puppet(spec, folder)` writes `rig.json` (schema "rig") and the part PNGs into `folder`.
Geometry is described in *figure space* (x right, 0 at the centre line; y down; the ground is
`spec.height`), then each part is cropped to its own box. Nothing here is Mia-specific except the
default spec: another character is another `FlatSpec` (palette, proportions), at no model cost.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from studio_core.face_layout import FaceBox, FaceStyle, layout_face

SS = 3  # supersampling
Pt = tuple[float, float]


@dataclass
class Palette:
    skin: str = "#f6cba5"
    skin_shade: str = "#e6ab86"
    hair: str = "#6b4230"
    hair_hi: str = "#8d5c43"
    hair_lo: str = "#58352a"
    coat: str = "#f5be2d"
    coat_shade: str = "#e0a117"
    coat_trim: str = "#c98a0d"
    tights: str = "#3a5680"
    tights_shade: str = "#2e4668"
    boot: str = "#d8423a"
    boot_shade: str = "#b3322c"
    sole: str = "#7d2824"
    line: str = "#5a3326"  # eyes, brows, mouth outline
    iris: str = "#6a3f2c"
    blush: str = "#f3a08f"
    mouth_in: str = "#7a2c33"
    tongue: str = "#e8707f"


@dataclass
class FlatSpec:
    """A character's proportions in figure space (px at scale 1). Defaults are Mia: a child with a
    big head, short body, shoulder-length curly hair, a raincoat and boots."""

    id: str = "mia"
    name: str = "Mia"
    height: float = 785.0  # = hip_y + thigh + shin
    head_w: float = 330.0  # head incl. hair
    head_top: float = 20.0
    head_h: float = 298.0
    neck_y: float = 322.0
    hip_y: float = 485.0
    hip_x: float = 36.0
    shoulder_x: float = 82.0
    shoulder_y: float = 332.0
    arm_dir: float = 80.0  # degrees below horizontal: 90 = straight down, less = held out (A-pose)
    upper_arm: float = 82.0
    forearm: float = 100.0  # to the fingertip (hand included)
    thigh: float = 140.0
    shin: float = 160.0
    hem_y: float = 506.0  # where the coat ends; the legs show from here to the ground
    boot_h: float = 64.0
    limb_r: float = 21.0
    leg_r: float = 26.0  # legs are thicker than arms (round 3: the stick legs read as a shuffle)
    palette: Palette = field(default_factory=Palette)
    face_style: FaceStyle = field(default_factory=FaceStyle)


class Art:
    """An RGBA canvas for one part, positioned in figure space, drawn with masks."""

    def __init__(self, box: tuple[float, float, float, float]):
        x0, y0, x1, y1 = box
        self.x0, self.y0 = math.floor(x0), math.floor(y0)
        self.w, self.h = math.ceil(x1) - self.x0, math.ceil(y1) - self.y0
        self.img = Image.new("RGBA", (self.w * SS, self.h * SS), (0, 0, 0, 0))

    def _p(self, p: Pt) -> Pt:
        return ((p[0] - self.x0) * SS, (p[1] - self.y0) * SS)

    def mask(self) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        m = Image.new("L", self.img.size, 0)
        return m, ImageDraw.Draw(m)

    # --- shapes onto a mask
    def circle(self, d: ImageDraw.ImageDraw, c: Pt, r: float) -> None:
        self.ellipse(d, c, r, r)

    def ellipse(self, d: ImageDraw.ImageDraw, c: Pt, rx: float, ry: float) -> None:
        x, y = self._p(c)
        d.ellipse([x - rx * SS, y - ry * SS, x + rx * SS, y + ry * SS], fill=255)

    def poly(self, d: ImageDraw.ImageDraw, pts: list[Pt]) -> None:
        d.polygon([self._p(p) for p in pts], fill=255)

    def capsule(self, d: ImageDraw.ImageDraw, a: Pt, b: Pt, ra: float, rb: float | None = None):
        rb = ra if rb is None else rb
        n = max(2, int(math.dist(a, b) / 3))
        for i in range(n + 1):
            t = i / n
            self.circle(d, (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), ra + (rb - ra) * t)

    def rrect(self, d: ImageDraw.ImageDraw, x0: float, y0: float, x1: float, y1: float, r: float):
        p0, p1 = self._p((x0, y0)), self._p((x1, y1))
        d.rounded_rectangle([*p0, *p1], radius=r * SS, fill=255)

    # --- masks onto the canvas
    def fill(self, mask: Image.Image, colour: str) -> None:
        layer = Image.new("RGBA", self.img.size, colour)
        layer.putalpha(mask)
        self.img.alpha_composite(layer)

    def shade(self, base: Image.Image, colour: str, dx: float, dy: float = 0.0) -> None:
        """A crescent: the part of `base` not covered by `base` moved by (dx, dy). One light
        direction for every part, so a rotated part still looks like itself."""
        moved = ImageChops.offset(base, round(dx * SS), round(dy * SS))
        self.fill(ImageChops.subtract(base, moved), colour)

    def done(self) -> Image.Image:
        small = self.img.convert("RGBa").resize((self.w, self.h), Image.LANCZOS)
        return small.convert("RGBA")


def _hex(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _scallops(cx: float, cy: float, rx: float, ry: float, r: float, step: float, a0=0, a1=360):
    """Circle centres round an ellipse: a curly outline when the circles are unioned."""
    n = max(3, int((a1 - a0) / step))
    return [
        (
            cx + rx * math.cos(math.radians(a0 + i * (a1 - a0) / n)),
            cy + ry * math.sin(math.radians(a0 + i * (a1 - a0) / n)),
            r,
        )
        for i in range(n + 1)
    ]


# ------------------------------------------------------------------------------------- parts


@dataclass
class _Part:
    name: str
    bone: str
    art: Art
    joint: Pt  # figure space: where the bone's joint is

    @property
    def pivot(self) -> Pt:
        return (round(self.joint[0] - self.art.x0, 1), round(self.joint[1] - self.art.y0, 1))


def _limb(
    spec: FlatSpec,
    name: str,
    bone: str,
    a: Pt,
    b: Pt,
    r0: float,
    r1: float,
    fill: str,
    shade: str,
    extra=None,
    pad: float = 8.0,
) -> _Part:
    x0, x1 = min(a[0], b[0]) - max(r0, r1) - pad, max(a[0], b[0]) + max(r0, r1) + pad
    y0, y1 = min(a[1], b[1]) - max(r0, r1) - pad, max(a[1], b[1]) + max(r0, r1) + pad
    art = Art((x0, y0, x1, y1))
    m, d = art.mask()
    art.capsule(d, a, b, r0, r1)
    art.fill(m, fill)
    art.shade(m, shade, -r0 * 0.5)
    if extra:
        extra(art)
    return _Part(name, bone, art, a)


def _hand_cuff(spec: FlatSpec, wrist: Pt, tip: Pt, side: int):
    """A mitten (round palm + a thumb on the body side) that starts UNDER the cuff, then the cuff
    over it: the two always overlap, so no rotation can open a gap between sleeve and hand."""
    p = spec.palette

    def draw(art: Art) -> None:
        ang = math.atan2(tip[1] - wrist[1], tip[0] - wrist[0])
        ux, uy = math.cos(ang), math.sin(ang)
        palm = (wrist[0] + ux * 16, wrist[1] + uy * 16)
        m, d = art.mask()
        art.circle(d, palm, spec.limb_r * 0.98)
        art.capsule(d, (wrist[0] - ux * 12, wrist[1] - uy * 12), palm, spec.limb_r * 0.85)
        tx, ty = palm[0] + (-uy) * side * 12 + ux * 2, palm[1] + ux * side * 12 + uy * 2
        art.capsule(d, (tx - ux * 6, ty - uy * 6), (tx + ux * 8, ty + uy * 8), 7.5)
        art.fill(m, p.skin)
        art.shade(m, p.skin_shade, -6)
        cm, cd = art.mask()
        a0 = (wrist[0] - ux * 16, wrist[1] - uy * 16)
        art.capsule(cd, a0, (wrist[0] + ux * 5, wrist[1] + uy * 5), spec.limb_r + 2.5)
        art.fill(cm, p.coat_trim)

    return draw


def _torso(spec: FlatSpec) -> _Part:
    p = spec.palette
    art = Art((-118, 292, 118, 542))
    sh, hem = spec.shoulder_y, spec.hem_y
    m, d = art.mask()
    # an A-line raincoat: shoulders, a straight chest, a flared hem with a round bottom
    art.poly(
        d, [(-72, sh - 8), (72, sh - 8), (80, 396), (104, hem - 14), (-104, hem - 14), (-80, 396)]
    )
    art.circle(d, (0, sh - 4), 76)
    art.ellipse(d, (0, hem - 14), 104, 14)
    art.rrect(d, -76, sh - 18, 76, sh + 40, 30)
    art.fill(m, p.coat)
    art.shade(m, p.coat_shade, -20)
    # hem band, placket, buttons, one pocket: flat details that belong to the coat
    hm, hd = art.mask()
    art.ellipse(hd, (0, hem - 14), 104, 14)
    art.poly(hd, [(-104, hem - 36), (104, hem - 36), (104, hem - 14), (-104, hem - 14)])
    art.fill(ImageChops.multiply(hm, m), p.coat_trim)
    pm, pd = art.mask()
    art.rrect(pd, -4, sh + 22, 4, hem - 30, 3)
    art.fill(ImageChops.multiply(pm, m), p.coat_shade)
    bm, bd = art.mask()
    for y in (sh + 62, sh + 102, sh + 142):
        art.circle(bd, (0, y), 8)
    art.fill(bm, p.coat_trim)
    qm, qd = art.mask()
    art.rrect(qd, 34, 424, 76, 462, 8)
    art.fill(ImageChops.multiply(qm, m), p.coat_shade)
    # the hood behind the neck, then a narrow neck that tapers into the collar, an under-chin
    # shade at its top, and the collar's front band over its base (the neck is tucked under it)
    cm, cd = art.mask()
    art.ellipse(cd, (0, sh - 8), 62, 22)
    art.fill(cm, p.coat_trim)
    nk, nd = art.mask()
    art.poly(nd, [(-17, sh - 44), (17, sh - 44), (21, sh + 6), (-21, sh + 6)])
    art.fill(nk, p.skin)
    chin, cd2 = art.mask()
    art.ellipse(cd2, (0, sh - 24), 70, 24)
    art.fill(ImageChops.multiply(nk, chin), p.skin_shade)
    fm, fd = art.mask()
    art.ellipse(fd, (0, sh + 8), 50, 14)
    art.fill(fm, p.coat_trim)
    em, ed = art.mask()
    art.ellipse(ed, (0, sh + 12), 44, 8)
    art.fill(em, p.coat_shade)
    return _Part("torso", "torso", art, (0, spec.hip_y))


def _smooth(m: Image.Image, radius: float) -> Image.Image:
    """Round off a mask made of clipped circles and rectangles: blur, then cut at half. Concave
    notches fill, stair-steps and flat clipped edges become one smooth outline (a union of the
    shapes that reads as one drawn path)."""
    return m.filter(ImageFilter.GaussianBlur(radius * SS)).point(lambda v: 255 if v >= 128 else 0)


HAIR_PAD = 46.0  # room above and beside the head for curls, so no shape is clipped by its image


def _face_contour_x(box: FaceBox, y: float) -> float:
    """Half width of the face egg at height y (the skin ellipse of `_head_parts`)."""
    ey, b = box.top + box.h * 0.46, box.h * 0.56
    return (box.w / 2) * math.sqrt(max(0.0, 1.0 - ((y - ey) / b) ** 2))


def hairline_y(box: FaceBox, x: float) -> float:
    """The parted fringe's lower edge at x (round 3): highest at the centre parting, sweeping
    down to the temples along a curve (exponent 1.4), so the forehead is an arch and not a flat
    band with square corners. Beyond the face edge it keeps falling, to meet the side locks."""
    a = box.w / 2
    t = abs(x) / a
    y = box.top - 6 + (box.h * 0.36 + 6) * min(t, 1.0) ** 1.4
    return y + max(0.0, abs(x) - a) * 3.0


def _head_parts(spec: FlatSpec) -> tuple[list[_Part], FaceBox, dict[str, Art]]:
    """(hair_back, hair_l, hair_r, head), the face box, and the head's layers."""
    p = spec.palette
    W, top, H = spec.head_w, spec.head_top, spec.head_h
    box = FaceBox.from_head_bbox(-W / 2, top, W / 2, top + H)
    cx = 0.0
    hw = W / 2 - 14  # the hair's half width: it hugs the face (the first hair was a wide helmet)
    full = (-W / 2 - HAIR_PAD, top - HAIR_PAD, W / 2 + HAIR_PAD, spec.neck_y + 30)
    # hair behind the head: a rounded dome with a fine curl edge, ending in two round bob lobes
    back = Art(full)
    m, d = back.mask()
    back.ellipse(d, (cx, top + H * 0.5), hw + 2, H * 0.5 + 4)
    for c in _scallops(cx, top + H * 0.5, hw - 4, H * 0.5 - 2, 15, 10):
        back.circle(d, (c[0], c[1]), c[2])
    for sx in (-1, 1):  # the bob's lobes: round, one each side, tucked behind the collar
        back.circle(d, (sx * (hw - 36), top + H - 24), 38)
        back.ellipse(d, (sx * (hw - 30), top + H * 0.74), 36, 62)
    m = _smooth(m, 5)
    back.fill(m, p.hair_lo)
    inner, idr = back.mask()
    back.ellipse(idr, (cx, top + H * 0.46), hw - 22, H * 0.5 - 24)
    back.fill(ImageChops.multiply(_smooth(inner, 6), m), p.hair)
    # skin layer: the face (an egg); the neck belongs to the torso (tucked under the collar)
    skin = Art(full)
    sm, sd = skin.mask()
    skin.ellipse(sd, (cx, box.top + box.h * 0.46), box.w / 2, box.h * 0.56)
    skin.fill(sm, p.skin)
    for sx in (-1, 1):  # cheeks
        cm, cdraw = skin.mask()
        skin.ellipse(
            cdraw, (cx + sx * box.w * 0.30, box.top + box.h * 0.70), box.w * 0.075, box.h * 0.05
        )
        skin.fill(ImageChops.multiply(cm, sm), p.blush)
    # fringe and side hair: ONE path. A dome cut by the parted hairline, plus locks that follow
    # the face contour, unioned and smoothed (no clipped circles, no skin corner, no shade slab)
    over = Art(full)
    cap, cd2 = over.mask()
    over.ellipse(cd2, (cx, top + H * 0.46), hw, H * 0.46)
    for c in _scallops(cx, top + H * 0.46, hw - 10, H * 0.46 - 8, 15, 9, 150, 390):
        over.circle(cd2, (c[0], c[1]), c[2])
    xs = [-W / 2 - HAIR_PAD + i * 2 for i in range(int((W + 2 * HAIR_PAD) / 2) + 1)]
    above, ad = over.mask()
    over.poly(
        ad,
        [(xs[0], top - HAIR_PAD), *[(x, hairline_y(box, x)) for x in xs], (xs[-1], top - HAIR_PAD)],
    )
    hair, hd = over.mask()
    hair.paste(ImageChops.multiply(cap, above))
    y_end = box.top + box.h * 0.46 + box.h * 0.56 * 0.55
    for sx in (-1, 1):  # side locks hug the face's edge, a little over it, thinner toward the jaw
        y = box.top + box.h * 0.20
        while y <= y_end:
            t = (y - box.top) / (y_end - box.top)
            over.circle(hd, (sx * (_face_contour_x(box, y) + 8), y), 31 - 12 * t)
            y += 9
    hair = _smooth(hair, 5)
    over.fill(hair, p.hair)
    hi, hd2 = over.mask()  # light curls inside the fringe: a few arcs of the highlight colour
    for ax, ay in [(-88, 58), (-36, 40), (30, 42), (84, 60)]:
        x0, y0 = over._p((ax - 20, top + ay - 12))
        x1, y1 = over._p((ax + 20, top + ay + 12))
        hd2.arc([x0, y0, x1, y1], 200, 340, fill=255, width=7 * SS)
    over.fill(ImageChops.multiply(hi, hair), p.hair_hi)

    # locks: curly puffs at the temples that swing (bones of role ear)
    locks = []
    for side, nm_ in ((1, "hair_l"), (-1, "hair_r")):
        jx, jy = side * (hw - 28), top + H * 0.52
        a = Art((jx - 96, jy - 40, jx + 96, jy + 160))  # room for the turn's shift
        mm, dd = a.mask()
        for k in range(3):
            a.circle(dd, (jx - side * 4 * k, jy + 14 + 32 * k), 28 - 3 * k)
        mm = _smooth(mm, 5)
        a.fill(mm, p.hair)
        a.shade(mm, p.hair_lo, -9)
        locks.append(_Part(nm_, nm_, a, (jx, jy)))
    head = _Part("head", "head", skin, (cx, spec.neck_y))
    hairb = _Part("hair_back", "head", back, (cx, spec.neck_y))
    return [hairb, *locks, head], box, {"skin": skin, "over": over}


def _ellipse_mask(art: Art, c: Pt, rx: float, ry: float) -> Image.Image:
    m, d = art.mask()
    art.ellipse(d, c, rx, ry)
    return m


def _boot(spec: FlatSpec, knee: Pt, ankle_y: float, side: int) -> _Part:
    p = spec.palette
    x = knee[0]
    art = Art(
        (x - 52, knee[1] - 30, x + 52, spec.height)
    )  # the box bottom IS the ground
    m, d = art.mask()
    art.capsule(d, knee, (x, ankle_y), spec.leg_r - 1)
    art.fill(m, p.tights)
    art.shade(m, p.tights_shade, -9)
    bm, bd = art.mask()
    top = spec.height - spec.boot_h
    art.rrect(bd, x - 30, top, x + 30, spec.height - 4, 11)
    art.ellipse(bd, (x + side * 4, spec.height - 15), 35, 15)  # toe cap, wider in front
    art.fill(bm, p.boot)
    art.shade(bm, p.boot_shade, -10)
    sm, sd = art.mask()
    art.ellipse(sd, (x + side * 4, spec.height - 6), 35, 6)
    art.rrect(sd, x - 30, spec.height - 9, x + 30, spec.height - 4, 3)
    art.fill(ImageChops.multiply(sm, bm), p.sole)
    cm, cd = art.mask()  # the boot's top band
    art.rrect(cd, x - 32, top - 3, x + 32, top + 10, 5)
    art.fill(cm, p.boot_shade)
    return _Part("shin", "shin", art, knee)


def leg_ratios(spec: FlatSpec) -> dict[str, float]:
    """Shares of the figure's height: the visible leg (coat hem to sole) and the boot. A rule the
    tests hold: legs at least 27%, boots at most 10% (the first Mia had 11% legs, 14% boots)."""
    return {
        "visible_leg": (spec.height - spec.hem_y) / spec.height,
        "boot": spec.boot_h / spec.height,
    }


def build_parts(spec: FlatSpec) -> tuple[list[_Part], dict[str, Any]]:
    p = spec.palette
    parts: list[_Part] = []
    out: dict[str, Any] = {}
    rad = math.radians
    knee_y = spec.hip_y + spec.thigh
    ank = spec.height - spec.boot_h + 8  # the tights end inside the boot top
    for _side, sx, tag in ((1, 1, "l"), (-1, -1, "r")):
        # legs: thigh (tights) then shin + boot
        hip = (sx * spec.hip_x, spec.hip_y)
        knee = (hip[0], knee_y)
        th = _limb(
            spec,
            f"thigh_{tag}",
            f"thigh_{tag}",
            hip,
            knee,
            spec.leg_r + 1,
            spec.leg_r,
            p.tights,
            p.tights_shade,
        )
        sh = _boot(spec, knee, ank, sx)
        sh.name = sh.bone = f"shin_{tag}"
        # arms: sleeve to the wrist (a cuff), a mitten for the hand
        ang = rad(-(180 - spec.arm_dir)) if sx > 0 else rad(-spec.arm_dir)
        # left (+x) arm points down and out: angle -(arm_dir); right arm mirrors it
        ang = rad(-spec.arm_dir) if sx > 0 else rad(-(180 - spec.arm_dir))
        sho = (sx * spec.shoulder_x, spec.shoulder_y)
        elb = (sho[0] + spec.upper_arm * math.cos(ang), sho[1] - spec.upper_arm * math.sin(ang))
        tip = (elb[0] + spec.forearm * math.cos(ang), elb[1] - spec.forearm * math.sin(ang))
        wrist = (
            elb[0] + (spec.forearm - 34) * math.cos(ang),
            elb[1] - (spec.forearm - 34) * math.sin(ang),
        )
        ua = _limb(
            spec,
            f"upper_arm_{tag}",
            f"upper_arm_{tag}",
            sho,
            elb,
            spec.limb_r + 1,
            spec.limb_r,
            p.coat,
            p.coat_shade,
        )
        fa = _limb(
            spec,
            f"forearm_{tag}",
            f"forearm_{tag}",
            elb,
            wrist,
            spec.limb_r,
            spec.limb_r - 1,
            p.coat,
            p.coat_shade,
            extra=_hand_cuff(spec, wrist, tip, sx),
            pad=48,  # room for the mitten and thumb beyond the wrist (22 clipped the hand)
        )
        parts += [th, sh, ua, fa]
        out[tag] = {
            "hip": hip,
            "knee": knee,
            "shoulder": sho,
            "elbow": elb,
            "tip": tip,
            "ang": math.degrees(ang),
        }
    parts.append(_torso(spec))
    head_parts, box, layers = _head_parts(spec)
    parts += head_parts
    out["box"], out["layers"] = box, layers
    return parts, out


# ------------------------------------------------------------------------------------- rig

LIMITS = {
    "torso": (-15, 15),
    "head": (-25, 25),
    "upper_arm_l": (-30, 170),
    "forearm_l": (-20, 140),
    "upper_arm_r": (-170, 30),
    "forearm_r": (-140, 20),
    "thigh_l": (-35, 35),
    "shin_l": (-10, 60),
    "thigh_r": (-35, 35),
    "shin_r": (-60, 10),
    "hair_l": (-40, 40),
    "hair_r": (-40, 40),
}
DRAW_ORDER = [
    "upper_arm_r",
    "forearm_r",
    "upper_arm_l",
    "forearm_l",
    "thigh_r",
    "shin_r",
    "thigh_l",
    "shin_l",
    "hair_back",
    "torso",
    "hair_l",
    "hair_r",
    "head",
]


def build_flat_puppet(spec: FlatSpec, folder: Path) -> dict[str, Any]:
    """Write the puppet (rig.json + parts/front/*.png + the head layers) into `folder`."""
    pdir = folder / "parts" / "front"
    pdir.mkdir(parents=True, exist_ok=True)
    parts, info = build_parts(spec)
    by = {p.name: p for p in parts}
    images: dict[str, Image.Image] = {}
    for p in parts:
        images[p.name] = p.art.done()
    # the head's default look: skin + face at yaw 0 + fringe (the renderer composes the live one)
    from studio_core.engines.face_flat import FaceState, draw_face

    layers = info["layers"]
    skin_img, over_img = layers["skin"].done(), layers["over"].done()
    skin_img.save(pdir / "head_skin.png")
    over_img.save(pdir / "head_over.png")
    box0: FaceBox = info["box"]
    hx, hy = by["head"].art.x0, by["head"].art.y0
    local = FaceBox(box0.cx - hx, box0.top - hy, box0.w, box0.h)  # head-image px
    head = draw_face(
        skin_img, over_img, layout_face(local, spec.face_style, 0.0), FaceState(), spec.palette
    )
    images["head"] = head
    for name, img in images.items():
        img.save(pdir / f"{name}.png")

    parts_json = {}
    for n in DRAW_ORDER:
        pt = by[n]
        parts_json[n] = {
            "file": f"parts/front/{n}.png",
            "size_px": [images[n].width, images[n].height],
            "pivot_px": list(pt.pivot),
            "bone": pt.bone,
        }

    def att(parent_part: str, fig: Pt) -> dict[str, Any]:
        a = by[parent_part].art
        return {"part": parent_part, "at_px": [round(fig[0] - a.x0, 1), round(fig[1] - a.y0, 1)]}

    bones: dict[str, Any] = {
        "torso": {
            "role": "torso",
            "parent": None,
            "direction_deg": 90.0,
            "length_px": spec.hip_y - spec.neck_y,
            "side": "center",
            "limits_deg": _lim("torso"),
        },
        "head": {
            "role": "head",
            "parent": "torso",
            "direction_deg": 90.0,
            "length_px": spec.neck_y - spec.head_top,
            "side": "center",
            "limits_deg": _lim("head"),
            "attach": att("torso", (0, spec.neck_y)),
        },
    }
    for tag, side in (("l", "left"), ("r", "right")):
        g = info[tag]
        d_arm = g["ang"]
        bones[f"upper_arm_{tag}"] = {
            "role": "upper_arm",
            "parent": "torso",
            "direction_deg": round(d_arm, 2),
            "length_px": spec.upper_arm,
            "side": side,
            "limits_deg": _lim(f"upper_arm_{tag}"),
            "attach": att("torso", g["shoulder"]),
        }
        bones[f"forearm_{tag}"] = {
            "role": "forearm",
            "parent": f"upper_arm_{tag}",
            "direction_deg": round(d_arm, 2),
            "length_px": spec.forearm,
            "side": side,
            "limits_deg": _lim(f"forearm_{tag}"),
            "attach": att(f"upper_arm_{tag}", g["elbow"]),
        }
        bones[f"thigh_{tag}"] = {
            "role": "thigh",
            "parent": "torso",
            "direction_deg": -90.0,
            "length_px": spec.thigh,
            "side": side,
            "limits_deg": _lim(f"thigh_{tag}"),
            "attach": att("torso", g["hip"]),
        }
        bones[f"shin_{tag}"] = {
            "role": "shin",
            "parent": f"thigh_{tag}",
            "direction_deg": -90.0,
            "length_px": spec.shin,
            "side": side,
            "limits_deg": _lim(f"shin_{tag}"),
            "attach": att(f"thigh_{tag}", g["knee"]),
        }
        jx = by[f"hair_{tag}"].joint
        bones[f"hair_{tag}"] = {
            "role": "ear",
            "parent": "head",
            "direction_deg": -90.0,
            "length_px": 100.0,
            "side": side,
            "limits_deg": _lim(f"hair_{tag}"),
            "attach": att("head", jx),
        }

    face_box = [round(local.cx, 2), round(local.top, 2), round(local.w, 2), round(local.h, 2)]
    lay_px = layout_face(
        FaceBox(face_box[0], face_box[1], face_box[2], face_box[3]), spec.face_style
    )
    face = {
        "part": "head",
        "eyes": {
            "left_px": [round(v, 1) for v in lay_px.eye_l],
            "right_px": [round(v, 1) for v in lay_px.eye_r],
            "size_px": round(lay_px.eye_w_l, 1),
        },
        "brows": {
            "left_px": [round(v, 1) for v in lay_px.brow_l],
            "right_px": [round(v, 1) for v in lay_px.brow_r],
            "width_px": round(lay_px.brow_w, 1),
            "weight": 0.09,
        },
        "mouth": {
            "at_px": [round(v, 1) for v in lay_px.mouth],
            "width_px": round(lay_px.mouth_w, 1),
        },
        "colors": {"line": spec.palette.line, "iris": spec.palette.iris},
        "layout": {
            "box": face_box,
            "head_w": spec.head_w,
            "style": {k: getattr(spec.face_style, k) for k in vars(spec.face_style)},
            "layers": {"skin": "parts/front/head_skin.png", "over": "parts/front/head_over.png"},
        },
    }
    rig = {
        "schema_version": 1,
        "id": spec.id,
        "name": spec.name,
        "style": "flat",
        "default_view": "front",
        "views": {
            "front": {
                "root": "torso",
                "bones": bones,
                "parts": parts_json,
                "draw_order": DRAW_ORDER,
                "face": face,
            }
        },
    }
    (folder / "rig.json").write_text(json.dumps(rig, indent=2) + "\n")
    (folder / "palette.json").write_text(
        json.dumps({"colors": [{"hex": c} for c in vars(spec.palette).values()]}, indent=1)
    )
    return rig


def _lim(name: str) -> dict[str, int]:
    lo, hi = LIMITS[name]
    return {"min": lo, "max": hi}
