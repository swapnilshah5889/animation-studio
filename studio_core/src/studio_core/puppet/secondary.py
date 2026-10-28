"""Ears and tails as their own bones (task 4B, opt-in: build_puppet(secondary=True)).

The plain cut leaves the ears inside the head image and the tail inside the torso (D-050: "the
tail is torso"), so neither can lag behind the body. Here they are found and cut into parts of
their own, as bones with role `ear` (side left/right, parent the head) and `tail` (a chain of
1-3 segments, parent the torso; each segment's parent is the one before it).

**Ears** are the head mask's lobes: the head with a disc opened out of it (the skull, a disc
wider than any ear) is subtracted from the head, and what is left above the eye line, to
either side of the skull's centre, is an ear. The joint is where the lobe meets the skull.
A character without ears (Pim's feathers, Mia's hair) has no such lobes and gets none.

**The tail** is the torso-attached piece that no limb takes: the torso pixels outside the
body (the convex hull of shoulders and hips, grown by a margin) in the lower half of the
body, attached by a narrow root. A coat hem or a scarf end fails these tests (long attachment,
or too high, or the same piece on both sides).

Every test that fails refuses the detection; the report says why and the build goes on
without those bones. A part is cut by geometry (outside the skull or the body) and trimmed by
colour (the lobe must be coloured like the skull; the tail's root gives back what is coloured
like the body). The joint cap is a disc painted from the part's own pixels, drawn behind the
head or the torso, so nothing opens when it turns.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from studio_core.puppet.checks import components
from studio_core.puppet.skeleton import HEAD_W, Skeleton

SCALE = 4  # the skull is found on a mask this many times smaller
OPEN_RADIUS = 0.28  # x skull width: ears are thinner than a disc this big
MIN_EAR_AREA = 0.012  # of the head
MIN_EAR_LENGTH = 0.15  # x skull width, joint to tip
EAR_SYMMETRY = 2.5  # front view: the two ears' areas differ by less than this factor
EAR_PALETTE = 0.5  # share of ear pixels coloured like the skull
EAR_LIMITS = {"min": -35, "max": 35}
TAIL_LIMITS = {"min": -45, "max": 45}
TAIL_MARGIN = 0.05  # x figure height: the body hull is grown by this
MIN_TAIL_AREA = 0.012  # of the figure
MIN_TAIL_LENGTH = 0.08  # x figure height
SEGMENT_LENGTH = 0.11  # x figure height: one tail segment per this much length (1 to 3)
COLOUR_NEAR = 45.0  # RGB distance that counts as "the same colour"


def _shift(a: np.ndarray, dy: int, dx: int) -> np.ndarray:
    out = np.zeros_like(a)
    h, w = a.shape
    out[max(dy, 0) : h + min(dy, 0), max(dx, 0) : w + min(dx, 0)] = a[
        max(-dy, 0) : h + min(-dy, 0), max(-dx, 0) : w + min(-dx, 0)
    ]
    return out


def open_disc(mask: np.ndarray, r: int) -> np.ndarray:
    """Morphological opening with a disc of radius `r` (pixels): what a disc can fill."""
    offsets = [
        (dy, dx) for dy in range(-r, r + 1) for dx in range(-r, r + 1) if dy * dy + dx * dx <= r * r
    ]
    eroded = mask.copy()
    for dy, dx in offsets:
        eroded &= _shift(mask, dy, dx)
    opened = np.zeros_like(mask)
    for dy, dx in offsets:
        opened |= _shift(eroded, dy, dx)
    return opened & mask


def _grow(mask: np.ndarray, px: int) -> np.ndarray:
    from PIL import ImageFilter

    pil = Image.fromarray((mask * 255).astype("uint8")).filter(ImageFilter.MaxFilter(2 * px + 1))
    return np.asarray(pil) > 127


def _up(small: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    big = np.repeat(np.repeat(small, SCALE, axis=0), SCALE, axis=1)
    out = np.zeros(shape, dtype=bool)
    h, w = min(shape[0], big.shape[0]), min(shape[1], big.shape[1])
    out[:h, :w] = big[:h, :w]
    return out


def _direction_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.degrees(math.atan2(-(b[1] - a[1]), b[0] - a[0]))


def _palette_near(pixels: np.ndarray, colors: np.ndarray) -> np.ndarray:
    """Per pixel: the RGB distance to the nearest of `colors`."""
    return np.min([np.linalg.norm(pixels - c, axis=-1) for c in colors], axis=0)


# --------------------------------------------------------------------------------- ears


def find_ears(
    head: np.ndarray, rgb: np.ndarray, sk: Skeleton
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """The head's ears: {side: {"mask", "joint", "tip", "area"}} and a note for the report
    (`found`, or `reason` when nothing is accepted). Refuses rather than guesses."""
    from studio_core.puppet.build import _bbox, _palette

    note: dict[str, Any] = {"found": [], "reason": None}
    if not head.any():
        note["reason"] = "no head"
        return {}, note
    skull_w = HEAD_W * sk.height_px
    x0, y0, x1, y1 = _bbox(head, pad=4)
    sub = head[y0:y1, x0:x1]
    half = SCALE // 2
    small = sub[half::SCALE, half::SCALE]
    skull_small = open_disc(small, max(2, round(OPEN_RADIUS * skull_w / SCALE)))
    if int(skull_small.sum()) < 0.3 * int(small.sum()):
        note["reason"] = "no round skull found in the head mask"
        return {}, note
    skull = _up(skull_small, sub.shape)
    skull_cx = float(np.nonzero(skull)[1].mean()) + x0
    eye_y = sk.joints["l_eye"][1]
    # strips thinner than ~5 small pixels (the skull's outline, left over by the opening) go
    lobes_small = open_disc(small & ~skull_small, 2)
    area_min = MIN_EAR_AREA * int(small.sum())
    candidates = []
    for lobe in components(lobes_small):
        if int(lobe.sum()) < area_min:
            break  # largest first
        ys, xs = np.nonzero(lobe)
        cx, cy = x0 + xs.mean() * SCALE + half, y0 + ys.mean() * SCALE + half
        if cy >= eye_y:
            continue  # below the eyes: a chin, a neck, a cheek
        if abs(cx - skull_cx) < 0.2 * skull_w:
            continue  # on the midline: a tuft of hair, not an ear
        candidates.append(lobe)
    if not candidates:
        note["reason"] = "no lobes above the eyes, to either side of the skull"
        return {}, note
    if len(candidates) > 2:
        note["reason"] = f"{len(candidates)} lobes above the eyes (expected 1 or 2)"
        return {}, note

    skull_colors = _palette(rgb[y0:y1, x0:x1][skull], 8, min_share=0.05)
    ears: dict[str, dict[str, Any]] = {}
    for lobe in candidates:
        zone = _up(lobe, sub.shape)
        zone = _grow(zone, SCALE + 2) & sub & ~skull
        mask = np.zeros(head.shape, dtype=bool)
        mask[y0:y1, x0:x1] = zone
        ys, xs = np.nonzero(mask)
        if len(xs) == 0:
            continue
        near_skull = _grow(skull, 2)[: zone.shape[0], : zone.shape[1]]
        touch = zone & near_skull
        if not touch.any():
            note["reason"] = "a lobe does not touch the skull"
            return {}, note
        ty, tx = np.nonzero(touch)
        joint = (float(tx.mean()) + x0, float(ty.mean()) + y0)
        # A round ear has no far end: it points from the joint to its middle, and its tip is
        # the farthest pixel along that direction.
        centre = (float(xs.mean()), float(ys.mean()))
        reach = math.hypot(centre[0] - joint[0], centre[1] - joint[1])
        if reach < 1:
            note["reason"] = "a lobe's middle sits on its joint"
            return {}, note
        ux, uy = (centre[0] - joint[0]) / reach, (centre[1] - joint[1]) / reach
        along = (xs - joint[0]) * ux + (ys - joint[1]) * uy
        tip = (joint[0] + ux * along.max(), joint[1] + uy * along.max())
        if along.max() < MIN_EAR_LENGTH * skull_w:
            note["reason"] = "a lobe is too short to be an ear"
            return {}, note
        direction = _direction_deg(joint, tip)
        if not 5 < direction < 175:
            note["reason"] = f"a lobe points {direction:.0f} degrees, not upward"
            return {}, note
        share = float((_palette_near(rgb[mask], skull_colors) < COLOUR_NEAR).mean())
        if share < EAR_PALETTE:
            note["reason"] = f"a lobe is not coloured like the skull ({share:.2f}): a hat or bow?"
            return {}, note
        side = "left" if joint[0] > skull_cx else "right"  # the character's left is on the right
        if side in ears:
            note["reason"] = "both lobes are on the same side of the skull"
            return {}, note
        ears[side] = {"mask": mask, "joint": joint, "tip": tip, "area": int(mask.sum())}
    if sk.view == "front" and len(ears) == 1:
        note["reason"] = "front view shows one ear (ears come as a pair)"
        return {}, note
    if len(ears) == 2:
        a, b = (e["area"] for e in ears.values())
        if max(a, b) > EAR_SYMMETRY * min(a, b):
            note["reason"] = f"the two ears differ in size ({a} px against {b} px)"
            return {}, note
    note["found"] = sorted(ears)
    return ears, note


# --------------------------------------------------------------------------------- tail


def _body_hull(shape: tuple[int, int], sk: Skeleton) -> np.ndarray:
    j = sk.joints
    poly = [j[n] for n in ("r_shoulder", "neck", "l_shoulder", "l_hip", "pelvis", "r_hip")]
    canvas = Image.new("L", (shape[1], shape[0]), 0)
    ImageDraw.Draw(canvas).polygon([(float(x), float(y)) for x, y in poly], fill=255, outline=255)
    return _grow(np.asarray(canvas) > 127, round(TAIL_MARGIN * sk.height_px))


def find_tail(
    torso: np.ndarray, rgb: np.ndarray, sk: Skeleton
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """The tail: {"mask", "joints" (one per segment), "tip", "segments"} and a note. The piece of
    the torso outside the body, in its lower half, attached by a root no wider than the piece."""
    from studio_core.puppet.build import _palette

    note: dict[str, Any] = {"found": False, "reason": None}
    h = sk.height_px
    hull = _body_hull(torso.shape, sk)
    rows = np.arange(torso.shape[0])[:, None]
    shoulder_y = (sk.joints["l_shoulder"][1] + sk.joints["r_shoulder"][1]) / 2
    hip_y = (sk.joints["l_hip"][1] + sk.joints["r_hip"][1]) / 2
    outside = torso & ~hull & (rows > shoulder_y)
    pieces = [p for p in components(outside) if int(p.sum()) >= MIN_TAIL_AREA * 0.25 * h * h]
    if not pieces:
        note["reason"] = "no piece of the torso lies outside the body"
        return None, note
    if len(pieces) > 1 and int(pieces[1].sum()) >= 0.6 * int(pieces[0].sum()):
        note["reason"] = "two similar pieces outside the body: clothing, not a tail"
        return None, note
    piece = pieces[0]
    root = piece & _grow(hull, 3)
    if not root.any():
        note["reason"] = "the piece does not touch the body"
        return None, note
    ry, rx = np.nonzero(root)
    joint = (float(rx.mean()), float(ry.mean()))
    if not shoulder_y + 0.35 * (hip_y - shoulder_y) <= joint[1] <= hip_y + 0.2 * h:
        note["reason"] = "the piece is attached too high or too low for a tail (a scarf end?)"
        return None, note
    # colour: the root gives back what is coloured like the body and not like the tail
    ys, xs = np.nonzero(piece)
    far = np.hypot(xs - joint[0], ys - joint[1]) > 0.08 * h
    if far.sum() > 50 and (torso & hull).sum() > 50:
        tail_colors = _palette(rgb[piece][far], 5, min_share=0.1)
        body_colors = _palette(rgb[torso & hull], 6, min_share=0.05)
        near_root = piece & _grow(hull, round(0.04 * h))
        px = rgb[near_root]
        back = _palette_near(px, body_colors) + 8 < _palette_near(px, tail_colors)
        trimmed = piece.copy()
        trimmed[near_root] = ~back
        trimmed &= piece
        kept = components(trimmed)
        if kept:
            piece = kept[0]
            root = piece & _grow(hull, 3)
            if not root.any():
                note["reason"] = "after the colour trim the piece no longer touches the body"
                return None, note
            ry, rx = np.nonzero(root)
            joint = (float(rx.mean()), float(ry.mean()))
    ys, xs = np.nonzero(piece)
    dist = np.hypot(xs - joint[0], ys - joint[1])
    length = float(dist.max())
    tip = (float(xs[int(dist.argmax())]), float(ys[int(dist.argmax())]))
    area = int(piece.sum())
    if area < MIN_TAIL_AREA * h * h * 0.25 or length < MIN_TAIL_LENGTH * h:
        note["reason"] = f"the piece is small (area {area} px, length {length:.0f} px)"
        return None, note
    width = area / max(length, 1.0)
    contact = int(root.sum()) / 3.0  # the root is a 3 px band along the attachment
    if contact > 1.6 * width:
        note["reason"] = (
            f"attached along {contact:.0f} px but only {width:.0f} px wide: a hem, not a tail"
        )
        return None, note

    n = int(min(3, max(1, round(length / (SEGMENT_LENGTH * h)))))
    axis = np.array([tip[0] - joint[0], tip[1] - joint[1]]) / max(length, 1.0)
    t = (xs - joint[0]) * axis[0] + (ys - joint[1]) * axis[1]
    t_tip = float(t.max())
    cuts = [t_tip * k / n for k in range(1, n)]
    joints = [joint]
    for c in cuts:  # each inner joint: the centroid of the cross-section at the cut
        band = np.abs(t - c) <= 2.5
        joints.append(
            (float(xs[band].mean()), float(ys[band].mean()))
            if band.any()
            else (
                joint[0] + axis[0] * c,
                joint[1] + axis[1] * c,
            )
        )
    index = np.zeros(len(t), dtype=int)
    for c in cuts:
        index += (t >= c).astype(int)
    segments = []
    for k in range(n):
        m = np.zeros(torso.shape, dtype=bool)
        m[ys[index == k], xs[index == k]] = True
        segments.append(m)
    note.update(
        found=True,
        segments=n,
        length_px=round(length, 1),
        width_px=round(width, 1),
        contact_px=round(contact),
    )
    return {
        "mask": piece,
        "joints": joints,
        "tip": tip,
        "segments": segments,
        "width": width,
    }, note


# ------------------------------------------------------------------------------ the cut


def _disc(shape: tuple[int, int], centre: tuple[float, float], r: float) -> np.ndarray:
    ys, xs = np.ogrid[0 : shape[0], 0 : shape[1]]
    return (xs - centre[0]) ** 2 + (ys - centre[1]) ** 2 <= r * r


def _bone(role: str, side: str, parent: str, a, b, limits) -> dict[str, Any]:
    return {
        "role": role,
        "side": side,
        "parent": parent,
        "direction_deg": round(_direction_deg(a, b), 2),
        "length_px": round(math.hypot(b[0] - a[0], b[1] - a[1]), 1),
        "limits_deg": dict(limits),
        "joint_px": (round(a[0], 1), round(a[1], 1)),
        "end_px": (round(b[0], 1), round(b[1], 1)),
    }


def add_secondary(
    rgb: np.ndarray,
    figure: np.ndarray,
    parts: dict[str, np.ndarray],
    masks: dict[str, np.ndarray],
    pixels: dict[str, np.ndarray],
    bones: dict[str, dict],
    sk: Skeleton,
    order: tuple[str, ...],
) -> tuple[tuple[str, ...], dict[str, Any]]:
    """Cut the ears and the tail out of the head and the torso. Edits `masks`, `pixels` and
    `bones` in place (new entries `ear_l`, `ear_r`, `tail_1`...) and returns the new draw order
    and the report. Ears are drawn just behind the head, the tail behind everything."""
    from studio_core.puppet.build import paint_from

    report: dict[str, Any] = {}
    ears, ear_note = find_ears(parts["head"], pixels["head"], sk)
    report["ears"] = {k: v for k, v in ear_note.items() if v}
    behind_head: list[str] = []
    for side, ear in sorted(ears.items()):
        name = f"ear_{side[0]}"
        mask, joint, tip = ear["mask"], ear["joint"], ear["tip"]
        width = ear["area"] / max(math.hypot(tip[0] - joint[0], tip[1] - joint[1]), 1.0)
        cap = _disc(mask.shape, joint, 0.7 * width) & masks["head"] & ~mask
        masks[name] = mask | cap
        pixels[name] = paint_from(pixels["head"], mask, cap)
        masks["head"] = masks["head"] & ~mask
        bones[name] = _bone("ear", side, "head", joint, tip, EAR_LIMITS)
        behind_head.append(name)
    new_order = list(order)
    if behind_head:
        at = new_order.index("head")
        new_order[at:at] = behind_head
    tail, tail_note = find_tail(parts["torso"] & figure, pixels["torso"], sk)
    report["tail"] = {k: v for k, v in tail_note.items() if v}
    if tail is not None:
        names = [f"tail_{k + 1}" for k in range(len(tail["segments"]))]
        joints = [*tail["joints"], tail["tip"]]
        for k, name in enumerate(names):
            parent = "torso" if k == 0 else names[k - 1]
            bones[name] = _bone("tail", "center", parent, joints[k], joints[k + 1], TAIL_LIMITS)
            masks[name] = tail["segments"][k].copy()
            pixels[name] = pixels["torso"]
        masks["torso"] = masks["torso"] & ~tail["mask"]
        r = max(0.6 * tail["width"], 4.0)
        root_cap = _disc(figure.shape, joints[0], r) & figure & ~tail["mask"]
        masks[names[0]] = masks[names[0]] | root_cap
        pixels[names[0]] = paint_from(pixels["torso"], tail["segments"][0], root_cap)
        for k in range(1, len(names)):  # inner joints: both segments keep the sheet's pixels
            cap = _disc(figure.shape, joints[k], r) & tail["mask"]
            masks[names[k - 1]] = masks[names[k - 1]] | cap
            masks[names[k]] = masks[names[k]] | cap
        new_order = [*reversed(names), *new_order]
    return tuple(new_order), report
