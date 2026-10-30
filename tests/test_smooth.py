"""Smooth motion (D-093): pops blended, speed capped, faces continuous, shots cross-faded."""

import itertools
import math

import pytest

from studio_core.motions import smooth
from studio_core.motions.timeline import Clip, Key


def test_blend_pops_leaves_clean_motion_untouched_and_softens_a_jump():
    ramp = [i * 2.0 for i in range(30)]
    assert smooth.blend_pops(ramp) == ramp  # no pop: byte-identical
    jump = [0.0] * 10 + [60.0] * 10
    out = smooth.blend_pops(jump)
    assert max(abs(b - a) for a, b in itertools.pairwise(out)) < 60 * 0.5
    assert out[0] == pytest.approx(0.0, abs=1e-3) and out[-1] == pytest.approx(60.0, abs=1e-3)
    assert all(0 <= v <= 60 for v in out)  # no overshoot


def test_limit_step_caps_every_frame_to_frame_change():
    spiky = [0, 0, 80, 0, 0, 40, 40, 40, -40, -40]
    out = smooth.limit_step(spiky, 12.0)
    assert max(abs(b - a) for a, b in itertools.pairwise(out)) <= 12.0 + 1e-6
    assert smooth.limit_step([1, 2, 3], 5.0) == [1, 2, 3]  # already within: unchanged


def test_smooth_offsets_respects_per_bone_caps_and_keeps_bones():
    offs = [{"a": 0.0, "b": 0.0}] * 5 + [{"a": 90.0, "b": 10.0}] * 5
    out = smooth.smooth_offsets(offs, 24, max_dps={"a": 240.0})  # 10 deg/frame
    steps = [abs(y["a"] - x["a"]) for x, y in itertools.pairwise(out)]
    assert max(steps) <= 10.0 + 1e-6
    assert set(out[0]) == {"a", "b"}


def test_clip_declares_speed_caps_like_limits():
    c1 = Clip("x", 0, 5, {}, max_speed_dps={"arm": 500.0})
    c2 = Clip("y", 0, 5, {}, max_speed_dps={"arm": 300.0, "leg": 100.0})
    assert smooth.speed_caps([c1, c2]) == {"arm": 300.0, "leg": 100.0}
    assert Clip("z", 0, 1, {}).max_speed_dps == {}
    assert Key(0, 1.0)  # keys unchanged


def test_smootherstep_is_flat_at_both_ends():
    assert smooth.smootherstep(0) == 0 and smooth.smootherstep(1) == 1
    assert smooth.smootherstep(0.01) < 1e-4 and 1 - smooth.smootherstep(0.99) < 1e-4
    assert smooth.smootherstep(0.5) == pytest.approx(0.5)


def test_eased_track_eases_in_and_out_and_holds():
    v = smooth.eased_track([(0.5, 0.0), (1.5, 1.0)], 24, 48)
    assert v[0] == 0 and v[-1] == 1
    first, mid = v[13] - v[12], v[24] - v[23]
    assert first < mid * 0.2  # slow start, fast middle
    assert all(b >= a - 1e-12 for a, b in itertools.pairwise(v))


def test_blink_closes_over_frames_not_in_one():
    states = ["open"] * 5 + ["closed"] * 3 + ["open"] * 10
    eo = smooth.eye_series(states, 24)
    assert max(abs(b - a) for a, b in itertools.pairwise(eo)) < 0.5
    assert min(eo) < 0.2 and eo[0] == 1.0 and eo[-1] > 0.9
    assert sum(1 for v in eo if 0.05 < v < 0.95) >= 4  # real in-between frames


def test_mouth_blends_and_leads_the_sound():
    letters = ["X"] * 6 + ["D"] * 6 + ["X"] * 6
    m = smooth.mouth_series(letters, 24)
    opens = [f["open"] for f in m]
    assert max(abs(b - a) for a, b in itertools.pairwise(opens)) < 0.5
    assert opens[5] > 0.0  # leads by a frame: already opening before the D starts at 6
    assert max(opens) > 0.7
    f = smooth.mouth_series(["F"] * 12, 24)[-1]
    assert f["round"] > 0.9 and f["width"] < 0.7  # a held F reaches its pucker


def test_expressions_cross_over_instead_of_popping():
    ex = smooth.expression_series(
        [{"expr": "neutral", "start_s": 0}, {"expr": "surprised", "start_s": 1.0}], 24, 48
    )
    brows = [e[1] for e in ex]
    assert brows[23] == 0.0 and brows[-1] == pytest.approx(0.9)
    assert max(abs(b - a) for a, b in itertools.pairwise(brows)) < 0.2


def test_face_series_has_yaw_and_look_leads_it():
    fs = smooth.face_series(
        ["open"] * 48, ["X"] * 48, [{"expr": "happy", "start_s": 0}], [(0.5, 0.0), (1.5, 1.0)], 24
    )
    assert len(fs) == 48
    assert fs[0]["yaw"] == 0 and fs[-1]["yaw"] == 1.0
    mid = next(i for i, f in enumerate(fs) if 0.2 < f["yaw"] < 0.8)
    assert fs[mid]["look"][0] > fs[mid]["yaw"]  # eyes get there first
    assert all(math.isfinite(f["smile"]) for f in fs)


def test_crossfade_alpha_is_a_smooth_ramp():
    a = [smooth.crossfade_alpha(f, 10, 8) for f in range(24)]
    assert a[9] == 0 and a[18] == 1 and a[23] == 1
    assert all(y >= x for x, y in itertools.pairwise(a))
    assert smooth.crossfade_alpha(5, 5, 0) == 1.0  # zero length is a hard cut
