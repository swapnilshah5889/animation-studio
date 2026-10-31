"""The parametric face as pixels, drawn from continuous state (engine-neutral, D-030, D-093).

`face_sprite.py` draws a face from *switch* states (eyes open/half/closed, a mouth letter), so a
blink or a new mouth shape pops in one frame. Here the face is drawn from **numbers**:

    FaceState(eye_open=0..1, smile=-1..1, brow_raise=-1..1, brow_tilt=-1..1,
              mouth=MouthShape(open, width, round, teeth, tongue), look=(-1..1, -1..1))

The caller (`motions/smooth.py`) eases those numbers over time, so every in-between frame is a
real drawing. The layout (where things go, how a head turn moves them) is `face_layout.py`;
this module only draws what the layout says, in the head-image pixel frame.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

from PIL import Image, ImageChops, ImageDraw

from studio_core.face_layout import FaceLayout, mouth_half_width
from studio_core.motions.smooth import VISEME_PARAMS

SS = 4


@dataclass(frozen=True)
class MouthShape:
    open: float = 0.0  # 0 closed .. 1 wide open (share of the half width)
    width: float = 1.0  # width scale on the closed width
    round: float = 0.0  # 0 flat lips .. 1 an O
    teeth: float = 0.0  # 0..1 how much of the upper teeth show
    tongue: float = 0.0


# Rhubarb's mouth shapes as parameters (motions/smooth.py holds the table). Blending two of them
# is a per-number lerp, so a transition is a real in-between mouth, not a swap.
VISEMES: dict[str, MouthShape] = {k: MouthShape(**v) for k, v in VISEME_PARAMS.items()}


@dataclass(frozen=True)
class FaceState:
    eye_open: float = 1.0
    smile: float = 0.35
    brow_raise: float = 0.0
    brow_tilt: float = 0.0  # + = inner ends up (worried), - = inner ends down (grumpy)
    mouth: MouthShape = field(default_factory=MouthShape)
    look: tuple[float, float] = (0.0, 0.0)

    def lerp(self, other: FaceState, t: float) -> FaceState:
        def f(a: float, b: float) -> float:
            return a + (b - a) * t

        m, n = self.mouth, other.mouth
        return FaceState(
            f(self.eye_open, other.eye_open),
            f(self.smile, other.smile),
            f(self.brow_raise, other.brow_raise),
            f(self.brow_tilt, other.brow_tilt),
            MouthShape(
                f(m.open, n.open),
                f(m.width, n.width),
                f(m.round, n.round),
                f(m.teeth, n.teeth),
                f(m.tongue, n.tongue),
            ),
            (f(self.look[0], other.look[0]), f(self.look[1], other.look[1])),
        )


def _p(x: float, y: float) -> tuple[float, float]:
    return x * SS, y * SS


def _eye(
    layer: Image.Image,
    c: tuple[float, float],
    w: float,
    h: float,
    state: FaceState,
    pal: Any,
    yaw: float,
    mid_x: float,
) -> None:
    d = ImageDraw.Draw(layer)
    line = pal.line
    open_ = max(0.0, min(1.0, state.eye_open))
    if open_ < 0.12:  # closed: a downward-curved lid line
        lw = max(3, round(w * 0.11)) * SS
        x0, y0 = _p(c[0] - w / 2, c[1] - h * 0.18)
        x1, y1 = _p(c[0] + w / 2, c[1] + h * 0.18)
        d.arc([x0, y0, x1, y1], 15, 165, fill=line, width=lw)
        return
    ry = h / 2 * (0.25 + 0.75 * open_)
    rx = w / 2
    # clip everything to the eye's own shape: sclera, iris and shine move under the lid
    eye = Image.new("L", layer.size, 0)
    ImageDraw.Draw(eye).ellipse([*_p(c[0] - rx, c[1] - ry), *_p(c[0] + rx, c[1] + ry)], fill=255)
    paint = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    pd = ImageDraw.Draw(paint)
    pd.ellipse([*_p(c[0] - rx, c[1] - ry), *_p(c[0] + rx, c[1] + ry)], fill="#ffffff")
    ir = min(rx * 0.84, h * 0.46)
    # the pupils converge a little toward the nose, so a gaze at the camera is not wall-eyed
    ix = (
        c[0] + state.look[0] * rx * 0.22 + yaw * rx * 0.10 + (1 if mid_x > c[0] else -1) * rx * 0.09
    )
    iy = c[1] + state.look[1] * ry * 0.3 + h * 0.02
    pd.ellipse([*_p(ix - ir, iy - ir), *_p(ix + ir, iy + ir)], fill=pal.iris)
    pr = ir * 0.52
    pd.ellipse([*_p(ix - pr, iy - pr), *_p(ix + pr, iy + pr)], fill="#2a1710")
    sr = ir * 0.30
    pd.ellipse(
        [
            *_p(ix - ir * 0.38 - sr, iy - ir * 0.40 - sr),
            *_p(ix - ir * 0.38 + sr, iy - ir * 0.40 + sr),
        ],
        fill="#ffffff",
    )
    paint.putalpha(ImageChops.multiply(paint.getchannel("A"), eye))
    layer.alpha_composite(paint)
    lw = max(3, round(w * 0.10)) * SS  # the upper lid is a thick line
    x0, y0 = _p(c[0] - rx, c[1] - ry)
    x1, y1 = _p(c[0] + rx, c[1] + ry)
    d.arc([x0, y0, x1, y1], 188, 352, fill=line, width=lw)


def _brow(
    d: ImageDraw.ImageDraw,
    c: tuple[float, float],
    w: float,
    face_h: float,
    state: FaceState,
    inner_sign: int,
    pal: Any,
) -> None:
    lift = -state.brow_raise * face_h * 0.06
    tilt = state.brow_tilt * w * 0.28
    x0, x1 = c[0] - w / 2, c[0] + w / 2
    y = c[1] + lift
    inner_x = x0 if inner_sign < 0 else x1
    pts = []
    for i in range(13):
        t = i / 12
        x = x0 + (x1 - x0) * t
        arch = -math.sin(math.pi * t) * w * 0.10
        near_inner = (1 - t) if inner_sign < 0 else t  # 1 at the inner end
        pts.append(_p(x, y + arch - tilt * near_inner))
    del inner_x
    d.line(pts, fill=pal.line, width=max(4, round(w * 0.085)) * SS, joint="curve")
    for pt in (pts[0], pts[-1]):
        r = max(4, round(w * 0.085)) * SS / 2
        d.ellipse([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r], fill=pal.line)


def _mouth(layer: Image.Image, lay: FaceLayout, state: FaceState, pal: Any) -> None:
    d = ImageDraw.Draw(layer)
    ms = state.mouth
    hw = mouth_half_width(lay, ms.width)
    cx, cy = lay.mouth
    lw = max(3, round(hw * 0.14))
    c = -state.smile * hw * 0.42  # corner height (negative = up)
    xs = [i / 24 * 2 - 1 for i in range(25)]
    upper = [(cx + x * hw, cy + c * x * x + (state.smile * hw * 0.10)) for x in xs]
    depth = ms.open * hw * 1.05
    expo = 0.8 - 0.35 * ms.round
    lower = [
        (cx + x * hw, cy + c * x * x + depth * (1 - x * x) ** expo + state.smile * hw * 0.10)
        for x in xs
    ]
    if depth < 1.2:  # closed: one lip line, ends rounded
        d.line([_p(*q) for q in upper], fill=pal.line, width=lw * SS, joint="curve")
        for q in (upper[0], upper[-1]):
            r = lw * SS / 2
            x, y = _p(*q)
            d.ellipse([x - r, y - r, x + r, y + r], fill=pal.line)
        return
    poly = [_p(*q) for q in upper] + [_p(*q) for q in reversed(lower)]
    m = Image.new("L", layer.size, 0)
    ImageDraw.Draw(m).polygon(poly, fill=255)
    paint = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    pd = ImageDraw.Draw(paint)
    pd.polygon(poly, fill=pal.mouth_in)
    if ms.tongue > 0.02:
        tw, th = hw * (0.55 + 0.15 * ms.tongue), depth * (0.28 + 0.28 * ms.tongue)
        ty = cy + depth * 0.92 + state.smile * hw * 0.1
        pd.ellipse([*_p(cx - tw, ty - th), *_p(cx + tw, ty + th)], fill=pal.tongue)
    if ms.teeth > 0.02:
        th = min(depth * 0.55, hw * 0.34) * ms.teeth
        pd.polygon(
            [_p(cx + x * hw, cy + c * x * x + state.smile * hw * 0.10 - 1) for x in xs]
            + [
                _p(cx + x * hw, cy + c * x * x + state.smile * hw * 0.10 + th * (1 - x * x) ** 0.4)
                for x in reversed(xs)
            ],
            fill="#ffffff",
        )
    paint.putalpha(ImageChops.multiply(paint.getchannel("A"), m))
    layer.alpha_composite(paint)
    d.line(
        [_p(*q) for q in upper + list(reversed(lower))] + [_p(*upper[0])],
        fill=pal.line,
        width=lw * SS,
        joint="curve",
    )


def draw_face(
    skin: Image.Image, over: Image.Image, lay: FaceLayout, state: FaceState, pal: Any
) -> Image.Image:
    """skin + face (eyes, brows, nose, mouth at the layout's places) + fringe, as one RGBA head."""
    W, H = skin.size
    layer = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    yaw = lay.yaw
    # nose: a small curve (a dot would read as a button at this size)
    nx, ny = lay.nose
    nr = lay.box.w * 0.018
    d.arc(
        [*_p(nx - nr * 1.6, ny - nr * 2.0), *_p(nx + nr * 1.6, ny + nr * 1.0)],
        20,
        160,
        fill=pal.skin_shade if False else "#d9946f",
        width=max(3, round(lay.box.w * 0.014)) * SS,
    )
    eh = lay.eye_h
    mid = (lay.eye_l[0] + lay.eye_r[0]) / 2
    _eye(layer, lay.eye_l, lay.eye_w_l, eh, state, pal, yaw, mid)
    _eye(layer, lay.eye_r, lay.eye_w_r, eh, state, pal, yaw, mid)
    _brow(d, lay.brow_l, lay.brow_w, lay.box.h, state, -1, pal)
    _brow(d, lay.brow_r, lay.brow_w, lay.box.h, state, +1, pal)
    _mouth(layer, lay, state, pal)
    face = layer.convert("RGBa").resize((W, H), Image.LANCZOS).convert("RGBA")
    out = skin.convert("RGBA").copy()
    out.alpha_composite(face)
    out.alpha_composite(over.convert("RGBA"))
    return out


def with_yaw_squash(state: FaceState, **kw: Any) -> FaceState:  # pragma: no cover - convenience
    return replace(state, **kw)


def state_of(params: dict[str, Any]) -> FaceState:
    """The FaceState a baked frame's `face` dict (motions/smooth.py `face_series`) describes."""
    return FaceState(
        eye_open=params["eye_open"],
        smile=params["smile"],
        brow_raise=params["brow_raise"],
        brow_tilt=params["brow_tilt"],
        mouth=MouthShape(**params["mouth"]),
        look=tuple(params["look"]),  # type: ignore[arg-type]
    )


def warp_image(img: Image.Image, axis_px: float, warp: Any) -> Image.Image:
    """The image turned by `warp` (face_layout.HeadWarp) about the vertical line x = axis_px:
    each half is resized horizontally (the far side narrower, the near side nearly full) and
    both are placed at the shifted axis. Same size as the input; content shifted outside is
    cut, so part images carry padding for the shift."""
    if warp.toward == 0:
        return img.copy()
    W, H = img.size
    cut = round(axis_px)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    left = img.crop((0, 0, cut, H)) if cut > 0 else None
    right = img.crop((cut, 0, W, H)) if cut < W else None
    # figure x < 0 is the left half; scale by the side's factor
    s_left = warp.near if warp.toward < 0 else warp.far
    s_right = warp.near if warp.toward > 0 else warp.far
    new_axis = axis_px + warp.shift
    for half, scale, is_left in ((left, s_left, True), (right, s_right, False)):
        if half is None or half.width == 0:
            continue
        w2 = max(1, round(half.width * scale))
        small = half.convert("RGBa").resize((w2, H), Image.LANCZOS).convert("RGBA")
        x = round(new_axis - w2) if is_left else round(new_axis)
        if x < W and x + w2 > 0:
            out.alpha_composite(small, (max(x, 0), 0), (max(-x, 0), 0))
    return out


def write_flat_sprites(
    rig_dir: Any, view: dict[str, Any], frames: list[dict[str, Any]], folder: Any
) -> None:
    """One head PNG per distinct face state in `frames` (a held pose reuses its file); sets
    `frames[].head`. Layout, skin and fringe come from the view's `face.layout`."""
    import hashlib
    import json
    from pathlib import Path

    from studio_core.face_layout import FaceStyle, face_box_of_rig_face, layout_face

    class _Pal:  # the rig stores only the line and iris colours; the rest are the flat palette's
        pass

    face = view["face"]
    from studio_core.puppet.flat import Palette

    pal = Palette()
    pal.line, pal.iris = face["colors"]["line"], face["colors"]["iris"]
    root = Path(rig_dir)
    layers = face["layout"]["layers"]
    skin = Image.open(root / layers["skin"]).convert("RGBA")
    over = Image.open(root / layers["over"]).convert("RGBA")
    box = face_box_of_rig_face(face)
    style = FaceStyle(**face["layout"].get("style", {}))
    cache: dict[str, Path] = {}
    from studio_core.face_layout import head_warp

    parts = view["parts"]
    head_w = face["layout"].get("head_w") or box.w / 0.74  # the head incl. hair (box is its skin)
    head_axis = parts["head"]["pivot_px"][0]
    turned_parts = {}  # name -> (image, axis px in that image)
    for name in ("hair_back", "hair_l", "hair_r"):
        if name in parts:
            img = Image.open(root / parts[name]["file"]).convert("RGBA")
            axis = head_axis
            if name in view["bones"] and view["bones"][name].get("attach"):  # a lock: its own frame
                axis = parts[name]["pivot_px"][0] + (
                    head_axis - view["bones"][name]["attach"]["at_px"][0]
                )
            turned_parts[name] = (img, axis)
    for fr in frames:
        face_p = fr["face"]
        yaw, yaw_hair = face_p["yaw"], face_p.get("yaw_hair", face_p["yaw"])
        key = hashlib.sha1(json.dumps(face_p, sort_keys=True).encode()).hexdigest()[:12]
        if key not in cache:
            path = Path(folder) / f"head_{key}.png"
            if not path.exists():
                lay = layout_face(box, style, yaw)
                whole = draw_face(skin, over, lay, state_of(face_p), pal)
                warp_image(whole, head_axis, head_warp(yaw, head_w)).save(path)
            cache[key] = path
        fr["head"] = str(cache[key])
        if turned_parts:
            hk = f"{round(yaw_hair, 3):+.3f}"
            fr["part_images"] = {}
            for name, (img, axis) in turned_parts.items():
                path = Path(folder) / f"{name}_{hk}.png"
                if not path.exists():
                    warp_image(img, axis, head_warp(yaw_hair, head_w)).save(path)
                fr["part_images"][name] = str(path)
