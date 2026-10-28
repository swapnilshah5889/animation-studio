"""Follow-through for ears and tails (motions/follow.py): a damped-spring layer after the main
motions. Checked on a synthetic rig with ears and a three-segment tail, and on Pip, who has
neither (and must come out exactly as before)."""

import copy
import math

import pytest

from studio_core.config import REPO_ROOT
from studio_core.motions import MOTIONS, Key, MotionContext, animate, follow_through
from studio_core.motions.follow import secondary_bones, simulate, spring_params
from studio_core.motions.timeline import sample
from studio_core.rig import load_rig
from studio_core.schema import validate
from studio_core.sif import Angle, Vec

FPS = 24
PIP = load_rig(REPO_ROOT / "tests" / "fixtures" / "characters" / "pip" / "rig.json")


def with_secondary(
    view: dict, ears: bool = True, tail: int = 3, tail_dir: float = 10.0, **limits
) -> dict:
    """Pip's view plus ear_l/ear_r on the head and a tail chain on the torso."""
    v = copy.deepcopy(view)
    head = v["parts"]["head"]
    lim = {"min": limits.get("lo", -35), "max": limits.get("hi", 35)}

    def add(name, role, side, parent, part, direction, at):
        v["bones"][name] = {
            "role": role, "side": side, "parent": parent, "direction_deg": direction,
            "length_px": 80, "limits_deg": dict(lim), "attach": {"part": part, "at_px": at},
        }  # fmt: skip
        v["parts"][name] = {
            "file": head["file"], "size_px": head["size_px"], "pivot_px": [10, 10], "bone": name,
        }  # fmt: skip

    if ears:
        add("ear_l", "ear", "left", "head", "head", 60, [150, 20])
        add("ear_r", "ear", "right", "head", "head", 120, [50, 20])
        v["draw_order"].insert(v["draw_order"].index("head"), "ear_r")
        v["draw_order"].insert(v["draw_order"].index("head"), "ear_l")
    names = [f"tail_{k + 1}" for k in range(tail)]
    for k, name in enumerate(names):
        add(name, "tail", "center", "torso" if k == 0 else names[k - 1],
            "torso" if k == 0 else names[k - 1], tail_dir, [40, 60])  # fmt: skip
    v["draw_order"] = [*reversed(names), *v["draw_order"]]
    return v


VIEW = with_secondary(PIP.view())


def run(actions, view=VIEW, n=120, **kw):
    return animate(view, actions, fps=FPS, n_frames=n, **kw)


def tilt(side="left", at=0.5, **params):
    return {"motion": "head_tilt", "start_s": at, "params": {"side": side, **params}}


def keys_of(anim, bone, n):
    track = anim.angles[bone]
    by_frame = {w.frame: w.value.degrees for w in track.waypoints}
    frames = sorted(by_frame)

    def at(f):
        if f <= frames[0]:
            return by_frame[frames[0]] if f == frames[0] else 0.0
        if f >= frames[-1]:
            return 0.0 if f > frames[-1] else by_frame[frames[-1]]
        lo = max(x for x in frames if x <= f)
        hi = min(x for x in frames if x >= f)
        if lo == hi:
            return by_frame[lo]
        t = (f - lo) / (hi - lo)
        return by_frame[lo] + (by_frame[hi] - by_frame[lo]) * t

    return [at(f) for f in range(n)]


def head_track(anim, n):
    return keys_of(anim, "head", n)


# --------------------------------------------------------------------------- the spring


def test_the_spring_trails_a_steady_turn_by_its_lag_and_overshoots_a_step() -> None:
    ramp = [2.0 * f for f in range(60)]  # 2 degrees a frame
    sprung = simulate(ramp, lag_s=0.1, damping=0.5, fps=FPS)
    lag_frames = (ramp[50] - sprung[50]) / 2.0
    assert 1.5 < lag_frames < 2.6  # 2z/w = 0.1 s = 2.4 frames, less half a frame of sampling
    step = [0.0] * 5 + [10.0] * 80
    peak = max(simulate(step, lag_s=0.1, damping=0.5, fps=FPS))
    assert 10.2 < peak < 12.5  # a little overshoot (16% at damping 0.5), then it settles
    assert simulate(step, 0.1, 0.5, FPS)[-1] == pytest.approx(10.0, abs=0.05)
    assert simulate([], 0.1, 0.5, FPS) == []


# --------------------------------------------------------------------------- ears


def test_ears_lag_a_head_tilt_by_a_few_frames_and_overshoot_a_little() -> None:
    anim = run([tilt("left", at=0.5, energy=0.5)])
    head = head_track(anim, 120)
    for bone in ("ear_l", "ear_r"):
        off = keys_of(anim, bone, 120)
        world = [h + o for h, o in zip(head, off, strict=True)]
        goal = max(head)
        reach = lambda xs, g=goal: next(f for f, x in enumerate(xs) if x >= 0.5 * g)  # noqa: E731
        assert 1 <= reach(world) - reach(head) <= 6  # trails by a few frames
        assert off[reach(head)] < 0  # on the way up the ear is behind: the offset opposes
        # a little overshoot of the hold, then it settles back on the head
        assert goal < max(world) < 1.3 * goal
        assert off[-1] == pytest.approx(0.0, abs=0.05)
        assert all(abs(o) <= 35 for o in off)
    assert "ear_l" in anim.angles and "ear_r" in anim.angles


def test_ears_splay_outward_when_the_head_drops_in_a_nod() -> None:
    anim = run([{"motion": "nod", "start_s": 0.5, "params": {"energy": 1.0}}])
    left, right = keys_of(anim, "ear_l", 120), keys_of(anim, "ear_r", 120)
    assert min(left) < -1.0 and max(right) > 1.0  # outward: clockwise on the left ear
    assert max(left) < 1.0 and min(right) > -1.0  # and not the other way
    first = next(f for f, x in enumerate(left) if abs(x) > 0.05)
    nod_starts = round(0.5 * FPS)
    assert nod_starts <= first <= nod_starts + 6
    assert left[-1] == pytest.approx(0.0, abs=0.05)


def test_energy_scales_the_ears_response() -> None:
    soft = keys_of(run([tilt(energy=0.0)]), "ear_l", 120)
    big = keys_of(run([tilt(energy=1.0)]), "ear_l", 120)
    assert max(abs(x) for x in big) > 1.5 * max(abs(x) for x in soft) > 0.3


def test_follow_through_stays_inside_the_joint_limits() -> None:
    tight = with_secondary(PIP.view(), lo=-3, hi=3)
    anim = run([tilt(energy=1.0), {"motion": "nod", "start_s": 3.0}], view=tight)
    for bone in ("ear_l", "ear_r", "tail_1", "tail_2", "tail_3"):
        if bone in anim.angles:
            assert all(abs(w.value.degrees) <= 3 + 1e-6 for w in anim.angles[bone].waypoints)
    # the layer clamps itself too, before the final clamp
    channels = {("angle", "head"): [Key(0, 0.0), Key(4, 60.0), Key(30, 0.0)]}
    layer = follow_through(tight, channels, [], fps=FPS, n_frames=60)
    assert layer is not None
    assert all(abs(k.value) <= 3 for keys in layer.channels.values() for k in keys)


def test_follow_through_is_deterministic_and_additive() -> None:
    a = run([tilt(), {"motion": "idle_breathe", "start_s": 0}])
    b = run([tilt(), {"motion": "idle_breathe", "start_s": 0}])
    assert a.angles == b.angles
    layer = next(c for c in a.clips if c.motion == "follow_through")
    assert layer.additive


def test_the_bones_own_follow_block_tunes_or_switches_it_off() -> None:
    v = with_secondary(PIP.view())
    v["bones"]["ear_l"]["follow"] = {"gain": 0.0}
    v["bones"]["ear_r"]["follow"] = {"lag_s": 0.3, "damping": 0.9, "gain": 1.0}
    assert spring_params(v, "ear_r", 0.5) == (0.3, 0.9, 1.0)
    anim = run([tilt()], view=v)
    assert "ear_l" not in anim.angles and "ear_r" in anim.angles
    data = {**PIP.data, "views": {"front": v}}
    assert validate("rig", data) == []


# --------------------------------------------------------------------------- tails


def test_the_tail_sways_with_idle_breathe_and_each_segment_trails_the_last() -> None:
    n = 240
    anim = run([{"motion": "idle_breathe", "start_s": 0}], n=n)
    t1, t2, t3 = (keys_of(anim, f"tail_{k}", n) for k in (1, 2, 3))
    assert t1[0] == 0.0 and max(abs(x) for x in t1) > 1.5  # sways, easing in from rest
    assert abs(t1[2]) < 0.5 * max(abs(x) for x in t1)  # the ramp-in starts gently
    # one sway per period (2.8 s at energy 0.5 -> 2.4 s): count the upward zero crossings
    period = 2.8 + (1.8 - 2.8) * 0.5  # a sway a little over two seconds
    crossings = [f for f in range(60, n - 1) if t1[f] < 0 <= t1[f + 1]]
    assert len(crossings) >= 2
    assert (crossings[1] - crossings[0]) / FPS == pytest.approx(period, rel=0.05)
    # offsets are relative to the parent: the second segment's angle in the world is t1 + t2,
    # and it turns after the first does, not with it
    w2 = [a + b for a, b in zip(t1, t2, strict=True)]
    first_up = lambda xs: next(f for f in range(10, n - 1) if xs[f] < 0 <= xs[f + 1])  # noqa: E731
    assert first_up(w2) > first_up(t1)
    assert max(abs(x) for x in t2) > 0.3 and max(abs(x) for x in t3) > 0.3


def test_the_tail_lags_the_bobbing_body_in_a_walk_and_lifts_while_travelling() -> None:
    n = 120
    travel = [min(f, 80) * 4.0 for f in range(n + 1)]  # 4 px a frame for 80 frames, then still
    anim = run([{"motion": "walk_cycle", "start_s": 0.5}], n=n, travel=travel)
    t1 = keys_of(anim, "tail_1", n)
    sign = -1.0  # the tail points right (10 deg): trailing the rise turns it clockwise
    assert max(abs(x) for x in t1) > 0.5
    moving = [t1[f] for f in range(30, 80)]
    assert sum(moving) / len(moving) > 0.3  # lifted by the travel (counter-clockwise: +)
    after = [t1[f] for f in range(100, 120)]
    assert sum(abs(x) for x in after) / len(after) < sum(moving) / len(moving)  # it settles
    # the bob: its own channel, trailed by a few frames
    root = [w for w in anim.shifts["torso"].waypoints]
    peak_bob = max(root, key=lambda w: w.value.y).frame
    layer_off = [sign * x for x in t1]  # trailing the rise is clockwise
    assert max(layer_off[peak_bob : peak_bob + 8]) > layer_off[peak_bob] - 1e-9


def test_a_tail_pointing_up_does_not_trail_the_bob() -> None:
    v = with_secondary(PIP.view(), ears=False, tail=1, tail_dir=90.0)
    n = 120
    anim = run([{"motion": "walk_cycle", "start_s": 0.5}], view=v, n=n)
    assert "tail_1" not in anim.angles  # no sway without idle, no lift without travel, no bob


def test_one_segment_and_three_segment_tails_both_work() -> None:
    for segments in (1, 2, 3):
        v = with_secondary(PIP.view(), ears=False, tail=segments)
        anim = run([{"motion": "idle_breathe", "start_s": 0}], view=v, n=120)
        assert sorted(b for b in anim.angles if b.startswith("tail")) == [
            f"tail_{k + 1}" for k in range(segments)
        ]


# --------------------------------------------------------------------------- off without them


def test_rigs_without_ears_or_tail_get_no_follow_through() -> None:
    view = PIP.view()
    assert secondary_bones(view) == []
    assert follow_through(view, {}, [], fps=FPS, n_frames=60) is None
    actions = [tilt(), {"motion": "idle_breathe", "start_s": 0}, {"motion": "nod", "start_s": 2}]
    on = animate(view, actions, fps=FPS, n_frames=120)
    off = animate(view, actions, fps=FPS, n_frames=120, secondary=False)
    assert on.angles == off.angles and on.shifts == off.shifts
    assert not any(c.motion == "follow_through" for c in on.clips)


def test_secondary_false_leaves_the_ears_and_tail_at_rest() -> None:
    anim = run([tilt(), {"motion": "idle_breathe", "start_s": 0}], secondary=False)
    assert not any(b.startswith(("ear", "tail")) for b in anim.angles)


def test_the_motions_themselves_do_not_touch_secondary_bones() -> None:
    ctx = MotionContext(view=VIEW, fps=FPS, start=0, last_frame=119, seed="x")
    for name, motion in MOTIONS.items():
        clip = motion(ctx)
        touched = {bone for (_, bone) in clip.channels}
        assert not touched & {"ear_l", "ear_r", "tail_1", "tail_2", "tail_3"}, name


def test_a_pose_on_an_ear_is_kept_and_summed_with_the_layer() -> None:
    pose = [{"time_s": 3.0, "bones": {"ear_l": 20.0}}]
    anim = run([tilt()], poses=pose)
    wp = {w.frame: w.value.degrees for w in anim.angles["ear_l"].waypoints}
    assert wp[72] == pytest.approx(20.0, abs=1.0)
    assert math.isfinite(Angle(0).degrees) and Vec(0, 0).x == 0


# ------------------------------------------------------------- the tail's gains (looked at by eye
# in renders/secondary/kit_follow.png: ears and tail read at preview size, none too big)


def offset(layer, bone, frame):
    return sample(layer.channels[("angle", bone)], frame)


def test_the_tail_sway_has_a_few_degrees_and_a_period_that_shortens_with_energy() -> None:
    peaks, periods = {}, {}
    for energy in (0.0, 0.5, 1.0):
        anim = run([{"motion": "idle_breathe", "start_s": 0, "params": {"energy": energy}}], n=360)
        t1 = keys_of(anim, "tail_1", 360)
        up = [f for f in range(60, 359) if t1[f] < 0 <= t1[f + 1]]
        peaks[energy], periods[energy] = max(abs(x) for x in t1), (up[1] - up[0]) / FPS
    assert peaks[0.0] == pytest.approx(3.6, abs=0.6)
    assert peaks[0.5] == pytest.approx(5.9, abs=0.8)
    assert peaks[1.0] == pytest.approx(8.2, abs=1.0)
    assert periods[0.0] == pytest.approx(2.8, rel=0.05)
    assert periods[1.0] == pytest.approx(1.8, rel=0.05)


def test_the_sway_eases_in_from_rest_over_half_a_second() -> None:
    anim = run([{"motion": "idle_breathe", "start_s": 0}], n=240)
    t1 = keys_of(anim, "tail_1", 240)
    assert max(abs(x) for x in t1[:7]) < 0.07 * max(abs(x) for x in t1)  # 1.1 without the ease


def test_the_tail_lifts_while_the_character_travels_by_more_the_faster_it_goes() -> None:
    n = 160
    lifts = {}
    for energy in (0.5, 1.0):
        layer = follow_through(
            VIEW, {}, [], fps=FPS, n_frames=n, energy=energy, travel=[8.0 * f for f in range(n + 1)]
        )  # 8 px a frame: 0.37 of the body's height in px a second
        lifts[energy] = offset(layer, "tail_1", 120)
    assert lifts[0.5] == pytest.approx(2.6, abs=0.15)  # counter-clockwise: the tail points right
    assert lifts[1.0] == pytest.approx(3.7, abs=0.15)


def test_the_first_tail_segment_trails_the_bodys_rise_and_the_others_only_follow_it() -> None:
    from studio_core.sif import Vec

    rise = {("shift", "torso"): [Key(0, Vec(0, 0)), Key(10, Vec(0, 10))]}  # up 10 px, then held
    layer = follow_through(VIEW, rise, [], fps=FPS, n_frames=160, energy=0.5)
    assert offset(layer, "tail_1", 150) == pytest.approx(-11.0, abs=0.3)  # 1.1 degrees per px
    for k in (2, 3):  # settled: they chase the segment before, which has stopped moving
        assert (
            abs(offset(layer, f"tail_{k}", 150)) < 0.3
            if ("angle", f"tail_{k}") in layer.channels
            else True
        )


def test_the_ears_lag_shortens_with_energy() -> None:
    lags = [spring_params(VIEW, "ear_l", e)[0] for e in (0.0, 1.0)]
    assert lags == pytest.approx([0.10, 0.06])
