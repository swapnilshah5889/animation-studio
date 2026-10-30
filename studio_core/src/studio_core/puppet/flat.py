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

from PIL import Image, ImageChops, ImageDraw

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
    height: float = 700.0
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
    thigh: float = 88.0
    shin: float = 127.0
    limb_r: float = 21.0
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


def _hand_art(spec: FlatSpec, wrist: Pt, tip: Pt, side: int):
    """A mitten (round palm + a thumb on the body side) at the end of the forearm."""
    p = spec.palette

    def draw(art: Art) -> None:
        ang = math.atan2(tip[1] - wrist[1], tip[0] - wrist[0])
        ux, uy = math.cos(ang), math.sin(ang)
        palm = (wrist[0] + ux * 16, wrist[1] + uy * 16)
        m, d = art.mask()
        art.circle(d, palm, spec.limb_r * 0.98)
        art.capsule(d, wrist, palm, spec.limb_r * 0.85)
        tx, ty = palm[0] + (-uy) * side * 12 + ux * 2, palm[1] + ux * side * 12 + uy * 2
        art.capsule(d, (tx - ux * 6, ty - uy * 6), (tx + ux * 8, ty + uy * 8), 7.5)
        art.fill(m, p.skin)
        art.shade(m, p.skin_shade, -6)

    return draw


def _cuff(spec: FlatSpec, wrist: Pt, ang: float):
    p = spec.palette

    def draw(art: Art) -> None:
        ux, uy = math.cos(ang), math.sin(ang)
        a, b = (wrist[0] - ux * 14, wrist[1] - uy * 14), (wrist[0] + ux * 4, wrist[1] + uy * 4)
        m, d = art.mask()
        art.capsule(d, a, b, spec.limb_r + 2.5)
        art.fill(m, p.coat_trim)

    return draw


def _torso(spec: FlatSpec) -> _Part:
    p = spec.palette
    art = Art((-118, 292, 118, 542))
    sh, hem = spec.shoulder_y, 524.0
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
    # the hood: a collar ring round the neck, drawn over the neck base
    cm, cd = art.mask()
    art.ellipse(cd, (0, sh - 18), 58, 26)
    art.fill(cm, p.coat_trim)
    nm, nd = art.mask()
    art.ellipse(nd, (0, sh - 24), 36, 16)
    art.fill(nm, p.coat_shade)
    return _Part("torso", "torso", art, (0, spec.hip_y))


def _head_parts(spec: FlatSpec) -> tuple[list[_Part], FaceBox, dict[str, Art]]:
    """(hair_back, hair_l, hair_r, head), the face box, and the head's layers."""
    p = spec.palette
    W, top, H = spec.head_w, spec.head_top, spec.head_h
    box = FaceBox.from_head_bbox(-W / 2, top, W / 2, top + H)
    cx = 0.0
    hb_box = (-W / 2 - 14, top - 10, W / 2 + 14, spec.neck_y + 30)
    # hair behind the head: a big curly bob that ends behind the collar
    back = Art(hb_box)
    m, d = back.mask()
    back.ellipse(d, (cx, top + H * 0.5), W / 2 + 4, H * 0.5 + 6)
    for c in _scallops(cx, top + H * 0.5, W / 2 - 6, H * 0.5 - 4, 24, 14):
        back.circle(d, (c[0], c[1]), c[2])
    for x in range(-150, 151, 36):  # the curls that fall behind the neck
        back.circle(d, (x, top + H - 4), 30)
    back.fill(m, p.hair_lo)
    for c in _scallops(cx, top + H * 0.5, W / 2 - 40, H * 0.5 - 40, 16, 30, 20, 160):
        mm, dd = back.mask()
        back.circle(dd, (c[0], c[1]), c[2])
        back.fill(ImageChops.multiply(mm, m), p.hair)
    # skin layer: the face (an egg), the neck
    skin = Art((-W / 2, top, W / 2, spec.neck_y + 22))
    sm, sd = skin.mask()
    skin.ellipse(sd, (cx, box.top + box.h * 0.46), box.w / 2, box.h * 0.56)
    skin.rrect(sd, -26, box.bottom - 40, 26, spec.neck_y + 20, 8)
    skin.fill(sm, p.skin)
    nm, nd = skin.mask()  # the neck's shade under the chin
    skin.ellipse(nd, (cx, box.bottom + 6), 40, 22)
    skin.fill(ImageChops.multiply(nm, sm), p.skin_shade)
    # cheeks
    for sx in (-1, 1):
        cm, cdraw = skin.mask()
        skin.ellipse(
            cdraw, (cx + sx * box.w * 0.30, box.top + box.h * 0.70), box.w * 0.075, box.h * 0.05
        )
        skin.fill(ImageChops.multiply(cm, sm), p.blush)
    # fringe and side hair: everything of the hair cap that is not the face window
    over = Art((-W / 2, top, W / 2, spec.neck_y + 22))
    cap, cd2 = over.mask()
    over.ellipse(cd2, (cx, top + H * 0.46), W / 2, H * 0.46)
    for c in _scallops(cx, top + H * 0.46, W / 2 - 14, H * 0.46 - 12, 26, 16, 160, 380):
        over.circle(cd2, (c[0], c[1]), c[2])
    for sx in (-1, 1):
        over.capsule(
            cd2, (sx * (W / 2 - 24), top + H * 0.42), (sx * (W / 2 - 26), top + H * 0.80), 26
        )
        for k in range(4):
            over.circle(cd2, (sx * (W / 2 - 24), top + H * (0.42 + 0.12 * k)), 30)
    window, wd = over.mask()
    fy = box.top + 2
    over.rrect(wd, -box.w / 2 + 2, fy, box.w / 2 - 2, spec.neck_y + 40, 4)
    over.ellipse(wd, (cx, box.top + box.h * 0.46), box.w / 2 - 2, box.h * 0.56 - 2)
    face_win = ImageChops.multiply(
        window, _ellipse_mask(over, (cx, box.top + box.h * 0.46), box.w / 2 - 2, box.h * 0.56 - 2)
    )
    hair = ImageChops.subtract(cap, face_win)
    bumps, bd = over.mask()
    x = -box.w / 2 + 28
    while x < box.w / 2 - 20:
        over.circle(bd, (x, fy + 4 + 6 * math.sin(x / 19.0)), 25)
        x += 30
    bumps = ImageChops.multiply(
        bumps, _ellipse_mask(over, (cx, box.top + box.h * 0.46), box.w / 2 - 6, box.h * 0.56)
    )
    hair = ImageChops.lighter(hair, bumps)
    over.fill(hair, p.hair)
    # light curls inside the fringe: a few arcs of the highlight colour
    hi, hd2 = over.mask()
    for _i, (ax, ay) in enumerate([(-96, 64), (-40, 44), (30, 48), (92, 66)]):
        x0, y0 = over._p((ax - 22, top + ay - 14))
        x1, y1 = over._p((ax + 22, top + ay + 14))
        hd2.arc([x0, y0, x1, y1], 200, 340, fill=255, width=7 * SS)
    over.fill(ImageChops.multiply(hi, hair), p.hair_hi)
    over.shade(hair, p.hair_lo, -8)

    # locks: curly puffs at the temples that swing (bones of role ear)
    locks = []
    for side, nm_ in ((1, "hair_l"), (-1, "hair_r")):
        jx, jy = side * (W / 2 - 34), top + H * 0.52
        a = Art((jx - 44, jy - 30, jx + 44, jy + 150))
        mm, dd = a.mask()
        for k in range(3):
            a.circle(dd, (jx + side * 3 * k, jy + 18 + 36 * k), 30 - 2 * k)
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
    art = Art((x - 46, knee[1] - 30, x + 46, spec.height + 10))
    m, d = art.mask()
    art.capsule(d, knee, (x, ankle_y), spec.limb_r - 1)
    art.fill(m, p.tights)
    art.shade(m, p.tights_shade, -9)
    bm, bd = art.mask()
    top = ankle_y - 38
    art.rrect(bd, x - 27, top, x + 27, spec.height - 4, 12)
    art.ellipse(bd, (x + side * 4, spec.height - 18), 33, 17)  # toe cap, wider in front
    art.fill(bm, p.boot)
    art.shade(bm, p.boot_shade, -11)
    sm, sd = art.mask()
    art.ellipse(sd, (x + side * 4, spec.height - 6), 33, 7)
    art.rrect(sd, x - 27, spec.height - 10, x + 27, spec.height - 4, 3)
    art.fill(ImageChops.multiply(sm, bm), p.sole)
    cm, cd = art.mask()  # the boot's top band
    art.rrect(cd, x - 29, top - 3, x + 29, top + 12, 5)
    art.fill(cm, p.boot_shade)
    return _Part("shin", "shin", art, knee)


def build_parts(spec: FlatSpec) -> tuple[list[_Part], dict[str, Any]]:
    p = spec.palette
    parts: list[_Part] = []
    out: dict[str, Any] = {}
    rad = math.radians
    knee_y = spec.hip_y + spec.thigh
    ank = knee_y + spec.shin - 62  # the boot starts above the ankle line
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
            spec.limb_r + 1,
            spec.limb_r,
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
            extra=lambda art, w=wrist, t=tip, s=sx, a=ang: (
                _cuff(spec, w, -a)(art),
                _hand_art(spec, w, t, s)(art),
            ),
            pad=22,
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
