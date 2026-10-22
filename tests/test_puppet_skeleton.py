"""Skeleton templates (task 4.2): the pose image and the rig come from the same numbers, and the
rig matches Pip's conventions so the motion library works on generated puppets unchanged."""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from studio_core.puppet.skeleton import (
    BONES,
    COLORS,
    DRAW_ORDER,
    OPENPOSE,
    Skeleton,
    direction_deg,
    place,
    pose_image,
    rig_bones,
    turnaround,
)

CANVAS = (1344, 768)
PIP = json.loads(
    (Path(__file__).parent / "fixtures" / "characters" / "pip" / "rig.json").read_text()
)["views"]["front"]


def detected(img, sk: Skeleton) -> dict[str, tuple[float, float]]:
    """Each visible keypoint found again in the image: the centroid of its exact colour near the
    joint (dots are drawn last, at full colour, so their centres are unambiguous)."""
    px = np.asarray(img)
    found = {}
    for i, name in enumerate(OPENPOSE):
        if name in sk.hidden:
            continue
        x0, y0 = sk.joints[name]
        r = 12
        ys, xs = slice(int(y0) - r, int(y0) + r + 1), slice(int(x0) - r, int(x0) + r + 1)
        hit = np.all(px[ys, xs] == COLORS[i], axis=2)
        if hit.sum() < 20:  # mostly covered by a later dot (close keypoints on the face)
            continue
        yy, xx = np.nonzero(hit)
        found[name] = (xs.start + xx.mean(), ys.start + yy.mean())
    return found


def test_keypoints_are_drawn_where_the_skeleton_says() -> None:
    front, side = turnaround(CANVAS)
    img = pose_image([front, side], CANVAS)
    for sk in (front, side):
        found = detected(img, sk)
        assert {"neck", "r_shoulder", "l_elbow", "r_knee", "l_ankle"} <= set(found)
        for name, (x, y) in found.items():
            jx, jy = sk.joints[name]
            assert math.hypot(x - jx, y - jy) < 1.5, (sk.view, name)  # pixel rasterization


@pytest.mark.parametrize("view", ["front", "three_quarter"])
def test_rig_directions_match_the_drawing(view: str) -> None:
    sk = place(view, height_px=660, feet_px=(400, 720))
    img = pose_image([sk], (800, 768))
    found = detected(img, sk)
    bones = rig_bones(sk)
    measured = {  # bone → keypoints that run along it in the drawing
        "upper_arm_l": ("l_shoulder", "l_elbow"),
        "forearm_l": ("l_elbow", "l_wrist"),
        "upper_arm_r": ("r_shoulder", "r_elbow"),
        "forearm_r": ("r_elbow", "r_wrist"),
        "thigh_l": ("l_hip", "l_knee"),
        "thigh_r": ("r_hip", "r_knee"),
    }
    for bone, (a, b) in measured.items():
        (x1, y1), (x2, y2) = found[a], found[b]
        seen = math.degrees(math.atan2(-(y2 - y1), x2 - x1))
        assert seen == pytest.approx(bones[bone]["direction_deg"], abs=1.0), bone
        assert bones[bone]["joint_px"] == pytest.approx(sk.joints[a], abs=0.06), bone
    if view == "front":  # in 3/4 the hip dots straddle the centre line unevenly (cartoon depth)
        hips = [(found["l_hip"][i] + found["r_hip"][i]) / 2 for i in (0, 1)]
        dy, dx = -(found["neck"][1] - hips[1]), found["neck"][0] - hips[0]
        assert math.degrees(math.atan2(dy, dx)) == pytest.approx(90, abs=1.0)
    assert bones["torso"]["direction_deg"] == 90  # the root stays on the body's centre line


def test_bones_follow_pips_conventions() -> None:
    front, _ = turnaround(CANVAS)
    bones = rig_bones(front)
    assert set(bones) == set(PIP["bones"]) == set(DRAW_ORDER)
    for name, bone in bones.items():
        pip = PIP["bones"][name]
        assert (bone["role"], bone["side"], bone["parent"]) == (
            pip["role"],
            pip["side"],
            pip["parent"],
        )
        assert bone["limits_deg"] == pip["limits_deg"], name
    assert list(DRAW_ORDER) == PIP["draw_order"]
    assert bones["torso"]["direction_deg"] == 90 and bones["head"]["direction_deg"] == 90
    assert bones["upper_arm_l"]["direction_deg"] == pytest.approx(-65)  # 25° out from hanging
    assert bones["upper_arm_r"]["direction_deg"] == pytest.approx(-115)


def test_front_is_symmetric_and_proportioned() -> None:
    sk = place("front", height_px=660, feet_px=(300, 700))
    cx = sk.joints["neck"][0]
    for name in ("shoulder", "elbow", "wrist", "hip", "knee", "ankle", "eye", "ear"):
        (lx, ly), (rx, ry) = sk.joints[f"l_{name}"], sk.joints[f"r_{name}"]
        assert lx - cx == pytest.approx(cx - rx) and ly == pytest.approx(ry), name
        assert lx > cx  # the character's left is on the viewer's right
    assert sk.joints["sole"][1] == pytest.approx(700) and sk.height_px == pytest.approx(660)
    head = (sk.joints["neck"][1] - sk.joints["head_top"][1]) / sk.height_px
    assert 0.33 < head < 0.42  # a child-like cartoon head, like Pip's


def test_three_quarter_faces_right_with_a_tucked_far_side() -> None:
    sk = place("three_quarter", height_px=660, feet_px=(300, 700))
    cx = sk.joints["neck"][0]
    assert sk.joints["nose"][0] > cx  # facing screen-right
    near = cx - sk.joints["r_shoulder"][0]
    far = sk.joints["l_shoulder"][0] - cx
    assert near > far > 0
    assert sk.hidden == {"l_ear"}
    assert len(BONES) == 10 and sk.height_px == pytest.approx(660)


def test_turnaround_layout() -> None:
    front, side = turnaround(CANVAS)
    assert front.joints["sole"][0] == pytest.approx(CANVAS[0] * 0.25)
    assert side.joints["sole"][0] == pytest.approx(CANVAS[0] * 0.75)
    for sk in (front, side):
        xs = [x for x, _ in sk.joints.values()]
        ys = [y for _, y in sk.joints.values()]
        half = (0, CANVAS[0] / 2) if sk is front else (CANVAS[0] / 2, CANVAS[0])
        assert half[0] < min(xs) and max(xs) < half[1]  # each figure stays in its half
        assert min(ys) > 0 and max(ys) < CANVAS[1]
    assert direction_deg(front, "pelvis", "neck") == 90
