"""Round 3 of the rigged-character spike (D-098): framing, the walk's feet, the round head."""

import sys
from pathlib import Path

import numpy as np
import pytest

from studio_core.engines.bake import bake_shot
from studio_core.framing import Margins, check_framing, figure_boxes, screen_box
from studio_core.motions import smooth
from studio_core.motions.gait import foot_report, sole_tracks
from studio_core.puppet.flat import (
    FlatSpec,
    build_flat_puppet,
    build_parts,
    hairline_y,
    leg_ratios,
)

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts/spikes"))
import rigged_character_test as rct

OLD_CAM = {  # the push-in of clip_v2: zoom 1.58 cropped the hair and the boots from 4.25 s
    "move": "track",
    "keys": [
        {"time_s": 0.0, "zoom": 1.0, "cx": 880, "cy": 560},
        {"time_s": 2.4, "zoom": 1.12, "cx": 900, "cy": 570},
        {"time_s": 3.8, "zoom": 1.5, "cx": 800, "cy": 610},
        {"time_s": 6.0, "zoom": 1.58, "cx": 800, "cy": 600},
    ],
}


@pytest.fixture(scope="module")
def film(tmp_path_factory):
    return rct.setup_film(tmp_path_factory.mktemp("film"))


@pytest.fixture(scope="module")
def baked(film):
    return bake_shot(film, rct.shot_spec(rct.CAM))


# --- 1. framing
def test_the_new_push_in_keeps_head_and_feet_in_frame_at_every_frame(baked):
    char, cams = baked["characters"][0], baked["camera_track"]
    assert check_framing(char, cams, (rct.W, rct.H)) == []


def test_the_old_push_in_fails_the_framing_rule(film):
    bake = bake_shot(film, rct.shot_spec(OLD_CAM))
    bad = check_framing(bake["characters"][0], bake["camera_track"], (rct.W, rct.H))
    assert bad and bad[-1]["frame"] == rct.N - 1
    assert any("foot room" in p for b in bad for p in b["problems"])  # the boots are cut off


def test_framing_flags_a_head_over_the_top_edge_and_boots_under_the_bottom(baked):
    char = baked["characters"][0]
    box = figure_boxes(char)[-1]
    w, h = rct.W, rct.H
    _x0, y0, _x1, y1 = screen_box(box, (1.0, w / 2, h / 2), (w, h))
    assert 0 < y0 < y1 < h  # one-to-one at zoom 1
    zoomed = [[3.0, (box[0] + box[2]) / 2, h - (box[1] + box[3]) / 2]]
    assert check_framing({**char, "frames": char["frames"][-1:]}, zoomed, (w, h))  # cropped
    assert (
        not check_framing(
            {**char, "frames": char["frames"][-1:]}, [[1.0, (box[0] + box[2]) / 2, h / 2]], (w, h)
        )
        or Margins().top * h > y0
    )  # a margin is a share of the frame, not a pixel count


# --- 2. the walk's feet
def test_planted_foot_stays_on_the_ground_and_does_not_slide(baked):
    char = baked["characters"][0]
    r = foot_report(char, rct.H - 0.92 * rct.H)
    assert r["float"] <= 4.0, r  # the lower sole touches the ground (the old Mia hovered 9-14 px)
    assert r["sink"] <= 6.0, r  # (a take-off foot dips a few px under the smoothing filter)
    assert r["slide"] <= 4.0, r  # a planted run drifts less than 4 px (the settle slid 30 px)


def test_the_foot_report_catches_a_hovering_and_a_sliding_foot(baked):
    char = baked["characters"][0]
    ground = rct.H - 0.92 * rct.H
    raised = {
        **char,
        "frames": [
            {**fr, "bones": {b: [v[0], v[1] + 12, v[2]] for b, v in fr["bones"].items()}}
            for fr in char["frames"]
        ],
    }
    assert foot_report(raised, ground)["float"] > 8  # 12 px up, whatever the stride
    skating = {
        **char,
        "frames": [
            {
                **fr,
                "bones": {
                    b: [v[0] + (f * 3 if b.startswith("shin") else 0), v[1], v[2]]
                    for b, v in fr["bones"].items()
                },
            }
            for f, fr in enumerate(char["frames"])
        ],
    }
    assert foot_report(skating, ground)["slide"] > 8


def test_feet_lift_off_the_ground_in_turn_and_the_arms_swing_against_the_legs(baked):
    char = baked["characters"][0]
    soles = sole_tracks(char)
    ground = rct.H * 0.08
    walk = range(0, 41)
    for shin, track in soles.items():
        assert max(track[f][1] - ground for f in walk) >= 40, shin  # a real foot lift
    arm = [fr["bones"]["upper_arm_l"][2] for fr in char["frames"][:41]]
    assert max(arm) - min(arm) >= 30  # the arm swings through 30 degrees or more (was ~10)


def test_legs_are_a_third_of_the_figure():
    r = leg_ratios(FlatSpec())
    assert r["visible_leg"] >= 0.33 and r["boot"] <= 0.09


def test_a_torso_lean_does_not_swing_the_planted_feet(tmp_path):
    build_flat_puppet(FlatSpec(), tmp_path)
    from studio_core.rig import load_rig

    view = load_rig(tmp_path / "rig.json").view("front")
    offs = [{"torso": 5.0, "thigh_l": 10.0, "thigh_r": -3.0, "head": 4.0}]
    out = smooth.ground_legs(offs, view)[0]
    assert out["thigh_l"] == 5.0 and out["thigh_r"] == -8.0 and out["head"] == 4.0


# --- 3. the round head
def _layer_alpha(parts, name):
    return np.asarray(parts[1]["layers"][name].done())[..., 3] > 128


def _hull_area(mask: np.ndarray) -> float:
    pts = []
    for y in range(mask.shape[0]):
        xs = np.nonzero(mask[y])[0]
        if len(xs):
            pts += [(xs.min(), y), (xs.max() + 1, y)]
    pts = sorted(set(pts))

    def half(seq):
        h = []
        for p in seq:
            while (
                len(h) >= 2
                and (
                    (h[-1][0] - h[-2][0]) * (p[1] - h[-2][1])
                    - (h[-1][1] - h[-2][1]) * (p[0] - h[-2][0])
                )
                <= 0
            ):
                h.pop()
            h.append(p)
        return h

    hull = half(pts)[:-1] + half(pts[::-1])[:-1]
    return 0.5 * abs(
        sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(hull, hull[1:] + hull[:1], strict=True))
    )


@pytest.fixture(scope="module")
def head_parts():
    ps, info = build_parts(FlatSpec())
    return {p.name: p for p in ps}, info


def test_hair_and_face_form_one_round_silhouette(head_parts):
    parts, info = head_parts
    sil = _layer_alpha((None, info), "over") | _layer_alpha((None, info), "skin")
    sil |= np.asarray(parts["hair_back"].art.done())[..., 3] > 128
    solidity = sil.sum() / _hull_area(sil)
    assert solidity >= 0.93, solidity  # a helmet with lobes and notches sat near 0.88


def test_the_forehead_is_an_arch_not_a_flat_band_with_square_corners(head_parts):
    box = head_parts[1]["box"]
    a = box.w / 2
    centre, temple = hairline_y(box, 0.0), hairline_y(box, 0.95 * a)
    assert (
        temple - centre >= 0.25 * box.h
    )  # the parting is high, the hair sweeps down to the temple
    ys = [hairline_y(box, x) for x in np.linspace(0, a, 40)]
    assert all(b >= a_ for a_, b in zip(ys, ys[1:], strict=False))  # monotone: no step, no corner


def test_skin_never_forms_a_square_corner_beside_the_fringe(head_parts):
    box = head_parts[1]["box"]
    parts, info = head_parts
    skin = _layer_alpha((None, info), "skin")
    over = _layer_alpha((None, info), "over")
    visible = skin & ~over  # the skin the viewer sees on the forehead and cheeks
    oy = parts["head"].art.y0
    rows = range(int(box.top - oy), int(box.top + box.h * 0.6 - oy))
    widths = np.array([visible[y].sum() for y in rows], float)
    widths = widths[widths > 0]
    # a flat hairline over a straight lock gives a width that jumps; the arch grows smoothly
    assert np.abs(np.diff(widths)).max() <= 0.04 * box.w, np.abs(np.diff(widths)).max()
