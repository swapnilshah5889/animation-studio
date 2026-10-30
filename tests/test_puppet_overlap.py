"""Joint overlap (D-091): parts are drawn under their neighbours around the joints, so a bent joint
shows paint and not background, and the picture at rest does not change."""

import numpy as np

from studio_core.puppet import overlap
from studio_core.puppet.overlap import fill_notches, grow_under, joints_of

SHAPE = (300, 300)
HIP, KNEE = (150.0, 150.0), (150.0, 250.0)
BONES = {
    "torso": {"parent": None, "joint_px": HIP},
    "thigh_l": {"parent": "torso", "joint_px": HIP},
    "shin_l": {"parent": "thigh_l", "joint_px": KNEE},
}
ORDER = ("thigh_l", "shin_l", "torso")  # the leg behind the coat, as DRAW_ORDER has it
RED, BLUE = (200.0, 0.0, 0.0), (0.0, 0.0, 200.0)


def _box(y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
    m = np.zeros(SHAPE, bool)
    m[y0:y1, x0:x1] = True
    return m


def _scene(radius: float = 20.0):
    """A thigh (red) whose top end lies under a torso (blue) that covers rows 60-180."""
    masks = {
        "thigh_l": _box(150, 250, 130, 170),
        "shin_l": _box(250, 330, 130, 170) & _box(0, 300, 0, 300),
        "torso": _box(60, 180, 100, 200),
    }
    pixels = {n: np.zeros((*SHAPE, 3), "float32") for n in masks}
    pixels["thigh_l"][:] = RED
    pixels["torso"][:] = BLUE
    fits = {n: {"radius_px": radius} for n in ("thigh_l", "shin_l")}
    return masks, pixels, fits


def _owner(masks: dict[str, np.ndarray]) -> np.ndarray:
    """Which part shows at each pixel (the last in draw order), -1 = background."""
    out = np.full(SHAPE, -1)
    for i, name in enumerate(ORDER):
        out[masks[name]] = i
    return out


def test_joints_of_lists_the_parents_joint_and_each_childs() -> None:
    assert joints_of("thigh_l", BONES) == [(HIP, "torso"), (KNEE, "shin_l")]
    assert joints_of("torso", BONES) == [(HIP, "thigh_l")]  # the root has no joint of its own


def test_the_part_behind_grows_under_the_front_part_near_the_joint() -> None:
    masks, pixels, fits = _scene()
    before = masks["thigh_l"].copy()
    added = grow_under(masks, pixels, BONES, fits, ORDER, 1000.0, notch=0)
    assert masks["thigh_l"][140, 150] and added["thigh_l"][140, 150]  # under the coat, by the hip
    assert np.array_equal(masks["thigh_l"] & before, before)  # nothing was taken away
    assert tuple(pixels["thigh_l"][140, 150]) == RED  # painted from the thigh's own colour


def test_the_reach_scales_with_the_limb_and_stops_there() -> None:
    m1, p1, f1 = _scene(radius=10.0)
    m2, p2, f2 = _scene(radius=30.0)
    grow_under(m1, p1, BONES, f1, ORDER, 1000.0, notch=0)
    grow_under(m2, p2, BONES, f2, ORDER, 1000.0, notch=0)
    assert m2["thigh_l"].sum() > m1["thigh_l"].sum()
    assert not m1["thigh_l"][100, 150]  # 50 px above the hip: far beyond a thin limb's reach
    assert not m2["thigh_l"][60, 150]  # 90 px: beyond even the thick limb's


def test_it_changes_nothing_that_shows_at_rest() -> None:
    """The growth is only where a part in front covers it, so the picture at rest is the same."""
    masks, pixels, fits = _scene()
    before = _owner(masks)
    grow_under(masks, pixels, BONES, fits, ORDER, 1000.0, notch=0)
    assert np.array_equal(_owner(masks), before)


def test_it_never_grows_into_background_that_no_part_covers() -> None:
    masks, pixels, fits = _scene()
    masks["torso"] = _box(60, 180, 100, 140)  # the coat no longer covers the right side of the hip
    grow_under(masks, pixels, BONES, fits, ORDER, 1000.0, notch=0)
    assert not masks["thigh_l"][140, 160]  # background there: it stays background
    assert masks["thigh_l"][140, 135]  # covered: filled
    assert not masks["thigh_l"][
        140, 139
    ]  # the front part's last pixels are antialiased: kept clear


def test_the_front_most_part_is_not_grown() -> None:
    masks, pixels, fits = _scene()
    torso = masks["torso"].copy()
    grow_under(masks, pixels, BONES, fits, ORDER, 1000.0, notch=0)
    assert np.array_equal(masks["torso"], torso)


def test_a_bite_in_the_outline_is_closed_and_a_wide_gap_is_not() -> None:
    m = _box(100, 200, 100, 200)
    m[140:150, 100:140] = False  # a 10 px bite from the left edge, 40 px deep
    m[:, 170:175] = False  # a 5 px slit across the part
    side = _box(120, 160, 60, 100) | _box(0, 300, 175, 180)  # parts lying against the bites
    new = fill_notches(m, side, 12)
    assert new[145, 120] and new[100:200, 172].all()  # both narrower than 12 px: closed
    assert not (new & m).any()  # only new pixels are returned
    wide = _box(100, 200, 100, 200)
    wide[130:160, 100:140] = False  # a 30 px gap
    assert not fill_notches(wide, side, 12)[145, 120]


def test_the_torsos_bite_is_closed_by_the_cut() -> None:
    """Kit's tail had a leg-shaped bite out of it; the leg hid it at rest and a step showed it."""
    masks, pixels, fits = _scene()
    masks["torso"][100:180, 135:145] = False  # a slit the leg lies against at its lower end
    grow_under(masks, pixels, BONES, fits, ORDER, 1000.0)  # the default notch width: 25 px
    assert masks["torso"][160, 140]
    assert overlap.NOTCH > 0


def test_a_see_through_front_edge_does_not_hide_the_growth() -> None:
    """The figure's antialiased outer ring is partly transparent: a part grown under it would
    show through at rest (a hard fringe along the silhouette)."""
    masks, pixels, fits = _scene()
    opaque = np.ones(SHAPE, bool)
    opaque[130:150, :] = False  # the coat's lower rows are see-through
    grow_under(masks, pixels, BONES, fits, ORDER, 1000.0, notch=0, opaque=opaque)
    assert not masks["thigh_l"][140, 150]  # not hidden there: not grown
    assert masks["thigh_l"][155, 150] and masks["thigh_l"][125, 150]  # opaque rows: grown


def test_a_turned_point_follows_a_turned_mask() -> None:
    """The arms' rest frame: points and masks must turn the same way (hang_arms turns the art)."""
    m = _box(100, 110, 200, 220)  # a blob right of the centre
    centre = (150.0, 105.0)
    turned = overlap._turned(m, 90.0, centre)  # counter-clockwise on screen: right goes to up
    ys, xs = np.nonzero(turned)
    x, y = overlap._turn_point((210.0, 105.0), 90.0, centre)
    assert abs(x - 150) < 1e-6 and abs(y - 45) < 1e-6
    assert abs(xs.mean() - x) < 2 and abs(ys.mean() - y) < 2


def test_growth_is_judged_with_the_arm_hanging_not_as_the_sheet_drew_it() -> None:
    """A-pose arms are turned to hang after the cut, so a pixel the torso hides next to an arm in
    the sheet may not be hidden once the arm hangs: growing there would show at rest."""
    bones = {
        "torso": {"parent": None, "joint_px": (150.0, 150.0)},
        "upper_arm_l": {"parent": "torso", "joint_px": (150.0, 150.0)},
    }
    fits = {"upper_arm_l": {"radius_px": 20.0}}
    order = ("upper_arm_l", "torso")
    centre = (150.0, 150.0)

    def uncovered_at_rest(turn) -> int:
        masks = {"upper_arm_l": _box(150, 250, 140, 160), "torso": _box(60, 180, 150, 160)}
        pixels = {n: np.zeros((*SHAPE, 3), "float32") for n in masks}
        before = masks["upper_arm_l"].copy()
        grow_under(masks, pixels, bones, fits, order, 1000.0, notch=0, turn=turn)
        added = overlap._turned(masks["upper_arm_l"] & ~before, 90.0, centre)  # the arm hung
        torso_at_rest = overlap._turned(masks["torso"], 0.0, centre)  # the torso never turns
        return int((added & ~torso_at_rest).sum())

    assert uncovered_at_rest(None) > 100  # judged in the sheet's frame, the growth would show
    assert uncovered_at_rest({"upper_arm_l": (90.0, centre)}) < 20  # judged as it hangs: hidden


def _hanging_arm_scene():
    """Shoulder (150, 100), elbow (150, 200) in the sheet; the rig turns the arm 90 degrees about
    the shoulder, so at rest the elbow is at (250, 100), under a block of torso there."""
    bones = {
        "torso": {"parent": None, "joint_px": (150.0, 100.0)},
        "upper_arm_l": {"parent": "torso", "joint_px": (150.0, 100.0)},
        "forearm_l": {"parent": "upper_arm_l", "joint_px": (150.0, 200.0)},
    }
    fits = {n: {"radius_px": 20.0} for n in ("upper_arm_l", "forearm_l")}
    masks = {
        "upper_arm_l": _box(100, 200, 140, 160),
        "forearm_l": _box(200, 290, 140, 160),
        "torso": _box(60, 140, 210, 290),
    }
    pixels = {n: np.zeros((*SHAPE, 3), "float32") for n in masks}
    turn = {n: (90.0, (150.0, 100.0)) for n in ("upper_arm_l", "forearm_l")}
    return bones, fits, masks, pixels, turn


def test_a_part_behind_a_hanging_arm_grows_under_the_arm_as_it_rests() -> None:
    """The torso is behind the arm and loses pixels where it grows under it, in the rest frame."""
    bones, fits, masks, pixels, turn = _hanging_arm_scene()
    order = ("torso", "upper_arm_l", "forearm_l")
    masks["torso"] = _box(60, 140, 100, 140)  # stops short of the shoulder: the arm hides the rest
    before = masks["torso"].copy()
    grow_under(masks, pixels, bones, fits, order, 1000.0, notch=0, turn=turn)
    gained = masks["torso"] & ~before
    arm_at_rest = overlap._turned(masks["upper_arm_l"], 90.0, (150.0, 100.0))
    assert gained.any()
    assert (gained & arm_at_rest).sum() == gained.sum()  # all of it lies under the hanging arm
    sheet_arm = masks["upper_arm_l"]
    assert (gained & sheet_arm).sum() < gained.sum()  # ... not under where the sheet drew the arm


def test_a_joint_the_turned_arm_carries_round_is_judged_where_it_rests() -> None:
    """The elbow turns with the arm: judged at the sheet's elbow nothing would be under the
    forearm; at its rest position the upper arm reaches under the forearm's first stretch."""
    bones, fits, masks, pixels, turn = _hanging_arm_scene()
    order = ("upper_arm_l", "forearm_l", "torso")
    before = masks["upper_arm_l"].copy()
    grow_under(masks, pixels, bones, fits, order, 1000.0, notch=0, turn=turn)
    gained = masks["upper_arm_l"] & ~before
    assert gained.any()
    assert (gained & _box(200, 290, 140, 160)).sum() == gained.sum()  # all of it in the forearm
    assert gained[205, 150] and not gained[260, 150]  # its first stretch only


def test_a_part_is_only_hidden_by_its_neighbours() -> None:
    """The torso lies over the shin in this drawing, but it is not across a joint of the shin: a
    shin grown under a part it does not meet would show as a phantom bump when the legs pass."""
    masks, pixels, fits = _scene()
    masks["shin_l"] = _box(240, 290, 130, 170)
    masks["torso"] = _box(60, 280, 100, 200)  # covers the knee region too
    pixels["shin_l"] = np.zeros((*SHAPE, 3), "float32")
    before = masks["shin_l"].copy()
    grow_under(masks, pixels, BONES, fits, ORDER, 1000.0, notch=0)
    assert np.array_equal(masks["shin_l"], before)
    assert masks["thigh_l"][140, 150]  # the thigh meets the torso at the hip: it still grows
