"""Real motion: mocap parsing and retargeting maths (no files, no rendering)."""

import math

import numpy as np
import pytest

from studio_core.mocap import acclaim, retarget

ASF = """:version 1.10
:name test
:units
  length 1.0
  angle deg
:root
   order TX TY TZ RX RY RZ
   axis XYZ
   position 0 0 0
   orientation 0 0 0
:bonedata
  begin
     id 1
     name arm
     direction 0 -1 0
     length 2
     axis 0 0 0 XYZ
     dof rz
  end
  begin
     id 2
     name hand
     direction 0 -1 0
     length 1
     axis 0 0 0 XYZ
     dof rz
  end
:hierarchy
  begin
    root arm
    arm hand
  end
"""
AMC = """:FULLY-SPECIFIED
:DEGREES
1
root 0 0 0 0 0 0
arm 0
hand 0
2
root 1 0 0 0 0 0
arm 90
hand 0
"""


# --------------------------------------------------------------------------- acclaim


def test_forward_kinematics_of_a_two_bone_arm() -> None:
    skel = acclaim.parse_asf(ASF)
    frames, fps = acclaim.parse_amc(AMC)
    assert skel.bones["hand"].parent == "arm" and skel.bones["arm"].parent is None
    m = acclaim.joints_from(skel, frames, fps)
    assert m.joints["hand_end"][0] == pytest.approx([0, -3, 0])  # hanging straight down
    # 90 degrees about z swings the arm to point along +x; the root also moved 1 along x
    assert m.joints["arm_end"][1] == pytest.approx([3, 0, 0])
    assert m.joints["hand_end"][1] == pytest.approx([4, 0, 0])  # the hand follows its parent
    lengths = np.linalg.norm(m.joints["hand_end"] - m.joints["hand"], axis=1)
    assert lengths == pytest.approx([1, 1])


# --------------------------------------------------------------------------- signals


def test_gaussian_smooth_keeps_constants_and_flattens_a_spike() -> None:
    assert retarget.gaussian_smooth(np.full(20, 3.0), 2.0) == pytest.approx(np.full(20, 3.0))
    spike = np.zeros(40)
    spike[20] = 10
    out = retarget.gaussian_smooth(spike, 2.0)
    assert out.max() < 3 and out.sum() == pytest.approx(10, rel=1e-6)
    ramp = np.arange(10.0)
    assert retarget.gaussian_smooth(ramp, 1.0)[5] == pytest.approx(5.0)  # a line is untouched


def test_gaussian_smooth_wraps_for_loops() -> None:
    a = np.zeros(30)
    a[0] = 6.0
    wrapped = retarget.gaussian_smooth(a, 2.0, wrap=True)
    assert wrapped[-1] == pytest.approx(wrapped[1])  # symmetric across the seam


def test_resample_hits_the_samples_and_interpolates() -> None:
    a = np.array([0.0, 10.0, 20.0, 30.0, 40.0])  # 4 fps
    out = retarget.resample(a, 4, 8, 9)
    assert out == pytest.approx(np.arange(9) * 5.0)


def test_close_loop_makes_the_ends_meet() -> None:
    a = np.array([1.0, 2.0, 4.0, 7.0])
    out = retarget.close_loop(a)
    assert out[0] == out[-1] and out[1] == pytest.approx(0.0)


# --------------------------------------------------------------------------- projection


def synthetic_standing(frames: int = 6) -> acclaim.Mocap:
    """Hips apart along +x (left at +x), facing +z, y up."""
    z = np.zeros((frames, 3))
    j = {name: z.copy() for name in ("lfemur", "rfemur", "root", "lowerneck", "head_end")}
    j["lfemur"][:, 0] = 1.0
    j["rfemur"][:, 0] = -1.0
    return acclaim.Mocap(120, j)


def test_lateral_and_forward_axes_from_the_hips() -> None:
    left, fwd = retarget.lateral_forward(synthetic_standing())
    assert left == pytest.approx([1, 0, 0]) and fwd == pytest.approx([0, 0, 1])


def test_projection_front_and_side() -> None:
    m = synthetic_standing(2)
    m.joints["head_end"][:] = [0.5, 3.0, 2.0]  # left of the middle, up, in front
    front = retarget.project(m, 0)["head_end"][0]
    side = retarget.project(m, 90)["head_end"][0]
    assert front == pytest.approx([0.5, 3.0])  # screen x = the actor's left
    assert side == pytest.approx([2.0, 3.0])  # screen x = forward


def test_best_yaw_turns_toward_the_motion() -> None:
    m = synthetic_standing(20)
    t = np.linspace(0, 2 * np.pi, 20)
    m.joints["head_end"][:, 2] = np.sin(t)  # moves only forward and back
    assert retarget.best_yaw(m, [("head_end", "root")]) == 90.0
    m.joints["head_end"][:, 2] = 0
    m.joints["head_end"][:, 0] = np.sin(t)
    assert retarget.best_yaw(m, [("head_end", "root")]) == 0.0


def test_relative_angles_compose_like_bones() -> None:
    n = 3
    deg = lambda a: np.full(n, float(a))  # noqa: E731
    absolute = {
        "torso": deg(80),  # leaning 10 degrees clockwise
        "head": deg(80),  # in line with the torso
        "upper_arm:left": deg(-90),  # hanging straight down in the world
        "upper_arm:right": deg(-60),
        "forearm:left": deg(-90),
        "forearm:right": deg(-60),
    }
    rel = retarget.relative_angles(absolute)
    assert rel["torso"] == pytest.approx(deg(-10))
    assert rel["head"] == pytest.approx(deg(0))  # follows the torso: no extra offset
    assert rel["upper_arm:left"] == pytest.approx(
        deg(10)
    )  # the torso leaned, so the arm is "up" 10
    assert rel["forearm:right"] == pytest.approx(deg(0))


# --------------------------------------------------------------------------- foot lock


def test_lock_stance_holds_a_planted_foot_still_in_the_world() -> None:
    n, step = 24, 2.0  # the hip advances 2 per frame; a planted foot moves back 2 per frame
    k = np.arange(n)
    world = np.where((k >= 4) & (k <= 15), 10.0 + 0.3 * np.sin(k), 10.0 + 4.0 * (k - 4))
    rel = world - step * k  # periodic enough for this
    flags = (k >= 4) & (k <= 15)
    locked = retarget.lock_stance(rel, flags, step, blend=2)
    w = locked + step * k
    assert np.ptp(w[6:14]) == pytest.approx(0, abs=1e-9)  # still, away from the blended ends
    assert np.ptp(rel[6:14] + step * k[6:14]) > 0.3  # the input was not
    assert locked[0] == pytest.approx(rel[0])  # outside the run, untouched


def test_lock_stance_handles_a_run_that_wraps_around_the_loop() -> None:
    n, step = 20, 1.0
    k = np.arange(n)
    flags = (k >= 16) | (k <= 3)
    rel = np.zeros(n)
    out = retarget.lock_stance(rel, flags, step)
    assert out.shape == (n,) and np.isfinite(out).all()
    assert (out == 0).sum() >= n - 8  # only the planted run was changed


def test_lock_stance_floor_mode_flattens_heights() -> None:
    h = np.array([5.0, 0.4, 0.2, 0.3, 5.0, 5.0])
    flags = np.array([False, True, True, True, False, False])
    out = retarget.lock_stance(h, flags, 0.0, blend=0, mode="floor")
    assert out[1:4] == pytest.approx([0.2, 0.2, 0.2])
    assert out[0] == 5.0 and out[4] == 5.0


def test_find_loop_finds_a_period() -> None:
    fps = 120
    t = np.arange(fps * 4) / fps
    x = np.sin(2 * math.pi * t / 1.0)  # a 1 s gait
    i0, i1 = retarget.find_loop(x, fps)
    assert (i1 - i0) / fps == pytest.approx(1.0, abs=0.05)


def test_oneshot_clip_starts_at_rest_and_mirrors() -> None:
    m = synthetic_standing(120)
    t = np.linspace(0, 1, 120)
    for name in (
        "lfemur_end",
        "lradius",
        "lradius_end",
        "lhumerus",
        "lhumerus_end",
        "rhumerus",
        "rhumerus_end",
        "rradius",
        "rradius_end",
        "ltibia",
        "ltibia_end",
        "rtibia",
        "rtibia_end",
    ):
        m.joints[name] = np.zeros((120, 3))
    m.joints["rfemur_end"] = np.zeros((120, 3))
    for side, x0 in (("l", 1.0), ("r", -1.0)):
        m.joints[f"{side}humerus"][:] = [x0, 5, 0]
        m.joints[f"{side}humerus_end"][:] = [x0, 4, 0]  # hangs down
        m.joints[f"{side}radius"][:] = [x0, 4, 0]
        m.joints[f"{side}radius_end"][:] = [x0, 3, 0]
        m.joints[f"{side}femur_end"] = np.tile([x0, -2, 0], (120, 1)).astype(float)
        m.joints[f"{side}tibia"][:] = [x0, -2, 0]
        m.joints[f"{side}tibia_end"][:] = [x0, -4, 0]
    m.joints["lfemur"][:, 1] = m.joints["rfemur"][:, 1] = 0.0
    m.joints["lowerneck"][:] = [0, 6, 0]
    m.joints["head_end"][:] = [0, 8, 0]
    m.joints["root"][:] = [0, 0, 0]
    m.joints["lhumerus_end"][:, 0] = 1.0 + 1.5 * np.sin(t * 3)  # the left arm swings out
    clip = retarget.build_oneshot(m, "x", "t", 24, 0.0, gesture_side="left")
    assert clip.tracks["upper_arm:left"][0] == 0.0 and max(clip.tracks["upper_arm:left"]) > 20
    flip = clip.mirrored()
    assert flip.side == "right"
    assert flip.tracks["upper_arm:right"] == [-v for v in clip.tracks["upper_arm:left"]]
    assert flip.mirrored().tracks == clip.tracks
