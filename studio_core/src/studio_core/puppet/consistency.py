"""Do the two views show the same character, and is the three-quarter view turned? (task 4.5,
D-051)

    report = compare_views(img, {"front": front_cut, "three_quarter": tq_cut})
    report["ok"], report["problems"]

The turnaround's two figures come out of one SDXL image, which keeps them close, but not
always identical: c3's three-quarter fox wears a hat the front one doesn't. And SDXL often
draws the "three-quarter" figure barely turned. Both are measured here, without a model:

- **Colours per region** (head, torso, arms, legs): paint covering at least 3% of a region in
  one view that the same region of the other view doesn't have (colour histograms, with
  neighbouring shades counted as the same paint). A hat, a bag, a different shirt. A small
  patch (under `TOLERATED_SHARE`) is a **note**, not a problem: turning a head or a foot shows
  a feature the other view doesn't (a bird's beak in profile, a shoe's side), and a few
  per cent of paint is about that size.
- **Head size:** head height as a share of the figure's height, per view.
- **Turn:** how far the face's marks (eyes, nose, mouth) sit off the head's centre line, as a
  share of the head's width, compared with what the three-quarter skeleton asked for.
  1.0 = turned as asked, 0 = a front view, above 1 = turned further (toward a profile).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

from studio_core.puppet.skeleton import Skeleton

REGIONS = {
    "head": ("head",),
    "torso": ("torso",),
    "arms": ("upper_arm_l", "forearm_l", "upper_arm_r", "forearm_r"),
    "legs": ("thigh_l", "shin_l", "thigh_r", "shin_r"),
}
MIN_SHARE = 0.03  # a colour must cover this share of a region to be reported
TOLERATED_SHARE = 0.07  # below this it is a note, not a problem: a feature the turn reveals
BIN = 32  # colour grid cell size (RGB levels); neighbouring cells count as the same paint
PRESENT = 0.002  # a cell is present in a region if this share of its pixels fall in it
MIN_TURN = 0.5  # the three-quarter view must turn at least this share of what was asked
HEAD_TOLERANCE = 0.1  # head height shares may differ by this much (relative)


@dataclass
class ViewCut:
    """What compare_views needs from a cut view."""

    sk: Skeleton
    parts: dict[str, np.ndarray]  # bone → its pixels in the sheet (before caps)


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
    return [{"hex": _hex(colour), "share": round(share, 3), "tolerated": share < TOLERATED_SHARE}]


def face_offset(img: np.ndarray, head: np.ndarray) -> float | None:
    """Where the face's marks (eyes, nose, mouth) sit across the head: the centroid of the
    pixels clearly darker than their surroundings, inside the head's face band (45-92% of its
    height), as an offset from the head's centre line in shares of its width (+ = right).

    A front face is centred (about 0); a face turned toward screen-right shifts right. Using
    every mark, not the nose alone, keeps it working when a strongly turned head puts the
    nose on its outline, where a nose finder can't tell it from the outline."""
    if not head.any():
        return None
    ys = np.nonzero(head.any(axis=1))[0]
    top, bottom = ys.min(), ys.max()
    mid = int(top + 0.6 * (bottom - top))
    row = np.nonzero(head[mid])[0]
    if not len(row):
        return None
    width = float(row.max() - row.min() + 1)
    luma = img @ np.array([0.299, 0.587, 0.114], dtype="float32")
    around = Image.fromarray(np.clip(luma, 0, 255).astype("uint8")).filter(
        ImageFilter.BoxBlur(max(4, int(width * 0.04)))
    )
    inner = (
        np.asarray(
            Image.fromarray((head * 255).astype("uint8")).filter(
                ImageFilter.MinFilter(2 * max(2, int(width * 0.015)) + 1)
            )
        )
        > 127
    )  # not the head's own outline
    # The face band: below the ears' inner shading (dark, and on the far side once the head
    # turns, so it pulls the wrong way) and above the chin's outline.
    inner[: int(top + 0.45 * (bottom - top))] = False
    inner[int(top + 0.92 * (bottom - top)) :] = False
    marks = inner & (luma < np.asarray(around, dtype="float32") - 40)
    if marks.sum() < 20:
        return None
    centre = (row.min() + row.max()) / 2
    return float((np.nonzero(marks)[1].mean() - centre) / width)


def asked_turn(sk: Skeleton) -> float:
    """The same measure on the skeleton: the mean of the eyes and nose against the neck, over
    the skeleton head's width."""
    j = sk.joints
    features = (j["r_eye"][0] + j["l_eye"][0] + j["nose"][0]) / 3
    return (features - j["neck"][0]) / (2 * abs(j["r_ear"][0] - j["neck"][0]))


def compare_views(img: np.ndarray, cuts: dict[str, ViewCut]) -> dict[str, Any]:
    front, tq = cuts["front"], cuts["three_quarter"]
    report: dict[str, Any] = {"regions": {}, "problems": [], "notes": []}
    for region, bones in REGIONS.items():
        fm = np.any([front.parts[b] for b in bones], axis=0)
        tm = np.any([tq.parts[b] for b in bones], axis=0)
        if not fm.any() or not tm.any():
            continue
        only_tq, only_front = extra_colours(img[tm], img[fm]), extra_colours(img[fm], img[tm])
        report["regions"][region] = {"only_three_quarter": only_tq, "only_front": only_front}
        for which, extra in (("three-quarter", only_tq), ("front", only_front)):
            for c in extra:
                what = f"{region}: {c['hex']} covers {c['share']:.1%} of the {which} view only"
                report["notes" if c["tolerated"] else "problems"].append(what)
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
    measured, asked = face_offset(img, tq.parts["head"]), asked_turn(tq.sk)
    front_offset = face_offset(img, front.parts["head"])
    report["turn"] = {
        "front_offset": None if front_offset is None else round(front_offset, 3),
        "measured": None if measured is None else round(measured, 3),
        "asked": round(asked, 3),
        "fraction": None if measured is None else round(measured / asked, 2),
    }
    if measured is None:
        report["problems"].append("three-quarter view: no face marks found to measure the turn")
    elif measured / asked < MIN_TURN:
        report["problems"].append(
            f"the three-quarter view is barely turned ({measured / asked:.0%} of the turn asked)"
        )
    report["ok"] = not report["problems"]
    return report
