"""Real-motion clips played on a puppet, and the principles layer (offline, no rendering)."""

import math

import pytest
from jsonschema import ValidationError  # noqa: F401  (schema errors come back as issues)

from studio_core.config import REPO_ROOT
from studio_core.mocap import metrics
from studio_core.mocap.retarget import RealClip
from studio_core.motions import MOTIONS, MotionContext, animate, compose, sample
from studio_core.motions import principles as pr
from studio_core.motions.real import (
    REAL_MOTIONS,
    at,
    available,
    fit_to_limits,
    load_clip,
    periodic,
    soft_limit,
    two_bone_ik,
)
from studio_core.motions.timeline import Clip, Key
from studio_core.rig import load_rig, world_pose
from studio_core.schema import validate
from studio_core.sif import Vec

PIP = REPO_ROOT / "tests" / "fixtures" / "characters" / "pip" / "rig.json"
VIEW = load_rig(PIP).view()
FPS = 24
LEG = 230.0  # Pip's thigh + shin


def eased_travel(distance: float, seconds: float, n: int) -> list[float]:
    def ss(t: float) -> float:
        t = max(0.0, min(1.0, t))
        return t * t * (3 - 2 * t)

    return [distance * ss(f / FPS / seconds) for f in range(n + 1)]


def run(motion: str, n: int = 120, travel: list[float] | None = None, **params):
    action = {"motion": motion, "start_s": 0.0, **params.pop("action", {}), "params": params}
    return animate(VIEW, [action], fps=FPS, n_frames=n, travel=travel, secondary=False)


# --------------------------------------------------------------------------- the clips


def test_the_real_clips_are_shipped_and_registered() -> None:
    assert set(available()) >= {"walk", "run", "wave", "jump", "shrug"}
    for motion in REAL_MOTIONS:
        assert motion in MOTIONS, motion


@pytest.mark.parametrize("name", ["walk", "run"])
def test_gait_clips_are_seamless_loops_that_travel(name: str) -> None:
    clip = load_clip(name)
    assert clip.loop and clip.stride_cycle and clip.stride_cycle > 1.0  # more than a leg per cycle
    for track in clip.tracks.values():
        assert abs(track[-1] - track[0]) < 25  # the seam is a normal frame step, not a jump
    for side in ("left", "right"):
        assert any(clip.contacts[side]) and not all(clip.contacts[side])
    assert clip.stats["loop_seam_deg"] < 15


def test_clip_json_round_trips() -> None:
    clip = load_clip("wave")
    assert RealClip.from_json(clip.to_json()).tracks == clip.tracks


# --------------------------------------------------------------------------- the maths


def test_fit_to_limits_scales_instead_of_flat_clamping() -> None:
    track = [0.0, 40.0, 80.0, 40.0, -20.0]
    out = fit_to_limits(track, -30, 60)
    assert max(out) == pytest.approx(60) and out[2] > out[1] > out[0]  # still strictly rising
    assert out[4] == pytest.approx(-20)  # the part inside the range is not touched (down = 1)
    assert fit_to_limits([0.0, 5.0], -30, 60) == [0.0, 5.0]
    assert min(fit_to_limits([0.0, -400.0], -30, 60)) >= -30  # never beyond, even after the floor


def test_two_bone_ik_reaches_the_target_with_the_asked_bend() -> None:
    for bend in (1.0, -1.0):
        t1, t2, _ = two_bone_ik(100.0, 120.0, 60.0, -150.0, bend)
        ex = 100 * math.cos(math.radians(t1)) + 120 * math.cos(math.radians(t2))
        ey = 100 * math.sin(math.radians(t1)) + 120 * math.sin(math.radians(t2))
        assert (ex, ey) == pytest.approx((60, -150), abs=1e-6)
        kx, ky = 100 * math.cos(math.radians(t1)), 100 * math.sin(math.radians(t1))
        cross = kx * (ey - ky) - ky * (ex - kx)
        assert cross * bend > 0
    far = two_bone_ik(100.0, 120.0, 0.0, -500.0, 1.0)  # out of reach: a straight leg
    assert far[2] < 220 and far[0] == pytest.approx(far[1], abs=0.05)


def test_soft_limit_eases_deep_bends_and_leaves_small_ones() -> None:
    assert soft_limit(20.0, 35.0, 65.0) == 20.0 and soft_limit(-35.0, 35.0, 65.0) == -35.0
    deep = [soft_limit(v, 35.0, 65.0) for v in (-40.0, -60.0, -100.0, -300.0)]
    assert deep == sorted(deep, reverse=True) and deep[-1] > -65.0  # monotonic, never past the cap
    assert soft_limit(-60.0, 35.0, 65.0) > -60.0


def test_loop_and_hold_sampling() -> None:
    assert periodic([0.0, 10.0], 0.5) == 5.0 and periodic([0.0, 10.0], 1.5) == 5.0
    assert at([0.0, 10.0], 7.0) == 10.0 and at([0.0, 10.0], 0.25) == 2.5


# --------------------------------------------------------------------------- playing them


def test_walk_real_steps_with_the_distance_and_keeps_the_foot_planted() -> None:
    n = 120
    travel = eased_travel(700.0, 2.2, n)
    anim = run("walk_real", n, travel, action={"duration_s": 2.2}, energy=0.6)
    feet = metrics.foot_tracks(VIEW, anim.clips, n, travel)
    slide = metrics.foot_slide(
        {s: metrics.FootTrack(t.x[:40], t.y[:40]) for s, t in feet.items()}, LEG
    )
    assert slide["contacts"] >= 2
    assert slide["mean"] < 0.06  # the planted ankle drifts under 6% of a leg length
    # the legs really bend (an old-style walk keeps the shins rigid)
    knee = [sample(anim.clips[0].channels[("angle", "shin_l")], f) for f in range(2, 40)]
    assert max(knee) - min(knee) > 40


def test_walk_real_covers_whole_half_cycles() -> None:
    """Stopping mid-stride would leave a foot in the air: the walk ends on a passing pose."""
    n = 90
    travel = eased_travel(520.0, 2.0, n)
    anim = run("walk_real", n, travel, action={"duration_s": 2.0})
    keys = anim.clips[0].channels[("angle", "thigh_l")]
    assert abs(float(sample(keys, 49))) < 25 and keys[-1].frame >= 47


def test_walk_real_in_place_plays_at_the_actors_pace() -> None:
    anim = run("walk_real", 120, None, action={"duration_s": 2.0})
    keys = anim.clips[0].channels[("angle", "thigh_l")]
    values = [float(sample(keys, f)) for f in range(0, 49)]
    assert max(values) - min(values) > 15


def test_run_real_and_walk_real_differ() -> None:
    travel = eased_travel(900.0, 2.0, 100)
    walk = run("walk_real", 100, travel, action={"duration_s": 2.0}).clips[0]
    jog = run("run_real", 100, travel, action={"duration_s": 2.0}).clips[0]
    assert len(jog.channels[("angle", "thigh_l")]) != len(walk.channels[("angle", "thigh_l")]) or (
        jog.channels[("angle", "thigh_l")][10].value
        != walk.channels[("angle", "thigh_l")][10].value
    )


def test_wave_real_raises_the_asked_arm_and_mirrors() -> None:
    right = run("wave_real", 120, side="right", energy=1.0).clips[0].channels
    left = run("wave_real", 120, side="left", energy=1.0).clips[0].channels
    r = [float(k.value) for k in right[("angle", "upper_arm_r")]]
    lf = [float(k.value) for k in left[("angle", "upper_arm_l")]]
    assert min(r) < -90 and max(lf) > 90  # raised past horizontal, each in its own direction
    assert lf == pytest.approx([-v for v in r])  # the mirror image
    assert ("angle", "upper_arm_l") not in right or max(
        abs(float(k.value)) for k in right[("angle", "upper_arm_l")]
    ) < 5


def test_every_real_motion_starts_and_ends_near_rest() -> None:
    for motion in ("wave_real", "jump_real", "shrug_real"):
        clip = run(motion, 200, energy=0.6).clips[0]
        for (kind, bone), keys in clip.channels.items():
            if kind != "angle" or bone.startswith(("thigh", "shin")):
                continue
            assert abs(float(keys[0].value)) < 1e-6, (motion, bone)
            assert abs(float(keys[-1].value)) < 12, (motion, bone, keys[-1].value)


def test_upper_body_gestures_keep_the_legs_standing() -> None:
    """Bent legs open seams in a rigid cut (pose sweep): a wave or a shrug moves no leg bone."""
    for motion in ("wave_real", "shrug_real"):
        clip = run(motion, 120, energy=0.6).clips[0]
        leg = [
            keys
            for (kind, bone), keys in clip.channels.items()
            if kind == "angle" and bone.startswith(("thigh", "shin"))
        ]
        assert all(abs(float(k.value)) < 1e-6 for keys in leg for k in keys), motion
        torso = clip.channels.get(("shift", "torso"), [])
        assert all(abs(k.value.y) < 1e-6 for k in torso)  # type: ignore[union-attr]


def test_jump_real_leaves_the_ground_and_lands() -> None:
    clip = run("jump_real", 200, energy=0.6).clips[0]
    ys = [sample(clip.channels[("shift", "torso")], f).y for f in range(0, 80)]  # type: ignore[union-attr]
    assert max(ys) > 50  # airborne by a good fraction of a leg
    assert min(ys) < -20  # the crouch before it
    assert abs(ys[-1]) < 30  # landed


def test_real_clips_widen_the_shin_range_they_need_and_nothing_else() -> None:
    anim = run("walk_real", 120, eased_travel(600, 2, 120), action={"duration_s": 2.0})
    assert anim.clips[0].limits == {
        "shin_l": (-65.0, 65.0),
        "shin_r": (-65.0, 65.0),
        "thigh_l": (-50.0, 50.0),
        "thigh_r": (-50.0, 50.0),
        "forearm_l": (-100.0, 100.0),
        "forearm_r": (-100.0, 100.0),
    }
    shin = [
        w.value.degrees if hasattr(w.value, "degrees") else w.value
        for w in anim.angles["shin_l"].waypoints
    ]
    assert min(float(getattr(v, "degrees", v)) for v in shin) < -40  # beyond the front rig's -10
    # a non-real motion still clamps to the rig's own limits
    wave = animate(
        VIEW, [{"motion": "wave", "start_s": 0, "params": {"energy": 1}}], fps=FPS, n_frames=100
    )
    assert wave.clips[0].limits == {}


def test_real_motion_names_pass_the_shot_schema() -> None:
    def spec(action: dict) -> dict:
        char = {"id": "pip", "position": [0.5, 0.9], "actions": [action]}
        return {"id": "s01_sh01", "duration_s": 4, "background": "meadow", "characters": [char]}

    assert (
        validate("shot", spec({"motion": "walk_real", "start_s": 0, "params": {"speed": 1.2}}))
        == []
    )
    assert (
        validate("shot", spec({"motion": "jump", "start_s": 0, "params": {"principles": 0.5}}))
        == []
    )
    assert validate(
        "shot", spec({"motion": "walk_real", "start_s": 0, "params": {"principles": 2}})
    )


# --------------------------------------------------------------------------- the principles


def test_anticipation_dips_against_the_move_and_leaves_the_move_alone() -> None:
    move = [0.0] * 10 + [5.0 * i for i in range(1, 9)] + [40.0] * 6
    out = pr.anticipate(move, 1.0)
    assert min(out[4:10]) < -1  # winds up opposite to the upward move
    assert out[10:] == move[10:]  # the move itself is the same
    assert pr.anticipate(move, 0.0) == move


def test_overshoot_goes_past_then_settles() -> None:
    move = [0.0] * 6 + [10.0 * i for i in range(1, 6)] + [50.0] * 25
    out = pr.overshoot_settle(move, 0.6)
    assert max(out) > 50.5 and min(out[12:]) < 50  # past, then back under: a spring
    assert out[-1] == pytest.approx(50.0, abs=0.2)  # settled
    assert pr.overshoot_settle(move, 0.0) == move


def test_lead_and_drag_shift_in_time() -> None:
    v = [0.0, 0.0, 1.0, 2.0, 3.0, 3.0]
    assert pr.lead(v, 2) == [1.0, 2.0, 3.0, 3.0, 3.0, 3.0]
    assert pr.drag(v, 2)[4] == 1.0 and pr.drag(v, 2, 0.5)[4] == 2.0


def test_contact_dips_and_breathing() -> None:
    dips = pr.contact_dips(20, [5], 10.0, 4)
    assert dips[5] == -10.0 and dips[9] == pytest.approx(0, abs=1e-9) and dips[4] == 0
    b = pr.breathing(100, 24, 3.0, 2.0)
    assert min(b) == 0.0 and max(b) == pytest.approx(3.0, abs=0.05)
    assert pr.landing_frames([0, 10, 20, 10, 0, -10, -20, -20, -20]) != []


def test_apply_principles_changes_a_hand_keyed_motion_and_is_opt_in() -> None:
    def arm(principles: float | None) -> list[float]:
        params = {"energy": 0.5, "side": "left"}
        if principles is not None:
            params["principles"] = principles
        anim = animate(
            VIEW, [{"motion": "wave", "start_s": 0.0, "params": params}], fps=FPS, n_frames=100
        )
        return [float(w.value.degrees) for w in anim.angles["upper_arm_l"].waypoints]

    plain, same, more = arm(None), arm(0.0), arm(0.8)
    assert same == plain  # opt-in: 0 changes nothing
    assert max(more) > max(plain) + 1  # it overshoots the top of the raise, then settles back
    assert more[0] == pytest.approx(0.0, abs=1e-6)  # still starts at rest
    assert len(more) > len(plain)  # keyed on every frame now


def test_principles_skip_additive_clips() -> None:
    idle = Clip("idle", 0, 10, {("angle", "head"): [Key(0, 0.0), Key(10, 2.0)]}, additive=True)
    assert pr.apply_principles(idle, FPS, 1.0) is idle
    assert compose([idle])[("angle", "head")][-1].value == 2.0
    assert Vec(0, 1) is not None and MotionContext and world_pose
