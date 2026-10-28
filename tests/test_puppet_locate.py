"""The vision locator as a seed stage (task 4B, D-070): swap by geometry, seeds checked by the
pixel rules, a cache. No model runs here: `ask` is a fake."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image
from test_puppet_build import FRONT, face_points, pixels
from test_puppet_fit import SIDE, drawn_arm, on_skeleton, radius, silhouette

from studio_core.puppet.build import _locator_report, clean_face, figure_mask, head_mask
from studio_core.puppet.fit import _seed_check, fit_limbs
from studio_core.puppet.locate import (
    HALF,
    locate_sheet,
    settle,
    swap_by_geometry,
)
from studio_core.puppet.skeleton import Skeleton

H = 100.0  # a head height, for settle
FULL = np.ones((400, 400), dtype=bool)


def head_height(sk) -> float:
    return sk.joints["neck"][1] - sk.joints["head_top"][1]


# ------------------------------------------------------------------------ the locator's rules


def test_a_pair_is_swapped_by_where_it_is_not_by_its_label() -> None:
    wrong = {"left_eye": (100.0, 50.0), "right_eye": (200.0, 50.0), "left_wrist": None,
             "right_wrist": (10.0, 10.0)}  # fmt: skip
    out = swap_by_geometry(wrong)
    assert out["right_eye"] == (100.0, 50.0) and out["left_eye"] == (200.0, 50.0)
    assert out["right_wrist"] == (10.0, 10.0) and out["left_wrist"] is None  # one missing: kept
    assert swap_by_geometry(out) == out  # already right: unchanged


def test_a_pixel_result_near_its_seed_is_kept() -> None:
    at, how = settle((110.0, 100.0), (100.0, 100.0), [], FULL, H)  # 0.1 head heights apart
    assert (at, how) == ((100.0, 100.0), "pixel")


def test_a_mark_near_the_seed_beats_a_pixel_result_elsewhere() -> None:
    at, how = settle((200.0, 100.0), (100.0, 100.0), [(205.0, 98.0), (300.0, 100.0)], FULL, H)
    assert (at, how) == ((205.0, 98.0), "pixel_near_seed")


def test_the_seed_is_used_and_flagged_when_the_rules_find_nothing_near_it() -> None:
    assert settle((200.0, 100.0), None, [], FULL, H) == ((200.0, 100.0), "seed")
    # the rules found something 0.2 head heights away: not exact, not far enough to fail
    assert settle((120.0, 100.0), (100.0, 100.0), [], FULL, H) == ((120.0, 100.0), "seed")


def test_methods_more_than_a_third_of_a_head_apart_fail_the_part() -> None:
    at, how = settle((200.0, 100.0), (100.0, 100.0), [], FULL, H)  # a whole head apart
    assert (at, how) == ((100.0, 100.0), "disagree")  # the pixel result stays


def test_a_seed_outside_the_figure_fails_and_is_ignored() -> None:
    mask = np.zeros((400, 400), dtype=bool)
    mask[100:200, 100:200] = True
    at, how = settle((350.0, 350.0), (150.0, 150.0), [(350.0, 351.0)], mask, H)
    assert (at, how) == ((150.0, 150.0), "outside")
    assert settle((350.0, 350.0), None, [], mask, H) == (None, "outside")


def test_answers_are_swapped_cached_and_the_cache_is_reused(tmp_path: Path) -> None:
    sheet = tmp_path / "sheet.png"
    Image.new("RGB", (1344, 768), "white").save(sheet)
    calls = []

    def fake(crop: Image.Image, view: str) -> dict:
        calls.append(view)
        # labels swapped on purpose: "left" is on screen-left
        return {"left_eye": (100.0, 80.0), "right_eye": (160.0, 80.0), "left_elbow": None}

    seeds, payload = locate_sheet(sheet, None, fake)
    assert calls == ["front", "three_quarter"]
    assert seeds["front"]["r_eye"] == (100.0, 80.0)  # screen-left is the character's right
    assert seeds["three_quarter"]["l_eye"] == (160.0 + HALF, 80.0)  # crop to sheet pixels
    assert "l_elbow" not in seeds["front"]
    again, _ = locate_sheet(sheet, json.loads(json.dumps(payload)), fake)
    assert calls == ["front", "three_quarter"] and again == seeds  # the cache: no second call
    Image.new("RGB", (1344, 768), "black").save(sheet)  # another sheet: asked again
    locate_sheet(sheet, payload, fake)
    assert len(calls) == 4


# ------------------------------------------------------------------------------- the face


def _face(seeds: dict | None):
    img = pixels()
    figure, _ = figure_mask(img, FRONT)
    head = head_mask(img, figure, FRONT)
    return clean_face(img, head, FRONT, seeds=seeds), face_points(FRONT), head


def test_eyes_the_rules_find_beside_their_seeds_stay_exact() -> None:
    f = face_points(FRONT)
    (_, plain, _), _, _ = _face(None)
    seeds = {"l_eye": (f["eye_l"][0] + 6, f["eye_l"][1] + 4),
             "r_eye": (f["eye_r"][0] - 5, f["eye_r"][1] - 4)}  # fmt: skip
    (_, anchors, notes), _, _ = _face(seeds)
    assert anchors["eyes"] == plain["eyes"]  # the marks' own centres, not the seeds
    assert notes["eyes_found"] == ["left", "right"] and notes["eyes_seeded"] == []
    assert {p["status"] for k, p in notes["locator"].items() if k.endswith("eye")} == {"pixel"}


def test_an_eye_the_rules_place_off_its_seed_takes_the_seed_and_says_so() -> None:
    f = face_points(FRONT)
    off = 0.22 * head_height(FRONT)  # beyond 0.15 head heights, short of 0.3
    seeds = {"l_eye": (f["eye_l"][0] + off, f["eye_l"][1]), "r_eye": f["eye_r"]}
    (_, anchors, notes), _, _ = _face(seeds)
    assert notes["locator"]["l_eye"]["status"] == "seed"
    assert notes["locator"]["r_eye"]["status"] == "pixel"
    assert anchors["eyes"]["left"] == seeds["l_eye"]  # the seed, not the mark
    assert notes["eyes_seeded"] == ["left"] and notes["eyes_found"] == ["right"]


def test_an_eye_seed_off_the_head_is_ignored_when_the_rules_found_the_eye() -> None:
    seeds = {"l_eye": (5.0, 5.0)}
    (_, anchors, notes), f, _ = _face(seeds)
    assert notes["locator"]["l_eye"]["status"] == "outside_ignored"
    assert abs(anchors["eyes"]["left"][0] - f["eye_l"][0]) < 3  # the mark, not the seed


# -------------------------------------------------------------------------------- the limbs


def _figure(sk):
    arms = {side: on_skeleton(sk, side) for side in ("r", "l")}
    return silhouette(sk, arms, radius(sk))


def test_a_figure_drawn_on_its_skeleton_stays_unchanged_with_good_seeds() -> None:
    figure = _figure(FRONT)
    h = head_height(FRONT)
    seeds = {n: (x + 0.08 * h, y - 0.05 * h) for n, (x, y) in FRONT.joints.items()
             if n[2:] in ("shoulder", "elbow", "wrist", "hip", "knee", "ankle")}  # fmt: skip
    fitted, report = fit_limbs(figure, FRONT, seeds=seeds)
    assert fitted.joints == FRONT.joints
    assert {j["status"] for r in report.values() for j in r["locator"].values()} == {"pixel"}


def test_two_pixel_fits_that_agree_keep_the_arm_when_the_seed_is_off() -> None:
    figure = _figure(FRONT)
    h = head_height(FRONT)
    (ex, ey), (wx, wy) = FRONT.joints["r_elbow"], FRONT.joints["r_wrist"]
    d = math.dist((ex, ey), (wx, wy))
    seed = (ex + 0.25 * h * (wx - ex) / d, ey + 0.25 * h * (wy - ey) / d)  # on the arm, 0.25 off
    fitted, report = fit_limbs(figure, FRONT, seeds={"r_elbow": seed})
    assert fitted.joints["r_elbow"] == FRONT.joints["r_elbow"]  # the drawing holds
    assert report["arm_r"]["locator"]["r_elbow"]["status"] == "seed_off"


def test_a_limb_the_rules_cannot_fit_takes_the_seed_and_flags_it() -> None:
    sk, h = FRONT, head_height(FRONT)
    # arms pressed against the body: nothing narrow to fit, the skeleton is kept
    arms = {s: drawn_arm(sk, s, -90, -90, shoulder=sk.joints[f"{s}_shoulder"]) for s in ("r", "l")}
    figure = silhouette(sk, arms, radius(sk))
    wx, wy = arms["r"]["wrist"]
    seed = (wx, wy + 0.2 * h)  # down the drawn arm: on the figure
    fitted, report = fit_limbs(figure, sk, seeds={"r_wrist": seed})
    assert report["arm_r"]["locator"]["r_wrist"]["status"] == "seed"
    assert fitted.joints["r_wrist"] == seed


def test_a_limb_seed_off_the_figure_is_ignored_when_the_limb_was_seen() -> None:
    figure = _figure(SIDE)
    fitted, report = fit_limbs(figure, SIDE, seeds={"r_knee": (5.0, 5.0)})
    assert fitted.joints["r_knee"] == SIDE.joints["r_knee"]
    assert report["leg_r"]["locator"]["r_knee"]["status"] == "outside_ignored"


def test_a_limb_nothing_was_seen_of_fails_on_a_seed_off_the_figure_without_crashing() -> None:
    sk = FRONT
    arms = {s: drawn_arm(sk, s, -90, -90, shoulder=sk.joints[f"{s}_shoulder"]) for s in ("r", "l")}
    figure = silhouette(sk, arms, radius(sk))  # arms pressed to the body: nothing to measure
    fitted, report = fit_limbs(figure, sk, seeds={"r_elbow": (5.0, 5.0)})
    assert report["arm_r"]["locator"]["r_elbow"]["status"] == "outside"
    assert fitted.joints["r_elbow"] == sk.joints["r_elbow"]
    fits = {
        f"{b}_{s}": {"ok": True} for b in ("upper_arm", "forearm", "thigh", "shin") for s in "rl"
    }
    assert _locator_report(report, fits)["parts"]["r_elbow"]["status"] == "outside"
    assert (
        not fits["upper_arm_r"]["ok"] and not fits["forearm_r"]["ok"] and fits["upper_arm_l"]["ok"]
    )


def test_a_rescued_limb_and_a_two_pixel_disagreement_follow_the_rules() -> None:
    sk, h = FRONT, head_height(FRONT)
    seen, blind = {"note": None}, {"note": "no arm-shaped strip near the shoulder"}
    names = ("r_shoulder", "r_elbow", "r_wrist")

    def moved(by: float, which=("r_elbow",)) -> Skeleton:
        j = dict(sk.joints)
        for n in which:
            j[n] = (j[n][0], j[n][1] + by * h)
        return replace(sk, joints=j)

    seed = {"r_elbow": (sk.joints["r_elbow"][0], sk.joints["r_elbow"][1] + 0.4 * h)}
    reports = lambda t, s: ({"arm_r": t}, {"arm_r": s})  # noqa: E731
    # the template saw nothing, the seeded fit saw the limb 0.4 head heights from the seed
    # (it can't have moved: the template fit is the skeleton): the two methods disagree
    rep, srep = reports(blind, seen)
    out = _seed_check(np.ones((800, 1344), bool), sk, seed, sk, moved(0.0), rep, srep)
    assert rep["arm_r"]["locator"]["r_elbow"]["status"] == "disagree" and out.joints == sk.joints
    # the template saw a limb far from the seed, the seeded fit landed on the seed: it wins
    rescued = moved(0.4)
    rep, srep = reports(seen, seen)
    out = _seed_check(np.ones((800, 1344), bool), sk, seed, sk, rescued, rep, srep)
    assert out.joints["r_elbow"] == rescued.joints["r_elbow"]
    # the template saw a limb and the seeded fit did not move it: the pixel limb stays
    rep, srep = reports(seen, seen)
    out = _seed_check(np.ones((800, 1344), bool), sk, seed, sk, sk, rep, srep)
    assert out.joints == sk.joints and rep["arm_r"]["locator"]["r_elbow"]["status"] == "seed_off"
    assert names  # (the joints a limb check reads)


def test_without_seeds_the_limbs_are_fitted_exactly_as_before() -> None:
    figure = _figure(SIDE)
    a, ra = fit_limbs(figure, SIDE)
    b, rb = fit_limbs(figure, SIDE, seeds=None)
    assert a.joints == b.joints and ra == rb
    assert all("locator" not in r for r in ra.values())
    assert math.isfinite(sum(x for p in a.joints.values() for x in p))
