"""Do the two views show the same character, and is the three-quarter view turned? (task 4.5,
D-051)

    report = compare_views(img, {"front": front_cut, "three_quarter": tq_cut})
    report["ok"], report["problems"]

The turnaround's two figures come out of one SDXL image, which keeps them close, but not
always identical: c3's three-quarter fox wears a hat the front one doesn't. And SDXL often
draws the "three-quarter" figure barely turned. Both are measured here, without a model:

- **Colours per region** (head, torso, arms, legs): paint covering at least 3% of a region in
  one view that the same region of the other view doesn't have (colour histograms, with
  neighbouring shades counted as the same paint). A hat, a bag, a different shirt.
- **Head size:** head height as a share of the figure's height, per view.
- **Turn:** how far the drawn nose sits from the head's centre line, as a share of the head's
  width, compared with what the three-quarter skeleton asked for. 1.0 = turned as asked,
  0 = a front view.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from studio_core.puppet.skeleton import Skeleton

REGIONS = {
    "head": ("head",),
    "torso": ("torso",),
    "arms": ("upper_arm_l", "forearm_l", "upper_arm_r", "forearm_r"),
    "legs": ("thigh_l", "shin_l", "thigh_r", "shin_r"),
}
MIN_SHARE = 0.03  # a colour must cover this share of a region to count
BIN = 32  # colour grid cell size (RGB levels); neighbouring cells count as the same paint
PRESENT = 0.002  # a cell is present in a region if this share of its pixels fall in it
MIN_TURN = 0.5  # the three-quarter view must turn at least this share of what was asked
HEAD_TOLERANCE = 0.1  # head height shares may differ by this much (relative)


@dataclass
class ViewCut:
    """What compare_views needs from a cut view."""

    sk: Skeleton
    parts: dict[str, np.ndarray]  # bone → its pixels in the sheet (before caps)
    nose_x: float | None  # the drawn nose's centre, if found


def _colours(pixels: np.ndarray, k: int = 8) -> list[tuple[np.ndarray, float]]:
    """Main colours of some pixels with their shares (median cut)."""
    strip = Image.fromarray(pixels.reshape(1, -1, 3).astype("uint8"))
    q = strip.quantize(k, method=Image.Quantize.MEDIANCUT)
    counts = np.bincount(np.asarray(q).ravel(), minlength=k)
    flat = q.getpalette()
    return [
        (np.array(flat[3 * i : 3 * i + 3], dtype="float32"), n / len(pixels))
        for i, n in enumerate(counts)
        if n
    ]


def _hex(c: np.ndarray) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(int(v) for v in c))


def _bins(pixels: np.ndarray) -> np.ndarray:
    """Each pixel's cell in an 8x8x8 colour grid (32 RGB levels per cell)."""
    q = (pixels // BIN).astype(int).clip(0, 255 // BIN)
    return q[:, 0] * 64 + q[:, 1] * 8 + q[:, 2]


def extra_colours(a: np.ndarray, b: np.ndarray) -> list[dict[str, Any]]:
    """Paint in pixels `a` that pixels `b` don't have: `a`'s pixels whose colour cell, and every
    neighbouring cell, is (nearly) empty in `b`. Reported when they cover ≥ MIN_SHARE of `a`,
    with their most common colour. Comparing colour histograms, not palettes: a palette
    blends a small hat's green with the fur next to it into a colour nobody painted."""
    counts = np.bincount(_bins(b), minlength=512).reshape(8, 8, 8)
    present = counts >= max(3, PRESENT * len(b))
    near = np.zeros_like(present)
    padded = np.pad(present, 1)
    for dr in range(3):
        for dg in range(3):
            for db in range(3):
                near |= padded[dr : dr + 8, dg : dg + 8, db : db + 8]
    cells = _bins(a)
    unmatched = ~near.ravel()[cells]
    share = float(unmatched.mean())
    if share < MIN_SHARE:
        return []
    common = np.bincount(cells[unmatched]).argmax()
    colour = a[unmatched][cells[unmatched] == common].mean(axis=0)
    return [{"hex": _hex(colour), "share": round(share, 3)}]


def _turn(cut: ViewCut) -> float | None:
    """The drawn nose's offset from the head's centre line, as a share of the head's width
    at nose level (+ = toward screen-right)."""
    head = cut.parts["head"]
    row = head[int(cut.sk.joints["nose"][1])]
    xs = np.nonzero(row)[0]
    if cut.nose_x is None or not len(xs):
        return None
    return float((cut.nose_x - (xs.min() + xs.max()) / 2) / (xs.max() - xs.min() + 1))


def asked_turn(sk: Skeleton) -> float:
    """The same measure on the skeleton: nose offset over the skeleton head's width."""
    width = 2 * abs(sk.joints["r_ear"][0] - sk.joints["neck"][0])
    return (sk.joints["nose"][0] - sk.joints["neck"][0]) / width


def compare_views(img: np.ndarray, cuts: dict[str, ViewCut]) -> dict[str, Any]:
    front, tq = cuts["front"], cuts["three_quarter"]
    report: dict[str, Any] = {"regions": {}, "problems": []}
    for region, bones in REGIONS.items():
        fm = np.any([front.parts[b] for b in bones], axis=0)
        tm = np.any([tq.parts[b] for b in bones], axis=0)
        if not fm.any() or not tm.any():
            continue
        only_tq, only_front = extra_colours(img[tm], img[fm]), extra_colours(img[fm], img[tm])
        report["regions"][region] = {"only_three_quarter": only_tq, "only_front": only_front}
        for which, extra in (("three-quarter", only_tq), ("front", only_front)):
            for c in extra:
                report["problems"].append(
                    f"{region}: {c['hex']} covers {c['share']:.0%} of the {which} view only"
                )
    heads = {}
    for view, cut in cuts.items():
        figure = np.any(list(cut.parts.values()), axis=0)
        fy = np.nonzero(figure.any(axis=1))[0]
        hy = np.nonzero(cut.parts["head"].any(axis=1))[0]
        heads[view] = float((hy.max() - hy.min()) / (fy.max() - fy.min()))
    report["head_share"] = {v: round(h, 3) for v, h in heads.items()}
    if abs(heads["three_quarter"] / heads["front"] - 1) > HEAD_TOLERANCE:
        report["problems"].append(
            f"the head is {heads['three_quarter'] / heads['front']:.0%} as tall (relative to the "
            "body) in the three-quarter view as in the front view"
        )
    measured, asked = _turn(tq), asked_turn(tq.sk)
    report["turn"] = {
        "measured": None if measured is None else round(measured, 3),
        "asked": round(asked, 3),
        "fraction": None if measured is None else round(measured / asked, 2),
    }
    if measured is None:
        report["problems"].append("three-quarter view: no nose found to measure the turn")
    elif measured / asked < MIN_TURN:
        report["problems"].append(
            f"the three-quarter view is barely turned ({measured / asked:.0%} of the turn asked)"
        )
    report["ok"] = not report["problems"]
    return report
