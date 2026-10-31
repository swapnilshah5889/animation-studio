"""A head turn moves the whole head as one (D-097): skin, hair and face together, with parallax."""

import numpy as np
import pytest

from studio_core import face_layout as fl
from studio_core.engines.face_flat import warp_image
from studio_core.motions import smooth
from studio_core.puppet.flat import FlatSpec, build_parts

YAWS = [round(-1 + i * 0.05, 2) for i in range(41)]


@pytest.fixture(scope="module")
def mia():
    spec = FlatSpec()
    ps, info = build_parts(spec)
    by = {p.name: p for p in ps}
    head = by["head"].art
    local = fl.FaceBox(
        info["box"].cx - head.x0, info["box"].top - head.y0, info["box"].w, info["box"].h
    )
    return spec, by, local, -head.x0, info


def alpha(img) -> np.ndarray:
    return np.asarray(img)[..., 3] > 128


def test_warp_is_identity_at_zero_and_mirrors_for_negative_yaw():
    w0 = fl.head_warp(0.0, 330)
    assert w0.map_x(50) == 50 and w0.map_x(-50) == -50
    a, b = fl.head_warp(0.6, 330), fl.head_warp(-0.6, 330)
    for x in (-120, -30, 40, 150):
        assert a.map_x(x) == pytest.approx(-b.map_x(-x))
    assert fl.head_warp(5.0, 330).shift == pytest.approx(fl.HEAD_SHIFT * 330)  # clamped to yaw 1


def test_warp_is_continuous_and_monotone_so_nothing_folds():
    for yaw in YAWS:
        w = fl.head_warp(yaw, 330)
        xs = np.linspace(-200, 200, 401)
        mapped = np.array([w.map_x(x) for x in xs])
        assert (np.diff(mapped) > 0).all()
        assert abs(w.map_x(1e-6) - w.map_x(-1e-6)) < 1e-3


@pytest.mark.parametrize("yaw", YAWS)
def test_face_features_stay_inside_the_skin_at_every_yaw(mia, yaw):
    spec, by, local, axis, _ = mia
    skin = by["head"].art.done()
    w = fl.head_warp(yaw, spec.head_w)
    mask = alpha(warp_image(skin, axis, w))
    lay = fl.layout_face(local, spec.face_style, yaw)
    pts = [
        (lay.eye_l[0] + lay.eye_w_l / 2, lay.eye_l[1]),
        (lay.eye_r[0] - lay.eye_w_r / 2, lay.eye_r[1]),
        lay.nose,
        (lay.mouth[0] - lay.mouth_w / 2, lay.mouth[1]),
        (lay.mouth[0] + lay.mouth_w / 2, lay.mouth[1]),
    ]
    for x, y in pts:
        xw = axis + w.map_x(x - axis)  # the face is drawn on the head, then the head is turned
        assert mask[int(y), round(xw)], (yaw, x, y)


@pytest.mark.parametrize("yaw", [y for y in YAWS if abs(y) >= 0.1])
def test_head_moves_a_stated_share_of_the_face_shift_and_features_move_more(mia, yaw):
    spec, _, local, axis, _ = mia
    w = fl.head_warp(yaw, spec.head_w)
    lay = fl.layout_face(local, spec.face_style, yaw)
    slide = lay.mouth[0] - local.cx  # the face's slide within the head
    total = w.map_x(slide)  # where the mouth ends up (head shift + slide, squashed)
    assert abs(w.shift) >= fl.MIN_HEAD_SHARE * abs(total)
    nose = w.map_x(lay.nose[0] - local.cx)
    assert (
        abs(nose) > abs(total) > abs(w.shift)
    )  # parallax: nose most, then the face, then the head


@pytest.mark.parametrize("yaw", YAWS)
def test_head_outline_never_detaches_from_the_neck(mia, yaw):
    spec, by, _, axis, _ = mia
    w = fl.head_warp(yaw, spec.head_w)
    mask = alpha(warp_image(by["head"].art.done(), axis, w))
    row = int(spec.neck_y - 8 - by["head"].art.y0)
    cols = slice(int(axis - 17), int(axis + 17))  # the neck's width at the collar
    assert mask[row, cols].mean() >= 0.6  # the chin still sits over the neck


@pytest.mark.parametrize("name", ["hair_back", "hair_l", "hair_r", "head"])
@pytest.mark.parametrize("yaw", [-1.0, -0.55, 0.55, 1.0])
def test_turned_parts_keep_size_are_not_clipped_and_the_far_side_tucks(mia, name, yaw):
    spec, by, _, axis, _ = mia
    art = by[name].art
    img = art.done()
    ax = (
        axis if name in ("head", "hair_back") else -art.x0 + 0
    )  # a lock: figure x = 0 axis in its image
    w = fl.head_warp(yaw, spec.head_w)
    out = warp_image(img, ax, w)
    assert out.size == img.size
    a = alpha(out)
    assert a[:, 0].sum() == 0 and a[:, -1].sum() == 0  # the shift did not push art off its image
    if name in ("head", "hair_back"):
        left, right = a[:, : round(axis)].sum(), a[:, round(axis) :].sum()
        far_is_left = yaw > 0
        assert (left < right) == far_is_left  # the far lobe narrows


def test_hair_lags_the_head_and_settles():
    yaws = [0.0] * 6 + [0.8] * 30
    lag = fl.smooth_lag(yaws, 24)
    assert lag[6] < 0.5 * 0.8 and lag[8] < 0.8  # it has not caught up in the first frames
    assert lag[-1] == pytest.approx(0.8, abs=0.01)  # it settles on the head
    assert all(
        b >= a - 1e-9 for a, b in zip(lag, lag[1:], strict=False)
    )  # no overshoot into a wobble
    fs = smooth.face_series(["open"] * 48, ["X"] * 48, [], [(0.5, 0.0), (1.2, 0.9)], 24)
    mid = next(i for i, f in enumerate(fs) if 0.2 < f["yaw"] < 0.8)
    assert fs[mid]["yaw_hair"] < fs[mid]["yaw"]  # the baked hair yaw trails the head's


def test_rig_carries_head_width_for_the_turn(tmp_path):
    from studio_core.puppet.flat import build_flat_puppet
    from studio_core.rig import load_rig

    build_flat_puppet(FlatSpec(), tmp_path)
    face = load_rig(tmp_path / "rig.json").view("front")["face"]
    assert face["layout"]["head_w"] == FlatSpec().head_w
