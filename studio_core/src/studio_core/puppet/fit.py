"""Fit the skeleton's limb bones to the limbs actually drawn (task 4.5, D-052).

    fitted, report = fit_limbs(figure, skeleton)  # figure: the view's boolean silhouette
    report["arm_r"]["upper_arm"]                  # skeleton vs fitted angle and score
    report["leg_l"]["shift_px"]                   # how far the drawn leg is from the bone

`fit_limbs` is `fit_arms` then `fit_legs`; each can be called alone.

The cut (build.py) assumes the drawing follows the skeleton it was generated on. SDXL with a
ControlNet mostly does. A three-quarter figure redrawn by FLUX.2 klein from the front view
doesn't: its arms come out nearly horizontal or at 45°, longer or shorter than the
skeleton's, and its whole lower body can sit 80 px beside the skeleton's. The skeleton's
joints then land on background or on the tail, and the corridors cut a strip of jacket
instead of an arm, or tail instead of a thigh. No model here, only the silhouette.

## Arms

The upper arm keeps the skeleton's length. The shoulder moves only to where the drawn arm
attaches (step 0 below).

**How a line is scored.** A candidate bone is a straight line from its pivot at some angle,
sampled at `SAMPLES` points. A sample is *arm-like* when it is on the figure and the figure
is narrow there: walking perpendicular to the line, background is reached within `NARROW`
limb radii on *both* sides. "On the figure" alone isn't enough: a line into the torso is
inside the silhouette too. The narrow test tells an arm (a strip a few radii wide) from the
body (much wider), and a line *along* the arm from one that only crosses it.

The score is the longest *strip* of arm-like samples (gaps of up to `MAX_GAP` samples
bridged, for a cuff or a glove seam) that starts near the pivot, as a share of all the
samples. "Starts near the pivot" matters: the tail, the legs and a paw hanging beside the
trousers are narrow too, but they begin about two upper-arm lengths below the shoulder,
while an arm begins at the shoulder or, in a three-quarter view, where the far arm comes
out from behind the body. A strip, rather than a count of samples, is what a drawn arm is:
whatever lies before it (the body hiding a far upper arm) and after it (background past a
shorter paw) costs every candidate angle alike.

**Fitting, bone by bone** (the elbow has to be known before the forearm can turn about it):

0. **Shoulder** (not the three-quarter far arm, which comes out from behind the body). A
   klein figure isn't registered to the skeleton: Kit's near shoulder sat 56 px off the drawn
   arm, so the upper arm ran *across* the arm and covered a quarter of it. The arm's centre
   line is measured from the cross-section midpoints of the first fit (`_arm_axis`: a chord's
   midpoint lies on a straight strip's centre line, however slanted the chord). The shoulder
   drops square onto that line, at its own place along the arm, or slides in to where the
   arm leaves the body if that place is out on the arm (`_slide_shoulder`). It moves only
   within `SHOULDER_SLIDE` upper arms, by more than `MOVE_TOL` radii, and when the upper arm
   from there scores `MARGIN` more.
1. **Upper arm:** about the shoulder, from `INWARD` degrees inward to `OUTWARD` degrees
   outward of the skeleton's direction (outward reaches past horizontal). It is scored along
   the *whole* arm, shoulder to fingertips, as one straight line. In a three-quarter view the
   far upper arm starts behind the torso, so its own segment has almost nothing to measure,
   while the arm beyond it does. Rest-pose arms on a model sheet are nearly straight.
2. **Forearm:** about the fitted elbow, within `FOREARM_RANGE` degrees of where the upper
   arm carried it, scored along the forearm and hand only. The wrist and hand turn with it.
3. **Forearm length**, on an arm that moved: the hand goes to the end of the drawn paw (the
   fitted line walked to background), within `LENGTH_RANGE` of the skeleton's length, and
   the wrist a hand-length back. A klein far arm is drawn longer than the skeleton's, and its
   paw fell outside the forearm's corridor; a foreshortened near arm is shorter. An arm that
   follows its skeleton keeps the skeleton's lengths: its paw was drawn for them.

The best angle is the middle of the best-scoring run of angles (a line can swing a little
inside an arm and still pass every sample). It is then nudged onto the drawn arm's centre
line: the midpoints of the strip's cross-sections, fitted with a line through the pivot.

**When a bone moves.** Three tests, all needed:
- its best line scores at least `MIN_SCORE` (a weak signal never replaces the skeleton),
- it scores `MARGIN` more than the skeleton's own line,
- it points clearly elsewhere: the end of what it turns (the hand for the upper arm, which
  turns the whole arm; the hand for the forearm) moves by more than `MOVE_TOL` limb radii.
The last is what keeps a drawing that follows its skeleton (an SDXL front view) unchanged.
A thick arm holds lines several degrees apart almost equally well, so a score margin alone
either kept arms drawn 14° off (a large margin) or nudged arms that were already right (a
small one). An arm pressed against the body has no narrow cross-sections near the shoulder
(the walk runs on into the torso): nothing can be fitted, the skeleton is kept and the
report says so.

**The report**, per arm (`arm_r`, `arm_l`): for each bone the skeleton's angle and score,
the best line's angle and score, and whether the bone moved (the returned skeleton has the
fitted angle only then). The forearm also has its length in px (`skeleton_px`,
`fitted_px`, `length_changed`). Angles are in the rig's convention (degrees, y up, as
`skeleton.direction_deg`). For the forearm, "skeleton" is the skeleton's forearm as carried
by the fitted upper arm, its bend kept: the line the fit has to beat. For the upper arm,
it is the skeleton's direction from the (possibly moved) shoulder. `shoulder` holds both
positions in px, the shift, the best upper-arm score from each, and whether it moved.

## Legs

Legs touch each other, the tail or a coat, so the arms' narrow test doesn't work for them.
Each leg is a straight bar (centre line and width) searched under the torso, scored on
whether it is filled and has background just outside its edges, row after row (`_Bars`,
`fit_legs`). Joints keep their heights and move sideways onto the bar's line, hips included.
Both legs move or neither, by the arms' rule (a clearly better bar, and a joint more than
`MOVE_TOL` leg radii away). Report per leg (`leg_r`, `leg_l`): thigh and shin angles, the
skeleton's and the fitted bar's scores, the bar's width, the largest joint shift, whether it
moved, and a note.

## Known limits

- The three-quarter far arm keeps the skeleton's shoulder (behind the body). A far arm drawn
  beside the body starts too far out to fit at all (more than `UPPER_STRIP_START` upper
  arms from the skeleton's far shoulder), and a fitted far arm's elbow lands inside the
  body, short of the drawn one.
- A bent arm: the upper arm leans toward the shoulder-to-hand line, so the elbow lands off
  the drawn one, about half a limb radius for a 10° bend and a radius for 30-40°.
- Legs drawn touching *and* with the tail merged into one of them leave only one clean edge
  for both: they can't be told apart from the silhouette, and are kept (reported). The dark
  outline between them would tell them apart; that needs the picture, not just the mask.
- A leg's thigh and shin share one line: a bent knee isn't followed.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

import numpy as np

from studio_core.puppet.skeleton import Skeleton, direction_deg

RADIUS = 0.035  # nominal arm radius as a share of the figure's height (Kit's arms: ~0.033)
NARROW = 2.5  # a cross-section is arm-like when both sides reach background within this many radii
MAX_GAP = 2  # samples that may fail inside a strip (a cuff, a glove seam)
UPPER_STRIP_START = 1.5  # an arm strip starts within this many upper arms of the shoulder
FOREARM_STRIP_START = 0.5  # a forearm strip starts within this many forearms of the elbow
MIN_SCORE = 0.35  # a strip covering less of the arm isn't trusted
MARGIN = 0.05  # a fitted line must score this much more than the skeleton's...
MOVE_TOL = 0.5  # ...and move the hand by more than this many limb radii
LENGTH_RANGE = (0.7, 1.5)  # a fitted forearm's length, as a share of the skeleton's
LENGTH_LOOK = 2.0  # the paw's end is looked for this many skeleton forearms out
SHOULDER_SLIDE = 0.75  # a shoulder slides at most this many upper arms to the drawn arm
AXIS_STEPS = 3  # re-measurements of a drawn arm's centre line
INWARD, OUTWARD = 35.0, 95.0  # upper-arm search: degrees either way of the skeleton's direction
FOREARM_RANGE = 60.0  # forearm search: degrees either way of where the upper arm carried it
UPPER_START = 0.3  # upper-arm samples start this far along the upper arm: its root is in the body
FOREARM_START = 0.15  # forearm samples start this far along the forearm
STEP = 1.0  # degrees between candidate angles
SAMPLES = 40  # samples along a candidate line
PLATEAU = 0.03  # angles scoring within this of the best form the best run
REFINE_STEPS = 4  # centre-line refinements of the best angle

# Legs (fit_legs)
LEG_WIDTH = 0.08  # nominal leg width as a share of the figure's height (Kit's trousers: ~0.08)
LEG_WIDTHS = (0.6, 0.8, 1.0, 1.2, 1.4)  # widths tried, as shares of the nominal
EDGE_TOL = 0.15  # an edge counts when background is within this share of the nominal width
LEG_BAND = (0.25, 0.15)  # rows searched: from this far below the hip to this far above the ankle
TORSO_ROW = 0.05  # the torso's width is read this share of the height above the hips
LEG_WINDOW = 0.3  # without a torso row, leg centres are searched this far from the pelvis
LEG_TILT, TILT_STEP = 0.2, 0.02  # leg slopes searched (dx/dy): up to about 11° from vertical
LEG_APART = 0.8  # the two legs' centres are at least this many nominal widths apart
LEG_MIN = 0.4  # a bar scoring less isn't trusted as a leg

Point = tuple[float, float]


# ------------------------------------------------------------------------------ geometry


def _screen_deg(a: Point, b: Point) -> float:
    """Direction a→b in degrees in image coordinates (y down), as atan2 gives it."""
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def _wrap(deg: float) -> float:
    """An angle in (-180, 180]."""
    deg = deg % 360.0
    return deg - 360.0 if deg > 180.0 else deg


def _rig_deg(screen_deg: float) -> float:
    """Image-coordinate angle (y down) → the rig's convention (y up)."""
    return _wrap(-screen_deg)


def _rotate(p: Point, pivot: Point, deg: float) -> Point:
    """`p` turned `deg` about `pivot`, in image coordinates (positive turns x toward y)."""
    r = math.radians(deg)
    dx, dy = p[0] - pivot[0], p[1] - pivot[1]
    return (
        pivot[0] + dx * math.cos(r) - dy * math.sin(r),
        pivot[1] + dx * math.sin(r) + dy * math.cos(r),
    )


def _unit(deg: float) -> np.ndarray:
    return np.array([math.cos(math.radians(deg)), math.sin(math.radians(deg))], dtype="float32")


# ----------------------------------------------------------------------- scoring a line


def _walks(figure: np.ndarray, points: np.ndarray, step: np.ndarray, limit: int) -> np.ndarray:
    """For each point, the steps along `step` (a unit vector) to the first background pixel,
    or `limit + 1` when there is none within `limit` steps. The image's edge counts as
    background. Like build.py's `_walk`, but for many points at once: the search walks
    thousands of cross-sections."""
    h, w = figure.shape
    k = np.arange(limit + 1, dtype="float32")
    xs = np.rint(points[:, 0:1] + step[0] * k).astype(int)
    ys = np.rint(points[:, 1:2] + step[1] * k).astype(int)
    valid = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    on = np.zeros(xs.shape, dtype=bool)
    on[valid] = figure[ys[valid], xs[valid]]
    off = ~on
    return np.where(off.any(axis=1), off.argmax(axis=1), limit + 1)


def _strip(armlike: np.ndarray, dist: np.ndarray, start_max: float) -> tuple[int, int] | None:
    """The longest run of arm-like samples (gaps up to MAX_GAP bridged) whose first sample is
    within `start_max` of the pivot: (first, last) sample indices, or None."""
    best: tuple[int, int] | None = None
    i = 0
    while i < len(armlike):
        if not armlike[i]:
            i += 1
            continue
        last, k = i, i + 1
        while k < len(armlike) and k - last <= MAX_GAP + 1:
            if armlike[k]:
                last = k
            k += 1
        if dist[i] <= start_max and (best is None or last - i > best[1] - best[0]):
            best = (i, last)
        i = last + 1
    return best


def _line(
    figure: np.ndarray,
    pivot: Point,
    deg: float,
    span: tuple[float, float],
    reach: float,
    start_max: float,
    samples: int = SAMPLES,
) -> tuple[float, np.ndarray, np.ndarray]:
    """Score of the line from `pivot` at `deg` (image coordinates), sampled from `span[0]` to
    `span[1]` pixels out: the share of samples in its arm strip (see the module docstring).
    Also returns the midpoints of the strip's cross-sections (the drawn limb's centre line)
    and their samples' distances from the pivot."""
    u = _unit(deg)
    n = np.array([-u[1], u[0]], dtype="float32")
    dist = np.linspace(span[0], span[1], samples, dtype="float32")
    points = np.array(pivot, dtype="float32") + dist[:, None] * u
    limit = math.ceil(reach)
    plus, minus = _walks(figure, points, n, limit), _walks(figure, points, -n, limit)
    # A sample on background walks 0 steps both ways, so it fails the "inside" part.
    armlike = (plus > 0) & (minus > 0) & (plus <= reach) & (minus <= reach)
    strip = _strip(armlike, dist, start_max)
    if strip is None:
        return 0.0, np.zeros((0, 2), dtype="float32"), np.zeros(0, dtype="float32")
    first, last = strip
    keep = np.zeros_like(armlike)
    keep[first : last + 1] = armlike[first : last + 1]
    mids = points[keep] + ((plus[keep] - minus[keep]) / 2)[:, None] * n
    return (last - first + 1) / samples, mids, dist[keep]


def _centre_line(pivot: Point, mids: np.ndarray, near_deg: float) -> float | None:
    """The direction through `pivot` closest to the midpoints (least squares, perpendicular
    distances), on the side of `near_deg`. Farther midpoints weigh more, as they pin the
    angle better. None with too few midpoints to trust."""
    if len(mids) < 4:
        return None
    v = mids - np.array(pivot, dtype="float32")
    _, vectors = np.linalg.eigh(v.T @ v)
    ux, uy = vectors[:, -1]  # the principal direction
    deg = math.degrees(math.atan2(uy, ux))
    return deg if abs(_wrap(deg - near_deg)) <= 90.0 else _wrap(deg + 180.0)


def _fit_bone(
    figure: np.ndarray,
    pivot: Point,
    start_deg: float,
    turns: tuple[float, float],
    span: tuple[float, float],
    reach: float,
    start_max: float,
) -> tuple[float, float, float]:
    """The best direction for a bone from `pivot`, searched over `start_deg` + `turns`.
    Returns (the start line's score, the best angle, its score); image-coordinate angles."""

    def score(deg: float) -> tuple[float, np.ndarray]:
        return _line(figure, pivot, deg, span, reach, start_max)[:2]

    offsets = np.arange(turns[0], turns[1] + STEP / 2, STEP)
    scores = np.array([score(start_deg + o)[0] for o in offsets])
    start_score = score(start_deg)[0]
    if scores.max() == 0.0:  # nothing arm-like anywhere in the range
        return start_score, start_deg, 0.0
    # The best run of angles, ties broken toward the skeleton; then its middle.
    best = int(np.argmax(scores - 1e-4 * np.abs(offsets)))
    floor = max(scores[best] - PLATEAU, 1e-6)  # never a run of zeros
    first, last = best, best
    while first > 0 and scores[first - 1] >= floor:
        first -= 1
    while last < len(scores) - 1 and scores[last + 1] >= floor:
        last += 1
    deg = start_deg + (offsets[first] + offsets[last]) / 2
    best_score, mids = score(deg)
    # Onto the drawn limb's centre line, as long as the line stays on the arm.
    for _ in range(REFINE_STEPS):
        nudged = _centre_line(pivot, mids, deg)
        if nudged is None or abs(_wrap(nudged - deg)) < 0.1:
            break
        nudged_score, nudged_mids = score(nudged)
        if nudged_score < best_score - PLATEAU:
            break
        deg, best_score, mids = nudged, nudged_score, nudged_mids
    return start_score, deg, best_score


def _arm_axis(
    figure: np.ndarray, mids: np.ndarray, near_deg: float, back: float, length: float, reach: float
) -> tuple[np.ndarray, np.ndarray, float] | None:
    """The drawn arm's centre line, found from cross-section midpoints (`mids`, from any line
    that crossed the arm: a chord's midpoint lies on a straight strip's centre line whatever
    the chord's slant). A line through them (least squares, not through any pivot) is
    re-measured with cross-sections square to itself, AXIS_STEPS times.

    Returns (a point on the axis, the unit vector outward along the arm, and the distance from
    that point to where the arm leaves the body), or None. The point is `back` pixels inward
    of the midpoints' nearest end; the walk runs `length` pixels out from there."""
    if len(mids) < 6:
        return None
    for _ in range(AXIS_STEPS):
        centre = mids.mean(axis=0)
        _, vectors = np.linalg.eigh(np.cov((mids - centre).T))
        u = vectors[:, -1].astype("float32")
        if u @ _unit(near_deg) < 0:
            u = -u
        inner = float(((mids - centre) @ u).min())
        start = centre + (inner - back) * u
        deg = math.degrees(math.atan2(u[1], u[0]))
        _, found, dist = _line(figure, tuple(start), deg, (0.0, length), reach, math.inf, 100)
        if len(found) < 6:
            return None
        mids = found
    return start, u, float(dist[0])


def _slide_shoulder(
    figure: np.ndarray, shoulder: Point, mids: np.ndarray, deg: float, upper: float, arm: float,
    reach: float,
) -> Point | None:  # fmt: skip
    """Where the drawn arm attaches, for a skeleton shoulder off the drawn arm: on the arm's
    centre line, at the skeleton shoulder's own place along it (dropped square onto the
    line), or further in, at the arm's root, if that place is out on the arm. None when the
    axis can't be found, or the attachment is more than SHOULDER_SLIDE upper arms away."""
    slide = SHOULDER_SLIDE * upper
    axis = _arm_axis(figure, mids, deg, slide + arm, slide + 2 * arm, reach)
    if axis is None:
        return None
    start, u, root = axis
    along = float((np.array(shoulder, dtype="float32") - start) @ u)
    x, y = start + min(along, root) * u
    h, w = figure.shape
    if math.dist((x, y), shoulder) > slide or not (0 <= x < w and 0 <= y < h):
        return None
    return float(x), float(y)


def _drawn_end(figure: np.ndarray, pivot: Point, deg: float, length: float) -> float | None:
    """Where the drawn limb ends along the line from `pivot` at `deg`: the distance to the
    last figure pixel of the first stretch of figure on the line (one-pixel gaps bridged).
    Background before it is skipped (an elbow just off the drawing). None when the line
    finds no figure within half of `length`, or doesn't leave it within LENGTH_LOOK times
    `length` (the paw runs into the body or the tail: its end can't be told)."""
    h, w = figure.shape
    u = _unit(deg)
    d = np.arange(0.0, LENGTH_LOOK * length + 2.0, 1.0, dtype="float32")
    xs = np.rint(pivot[0] + u[0] * d).astype(int)
    ys = np.rint(pivot[1] + u[1] * d).astype(int)
    valid = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    on = np.zeros(len(d), dtype=bool)
    on[valid] = figure[ys[valid], xs[valid]]
    if not on[: int(0.5 * length) + 1].any():
        return None
    first = int(np.argmax(on))
    gone = ~on[first:-1] & ~on[first + 1 :]  # two background pixels in a row
    if not gone.any():
        return None
    return float(d[first + int(np.argmax(gone)) - 1])


# ---------------------------------------------------------------------------- the arms


def _bone_report(
    skeleton_deg: float, skeleton_score: float, best_deg: float, best_score: float, moved: bool
) -> dict[str, Any]:
    return {
        "skeleton_deg": round(_rig_deg(skeleton_deg), 1),
        "skeleton_score": round(skeleton_score, 3),
        "fitted_deg": round(_rig_deg(best_deg), 1),
        "fitted_score": round(best_score, 3),
        "changed": moved,
    }


def _moves(
    skeleton_score: float, best_score: float, turn_deg: float, length: float, radius: float
) -> bool:
    """Does the fitted line replace the skeleton's? See "When a bone moves" in the module
    docstring. `length` is the distance from the pivot to the hand, which the turn moves."""
    shift = 2 * length * abs(math.sin(math.radians(turn_deg) / 2))
    return (
        best_score >= MIN_SCORE
        and best_score >= skeleton_score + MARGIN
        and shift > MOVE_TOL * radius
    )


def _fit_arm(
    figure: np.ndarray, sk: Skeleton, side: str, joints: dict[str, Point], radius: float
) -> dict[str, Any]:
    """Fit one arm's elbow, wrist and hand in `joints` (updated in place); returns its report."""
    shoulder, elbow = joints[f"{side}_shoulder"], joints[f"{side}_elbow"]
    wrist, hand = joints[f"{side}_wrist"], joints[f"{side}_hand"]
    upper, fore = math.dist(shoulder, elbow), math.dist(elbow, hand)
    arm = upper + math.dist(elbow, wrist) + math.dist(wrist, hand)
    reach = NARROW * radius
    # Outward is away from the neck: screen-left for the character's right arm, in both views.
    # A positive image-coordinate turn swings a hanging arm toward screen-left.
    turns = (-INWARD, OUTWARD) if shoulder[0] < sk.joints["neck"][0] else (-OUTWARD, INWARD)

    def fit_upper(pivot: Point) -> tuple[float, float, float]:
        return _fit_bone(
            figure, pivot, up_deg, turns, (UPPER_START * upper, arm), reach,
            UPPER_STRIP_START * upper,
        )  # fmt: skip

    # 0. The shoulder: does the drawn arm attach elsewhere? Not for the far arm of a
    # three-quarter view, which comes out from behind the body.
    up_deg = _screen_deg(shoulder, elbow)
    up_score, up_best, up_best_score = fit_upper(shoulder)
    far = sk.view == "three_quarter" and side == "l"
    report: dict[str, Any] = {
        "shoulder": {
            "skeleton_px": [round(shoulder[0], 1), round(shoulder[1], 1)],
            "fitted_px": [round(shoulder[0], 1), round(shoulder[1], 1)],
            "shift_px": 0.0,
            "skeleton_score": round(up_best_score, 3),
            "fitted_score": round(up_best_score, 3),
            "changed": False,
        }
    }
    if far:
        report["shoulder"]["note"] = "the far arm comes out from behind the body"
    elif up_best_score >= MIN_SCORE:
        mids = _line(figure, shoulder, up_best, (UPPER_START * upper, arm), reach, math.inf)[1]
        slid = _slide_shoulder(figure, shoulder, mids, up_best, upper, arm, reach)
        shift = math.dist(slid, shoulder) if slid else 0.0
        if slid and shift > MOVE_TOL * radius:
            tried = fit_upper(slid)
            report["shoulder"].update(fitted_score=round(tried[2], 3), shift_px=round(shift, 1))
            if tried[2] >= up_best_score + MARGIN:
                dx, dy = slid[0] - shoulder[0], slid[1] - shoulder[1]
                shoulder = slid
                elbow, wrist, hand = ((x + dx, y + dy) for x, y in (elbow, wrist, hand))
                up_score, up_best, up_best_score = tried
                report["shoulder"].update(
                    fitted_px=[round(slid[0], 1), round(slid[1], 1)], changed=True
                )

    # 1. The upper arm, scored along the whole straight arm.
    up_moved = _moves(up_score, up_best_score, up_best - up_deg, arm, radius)
    report["upper_arm"] = _bone_report(up_deg, up_score, up_best, up_best_score, up_moved)
    if (up_best_score if up_moved or report["shoulder"]["changed"] else up_score) < MIN_SCORE:
        report.update(
            forearm=None,
            changed=False,
            note=f"no arm-shaped strip near the shoulder (best {up_best_score:.2f}, needs "
            f"{MIN_SCORE}): the arm may be pressed against the body, or drawn far from the "
            "skeleton's shoulder; the skeleton is kept",
        )
        return report
    if up_moved:
        turn = up_best - up_deg
        elbow, wrist, hand = (_rotate(p, shoulder, turn) for p in (elbow, wrist, hand))

    # 2. The forearm about the (fitted) elbow, scored along the forearm and hand.
    fore_deg = _screen_deg(elbow, hand)
    fore_score, fore_best, fore_best_score = _fit_bone(
        figure, elbow, fore_deg, (-FOREARM_RANGE, FOREARM_RANGE), (FOREARM_START * fore, fore),
        reach, FOREARM_STRIP_START * fore,
    )  # fmt: skip
    fore_moved = _moves(fore_score, fore_best_score, fore_best - fore_deg, fore, radius)
    report["forearm"] = _bone_report(fore_deg, fore_score, fore_best, fore_best_score, fore_moved)
    if fore_moved:
        turn = fore_best - fore_deg
        wrist, hand = (_rotate(p, elbow, turn) for p in (wrist, hand))

    # 3. The forearm's length, on an arm the drawing has already moved: the hand goes to the
    # end of the drawn paw and the wrist a hand-length back. An arm drawn on its skeleton keeps
    # the skeleton's lengths (its paw was drawn for them).
    report["forearm"].update(skeleton_px=round(fore, 1), fitted_px=round(fore, 1))
    length_moved = False
    if up_moved or fore_moved:
        deg = _screen_deg(elbow, hand)
        end = _drawn_end(figure, elbow, deg, fore)
        if end is not None and abs(end - fore) > MOVE_TOL * radius:
            new = float(np.clip(end, LENGTH_RANGE[0] * fore, LENGTH_RANGE[1] * fore))
            hand_len = math.dist(wrist, hand) * new / fore
            u = _unit(deg)
            hand = (elbow[0] + u[0] * new, elbow[1] + u[1] * new)
            wrist = (hand[0] - u[0] * hand_len, hand[1] - u[1] * hand_len)
            report["forearm"]["fitted_px"] = round(new, 1)
            length_moved = True
    report["forearm"]["length_changed"] = length_moved

    joints[f"{side}_shoulder"], joints[f"{side}_elbow"] = shoulder, elbow
    joints[f"{side}_wrist"], joints[f"{side}_hand"] = wrist, hand
    report["changed"] = report["shoulder"]["changed"] or up_moved or fore_moved or length_moved
    report["note"] = None if report["changed"] else "the skeleton already fits"
    return report


def fit_arms(
    figure: np.ndarray, sk: Skeleton, radius_px: float | None = None
) -> tuple[Skeleton, dict[str, Any]]:
    """A copy of `sk` whose shoulders, elbows, wrists and hands follow the arms drawn in
    `figure` (the view's boolean silhouette, image-sized), and a report per arm (`arm_r`,
    `arm_l`), ready for JSON.

    `radius_px` is the drawn arms' radius when known (for instance measured on the front
    view); otherwise `RADIUS` of the figure's height. A shoulder moves to where its drawn arm
    attaches, and the upper arm keeps its length. A joint moves only when the drawing clearly
    disagrees with it (see the module docstring), so a figure drawn on its skeleton comes back
    unchanged."""
    radius = radius_px if radius_px is not None else RADIUS * sk.height_px
    joints = dict(sk.joints)
    report: dict[str, Any] = {}
    for side in ("r", "l"):
        report[f"arm_{side}"] = _fit_arm(figure, sk, side, joints, radius)
        report[f"arm_{side}"]["radius_px"] = round(radius, 1)
    return replace(sk, joints=joints), report


# ---------------------------------------------------------------------------- the legs


def _run_lengths(band: np.ndarray) -> np.ndarray:
    """For each pixel of each row, how many figure pixels end at it, counting leftward
    (0 on background). Flip the band to count rightward."""
    out = np.zeros(band.shape, dtype=np.int32)
    run = np.zeros(band.shape[0], dtype=np.int32)
    for x in range(band.shape[1]):
        run = np.where(band[:, x], run + 1, 0)
        out[:, x] = run
    return out


class _Bars:
    """Scores straight vertical-ish bars (a leg model) on a band of the figure's rows.

    A bar is a centre line x = c + s·(y - y_mid) and a width w. Each row scores the share of
    the bar that is figure, times the evidence for its two edges: background within EDGE_TOL
    outside each edge. A leg touching the other leg or the tail still has one clean edge in
    most rows, so it scores about half there; a bar shifted into its neighbour has neither."""

    def __init__(self, figure: np.ndarray, ys: np.ndarray, tol: float) -> None:
        self.band = figure[ys]
        self.rows = np.arange(len(ys))[None, :]
        self.dy = (ys - ys.mean()).astype("float32")[None, :]
        self.width = figure.shape[1]
        self.tol = tol
        zero = np.zeros((len(ys), 1), dtype=np.int32)
        self.sums = np.concatenate([zero, np.cumsum(self.band, axis=1, dtype=np.int32)], axis=1)
        self.left = _run_lengths(self.band)
        self.right = _run_lengths(self.band[:, ::-1])[:, ::-1]

    def scores(self, c: np.ndarray, s: float, w: float) -> np.ndarray:
        """Mean row score of the bars at centres `c` (at the band's middle row)."""
        xc = c[:, None] + s * self.dy
        x0 = np.clip(np.rint(xc - w / 2), 0, self.width - 1).astype(int)
        x1 = np.clip(np.rint(xc + w / 2) - 1, 0, self.width - 1).astype(int)
        x1 = np.maximum(x1, x0)
        fill = (self.sums[self.rows, x1 + 1] - self.sums[self.rows, x0]) / (x1 - x0 + 1)
        left, right = self.left[self.rows, x0], self.right[self.rows, x1]
        # On background the edge is already inside the bar (fill pays for it): evidence 1.
        e_left = np.where(left == 0, 1.0, np.clip(1 - (left - 1) / self.tol, 0, 1))
        e_right = np.where(right == 0, 1.0, np.clip(1 - (right - 1) / self.tol, 0, 1))
        return (fill * (e_left + e_right) / 2).mean(axis=1)


def _under_torso(figure: np.ndarray, sk: Skeleton) -> tuple[float, float] | None:
    """The torso's extent just above the hips (the figure's run there nearest the
    skeleton's pelvis): the legs hang from it. The tail, which can look just like a leg,
    comes out beside it."""
    y = round(sk.joints["pelvis"][1] - TORSO_ROW * sk.height_px)
    if not 0 <= y < figure.shape[0]:
        return None
    edges = np.flatnonzero(np.diff(np.concatenate([[0], figure[y].astype(np.int8), [0]])))
    runs = list(zip(edges[::2], edges[1::2] - 1, strict=True))
    if not runs:
        return None
    px = sk.joints["pelvis"][0]
    a, b = min(runs, key=lambda r: max(r[0] - px, px - r[1], 0))
    return float(a), float(b)


def _leg_line(sk: Skeleton, side: str, y_mid: float) -> tuple[float, float]:
    """The skeleton's leg as (x at `y_mid`, dx/dy): its hip, knee and ankle are on a line."""
    (hx, hy), (ax, ay) = sk.joints[f"{side}_hip"], sk.joints[f"{side}_ankle"]
    s = (ax - hx) / (ay - hy)
    return hx + s * (y_mid - hy), s


def fit_legs(figure: np.ndarray, sk: Skeleton) -> tuple[Skeleton, dict[str, Any]]:
    """A copy of `sk` whose hips, knees, ankles and feet follow the legs drawn in `figure`,
    and a report per leg (`leg_r`, `leg_l`), ready for JSON.

    Legs often touch each other, the tail or a coat, so the arms' "narrow on both sides"
    test doesn't work. Instead each leg is modelled as a straight bar (centre line and width)
    and searched over the rows between the upper thighs and the ankles (`_Bars`): the bar
    must be filled and have background just outside its edges, row after row. The two best
    bars that don't overlap are the legs, the one on screen-left being the character's right
    (true in both views). Joints keep their heights and move sideways onto the bar's centre
    line, hips included: a klein figure's whole lower body can sit beside the skeleton's.
    Model-sheet legs are straight, so thigh and shin share one line; a bent knee isn't
    followed.

    Same rule as the arms: a leg moves only when its bar scores at least LEG_MIN, MARGIN more
    than a bar on the skeleton's leg, and puts a hip, knee or ankle more than MOVE_TOL leg
    radii from the skeleton's."""
    j = sk.joints
    h = sk.height_px
    hip_y, knee_y, ankle_y = (j[f"r_{n}"][1] for n in ("hip", "knee", "ankle"))
    top = hip_y + LEG_BAND[0] * (knee_y - hip_y)  # below the hips: coats and hems cover them
    bottom = ankle_y - LEG_BAND[1] * (ankle_y - knee_y)  # above the shoes, which turn sideways
    ys = np.arange(round(top), round(bottom), 2)
    nominal = LEG_WIDTH * h
    bars = _Bars(figure, ys, EDGE_TOL * nominal)
    y_mid = float(ys.mean())
    px = j["pelvis"][0]
    a, b = _under_torso(figure, sk) or (px - LEG_WINDOW * h, px + LEG_WINDOW * h)
    centres = np.arange(a, b + 1, 1.0, dtype="float32")
    tilts = np.arange(-LEG_TILT, LEG_TILT + 1e-6, TILT_STEP)
    widths = [k * nominal for k in LEG_WIDTHS]

    # The best bar at every centre, over tilts and widths.
    best = np.full(len(centres), -1.0)
    params = np.zeros((len(centres), 2))
    for s in tilts:
        for w in widths:
            score = bars.scores(centres, float(s), w)
            better = score > best
            best[better], params[better] = score[better], (s, w)
    first = int(np.argmax(best))
    apart = np.abs(centres - centres[first]) >= LEG_APART * nominal
    second = int(np.argmax(np.where(apart, best, -1.0)))
    found = sorted((first, second), key=lambda i: centres[i])  # screen-left first

    # Both legs or neither: they hang from one pelvis, and when only one bar is clear the
    # other is usually the first one's twin merged with it (legs drawn touching).
    pair = all(best[i] >= LEG_MIN for i in found)
    joints = dict(j)
    report: dict[str, Any] = {}
    for side, i in zip(("r", "l"), found, strict=True):
        c, (s, w), score = float(centres[i]), params[i], float(best[i])
        c0, s0 = _leg_line(sk, side, y_mid)
        skeleton_score = max(float(bars.scores(np.array([c0]), s0, wk)[0]) for wk in widths)
        names = ("hip", "knee", "ankle")
        fitted_x = {n: c + s * (j[f"{side}_{n}"][1] - y_mid) for n in names}
        shift = max(abs(fitted_x[n] - j[f"{side}_{n}"][0]) for n in names)
        moved = bool(pair and score >= skeleton_score + MARGIN and shift > MOVE_TOL * w / 2)
        if moved:
            for n in names:
                joints[f"{side}_{n}"] = (fitted_x[n], j[f"{side}_{n}"][1])
            (ax, _), (fx, fy) = j[f"{side}_ankle"], j[f"{side}_foot"]
            joints[f"{side}_foot"] = (joints[f"{side}_ankle"][0] + fx - ax, fy)
        fitted = replace(sk, joints=joints)
        if moved:
            note = None
        elif not pair:
            note = (
                f"the two legs can't be told apart (best bars {best[found[0]]:.2f} and "
                f"{best[found[1]]:.2f}, need {LEG_MIN}): drawn touching each other or the "
                "tail? The skeleton is kept"
            )
        else:
            note = "the skeleton already fits"
        report[f"leg_{side}"] = {
            "thigh": {
                "skeleton_deg": round(direction_deg(sk, f"{side}_hip", f"{side}_knee"), 1),
                "fitted_deg": round(direction_deg(fitted, f"{side}_hip", f"{side}_knee"), 1),
            },
            "shin": {
                "skeleton_deg": round(direction_deg(sk, f"{side}_knee", f"{side}_ankle"), 1),
                "fitted_deg": round(direction_deg(fitted, f"{side}_knee", f"{side}_ankle"), 1),
            },
            "skeleton_score": round(skeleton_score, 3),
            "fitted_score": round(score, 3),
            "width_px": round(float(w), 1),
            "shift_px": round(shift, 1),
            "changed": moved,
            "note": note,
        }
    return replace(sk, joints=joints), report


def fit_limbs(
    figure: np.ndarray, sk: Skeleton, radius_px: float | None = None
) -> tuple[Skeleton, dict[str, Any]]:
    """`fit_arms` then `fit_legs`: a copy of `sk` whose limbs follow the drawing, and one
    report with `arm_r`, `arm_l`, `leg_r` and `leg_l`."""
    sk, arms = fit_arms(figure, sk, radius_px)
    sk, legs = fit_legs(figure, sk)
    return sk, arms | legs
