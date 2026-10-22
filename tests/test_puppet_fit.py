"""Fitting the limb bones to the drawn limbs (puppet/fit.py), on synthetic silhouettes drawn
from the skeleton: arms at chosen angles from the skeleton's shoulders, legs at chosen
places and slopes under a jacket. So the fitted joints have a known right answer: where the
limb was drawn. The last tests run on the real Kit sheets when they exist (git-ignored)."""

import itertools
import json
import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from studio_core.puppet.design import CANVAS
from studio_core.puppet.fit import fit_arms, fit_legs, fit_limbs
from studio_core.puppet.skeleton import Skeleton, direction_deg, turnaround

FRONT, SIDE = turnaround(CANVAS)
ARM_JOINTS = ("elbow", "wrist", "hand")
LEG_JOINTS = ("hip", "knee", "ankle")
ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "films" / "step4-demo" / "characters" / "kit" / "design" / "c3"

Point = tuple[float, float]
Leg = tuple[float, float]  # (x at the hip's height, dx/dy)


def drawn_arm(
    sk: Skeleton,
    side: str,
    upper_deg: float,
    fore_deg: float,
    fore_scale: float = 1.0,
    shoulder: Point | None = None,
) -> dict[str, Point]:
    """The arm's joints at the given directions (the rig's convention: degrees, y up), from
    `shoulder` (the skeleton's by default), with the skeleton's bone lengths (the forearm and
    hand scaled by `fore_scale`)."""
    j = sk.joints
    joints = {"shoulder": shoulder or j[f"{side}_shoulder"]}
    chain = ("shoulder", "elbow", "wrist", "hand")
    for a, b in itertools.pairwise(chain):
        deg = upper_deg if b == "elbow" else fore_deg
        length = math.dist(j[f"{side}_{a}"], j[f"{side}_{b}"]) * (1 if b == "elbow" else fore_scale)
        x, y = joints[a]
        r = math.radians(deg)
        joints[b] = (x + length * math.cos(r), y - length * math.sin(r))
    return joints


def on_skeleton(sk: Skeleton, side: str) -> dict[str, Point]:
    return {n: sk.joints[f"{side}_{n}"] for n in ("shoulder", *ARM_JOINTS)}


def legs_on_skeleton(sk: Skeleton) -> dict[str, Leg]:
    j = sk.joints
    out = {}
    for side in ("r", "l"):
        (hx, hy), (ax, ay) = j[f"{side}_hip"], j[f"{side}_ankle"]
        out[side] = (hx, (ax - hx) / (ay - hy))
    return out


def leg_x(sk: Skeleton, leg: Leg, y: float) -> float:
    hip_x, slope = leg
    return hip_x + slope * (y - sk.joints["r_hip"][1])


def silhouette(
    sk: Skeleton,
    arms: dict[str, dict[str, Point]],
    arm_radius: float,
    legs: dict[str, Leg] | None = None,
    leg_width: float | None = None,
    body_dx: float = 0.0,
    tail: bool = False,
) -> np.ndarray:
    """A cartoon figure as a boolean mask: a wide jacket from the shoulders to below the
    hips (shifted `body_dx` sideways, as a klein figure can be), a round head, two legs with
    shoes, arms ending exactly at their hands, and maybe a tail merging into the screen-left
    leg's thigh, curling down beside it."""
    img = Image.new("L", CANVAS, 0)
    draw = ImageDraw.Draw(img)
    j, h = sk.joints, sk.height_px
    (nx, ny), (_, ty), (px, py) = j["neck"], j["head_top"], j["pelvis"]
    legs = legs or legs_on_skeleton(sk)
    width = leg_width or 0.07 * h
    for side, leg in legs.items():
        ys = [j[f"{side}_{n}"][1] for n in LEG_JOINTS]
        draw.line([(leg_x(sk, leg, y), y) for y in ys], fill=255, width=round(width))
        fx, fy = leg_x(sk, leg, j[f"{side}_foot"][1]), j[f"{side}_foot"][1]
        draw.ellipse([fx - 0.6 * width, fy - 22, fx + 0.6 * width, fy], fill=255)
    if tail:
        root = (leg_x(sk, legs["r"], py + 40), py + 40)
        draw.line([root, (px - 150, py + 60), (px - 170, py + 160)], fill=255,
                  width=round(0.07 * h), joint="curve")  # fmt: skip
    half = 0.1 * h  # the jacket is wider than both arms together
    draw.rectangle(
        [nx + body_dx - half, ny - 0.02 * h, nx + body_dx + half, py + 0.06 * h], fill=255
    )
    r = (ny - ty) / 2
    draw.ellipse([nx - 0.8 * r, ty, nx + 0.8 * r, ny + 0.1 * r], fill=255)
    for arm in arms.values():
        points = [arm[n] for n in ("shoulder", "elbow", "wrist")]
        draw.line(points, fill=255, width=round(2 * arm_radius), joint="curve")
        for x, y in points[:2]:  # round joints, like a drawn shoulder and elbow
            draw.ellipse([x - arm_radius, y - arm_radius, x + arm_radius, y + arm_radius], fill=255)
        (wx, wy), (hx, hy) = arm["wrist"], arm["hand"]
        paw = 0.8 * arm_radius  # a round paw whose far side is the hand joint
        u = math.dist((wx, wy), (hx, hy))
        cx, cy = hx - paw * (hx - wx) / u, hy - paw * (hy - wy) / u
        draw.ellipse([cx - paw, cy - paw, cx + paw, cy + paw], fill=255)
    return np.asarray(img) > 0


def radius(sk: Skeleton) -> float:
    return 0.033 * sk.height_px  # Kit's arms


# ---------------------------------------------------------------------------------- arms


@pytest.mark.parametrize("sk", [FRONT, SIDE], ids=["front", "three_quarter"])
@pytest.mark.parametrize(
    ("r_below", "l_below"),
    [(15, 45), (45, 15), (60, 15)],
    ids=["r15-l45", "r45-l15", "r60-l15"],
)
def test_arms_drawn_at_other_angles_are_followed(sk: Skeleton, r_below: float, l_below: float):
    """Arms drawn straight at other angles than the skeleton's (degrees below horizontal, the
    right arm to screen-left, the left arm to screen-right): the fitted elbows, wrists and
    hands land on the drawn ones. In the three-quarter view the far (left) upper arm starts
    behind the jacket."""
    arms = {
        "r": drawn_arm(sk, "r", -180 + r_below, -180 + r_below),
        "l": drawn_arm(sk, "l", -l_below, -l_below),
    }
    fitted, report = fit_arms(silhouette(sk, arms, radius(sk)), sk)
    for side, arm in arms.items():
        for n in ARM_JOINTS:
            miss = math.dist(fitted.joints[f"{side}_{n}"], arm[n])
            assert miss <= 4.0, f"{side}_{n} is {miss:.1f} px from the drawn joint"
        assert report[f"arm_{side}"]["changed"]
        assert report[f"arm_{side}"]["upper_arm"]["changed"]
        assert not report[f"arm_{side}"]["forearm"]["length_changed"]  # drawn to length
    for side in ("r", "l"):  # drawn from the skeleton's shoulders: they stay
        assert fitted.joints[f"{side}_shoulder"] == sk.joints[f"{side}_shoulder"]
        assert not report[f"arm_{side}"]["shoulder"]["changed"]
    assert fitted.view == sk.view and fitted.hidden == sk.hidden
    json.dumps(report)  # it goes into the build report as is


@pytest.mark.parametrize("scale", [1.35, 0.8])
def test_a_longer_or_shorter_forearm_gets_its_drawn_length(scale: float):
    """A moved arm whose forearm is drawn longer (a klein far arm) or shorter (foreshortened):
    the hand goes to the end of the drawn paw and the wrist a hand-length back, so the paw
    sits inside the forearm's part when the puppet is cut."""
    sk = SIDE
    arms = {
        "r": drawn_arm(sk, "r", -165, -165, scale),
        "l": drawn_arm(sk, "l", -30, -30, scale),
    }
    fitted, report = fit_arms(silhouette(sk, arms, radius(sk)), sk)
    for side, arm in arms.items():
        for n in ARM_JOINTS:
            miss = math.dist(fitted.joints[f"{side}_{n}"], arm[n])
            assert miss <= 4.0, f"{side}_{n} is {miss:.1f} px from the drawn joint"
        forearm = report[f"arm_{side}"]["forearm"]
        assert forearm["length_changed"]
        assert forearm["fitted_px"] == pytest.approx(scale * forearm["skeleton_px"], rel=0.04)


@pytest.mark.parametrize("below", [30, 50])
def test_a_shoulder_off_the_drawn_arm_slides_onto_it(below: float):
    """Kit's klein near arm: drawn from a shoulder 40 px from the skeleton's (lower and
    further in, under the jacket's edge). The shoulder drops square onto the drawn arm's
    centre line, which here is the drawn shoulder, and the rest of the arm follows. The far
    arm of a three-quarter view keeps its shoulder: it comes out from behind the body."""
    sk = SIDE
    (sx, sy) = sk.joints["r_shoulder"]
    a = math.radians(below)
    n = (-math.sin(a), -math.cos(a))  # square to the drawn arm, toward the skeleton's shoulder
    drawn_shoulder = (sx - 40 * n[0], sy - 40 * n[1])
    far = (sk.joints["l_shoulder"][0] + 15, sk.joints["l_shoulder"][1] + 30)
    arms = {
        "r": drawn_arm(sk, "r", -180 + below, -180 + below, shoulder=drawn_shoulder),
        "l": drawn_arm(sk, "l", -20, -20, shoulder=far),
    }
    fitted, report = fit_arms(silhouette(sk, arms, radius(sk)), sk)
    for n_ in ("shoulder", *ARM_JOINTS):
        miss = math.dist(fitted.joints[f"r_{n_}"], arms["r"][n_])
        assert miss <= 4.0, f"r_{n_} is {miss:.1f} px from the drawn joint"
    shoulder = report["arm_r"]["shoulder"]
    assert shoulder["changed"] and shoulder["shift_px"] == pytest.approx(40, abs=4)
    assert shoulder["fitted_score"] >= shoulder["skeleton_score"]
    assert fitted.joints["l_shoulder"] == sk.joints["l_shoulder"]
    assert not report["arm_l"]["shoulder"]["changed"]
    json.dumps(report)


def test_a_slightly_bent_arm_lands_within_half_a_radius():
    """Upper arm at 30° below horizontal, forearm bent 10° further. The upper arm is scored
    along the whole arm, so it leans a little toward the hand; the joints still land within
    half a limb radius (a known limit: bends of 30-40° are about a radius off)."""
    arms = {
        "r": drawn_arm(FRONT, "r", -150, -140),
        "l": drawn_arm(FRONT, "l", -30, -40),
    }
    fitted, report = fit_arms(silhouette(FRONT, arms, radius(FRONT)), FRONT)
    for side, arm in arms.items():
        for n in ARM_JOINTS:
            miss = math.dist(fitted.joints[f"{side}_{n}"], arm[n])
            assert miss <= 0.5 * radius(FRONT), f"{side}_{n} is {miss:.1f} px from the drawn joint"
        forearm = report[f"arm_{side}"]["forearm"]
        if forearm["changed"]:  # the report's angle is the one in the returned skeleton
            drawn = direction_deg(fitted, f"{side}_elbow", f"{side}_hand")
            assert forearm["fitted_deg"] == pytest.approx(drawn, abs=0.1)


@pytest.mark.parametrize("sk", [FRONT, SIDE], ids=["front", "three_quarter"])
def test_a_figure_drawn_on_its_skeleton_is_unchanged(sk: Skeleton):
    arms = {side: on_skeleton(sk, side) for side in ("r", "l")}
    fitted, report = fit_limbs(silhouette(sk, arms, radius(sk)), sk)
    assert fitted.joints == sk.joints
    assert set(report) == {"arm_r", "arm_l", "leg_r", "leg_l"}
    for side in ("r", "l"):
        arm = report[f"arm_{side}"]
        assert not arm["changed"] and not report[f"leg_{side}"]["changed"]
        if sk.view == "front":  # in three-quarter the far arm hangs behind the jacket
            assert arm["upper_arm"]["skeleton_score"] >= 0.75
            assert arm["upper_arm"]["fitted_deg"] == pytest.approx(
                arm["upper_arm"]["skeleton_deg"], abs=3
            )
    json.dumps(report)


def test_arms_pressed_against_the_body_are_kept_and_reported():
    """Arms hanging straight down along the jacket: no narrow cross-section anywhere near the
    shoulder, so nothing can be fitted. The skeleton is kept and the report says why."""
    arms = {side: drawn_arm(FRONT, side, -90, -90) for side in ("r", "l")}
    fitted, report = fit_arms(silhouette(FRONT, arms, radius(FRONT)), FRONT)
    assert fitted.joints == FRONT.joints
    for side in ("r", "l"):
        arm = report[f"arm_{side}"]
        assert not arm["changed"]
        assert arm["forearm"] is None
        assert "pressed against the body" in arm["note"]


# ---------------------------------------------------------------------------------- legs


@pytest.mark.parametrize("tail", [False, True], ids=["no_tail", "tail"])
@pytest.mark.parametrize(
    ("sk", "dx", "slopes"),
    [(SIDE, 50, (-0.1, 0.0)), (SIDE, -40, (-0.05, 0.08)), (FRONT, 45, (-0.12, 0.1))],
    ids=["three_quarter_right", "three_quarter_left", "front_right"],
)
def test_legs_drawn_beside_the_skeleton_are_followed(
    sk: Skeleton, dx: float, slopes: tuple[float, float], tail: bool
):
    """The lower body drawn `dx` px beside the skeleton's (a klein figure isn't registered to
    it), each leg at its own slope, a few px apart. The hips, knees and ankles move sideways
    onto the drawn legs, even with a tail merging into the screen-left thigh."""
    width = 0.08 * sk.height_px
    hip = sk.joints["pelvis"][0] + dx
    legs = {"r": (hip - 0.55 * width, slopes[0]), "l": (hip + 0.55 * width, slopes[1])}
    arms = {side: on_skeleton(sk, side) for side in ("r", "l")}
    figure = silhouette(sk, arms, radius(sk), legs, width, body_dx=dx, tail=tail)
    fitted, report = fit_legs(figure, sk)
    for side, leg in legs.items():
        for n in (*LEG_JOINTS, "foot"):
            x, y = fitted.joints[f"{side}_{n}"]
            assert y == sk.joints[f"{side}_{n}"][1]  # joints keep their heights
            miss = abs(x - leg_x(sk, leg, y))
            assert miss <= 4.0, f"{side}_{n} is {miss:.1f} px from the drawn leg"
        assert report[f"leg_{side}"]["changed"]
    json.dumps(report)


def test_legs_that_cant_be_told_apart_are_kept_and_reported():
    """Legs drawn touching, with the tail merged into the screen-left one: only one clean
    edge is left for both legs together. Neither leg moves, and the report says why."""
    sk, dx = SIDE, 50
    width = 0.08 * sk.height_px
    hip = sk.joints["pelvis"][0] + dx
    legs = {"r": (hip - 0.45 * width, 0.0), "l": (hip + 0.45 * width, 0.0)}
    arms = {side: on_skeleton(sk, side) for side in ("r", "l")}
    figure = silhouette(sk, arms, radius(sk), legs, width, body_dx=dx, tail=True)
    fitted, report = fit_legs(figure, sk)
    assert fitted.joints == sk.joints
    for side in ("r", "l"):
        assert not report[f"leg_{side}"]["changed"]
        assert "can't be told apart" in report[f"leg_{side}"]["note"]


# ----------------------------------------------------------------- the real Kit sheets


def _figure(path: Path, sk: Skeleton) -> tuple[np.ndarray, np.ndarray]:
    from studio_core.puppet.build import figure_mask

    img = np.asarray(Image.open(path).convert("RGB")).astype("float32")
    return img, figure_mask(img, sk)[0]


@pytest.mark.skipif(not (KIT / "sheet.png").exists(), reason="Kit's SDXL sheet isn't here")
@pytest.mark.parametrize("sk", [FRONT, SIDE], ids=["front", "three_quarter"])
def test_kit_sdxl_sheet_is_unchanged(sk: Skeleton):
    """SDXL drew Kit on the skeleton: every limb already fits."""
    _, figure = _figure(KIT / "sheet.png", sk)
    fitted, report = fit_limbs(figure, sk)
    assert fitted.joints == sk.joints
    assert not any(limb["changed"] for limb in report.values())


@pytest.mark.skipif(
    not (KIT / "three_quarter" / "sheet.png").exists(), reason="Kit's klein sheet isn't here"
)
def test_kit_klein_three_quarter_figure_is_followed():
    """Kit's three-quarter figure redrawn by FLUX.2 klein: its lower body sits about 80 px
    beside the skeleton's, its near shoulder about 56 px off the drawn arm, and its far arm
    is longer. After the fit every checked joint is on the figure, the near upper arm's line
    lies on the drawn arm (build's coverage), and the far paw lies within the forearm's part
    (t ≤ 1.35, as cut by build)."""
    from studio_core.puppet.build import limb_fit
    from studio_core.puppet.checks import check_sheet
    from studio_core.puppet.skeleton import rig_bones

    path = KIT / "three_quarter" / "sheet.png"
    img, figure = _figure(path, SIDE)
    fitted, report = fit_limbs(figure, SIDE)
    image = Image.open(path)
    before = check_sheet(image, [FRONT, SIDE]).figures[1].joints_inside
    after = check_sheet(image, [FRONT, fitted]).figures[1].joints_inside
    assert after == 1.0 > before
    assert report["leg_r"]["changed"] and report["leg_l"]["changed"]
    assert report["arm_r"]["shoulder"]["changed"]
    assert limb_fit(figure, fitted, rig_bones(fitted)["upper_arm_r"])["coverage"] >= 0.9

    (ex, ey), (hx, hy) = fitted.joints["l_elbow"], fitted.joints["l_hand"]
    ys, xs = np.mgrid[0 : figure.shape[0], 0 : figure.shape[1]].astype("float32")
    vx, vy = hx - ex, hy - ey
    t = ((xs - ex) * vx + (ys - ey) * vy) / (vx * vx + vy * vy)
    d = ((xs - ex) * vy - (ys - ey) * vx) / math.hypot(vx, vy)
    luma = img @ np.array([0.299, 0.587, 0.114], dtype="float32")
    paw = figure & (luma < 90) & (t > 0.3) & (np.abs(d) < 2.5 * radius(SIDE))  # the dark glove
    assert paw.sum() > 500
    assert t[paw].max() <= 1.35
