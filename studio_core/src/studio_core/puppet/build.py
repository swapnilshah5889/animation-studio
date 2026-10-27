"""Cut a chosen design sheet into a rigged cut-out puppet (tasks 4.4-4.5, D-050, D-051).

    built = build_puppet(film_root, "kit", name="Kit")   # the sheet chosen in candidates.json
    built.report["views"]["front"]["limbs"]["forearm_l"] # how well a limb fits its bone
    built.report["consistency"]                          # do the two views match?

Both figures of the turnaround become views of one rig (front and three_quarter), cut the
same way (`_cut_view`), parts in parts/<view>/. Then puppet/consistency.py compares them.

The sheet was generated *on* a known skeleton (puppet/skeleton.py), so cutting it is geometry,
not guessing:

1. **Silhouette** of the front figure: the colour key with holes filled (puppet/checks.py),
   united with SAM 2.1's mask (puppet/segment.py), which keeps pale clothes that touch the
   background. A SAM mask far from the colour key (IoU < 0.85) is rejected and reported.
2. **Head:** the upper head, plus everything between the nose line and the neck that is
   coloured like it and connected to it. A scarf or collar stays with the torso, so turning
   the head doesn't drag the clothes along.
3. **Limbs by corridor:** a pixel belongs to a limb when it lies along that bone (between its
   joints, within about 1.4 limb radii of the bone line); the nearest bone wins. At the
   shoulders and hips the cut is the line through the joint, across the limb.
4. **Torso:** everything else (body, clothes, tail).
5. **Face:** dark marks in the face zone (eyes, brows, mouth) are painted over from the
   surrounding colours, and the nose stays. Where the marks were becomes the face block, so the
   vector face (face.py) sits where the artist drew it.
6. **Joint caps:** discs over the joints, so a bent elbow or a turned head shows no gap.
   Elbows and knees: both parts keep the sheet's own pixels (it is the same limb). Neck,
   shoulders and hips: the part drawn behind gets a disc painted from its own colours (hidden
   at rest), so a raised arm shows coat behind it, not background.
7. **Crop, pivots and attach points** in part pixels. Bones come from the skeleton, with Pip's
   names, roles, limits and draw order (D-048), so the motion library works unchanged.
8. **Arms hang at rest:** the arm parts are turned from the sheet's A-pose (25° out) to
   hanging straight down, Pip's rest, because motions are offsets tuned on that rest.

Also measured: **limb drift**, how far the drawn limb runs from its bone (the share of the
bone line inside the silhouette, and the offset of the limb's centre line). A limb that
drifts by more than its own radius would turn about the wrong point, and the report flags it.
"""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from studio_core.puppet.checks import (
    FG_THRESHOLD,
    SCALE,
    background,
    components,
    fill_holes,
    silhouette,
    skeleton_box,
)
from studio_core.puppet.consistency import ViewCut, compare_views
from studio_core.puppet.design import CANVAS, DesignError, design_dir, load_candidates
from studio_core.puppet.fit import fit_limbs
from studio_core.puppet.segment import segment_sheet
from studio_core.puppet.skeleton import (
    DRAW_ORDER,
    Skeleton,
    draw_order,
    rig_bones,
    turnaround,
)
from studio_core.rig import world_pose
from studio_core.shot_spec import FilmFolder, register_rig

LIMBS = (
    "upper_arm_l", "forearm_l", "upper_arm_r", "forearm_r",
    "thigh_l", "shin_l", "thigh_r", "shin_r",
)  # fmt: skip
END_LIMBS = {"forearm_l", "forearm_r", "shin_l", "shin_r"}  # hands and feet run past the joint
CORRIDOR = 1.4  # limb radii either side of the bone line
PALE_LUMA = 235  # a leg's highlight: lighter than this, it is white clothing's shine, not shading
DARK_LUMA = 100  # outline pixels are darker than this (0-255)
MARK_CONTRAST = 40  # face marks are this much darker than their surroundings (luma, 0-255)
NEIGHBOURS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


class BuildError(ValueError):
    """The puppet can't be built. The message says what to fix."""


@dataclass
class Built:
    rig: dict[str, Any]
    rig_path: Path
    report: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------------- pixel helpers


def _shift(a: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """`a` moved by (dy, dx), zero-filled: out[y, x] = a[y - dy, x - dx]."""
    out = np.zeros_like(a)
    h, w = a.shape[:2]
    out[max(dy, 0) : h + min(dy, 0), max(dx, 0) : w + min(dx, 0)] = a[
        max(-dy, 0) : h + min(-dy, 0), max(-dx, 0) : w + min(-dx, 0)
    ]
    return out


def _grow(mask: np.ndarray, px: int) -> np.ndarray:
    pil = Image.fromarray((mask * 255).astype("uint8")).filter(ImageFilter.MaxFilter(2 * px + 1))
    return np.asarray(pil) > 127


def _shrink(mask: np.ndarray, px: int) -> np.ndarray:
    pil = Image.fromarray((mask * 255).astype("uint8")).filter(ImageFilter.MinFilter(2 * px + 1))
    return np.asarray(pil) > 127


def _bbox(mask: np.ndarray, pad: int = 0) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    h, w = mask.shape
    return (
        max(0, int(xs.min()) - pad),
        max(0, int(ys.min()) - pad),
        min(w, int(xs.max()) + 1 + pad),
        min(h, int(ys.max()) + 1 + pad),
    )


def paint_from(rgb: np.ndarray, known: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Fill `target` pixels by spreading colours inward from `known` ones, one pixel ring per
    step (each new pixel = the mean of its known neighbours). A simple diffusion inpaint: right
    for flat cartoon colours, where it continues the surrounding fill smoothly."""
    out = rgb.astype("float32").copy()
    todo = target & ~known
    if not todo.any():
        return out
    x0, y0, x1, y1 = _bbox(todo, pad=2)
    sub, have, need = out[y0:y1, x0:x1], known[y0:y1, x0:x1].copy(), todo[y0:y1, x0:x1].copy()
    while need.any():
        total = np.zeros_like(sub)
        count = np.zeros(sub.shape[:2], dtype="float32")
        weighted = sub * have[..., None]
        for dy, dx in NEIGHBOURS:
            total += _shift(weighted, dy, dx)
            count += _shift(have.astype("float32"), dy, dx)
        ready = need & (count > 0)
        if not ready.any():
            break  # target pixels with no path to a known one stay as they were
        sub[ready] = total[ready] / count[ready][:, None]
        have |= ready
        need &= ~ready
    out[y0:y1, x0:x1] = sub
    return out


def _upscale(small: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    big = np.repeat(np.repeat(small, SCALE, axis=0), SCALE, axis=1)
    out = np.zeros(shape, dtype=bool)
    h, w = min(shape[0], big.shape[0]), min(shape[1], big.shape[1])
    out[:h, :w] = big[:h, :w]
    return out


# ------------------------------------------------------------------------------- silhouette


def figure_mask(img: np.ndarray, sk: Skeleton) -> tuple[np.ndarray, np.ndarray]:
    """The view's figure (colour key, enclosed holes filled) and the background colour."""
    bg, _ = background(img)
    mask = silhouette(img, bg)
    small = fill_holes(mask[::SCALE, ::SCALE], img[::SCALE, ::SCALE], bg)
    mask |= _upscale(small, mask.shape)
    x0, y0, x1, y1 = skeleton_box(sk, 0.15)
    keep = np.zeros_like(small)
    for blob in components(small):
        ys, xs = np.nonzero(blob)
        if x0 <= xs.mean() * SCALE <= x1 and y0 <= ys.mean() * SCALE <= y1:
            keep |= blob
    if not keep.any():
        raise BuildError(f"no {sk.view} figure where the skeleton is")
    return mask & _grow(_upscale(keep, mask.shape), 2), bg


# -------------------------------------------------------------------------------- the head


def _palette(pixels: np.ndarray, colors: int, min_share: float = 0.0) -> np.ndarray:
    """The main colours of a set of RGB pixels (median cut), dropping colours used by fewer
    than `min_share` of them (a few stray pixels of something else)."""
    strip = Image.fromarray(pixels.reshape(1, -1, 3).astype("uint8"))
    quantized = strip.quantize(colors, method=Image.Quantize.MEDIANCUT)
    counts = np.bincount(np.asarray(quantized).ravel(), minlength=colors)
    flat = quantized.getpalette()
    keep = [i for i, n in enumerate(counts) if n and n >= min_share * len(pixels)]
    return np.array([flat[3 * i : 3 * i + 3] for i in keep], dtype="float32")


def head_mask(img: np.ndarray, mask: np.ndarray, sk: Skeleton) -> np.ndarray:
    """Upper head (above the nose line) plus the head-coloured pixels below it, down to the
    neck, connected to it, with enclosed holes filled. Thin strands (a scarf's outline) are
    dropped by an opening. A muzzle in another colour below the nose line (Bo's cream one,
    task 4.9) joins too: see _between_the_cheeks."""
    nose_y, neck_y = sk.joints["nose"][1], sk.joints["neck"][1]
    rows = np.arange(mask.shape[0])[:, None]
    upper = mask & (rows < nose_y)
    band = mask & (rows >= nose_y) & (rows < neck_y)
    colors = _palette(img[upper], 10)
    near = np.full(mask.shape, np.inf, dtype="float32")
    for c in colors:
        near = np.minimum(near, np.linalg.norm(img - c, axis=2))
    candidate = upper | (band & (near < 38))
    candidate = _grow(_shrink(candidate, 3), 3) | upper
    x0, y0, x1, y1 = _bbox(candidate)
    head = np.zeros_like(mask)
    sub = candidate[y0:y1, x0:x1]
    top = upper[y0:y1, x0:x1]
    for blob in components(sub):
        if (blob & top).any():
            head[y0:y1, x0:x1] |= blob
    # Eyes, nose and mouth are darker than any head colour and thin strokes vanish in the
    # opening: they come back as holes, which belong to the head.
    head[y0:y1, x0:x1] = fill_holes(head[y0:y1, x0:x1])
    return _between_the_cheeks(head & mask, mask, int(nose_y), int(neck_y))


def _between_the_cheeks(head: np.ndarray, mask: np.ndarray, top: int, bottom: int) -> np.ndarray:
    """The rest of the face below the nose line, which the colour rule misses when it has its
    own colour (Bo's cream muzzle, task 4.9). Figure pieces in the band from the nose line to
    the neck join the head when they form a real region (1% of the head or more) and lie
    - between head pixels along their row: a muzzle between the cheeks
    - between head pixels along their column: a chin in a notch, with head above and below
    - inside the head's convex hull: the snout tip under a profile's nose, open on one side
    A scarf below the chin is none of these. Without this, the muzzle was cut onto the torso,
    stayed behind when the head turned, and kept its drawn mouth (only the head is cleaned).
    Kit's head is unchanged: his pale face reaches above the nose line."""
    top, bottom = max(0, top), min(bottom, mask.shape[0])
    between = np.zeros_like(mask)
    for y in range(top, bottom):
        xs = np.nonzero(head[y])[0]
        if len(xs) >= 2:
            between[y, xs.min() : xs.max() + 1] = True
    for x in range(mask.shape[1]):
        ys = np.nonzero(head[top:bottom, x])[0]
        if len(ys) >= 2:
            between[top + ys.min() : top + ys.max() + 1, x] = True
    between[top:bottom] |= _convex_hull(head)[top:bottom]
    out = head.copy()
    for blob in components(between & mask & ~head):
        if blob.sum() >= 0.01 * head.sum():
            out |= blob
    return out


def _convex_hull(mask: np.ndarray) -> np.ndarray:
    """The mask's convex hull, filled (Andrew's monotone chain over its pixels)."""
    ys, xs = np.nonzero(mask)
    if len(xs) < 3:
        return mask.copy()
    pts = sorted(set(zip(xs.tolist(), ys.tolist(), strict=True)))

    def turn(o: tuple[int, int], a: tuple[int, int], b: tuple[int, int]) -> int:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    chain: list[tuple[int, int]] = []
    for seq in (pts, pts[::-1]):  # the lower half, then the upper half
        half: list[tuple[int, int]] = []
        for p in seq:
            while len(half) >= 2 and turn(half[-2], half[-1], p) <= 0:
                half.pop()
            half.append(p)
        chain += half[:-1]
    canvas = Image.new("L", (mask.shape[1], mask.shape[0]), 0)
    ImageDraw.Draw(canvas).polygon([(float(x), float(y)) for x, y in chain], fill=255, outline=255)
    return np.asarray(canvas) > 127


# ---------------------------------------------------------------------------------- limbs


def _coords(shape: tuple[int, int], a: tuple[float, float], b: tuple[float, float]):
    """For every pixel: position along a→b (t, 0 at a, 1 at b) and signed distance from it."""
    ys, xs = np.mgrid[0 : shape[0], 0 : shape[1]].astype("float32")
    vx, vy = b[0] - a[0], b[1] - a[1]
    length2 = vx * vx + vy * vy
    t = ((xs - a[0]) * vx + (ys - a[1]) * vy) / length2
    d = ((xs - a[0]) * vy - (ys - a[1]) * vx) / math.sqrt(length2)
    return t, d


def _walk(mask: np.ndarray, x: float, y: float, nx: float, ny: float, limit: int) -> int | None:
    """Steps from (x, y) along (nx, ny) to the first background pixel; None if none in reach."""
    h, w = mask.shape
    for k in range(limit):
        px, py = round(x + nx * k), round(y + ny * k)
        if not (0 <= px < w and 0 <= py < h) or not mask[py, px]:
            return k
    return None


FAR_COVERAGE = 0.8  # a far-side limb is judged on coverage only (it overlaps the body)


def far_side_ok(fit: dict[str, Any]) -> bool:
    """A three-quarter far-side limb passes on how much of its bone line lies on the figure.
    0.8, not 0.85: a drawn sole sits a little short of the skeleton's ankle, so a shin that
    follows the drawing scores 17 of 21 samples (0.81) on Kit, Bo and Pim alike."""
    return bool(fit["coverage"] >= FAR_COVERAGE)


LEG_FITS = 0.7  # the leg fit's score above which the skeleton is on the legs (puppet/fit.py)


def touching_thigh_ok(fit: dict[str, Any], leg_report: dict[str, Any]) -> bool:
    """A thigh whose legs touch (Bo's dungarees) has a cross-section that runs on into the other
    leg, so its centre line reads as drifted by about a radius. The leg fit looks at the legs as
    bars under the torso instead, and when it found the skeleton already on them, the thigh passes
    on coverage alone."""
    on_skeleton = leg_report.get("skeleton_score", 0.0) >= LEG_FITS and not leg_report.get(
        "changed", False
    )
    return bool(fit["coverage"] >= 0.85 and (fit["drift"] <= 0.6 or on_skeleton))


def limb_fit(mask: np.ndarray, sk: Skeleton, bone: dict[str, Any]) -> dict[str, Any]:
    """How the drawn limb sits on its bone: radius, centre-line offset, coverage."""
    (ax, ay), (bx, by) = bone["joint_px"], bone["end_px"]
    length = math.hypot(bx - ax, by - ay)
    ux, uy = (bx - ax) / length, (by - ay) / length
    nx, ny = -uy, ux
    limit = int(sk.height_px * 0.15)
    radii, offsets, inside = [], [], []
    for t in np.linspace(0.0, 1.0, 21):
        x, y = ax + (bx - ax) * t, ay + (by - ay) * t
        inside.append(bool(mask[int(y), int(x)]) if 0 <= int(y) < mask.shape[0] else False)
        if not 0.2 <= t <= 0.9:
            continue
        plus, minus = _walk(mask, x, y, nx, ny, limit), _walk(mask, x, y, -nx, -ny, limit)
        if plus is not None and minus is not None:
            radii.append((plus + minus) / 2)
            offsets.append((plus - minus) / 2)
        elif plus is not None or minus is not None:  # one side runs into the body
            radii.append(plus if plus is not None else minus)
    # The lower quartile: a scarf end or a tail behind the limb widens some cross-sections,
    # never narrows them.
    lo, hi = sk.height_px * 0.025, sk.height_px * 0.1
    radius = float(np.clip(np.percentile(radii, 25) if radii else lo, lo, hi))
    offset = float(np.median(offsets)) if offsets else 0.0
    coverage = float(np.mean(inside))
    drift = abs(offset) / radius
    return {
        "radius_px": round(radius, 1),
        "offset_px": round(offset, 1),
        "coverage": round(coverage, 3),
        "drift": round(drift, 2),
        "ok": coverage >= 0.85 and drift <= 0.6,
    }


def join_leg_highlights(
    img: np.ndarray,
    mask: np.ndarray,
    head: np.ndarray,
    parts: dict[str, np.ndarray],
    bones: dict[str, dict],
    fits: dict[str, dict],
) -> None:
    """Give each leg the pale highlights inside it, in place. A highlight on a leg (Pim's cream
    trousers) isn't coloured like the leg's core, so the colour rule left it on the torso, where
    it stays behind when the leg moves. Pale pixels no limb owns, with the leg's own pixels on
    both sides of their row and inside its corridor, are the leg's. A coat hem or a tail lies to
    one side of a leg, not between its edges. (Mid-tone shading and dark seams between a leg's
    edges are left alone: that would change Kit.)"""
    pale = (img @ np.array([0.299, 0.587, 0.114], dtype="float32")) > PALE_LUMA
    for name in ("thigh_l", "shin_l", "thigh_r", "shin_r"):
        bone, r = bones[name], fits[name]["radius_px"]
        t, d = _coords(mask.shape, bone["joint_px"], bone["end_px"])
        free = mask & ~head & ~np.any([parts[n] for n in LIMBS], axis=0)
        mine = parts[name]
        left = np.maximum.accumulate(mine, axis=1)
        right = np.maximum.accumulate(mine[:, ::-1], axis=1)[:, ::-1]
        parts[name] = mine | (free & pale & left & right & (t >= 0) & (t <= 1.0) & (np.abs(d) <= r))


def assign_parts(
    img: np.ndarray,
    mask: np.ndarray,
    head: np.ndarray,
    bones: dict[str, dict],
    fits: dict[str, dict],
) -> dict[str, np.ndarray]:
    """bone name → its pixels (before caps). A limb only takes pixels coloured like its own
    core (the lower half of the limb, close to the bone line): all along an upper arm or a
    thigh, over the top 60% of a forearm or shin. A scarf end over the shoulder, a coat hem
    over the hip or a tail behind the leg stays with the torso, while wrists, paws and shoes,
    with their dark outlines, stay with the limb. A limb keeps only the pieces
    that touch its bone line, with enclosed holes filled (shading the colour rule missed)."""
    best = np.full(mask.shape, np.inf, dtype="float32")
    owner = np.full(mask.shape, -1, dtype="int8")
    lines = {}
    for i, name in enumerate(LIMBS):
        bone, r = bones[name], fits[name]["radius_px"]
        t, d = _coords(mask.shape, bone["joint_px"], bone["end_px"])
        t_min = 0.0 if bone["parent"] == "torso" else -0.2
        t_max = 1.35 if name in END_LIMBS else 1.15
        # Past the wrist or ankle (t > 0.85 of an end limb), paws and feet spread wider.
        width = np.where((t > 0.85) & (name in END_LIMBS), 2.2 * r, CORRIDOR * r) + 2
        corridor = mask & ~head & (t >= t_min) & (t <= t_max) & (np.abs(d) <= width)
        core = corridor & (t >= 0.55) & (t <= 0.9) & (np.abs(d) <= 0.6 * r)
        if core.any():  # its own colours: a whole upper arm or thigh, a forearm or shin's top
            colors = _palette(img[core], 6, min_share=0.05)
            near = np.min([np.linalg.norm(img - c, axis=2) for c in colors], axis=0)
            corridor &= (near < 40) | (t > (1.0 if name not in END_LIMBS else 0.6))
        score = np.abs(d) / r
        better = corridor & (score < best)
        best[better], owner[better] = score[better], i
        lines[name] = (np.abs(d) <= 0.5 * r) & (t >= t_min) & (t <= t_max)
    parts = {}
    claimed = owner >= 0  # holes may only take pixels no limb owns
    for i, name in enumerate(LIMBS):
        mine = owner == i
        keep = np.zeros_like(mine[::2, ::2])
        for piece in components(mine[::2, ::2]) if mine.any() else []:
            if (piece & lines[name][::2, ::2]).any():
                keep |= piece
        full = _grow(np.repeat(np.repeat(keep, 2, axis=0), 2, axis=1), 1)
        dropped = mine & ~full[: mine.shape[0], : mine.shape[1]]
        mine &= ~dropped
        claimed &= ~dropped
        if mine.any():
            x0, y0, x1, y1 = _bbox(mine, pad=1)
            holes = np.zeros_like(mine)
            holes[y0:y1, x0:x1] = fill_holes(mine[y0:y1, x0:x1])
            holes &= mask & ~head & ~claimed
            mine |= holes
            claimed |= holes
        parts[name] = mine
    parts["head"] = head
    join_leg_highlights(img, mask, head, parts, bones, fits)
    taken = np.any([parts[n] for n in LIMBS], axis=0) | head
    torso = mask & ~taken
    # Fur wisps along a limb's outline fall just outside its corridor and would stay on the
    # torso, where they show once the arm moves. Thin torso pixels near a limb go to it.
    thin = torso & ~_grow(_shrink(torso, 3), 3)
    for name in LIMBS:
        bone, r = bones[name], fits[name]["radius_px"]
        t, d = _coords(mask.shape, bone["joint_px"], bone["end_px"])
        near = thin & (t >= -0.1) & (t <= 1.2) & (np.abs(d) <= 2.2 * r)
        parts[name] |= near
        thin &= ~near
        torso &= ~near
    parts["torso"] = torso
    return parts


# ----------------------------------------------------------------------------------- face


def _blobs(mask: np.ndarray, min_px: int = 6) -> list[dict[str, Any]]:
    out = []
    for b in components(mask):
        ys, xs = np.nonzero(b)
        if len(xs) < min_px:
            continue
        out.append(
            {
                "mask": b,
                "area": len(xs),
                "cx": float(xs.mean()),
                "cy": float(ys.mean()),
                "w": int(xs.max() - xs.min() + 1),
                "h": int(ys.max() - ys.min() + 1),
                "bottom": int(ys.max()),
            }
        )
    return out


def clean_face(
    rgb: np.ndarray, head: np.ndarray, sk: Skeleton, *, no_nose: bool = False
) -> tuple[np.ndarray, dict[str, Any], dict[str, Any]]:
    """Paint out the drawn eyes, brows and mouth; keep the nose. Returns the new pixels, the
    face anchors in canvas pixels, and notes on what was found.

    Nothing assumes a symmetric face (the three-quarter view): the **nose** is the solid dark
    blob nearest the skeleton's nose line, the **eyes** the two best marks above it (big, and
    low rather than high, so not the brows) far enough apart, the **mouth** the marks below
    it.

    A face with no dark nose (a bird: a light beak, dark eyes) would give its eye to the nose
    and leave no eye. When the mark taken for the nose leaves no eye above it, the face is read
    again with no nose at all (`no_nose`): the marks are eyes, and the mouth is wherever the
    skeleton has it."""
    hx0, hy0, hx1, hy1 = _bbox(head)
    nose_row = int(sk.joints["nose"][1])
    xs = np.nonzero(head[nose_row])[0]
    row_w = float(xs.max() - xs.min() + 1) if len(xs) else float(hx1 - hx0)
    cx = float(xs.min() + xs.max()) / 2 if len(xs) else (hx0 + hx1) / 2
    luma = rgb @ np.array([0.299, 0.587, 0.114], dtype="float32")
    # The nose: the biggest solid, near-black mark around the nose line, looked for anywhere in
    # the head, because a turned head's nose sits on its outline, outside the face zone. Eyes
    # are smaller, outlines are thin, mouths are rarely black and never compact. (It was the
    # lowest such mark until Bo, task 4.9, whose open mouth is a black blob under the nose.)
    band = head.copy()
    band[: max(0, int(nose_row - 0.25 * row_w))] = False
    band[int(nose_row + 0.3 * row_w) :] = False
    blacks: list[dict[str, Any]] = []
    if band.any():
        bx0, by0, bx1, by1 = _bbox(band)
        black = (band & (luma < 60))[by0:by1, bx0:bx1]

        def noses(found_blobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
            out = []
            for b in found_blobs:
                compact = max(b["w"], b["h"]) <= 3 * min(b["w"], b["h"])  # not a mouth line
                if (
                    compact
                    and b["area"] / (b["w"] * b["h"]) >= 0.45
                    and b["area"] >= (0.03 * row_w) ** 2
                ):
                    out.append(b)
            return out

        blacks = [] if no_nose else noses(_blobs(black))
        # A nose drawn on the outline joins it into one long blob (Bo's three-quarter view,
        # whose eye was then taken for the nose and kept). Without the thin strokes it stands
        # free; pieces that overlap a mark already found add nothing.
        stroke = max(2, int(0.015 * row_w))
        freed = _grow(_shrink(black, stroke), stroke) & black
        blacks += (
            []
            if no_nose
            else [
                b
                for b in noses(_blobs(freed))
                if not any((b["mask"] & k["mask"]).any() for k in blacks)
            ]
        )
        for b in blacks:
            b["cx"], b["cy"], b["bottom"] = b["cx"] + bx0, b["cy"] + by0, b["bottom"] + by0
    nose = max(blacks, key=lambda b: b["area"]) if blacks else None
    nose_px = np.zeros_like(head)  # the nose's own pixels, on the canvas
    if nose is not None:
        nose_px[by0:by1, bx0:bx1] = nose["mask"]
    zone = _shrink(head, max(3, int(row_w * 0.05)))
    zone[: int(hy0 + 0.35 * (hy1 - hy0))] = False
    zone[:, : int(cx - 0.42 * row_w)] = False
    zone[:, int(cx + 0.42 * row_w) :] = False
    if nose is not None:
        # A turned head's mouth sits by its snout, beside the nose and below it, outside the
        # zone (Bo's three-quarter view, task 4.9: his open mouth and smile stayed drawn).
        # The zone also takes in a box around and below the nose, a few pixels inside the
        # outline, never the nose itself.
        n_ys, n_xs = np.nonzero(nose_px)
        snout = np.zeros_like(head)
        snout[
            n_ys.min() : int(n_ys.max() + 0.3 * row_w),
            max(0, int(n_xs.min() - 0.15 * row_w)) : n_xs.max() + 1,
        ] = True
        zone |= snout & _shrink(head, 6) & ~_grow(nose_px, 3)
    # A mark is clearly darker than its surroundings (a light brow stroke on a cream muzzle
    # counts; the shading of orange fur doesn't).
    around = Image.fromarray(np.clip(luma, 0, 255).astype("uint8")).filter(
        ImageFilter.BoxBlur(max(4, int(row_w * 0.04)))
    )
    dark = zone & (luma < np.asarray(around, dtype="float32") - MARK_CONTRAST)
    x0, y0, x1, y1 = _bbox(zone)
    found = _blobs(dark[y0:y1, x0:x1])
    for b in found:
        b["cx"], b["cy"], b["bottom"] = b["cx"] + x0, b["cy"] + y0, b["bottom"] + y0
        b["solid"] = b["area"] / (b["w"] * b["h"]) >= 0.45 and b["area"] >= (0.025 * row_w) ** 2
    solid = [b for b in found if b["solid"]]
    if nose is None and not no_nose:
        # No black nose. Open eyes are a pair of solid marks at one height and the nose is the
        # solid mark just below them; with closed (arc) eyes there is no pair, and the solid
        # mark nearest the skeleton's nose line, preferring the centre, is the nose.
        pairs = [
            (a, b)
            for i, a in enumerate(solid)
            for b in solid[i + 1 :]
            if abs(a["cy"] - b["cy"]) < 0.08 * row_w and abs(a["cx"] - b["cx"]) > 0.12 * row_w
        ]
        if pairs:
            # Two eyes match in size and height; a nose next to an eye doesn't.
            pair = min(
                pairs,
                key=lambda ab: (
                    abs(math.log(ab[0]["area"] / ab[1]["area"]))
                    + abs(ab[0]["cy"] - ab[1]["cy"]) / (0.08 * row_w)
                ),
            )
            eye_y = (pair[0]["cy"] + pair[1]["cy"]) / 2
            below = [b for b in solid if all(b is not e for e in pair) and b["cy"] > eye_y]
            nose = min(below, key=lambda b: b["cy"]) if below else None
        elif solid:
            nose = min(solid, key=lambda b: abs(b["cy"] - nose_row) + 0.5 * abs(b["cx"] - cx))

    def on_nose(b: dict[str, Any]) -> bool:
        return nose is not None and (
            abs(b["cx"] - nose["cx"]) <= nose["w"] / 2 + 2
            and abs(b["cy"] - nose["cy"]) <= nose["h"] / 2 + 2
        )

    # A mark joined to the nose (Bo's three-quarter view: the nose on the outline, an open
    # mouth drawn under it) is painted out except for the nose and a rim around it.
    keep = _grow(nose_px, 3)[y0:y1, x0:x1]
    marks = []
    for b in found:
        if b is nose or on_nose(b):
            continue
        if not (b["mask"] & keep).any():
            marks.append(b)
            continue
        for rest in _blobs(b["mask"] & ~keep):
            rest["cx"], rest["cy"], rest["bottom"] = (
                rest["cx"] + x0,
                rest["cy"] + y0,
                rest["bottom"] + y0,
            )
            rest["solid"] = False
            marks.append(rest)
    nose_y = nose["cy"] if nose else sk.joints["nose"][1]
    if no_nose:  # the eyes sit by the skeleton's nose line here, not above it
        nose_y += 0.12 * row_w
    nx = nose["cx"] if nose else sk.joints["nose"][0]
    # Eyes sit a little above the nose and within about half a head of it: further back or
    # higher, a turned head's marks are ear shading, not a far eye.
    above = [
        b
        for b in marks
        if nose_y - (0.5 if no_nose else 0.25) * row_w < b["cy"] < nose_y - 0.02 * row_w
        and abs(b["cx"] - nx) < 0.45 * row_w
        and max(b["w"], b["h"]) <= (2 if no_nose else 4) * min(b["w"], b["h"])  # a dot, not a line
    ]
    if above == [] and nose is not None and not no_nose:
        return clean_face(rgb, head, sk, no_nose=True)
    top = min((b["cy"] for b in above), default=nose_y)

    def score(b: dict[str, Any]) -> float:  # big, and lower (eyes) rather than higher (brows)
        return b["area"] * (1 + 2 * (b["cy"] - top) / max(1.0, nose_y - top))

    eyes: dict[str, dict[str, Any]] = {}
    ranked = sorted(above, key=score, reverse=True)
    if ranked:
        first = ranked[0]
        second = next(
            (
                b
                for b in ranked[1:]
                if abs(b["cx"] - first["cx"]) > 0.12 * row_w
                and (not no_nose or b["area"] >= 0.35 * first["area"])  # not an arc or a speck
            ),
            None,
        )
        pair = sorted([b for b in (first, second) if b], key=lambda b: b["cx"])
        if len(pair) == 2:
            eyes = {"right": pair[0], "left": pair[1]}  # the character's left is screen-right
        else:
            # One eye: the side whose skeleton eye sits at the most similar offset from the nose
            # (a turned face shows the near eye, well behind the nose).
            offset = first["cx"] - nx
            side = min(
                ("left", "right"),
                key=lambda e: abs(offset - (sk.joints[f"{e[0]}_eye"][0] - sk.joints["nose"][0])),
            )
            eyes = {side: first}
    mouth = [b for b in marks if b["cy"] > nose_y and abs(b["cx"] - nx) < 0.25 * row_w]

    remove = np.zeros_like(head)
    for b in marks:
        remove[y0:y1, x0:x1] |= b["mask"]
    # A pupil inside an eye's ring isn't darker than its own surroundings: fill the rings.
    remove[y0:y1, x0:x1] = fill_holes(remove[y0:y1, x0:x1])
    remove = _grow(remove, 3) & head
    cleaned = paint_from(rgb, head & ~remove, remove)

    skel = {"left": sk.joints["l_eye"], "right": sk.joints["r_eye"]}
    if len(eyes) == 1:  # place the other where the skeleton has it, relative to this one
        ((side, b),) = eyes.items()
        other = "right" if side == "left" else "left"
        dx, dy = skel[other][0] - skel[side][0], skel[other][1] - skel[side][1]
        eyes[other] = {**b, "cx": b["cx"] + dx, "cy": b["cy"] + dy, "inferred": True}
    at = {s: (eyes[s]["cx"], eyes[s]["cy"]) if s in eyes else skel[s] for s in ("left", "right")}
    eye_dist = max(abs(at["left"][0] - at["right"][0]), 0.15 * row_w)
    if eyes:
        e = max(eyes.values(), key=lambda b: b["area"])
        drawn = e["h"] * 1.1 if e["h"] > 0.6 * e["w"] else e["w"] * 0.9  # open eye or closed arc
    else:
        drawn = 0.45 * eye_dist
    eye_size = float(np.clip(drawn, 0.35 * eye_dist, 0.55 * eye_dist))
    if mouth:
        mx = float(np.mean([b["cx"] for b in mouth]))
        my = float(np.mean([b["cy"] for b in mouth]))
        mw = max(b["cx"] + b["w"] / 2 for b in mouth) - min(b["cx"] - b["w"] / 2 for b in mouth)
    else:
        mx, my = nx, (nose["bottom"] if nose else nose_y) + 0.2 * eye_dist
        mw = 0.5 * eye_dist
    outline = head & ~zone & (luma < DARK_LUMA)
    line = np.median(rgb[outline], axis=0) if outline.any() else np.array([70, 52, 48])
    anchors = {
        "eyes": {"left": at["left"], "right": at["right"], "size": eye_size},
        "brows": {
            "left": (at["left"][0], at["left"][1] - 0.95 * eye_size),
            "right": (at["right"][0], at["right"][1] - 0.95 * eye_size),
            "width": 0.55 * eye_dist,
        },
        "mouth": {"at": (mx, my), "width": float(np.clip(mw, 0.3 * eye_dist, 0.8 * eye_dist))},
        "line": "#{:02x}{:02x}{:02x}".format(*(int(v) for v in line)),
    }
    notes = {
        "nose_found": nose is not None,
        "nose_px": [round(nose["cx"], 1), round(nose["cy"], 1)] if nose else None,
        "eyes_found": sorted(k for k, b in eyes.items() if not b.get("inferred")),
        "mouth_marks": len(mouth),
        "marks_painted_over": len(marks),
        "head_width_px": round(row_w, 1),
    }
    return cleaned, anchors, notes


def emergence(figure: np.ndarray, bone: dict[str, Any], r: float) -> float:
    """Where along a bone (t, 0 = joint) the drawn limb comes out from behind the body. Walked
    from the far end inward: the limb is narrow (its cross-section reaches background within
    2.5 radii on both sides) until it enters the body. Walking outward from the shoulder
    instead is fooled by gaps above the shoulders (a near-horizontal arm's cross-section is
    vertical there)."""
    (ax, ay), (bx, by) = bone["joint_px"], bone["end_px"]
    length = math.hypot(bx - ax, by - ay)
    nx, ny = -(by - ay) / length, (bx - ax) / length
    limit = int(2.5 * r) + 1
    steps = np.linspace(0.9, 0.0, 46)
    for prev, t in pairwise(steps):
        x, y = ax + (bx - ax) * t, ay + (by - ay) * t
        narrow = _walk(figure, x, y, nx, ny, limit) is not None and (
            _walk(figure, x, y, -nx, -ny, limit) is not None
        )
        if not narrow:
            return float(prev)
    return 0.0


MOSTLY_HIDDEN = 0.75  # an upper arm emerging this far along is a plain sleeve, whatever it shows
SLEEVE_MATCH = 40.0  # RGB distance: the shown sleeve and the forearm are one fabric


def complete_hidden(
    rgb: np.ndarray,
    figure: np.ndarray,
    parts: dict[str, np.ndarray],
    bones: dict[str, dict],
    fits: dict[str, dict],
    order: tuple[str, ...],
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Arms drawn *behind* the torso (the far arm in a three-quarter view) start where they
    come out from behind the body: corridor pixels before that are the torso's (a scarf, the
    chest), and the hidden stretch back to the joint is painted from the sleeve's own colours,
    so a raised arm shows a whole sleeve. An upper arm that is mostly hidden becomes a plain
    sleeve in the forearm's colour. Returns, per hidden arm, where it emerges and
    the masks to fill, and notes."""
    fills: dict[str, dict[str, Any]] = {}
    notes: dict[str, Any] = {}
    rank = {name: i for i, name in enumerate(order)}
    for name in ("upper_arm_l", "upper_arm_r", "forearm_l", "forearm_r"):
        if rank[name] > rank["torso"]:
            continue  # in front of the torso: drawn whole
        bone, r = bones[name], fits[name]["radius_px"]
        t_e = emergence(figure, bone, r)
        if t_e <= 0.05:
            continue
        t, d = _coords(figure.shape, bone["joint_px"], bone["end_px"])
        sleeve = name.startswith("upper") and t_e >= 0.5
        if sleeve and t_e < MOSTLY_HIDDEN:
            # Half hidden: the part that shows is the arm's own sleeve. A plain sleeve in the
            # forearm's colour stands in for it only when that is the sleeve's colour (Bo: the
            # same fur). A sleeve of its own (Pim's white one over a blue forearm) is cut as it
            # is drawn, so it moves with the arm instead of staying behind on the torso.
            luma = rgb @ np.array([0.299, 0.587, 0.114], dtype="float32")
            shows = rgb[parts[name] & (t >= t_e) & (luma > 80)]
            forearm = rgb[parts["forearm" + name[-2:]] & (luma > 80)]
            if len(shows) and len(forearm):
                gap = np.linalg.norm(np.median(shows, axis=0) - np.median(forearm, axis=0))
                sleeve = bool(gap <= SLEEVE_MATCH)
        # A plain sleeve replaces the whole upper arm, so all its cut pixels go back.
        before = parts[name] & (t < t_e) if not sleeve else parts[name].copy()
        parts[name] &= ~before
        parts["torso"] |= before
        ends = _disc(figure.shape, bone["joint_px"], r) | _disc(figure.shape, bone["end_px"], r)
        fills[name] = {
            "t": t_e,
            "sleeve": sleeve,
            "stretch": (t >= 0) & (t < t_e + 0.05) & (np.abs(d) <= r),
            "whole": ((t >= 0) & (t <= 1) & (np.abs(d) <= r)) | ends,
        }
        notes[name] = {"emerges_at_t": round(t_e, 2), "drawn": "sleeve" if sleeve else "fill"}
    return fills, notes


# ----------------------------------------------------------------------------------- caps


def _disc(shape: tuple[int, int], centre: tuple[float, float], r: float) -> np.ndarray:
    ys, xs = np.ogrid[0 : shape[0], 0 : shape[1]]
    return (xs - centre[0]) ** 2 + (ys - centre[1]) ** 2 <= r * r


def add_caps(
    rgb: np.ndarray,
    mask: np.ndarray,
    parts: dict[str, np.ndarray],
    bones: dict[str, dict],
    fits: dict[str, dict],
    height_px: float,
    order: tuple[str, ...] = DRAW_ORDER,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Each part's final mask and pixels, with discs over the joints.

    - Elbows and knees (one limb): both parts get the sheet's own pixels in a disc.
    - Neck, shoulders and hips: only the part drawn *behind* gets a disc, painted from its own
      colours (the torso behind the head and arms, the thighs behind the torso). It is hidden
      at rest, and fills the gap when either part turns. A disc on the front part would
      change the rest look (a pale circle of chin on the scarf)."""
    masks = {name: m.copy() for name, m in parts.items()}
    pixels = {name: rgb.copy() for name in parts}
    rank = {name: i for i, name in enumerate(order)}
    for child, bone in bones.items():
        parent = bone["parent"]
        if parent is None:
            continue
        joint = bone["joint_px"]
        if child != "head" and parent != "torso":
            r = max(fits[child]["radius_px"], fits[parent]["radius_px"])
            for name in (parent, child):
                masks[name] |= _disc(mask.shape, joint, r) & mask
            continue
        behind = min((parent, child), key=rank.__getitem__)
        r = 0.09 * height_px if child == "head" else 1.1 * fits[child]["radius_px"]
        disc = _disc(mask.shape, joint, r) & mask & ~parts[behind]
        pixels[behind] = paint_from(pixels[behind], parts[behind], disc)
        masks[behind] |= disc
    return masks, pixels


# ------------------------------------------------------------------------------ the rig


def _alpha(img: np.ndarray, figure: np.ndarray, bg: np.ndarray) -> np.ndarray:
    """1 inside; near the figure's outer edge (3 px), how far each pixel is from the background
    colour. Antialiased outline pixels are part background, and the silhouette's clean-up
    traps a few background pixels in the nooks between fur tufts: both would show as a light
    fringe on another background."""
    edge = figure & ~_shrink(figure, 3)
    alpha = np.ones(figure.shape, dtype="float32")
    dist = np.linalg.norm(img - bg, axis=2)
    alpha[edge] = np.clip((dist[edge] - 0.5 * FG_THRESHOLD) / (2.5 * FG_THRESHOLD), 0.0, 1.0)
    return alpha * figure


def _unmix(rgb: np.ndarray, alpha: np.ndarray, bg: np.ndarray) -> np.ndarray:
    """Take the background's share out of semi-transparent edge pixels (no light halo)."""
    a = np.maximum(alpha, 1e-3)[..., None]
    return np.clip((rgb - (1 - a) * bg) / a, 0, 255)


def palette(img: np.ndarray, figure: np.ndarray, colors: int = 6) -> list[dict[str, Any]]:
    """The puppet's main colours with their share of the figure, most used first."""
    pixels = img[figure]
    centres = _palette(pixels, colors)
    nearest = np.argmin(np.stack([np.linalg.norm(pixels - c, axis=1) for c in centres]), axis=0)
    shares = np.bincount(nearest, minlength=len(centres)) / len(pixels)
    order = np.argsort(-shares)
    return [
        {"hex": "#{:02x}{:02x}{:02x}".format(*(int(v) for v in centres[i])), "share": round(
            float(shares[i]), 3)}
        for i in order
    ]  # fmt: skip


def _rotate_point(
    x: float, y: float, c: tuple[float, float], c2: tuple[float, float], deg: float
) -> tuple[float, float]:
    """Where image pixel (x, y) lands when the image turns `deg` counter-clockwise about its
    centre `c` and the result (expanded) has centre `c2`. Image coordinates, y down."""
    r = math.radians(deg)
    dx, dy = x - c[0], y - c[1]
    return (
        c2[0] + dx * math.cos(r) + dy * math.sin(r),
        c2[1] - dx * math.sin(r) + dy * math.cos(r),
    )


def hang_arms(folder: Path, view: dict[str, Any]) -> dict[str, float]:
    """Turn each arm's parts so the arm rests hanging straight down (-90°), like Pip's.

    The sheet's A-pose holds the arms 25° out so they can be cut cleanly (D-048), but the
    motions are offsets from rest tuned on hanging arms: a wave's +150° would point an A-pose
    arm straight up behind the head. Baking the turn into the art keeps the rig format, the
    motions and the engine unchanged. Returns the turn applied per arm bone."""
    turned = {}
    for side in ("l", "r"):
        upper, fore = view["bones"][f"upper_arm_{side}"], view["bones"][f"forearm_{side}"]
        delta = -90.0 - upper["direction_deg"]
        for name in (f"upper_arm_{side}", f"forearm_{side}"):
            part = view["parts"][name]
            path = folder / part["file"]
            art = Image.open(path)
            c = (art.width / 2, art.height / 2)
            out = art.rotate(delta, Image.Resampling.BICUBIC, expand=True)
            c2 = (out.width / 2, out.height / 2)
            out.save(path)
            px, py = _rotate_point(*part["pivot_px"], c, c2, delta)
            part["pivot_px"], part["size_px"] = (
                [round(px, 1), round(py, 1)],
                [out.width, out.height],
            )
            if name.startswith("upper_arm"):
                ax, ay = _rotate_point(*fore["attach"]["at_px"], c, c2, delta)
                fore["attach"]["at_px"] = [round(ax, 1), round(ay, 1)]
            view["bones"][name]["direction_deg"] = round(
                view["bones"][name]["direction_deg"] + delta, 2
            )
            turned[name] = round(delta, 2)
    return turned


def _add_sam(
    film_root: Path,
    sheet: Path,
    skeletons: list[Skeleton],
    keys: dict[str, np.ndarray],
    folder: Path,
) -> tuple[dict[str, np.ndarray], dict[str, dict[str, Any]]]:
    """Each view's colour-key figure plus SAM 2.1's (puppet/segment.py), in one run. The union
    keeps both the fur tufts SAM trims and the pale clothes the colour key loses against the
    background. If the two disagree badly, SAM's prompt went wrong: keep the colour key and
    say so."""
    paths = segment_sheet(film_root, sheet, skeletons, folder / "build" / "segment")
    figures, notes = {}, {}
    for sk, path in zip(skeletons, paths, strict=True):
        key = keys[sk.view]
        mask = np.asarray(Image.open(path)) > 127
        iou = float((mask & key).sum() / max(1, (mask | key).sum()))
        if iou < 0.85:
            figures[sk.view] = key
            notes[sk.view] = {
                "method": "colour key",
                "sam_iou": round(iou, 3),
                "sam_rejected": True,
            }
        else:
            figures[sk.view] = key | (mask & _grow(key, int(sk.height_px * 0.05)))
            notes[sk.view] = {"method": "colour key + SAM 2.1", "sam_iou": round(iou, 3)}
    return figures, notes


@dataclass
class _Cut:
    view: dict[str, Any]  # the rig view (bones, parts, draw order, face)
    report: dict[str, Any]
    for_consistency: ViewCut


def _cut_view(
    img: np.ndarray,
    sk: Skeleton,
    figure: np.ndarray,
    bg: np.ndarray,
    folder: Path,
) -> _Cut:
    """Cut one figure of the sheet into a rig view: parts/<view>/*.png and the view's bones,
    parts, draw order and face block. Debug images go to build/<view>/."""
    order = draw_order(sk.view)
    # Limbs drawn elsewhere than the skeleton's (a klein three-quarter figure: arms at other
    # angles and lengths, legs apart) are found first, so the bones and the cut follow the
    # drawing (puppet/fit.py). A drawing that follows the skeleton is left as it is.
    sk, limbs_fitted = fit_limbs(figure, sk)
    bones = rig_bones(sk)
    fits = {limb: limb_fit(figure, sk, bones[limb]) for limb in LIMBS}
    # No limb much thicker than its mirror (the three-quarter view's near side may be wider).
    allow = 1.3 if sk.view == "front" else 1.6
    for limb in LIMBS:
        mirror = fits[limb[:-1] + ("r" if limb.endswith("l") else "l")]
        fits[limb]["radius_px"] = min(
            fits[limb]["radius_px"], round(allow * mirror["radius_px"], 1)
        )
    if sk.view == "three_quarter":
        # The far side (the character's left) overlaps the body in this view: a cross-section
        # runs on into the torso, so drift can't be read from it. Judge coverage only.
        for limb in LIMBS:
            if limb.endswith("_l"):
                fits[limb]["ok"] = far_side_ok(fits[limb])
                fits[limb]["drift_judged"] = False
    for side in ("l", "r"):
        thigh = f"thigh_{side}"
        if not fits[thigh]["ok"] and touching_thigh_ok(fits[thigh], limbs_fitted[f"leg_{side}"]):
            fits[thigh]["ok"] = True
            fits[thigh]["drift_judged"] = False
    head = head_mask(img, figure, sk)
    parts = assign_parts(img, figure, head, bones, fits)
    rgb, anchors, face_notes = clean_face(img, head, sk)
    hidden, hidden_notes = complete_hidden(rgb, figure, parts, bones, fits, order)
    masks, pixels = add_caps(rgb, figure, parts, bones, fits, sk.height_px, order)
    drawn: dict[str, np.ndarray] = {}  # pixels made here, not cut: opaque wherever they are
    luma = rgb @ np.array([0.299, 0.587, 0.114], dtype="float32")
    for name, info in hidden.items():
        fore = "forearm" + name[-2:]
        if name.startswith("upper") and info["sleeve"]:
            # Mostly hidden (it comes out from behind the body near the elbow): a plain sleeve
            # in the forearm's colour with a darker edge, instead of whatever lies over it.
            shape = info["whole"]
            sleeve = np.median(rgb[parts[fore] & (luma > 80)], axis=0)
            pixels[name] = np.where(shape[..., None], sleeve, pixels[name])
            pixels[name][shape & ~_shrink(shape, 2)] = 0.55 * sleeve
            masks[name] = shape
            drawn[name] = shape
            # The forearm's elbow disc came from the sheet, where the scarf or the body lies:
            # repaint it from the forearm's own pixels.
            cap = masks[fore] & ~parts[fore]
            pixels[fore] = paint_from(pixels[fore], parts[fore], cap)
            drawn[fore] = cap
        else:  # partly hidden: the stretch behind the body, from the arm's own visible pixels
            fill = info["stretch"] & ~masks[name]
            pixels[name] = paint_from(pixels[name], parts[name], fill)
            masks[name] |= fill
            drawn[name] = fill
    alpha = _alpha(img, figure, bg)

    parts_dir = folder / "parts" / sk.view
    parts_dir.mkdir(parents=True)
    origins: dict[str, tuple[int, int]] = {}
    rig_parts: dict[str, dict] = {}
    for bone_name in order:
        m = masks[bone_name]
        x0, y0, x1, y1 = _bbox(m, pad=2)
        # The image must hold its pivot and its children's joints, even where the art stops
        # short of them (the head ends at the chin, above the neck joint): transparent margin.
        joints = [bones[bone_name]["joint_px"]] + [
            b["joint_px"] for b in bones.values() if b["parent"] == bone_name
        ]
        x0 = max(0, min(x0, *(int(x) - 2 for x, _ in joints)))
        y0 = max(0, min(y0, *(int(y) - 2 for _, y in joints)))
        x1 = min(m.shape[1], max(x1, *(int(x) + 3 for x, _ in joints)))
        y1 = min(m.shape[0], max(y1, *(int(y) + 3 for _, y in joints)))
        a = np.where(m, alpha, 0)
        if bone_name in drawn:
            a = np.where(drawn[bone_name], 1.0, a)
        a = a[y0:y1, x0:x1]
        color = _unmix(pixels[bone_name][y0:y1, x0:x1], a, bg)
        rgba = np.dstack([color, a * 255]).round().astype("uint8")
        Image.fromarray(rgba, "RGBA").save(parts_dir / f"{bone_name}.png")
        jx, jy = bones[bone_name]["joint_px"]
        origins[bone_name] = (x0, y0)
        rig_parts[bone_name] = {
            "file": f"parts/{sk.view}/{bone_name}.png",
            "size_px": [x1 - x0, y1 - y0],
            "pivot_px": [round(jx - x0, 1), round(jy - y0, 1)],
            "bone": bone_name,
        }
    rig_bones_out: dict[str, dict] = {}
    for bone_name, bone in bones.items():
        entry = {
            "role": bone["role"],
            "parent": bone["parent"],
            "direction_deg": bone["direction_deg"],
            "length_px": bone["length_px"],
            "side": bone["side"],
            "limits_deg": bone["limits_deg"],
        }
        if bone["parent"]:
            px, py = origins[bone["parent"]]
            jx, jy = bone["joint_px"]
            entry["attach"] = {
                "part": bone["parent"],
                "at_px": [round(jx - px, 1), round(jy - py, 1)],
            }
        rig_bones_out[bone_name] = entry

    hx, hy = origins["head"]

    def local(p: tuple[float, float]) -> list[float]:
        return [round(p[0] - hx, 1), round(p[1] - hy, 1)]

    view = {
        "root": "torso",
        "bones": rig_bones_out,
        "parts": rig_parts,
        "draw_order": list(order),
        "face": {
            "part": "head",
            "eyes": {
                "left_px": local(anchors["eyes"]["left"]),
                "right_px": local(anchors["eyes"]["right"]),
                "size_px": round(anchors["eyes"]["size"], 1),
            },
            "brows": {
                "left_px": local(anchors["brows"]["left"]),
                "right_px": local(anchors["brows"]["right"]),
                "width_px": round(anchors["brows"]["width"], 1),
            },
            "mouth": {
                "at_px": local(anchors["mouth"]["at"]),
                "width_px": round(anchors["mouth"]["width"], 1),
            },
            "colors": {"line": anchors["line"], "iris": anchors["line"]},
        },
    }
    hung = hang_arms(folder, view)
    report = {
        "limbs_fitted": limbs_fitted,
        "hidden_limbs": hidden_notes,
        "limbs": fits,
        "limbs_ok": all(f["ok"] for f in fits.values()),
        "face": face_notes,
        "parts_px": {n: p["size_px"] for n, p in rig_parts.items()},
        "arms_turned_to_hang_deg": hung,
    }
    debug = folder / "build" / sk.view
    debug.mkdir(parents=True, exist_ok=True)
    _debug_images(debug, img, rgb, parts, head)
    poses = [compose(view, folder, offsets) for offsets in POSES.values()]
    strip = Image.new("RGBA", (900 * len(poses), 900), (250, 248, 244, 255))
    for i, im in enumerate(poses):
        strip.alpha_composite(im, (900 * i, 0))
    strip.convert("RGB").save(debug / "poses.png")
    return _Cut(view, report, ViewCut(sk, parts))


def _match_face(front: _Cut, other: _Cut) -> None:
    """The other view's vector face takes the front's eye size, brow width and mouth width,
    scaled by head width. The eyes are part of who the character is: a redrawn view may draw
    them as tiny dots, but the puppet's eyes must look the same from every side."""
    scale = other.report["face"]["head_width_px"] / front.report["face"]["head_width_px"]
    f, o = front.view["face"], other.view["face"]
    size = round(f["eyes"]["size_px"] * scale, 1)
    o["eyes"]["size_px"] = size
    for side in ("left", "right"):
        x, y = o["eyes"][f"{side}_px"]
        o["brows"][f"{side}_px"] = [x, round(y - 0.95 * size, 1)]
    o["brows"]["width_px"] = round(f["brows"]["width_px"] * scale, 1)
    o["mouth"]["width_px"] = round(f["mouth"]["width_px"] * scale, 1)


def build_puppet(
    film_root: Path,
    character_id: str,
    *,
    name: str | None = None,
    candidate: str | None = None,
    sam: bool = True,
    three_quarter: Literal["klein", "sheet"] = "klein",
    regenerate_turn: bool = False,
) -> Built:
    """Cut the chosen candidate's two figures into the front and three-quarter views of one
    rig: parts/<view>/*.png, rig.json (validated and registered through shot_spec.register_rig),
    palette.json, and build/report.json with each view's fit and the views' consistency.

    `three_quarter="klein"` (D-053) first redraws the three-quarter figure from the front with
    FLUX.2 klein (puppet/turn.py, best of a few seeds, made once and reused unless
    `regenerate_turn`); "sheet" cuts SDXL's own three-quarter figure."""
    data = load_candidates(film_root, character_id)
    if data is None:
        raise BuildError(f"{character_id!r} has no design candidates; run design_character")
    candidate = candidate or data.get("chosen")
    if not candidate:
        raise BuildError(f"no design chosen for {character_id!r}; choose one first")
    sheet = design_dir(film_root, character_id) / candidate / "sheet.png"
    if not sheet.is_file():
        raise DesignError(f"no sheet for candidate {candidate!r}")
    source: dict[str, Any] = {"method": "sheet"}
    if three_quarter == "klein":
        from studio_core.puppet.turn import turn_design  # turn uses this module

        turned = turn_design(
            film_root, character_id, candidate=candidate, regenerate=regenerate_turn
        )
        sheet = turned.sheet
        source = {
            "method": "FLUX.2 klein from the front",
            "seed": turned.choice["chosen_seed"],
            "scores": turned.choice["seeds"][f"s{turned.choice['chosen_seed']}"],
        }
    img = np.asarray(Image.open(sheet).convert("RGB")).astype("float32")
    skeletons = list(turnaround(CANVAS))
    folder = film_root / "characters" / character_id
    for stale in ("parts", "build"):  # a rebuild starts clean (SAM's run lands in build/)
        if (folder / stale).exists():
            shutil.rmtree(folder / stale)
    keys, bgs = {}, {}
    for sk in skeletons:
        keys[sk.view], bgs[sk.view] = figure_mask(img, sk)
    figures = keys
    silhouettes = {sk.view: {"method": "colour key"} for sk in skeletons}
    if sam:
        figures, silhouettes = _add_sam(film_root, sheet, skeletons, keys, folder)

    cuts = {sk.view: _cut_view(img, sk, figures[sk.view], bgs[sk.view], folder) for sk in skeletons}
    _match_face(cuts["front"], cuts["three_quarter"])
    rig = {
        "schema_version": 1,
        "id": character_id,
        "name": name or character_id.replace("_", " ").title(),
        "style": data["style"],
        "default_view": "front",
        "views": {view: cut.view for view, cut in cuts.items()},
    }
    rig_path, _ = register_rig(FilmFolder(film_root), character_id, rig)

    colors = palette(img, figures["front"])
    (folder / "palette.json").write_text(json.dumps({"colors": colors}, indent=1) + "\n")
    report = {
        "candidate": candidate,
        "three_quarter_source": source,
        "views": {
            view: {"silhouette": silhouettes[view], **cut.report} for view, cut in cuts.items()
        },
        "consistency": compare_views(img, {v: c.for_consistency for v, c in cuts.items()}),
    }
    (folder / "build" / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    return Built(rig, rig_path, report)


def compose(
    view: dict[str, Any],
    folder: Path,
    offsets: dict[str, float] | None = None,
    size: tuple[int, int] = (900, 900),
    root_at: tuple[int, int] | None = None,
) -> Image.Image:
    """The puppet posed with forward kinematics (rig.world_pose), drawn with PIL: each part
    rotated about its pivot by its bone's turn from rest. A quick check of pivots, attach
    points and joint caps without Synfig (the real renders go through the Synfig backend)."""
    pose = world_pose(view, offsets)
    rx, ry = root_at or (size[0] // 2, int(size[1] * 0.62))
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    for name in view["draw_order"]:
        part = view["parts"][name]
        (joint, direction) = pose[part["bone"]]
        turn = direction - view["bones"][part["bone"]]["direction_deg"]
        jx, jy = rx + joint.x, ry - joint.y
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        art = Image.open(folder / part["file"]).convert("RGBA")
        px, py = part["pivot_px"]
        layer.paste(art, (round(jx - px), round(jy - py)))
        out.alpha_composite(layer.rotate(turn, Image.Resampling.BICUBIC, center=(jx, jy)))
    return out


POSES = {  # build/poses.png: rest, a wave, a turned head with bent knees
    "rest": {},
    "wave": {"upper_arm_l": 120, "forearm_l": 30, "upper_arm_r": -20},
    "turn": {"head": 20, "torso": -8, "thigh_l": 20, "shin_l": 40, "forearm_r": -60},
}


TINTS = {
    "torso": (230, 160, 60), "head": (90, 160, 230),
    "upper_arm_l": (220, 70, 70), "forearm_l": (240, 150, 150),
    "upper_arm_r": (70, 170, 70), "forearm_r": (150, 230, 150),
    "thigh_l": (160, 80, 200), "shin_l": (210, 160, 240),
    "thigh_r": (60, 160, 160), "shin_r": (150, 220, 220),
}  # fmt: skip


def _debug_images(
    folder: Path,
    img: np.ndarray,
    cleaned: np.ndarray,
    parts: dict[str, np.ndarray],
    head: np.ndarray,
) -> None:
    """build/parts.png: each part tinted; build/face.png: the head before and after the fill."""
    tinted = img.copy()
    for name, m in parts.items():
        tinted[m] = 0.45 * img[m] + 0.55 * np.array(TINTS[name], dtype="float32")
    figure = np.any(list(parts.values()), axis=0)
    x0, y0, x1, y1 = _bbox(figure, pad=10)
    Image.fromarray(tinted[y0:y1, x0:x1].astype("uint8")).save(folder / "parts.png")
    x0, y0, x1, y1 = _bbox(head, pad=10)
    before, after = img[y0:y1, x0:x1], cleaned[y0:y1, x0:x1]
    Image.fromarray(np.hstack([before, after]).astype("uint8")).save(folder / "face.png")
