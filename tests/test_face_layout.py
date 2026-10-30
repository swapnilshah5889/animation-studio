# ruff: noqa: E501
"""The parametric face keeps its proportions (D-093): limits, anchoring and the head turn."""

import itertools

import pytest

from studio_core import face_layout as fl
from studio_core.face_layout import FaceBox, FaceStyle, check_layout, layout_face

BOX = FaceBox.from_head_bbox(0, 0, 330, 300)


def test_default_face_is_legal_and_centred():
    lay = layout_face(BOX)
    assert check_layout(lay) == []
    assert lay.corrections == {}
    assert lay.mouth[0] == pytest.approx(BOX.cx)
    assert (lay.eye_l[0] + lay.eye_r[0]) / 2 == pytest.approx(BOX.cx)
    assert lay.mouth[1] > lay.nose[1] > lay.eye_l[1]


def test_mia_old_face_would_have_been_refused():
    """The measured bug: eyes 165 px apart on a 212 px face (78%), mouth 49 px off the eyes' midpoint."""
    box = FaceBox(cx=203.0, top=100, w=212, h=220)
    wide = FaceStyle(eye_gap=165 / 212, eye_w=57.8 / 212)
    lay = layout_face(box, wide)
    assert "eye_gap" in lay.corrections  # clamped, not trusted
    gap = lay.eye_l[0] - lay.eye_r[0]
    assert gap / box.w <= fl.LIMITS["eye_gap"][1] + 1e-9
    assert lay.mouth[0] == pytest.approx((lay.eye_l[0] + lay.eye_r[0]) / 2)  # never beside an eye
    assert check_layout(lay) == []


@pytest.mark.parametrize("box", [BOX, FaceBox(100, 40, 80, 90), FaceBox(500, 10, 1000, 700)])
def test_every_style_and_yaw_in_range_stays_legal(box):
    values = {k: (lo - 0.3, (lo + hi) / 2, hi + 0.3) for k, (lo, hi) in fl.LIMITS.items()}
    names = list(values)
    for combo in itertools.product(*(values[n] for n in names[:5])):  # 3^5 styles
        style = FaceStyle(**dict(zip(names[:5], combo, strict=True)))
        for yaw in (-2.0, -1.0, -0.4, 0.0, 0.4, 1.0, 2.0):
            lay = layout_face(box, style, yaw)
            assert check_layout(lay) == [], (style, yaw, check_layout(lay))


def test_limits_are_hard_per_proportion():
    st, notes = fl.clamp_style(
        FaceStyle(eye_gap=0.9, eye_w=0.5, eye_y=0.1, mouth_y=0.99, mouth_w=0.9)
    )
    for name, (lo, hi) in fl.LIMITS.items():
        assert lo <= getattr(st, name) <= hi
    assert {"eye_gap", "eye_w", "eye_y"} <= set(notes)


def test_mouth_stays_below_eyes_and_narrower_than_the_eye_gap():
    lay = layout_face(BOX, FaceStyle(eye_y=0.62, mouth_y=0.72, mouth_w=0.3, eye_gap=0.30))
    assert (lay.mouth[1] - lay.eye_l[1]) / BOX.h >= fl.MIN_MOUTH_DROP - 1e-9
    assert lay.mouth_w <= (lay.eye_l[0] - lay.eye_r[0]) * fl.MOUTH_TO_GAP + 1e-9
    assert fl.mouth_half_width(lay, 3.0) * 2 <= (lay.eye_l[0] - lay.eye_r[0]) * 1.0 + 1e-9


def test_head_turn_moves_the_whole_face_the_same_way_with_the_nose_furthest():
    straight, turned = layout_face(BOX, yaw=0.0), layout_face(BOX, yaw=0.5)
    for key in ("mouth", "nose", "eye_l", "eye_r"):
        assert getattr(turned, key)[0] > getattr(straight, key)[0]
    d = {k: getattr(turned, k)[0] - getattr(straight, k)[0] for k in ("mouth", "nose")}
    assert d["nose"] > d["mouth"] > 0
    assert turned.eye_w_r < turned.eye_w_l  # the viewer's-left eye is the far one
    mirrored = layout_face(BOX, yaw=-0.5)
    assert mirrored.mouth[0] - BOX.cx == pytest.approx(-(turned.mouth[0] - BOX.cx))
    assert mirrored.eye_w_l == pytest.approx(turned.eye_w_r)


def test_face_never_leaves_the_head_turned_hard_and_asks_for_a_turned_set():
    lay = layout_face(BOX, yaw=1.0)
    assert lay.needs_turned_set and not layout_face(BOX, yaw=0.3).needs_turned_set
    assert check_layout(lay) == []
    assert layout_face(BOX, yaw=7.0).yaw == 1.0


def test_face_box_from_head_bbox_scales_with_the_head():
    small, big = FaceBox.from_head_bbox(0, 0, 100, 100), FaceBox.from_head_bbox(0, 0, 200, 200)
    assert big.w == pytest.approx(2 * small.w) and big.h == pytest.approx(2 * small.h)
    a, b = layout_face(small), layout_face(big)
    assert b.eye_w_l == pytest.approx(2 * a.eye_w_l) and b.mouth[1] == pytest.approx(2 * a.mouth[1])


def test_check_layout_catches_a_bad_face():
    lay = layout_face(BOX)
    from dataclasses import replace

    off = replace(lay, mouth=(lay.eye_l[0], lay.mouth[1]))  # the bug: a mouth beside the eye
    assert any("mouth" in p for p in check_layout(off))
    cross = replace(lay, eye_l=(lay.eye_r[0] - 5, lay.eye_l[1]))
    assert check_layout(cross)


def test_flat_puppet_builds_a_valid_rig_with_a_legal_face(tmp_path):
    from studio_core.puppet.flat import FlatSpec, build_flat_puppet
    from studio_core.rig import load_rig

    rig = build_flat_puppet(FlatSpec(), tmp_path)
    view = load_rig(tmp_path / "rig.json").view("front")  # schema-valid, part files exist
    face = view["face"]
    lay = layout_face(fl.face_box_of_rig_face(face), fl.style_of_rig_face(face))
    assert check_layout(lay) == [] and lay.corrections == {}
    assert {"hair_l", "hair_r"} <= set(view["bones"]) and view["bones"]["hair_l"]["role"] == "ear"
    assert rig["views"]["front"]["parts"]["head"]["bone"] == "head"


def test_face_draws_from_continuous_numbers(tmp_path):
    import numpy as np
    from PIL import Image

    from studio_core.engines.face_flat import FaceState, MouthShape, draw_face
    from studio_core.puppet.flat import Palette

    skin = Image.new("RGBA", (330, 330), (246, 203, 165, 255))
    over = Image.new("RGBA", (330, 330), (0, 0, 0, 0))
    lay = layout_face(FaceBox(165, 60, 240, 220))
    imgs = [
        np.asarray(
            draw_face(skin, over, lay, FaceState(eye_open=o, mouth=MouthShape(open=m)), Palette())
        ).astype(int)
        for o, m in ((1.0, 0.0), (0.5, 0.3), (0.0, 0.9))
    ]
    assert abs(imgs[0] - imgs[1]).sum() > 0 and abs(imgs[1] - imgs[2]).sum() > 0
    # halfway states differ from both ends by less than the ends differ from each other
    assert abs(imgs[0] - imgs[1]).sum() < abs(imgs[0] - imgs[2]).sum()
