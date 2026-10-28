"""Motion library: timeline maths, composition rules, and per-motion timing (task 2.5)."""

import copy
from itertools import pairwise
from pathlib import Path

import pytest
from PIL import Image

from studio_core.config import REPO_ROOT, load_config
from studio_core.motions import (
    MOTIONS,
    Clip,
    Key,
    MotionContext,
    MotionError,
    animate,
    compose,
    sample,
)
from studio_core.rig import build_character, load_rig
from studio_core.sif import Canvas, Group, Interp, Space, Transform, Vec
from studio_core.sif.render import render_frames

PIP = REPO_ROOT / "tests" / "fixtures" / "characters" / "pip" / "rig.json"
VIEW = load_rig(PIP).view()
FPS = 24


def ctx(start: int = 24, last: int = 239, **kw) -> MotionContext:
    kw.setdefault("seed", "pip")
    return MotionContext(view=VIEW, fps=FPS, start=start, last_frame=last, **kw)


# --------------------------------------------------------------------------- timeline


def test_sample_interpolation_shapes() -> None:
    keys = [Key(0, 0.0, Interp.EASE), Key(8, 8.0)]
    assert sample(keys, -5) == 0.0 and sample(keys, 20) == 8.0  # held outside
    assert sample(keys, 4) == 4.0  # smoothstep(0.5) = 0.5
    assert sample(keys, 2) == pytest.approx(8 * 0.15625)  # eased start: slower than linear
    assert sample([Key(0, 0.0, Interp.LINEAR), Key(8, 8.0)], 2) == 2.0
    assert sample([Key(0, 0.0, Interp.CONSTANT), Key(8, 8.0)], 7) == 0.0
    assert sample([Key(0, Vec(0, 0), Interp.LINEAR), Key(10, Vec(10, -20))], 5) == Vec(5, -10)
    assert sample([Key(0, "open"), Key(3, "closed")], 2) == "open"


def test_clip_validates_keys() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        Clip("x", 0, 10, {("angle", "head"): [Key(5, 0.0), Key(5, 1.0)]})
    with pytest.raises(ValueError, match="outside"):
        Clip("x", 0, 10, {("angle", "head"): [Key(5, 0.0), Key(12, 1.0)]})


def test_override_drops_earlier_keys_in_its_window() -> None:
    a = Clip(
        "a", 0, 60, {("angle", "arm"): [Key(0, 0.0), Key(20, 90.0), Key(40, 90.0), Key(60, 0.0)]}
    )
    b = Clip("b", 30, 50, {("angle", "arm"): [Key(30, 0.0), Key(50, 45.0)]})
    out = compose([b, a])  # order of the list doesn't matter; start time does
    assert [(k.frame, k.value) for k in out[("angle", "arm")]] == [
        (0, 0.0),
        (20, 90.0),
        (30, 0.0),
        (50, 45.0),
        (60, 0.0),
    ]


def test_additive_layers_sum_at_every_key() -> None:
    base = Clip("base", 0, 20, {("angle", "arm"): [Key(0, 0.0, Interp.LINEAR), Key(20, 10.0)]})
    breathe = Clip(
        "idle",
        0,
        20,
        {("angle", "arm"): [Key(0, 0.0, Interp.LINEAR), Key(10, 2.0), Key(20, 0.0)]},
        additive=True,
    )
    keys = compose([base, breathe])[("angle", "arm")]
    assert [(k.frame, k.value) for k in keys] == [(0, 0.0), (10, 7.0), (20, 10.0)]


# --------------------------------------------------------------------------- motions


@pytest.mark.parametrize("name", sorted(MOTIONS))
def test_every_motion_starts_on_time_ends_at_rest_and_is_deterministic(name: str) -> None:
    params = {"target": [1500, 300]} if name == "point" else {}
    clip = MOTIONS[name](ctx(params=params, root_px=Vec(960, 900)))
    again = MOTIONS[name](ctx(params=params, root_px=Vec(960, 900)))
    assert clip.channels == again.channels
    assert clip.start == 24 and clip.end <= 239
    for (kind, _), keys in clip.channels.items():
        assert keys[0].frame >= 24
        rest = {"angle": 0.0, "shift": Vec(0, 0), "eyes": "open"}[kind]
        assert keys[0].value == rest, (name, kind)
        if name not in ("idle_breathe",):  # idle runs to the end of the shot mid-breath
            assert keys[-1].value == rest, (name, kind, keys[-1])


def test_natural_lengths() -> None:
    lengths = {
        name: MOTIONS[name](
            ctx(params={"target": [1500, 300]} if name == "point" else {}, root_px=Vec(960, 900))
        ).end
        - 24
        for name in MOTIONS
    }
    assert (
        lengths["idle_breathe"] == 239 - 24 and lengths["blink"] <= 239 - 24
    )  # run to the shot end
    assert 40 <= lengths["wave"] <= 80  # ~2-3 s
    assert 10 <= lengths["nod"] <= 30
    assert 22 <= lengths["jump"] <= 32  # ~1.1 s


def test_energy_scales_amplitude_and_side_picks_the_limb() -> None:
    small = MOTIONS["wave"](ctx(params={"energy": 0.0, "side": "right"}))
    big = MOTIONS["wave"](ctx(params={"energy": 1.0, "side": "right"}))
    peak = lambda c: max(abs(k.value) for k in c.channels[("angle", "upper_arm_r")])  # noqa: E731
    assert peak(big) > peak(small)
    assert min(k.value for k in big.channels[("angle", "upper_arm_r")]) < 0  # right arm: clockwise
    left = MOTIONS["wave"](ctx(params={"side": "left"}))
    assert ("angle", "upper_arm_l") in left.channels and max(
        k.value for k in left.channels[("angle", "upper_arm_l")]
    ) > 0


def test_a_wave_stays_clear_of_a_big_head() -> None:
    """The raised hand must stay visible: on a character with a big head (a fox's ears), the
    wave raises the arm less than on Pip (task 4.4)."""
    peak = lambda c, bone: max(abs(k.value) for k in c.channels[("angle", bone)])  # noqa: E731
    for energy, expected in ((0.0, 120), (0.5, 140), (0.75, 150)):
        wave = MOTIONS["wave"](ctx(params={"energy": energy, "side": "left"}))
        assert peak(wave, "upper_arm_l") == pytest.approx(expected), energy  # Pip: as approved
    wide = copy.deepcopy(VIEW)
    head = wide["parts"]["head"]
    head["size_px"][0], head["pivot_px"][0] = 700, 350  # a head (with ears) 700 px wide
    big = MotionContext(view=wide, fps=FPS, start=24, last_frame=239, seed="kit",
                        params={"energy": 0.5, "side": "left"})  # fmt: skip
    assert peak(MOTIONS["wave"](big), "upper_arm_l") < 140


def test_cycles_and_duration() -> None:
    fore = lambda c: len(c.channels[("angle", "forearm_r")])  # noqa: E731
    assert fore(MOTIONS["wave"](ctx(params={"cycles": 5}))) > fore(
        MOTIONS["wave"](ctx(params={"cycles": 1}))
    )
    long = MOTIONS["wave"](ctx(duration=FPS * 4))
    short = MOTIONS["wave"](ctx(duration=FPS * 2))
    assert long.end - long.start > short.end - short.start
    tilt = MOTIONS["head_tilt"](ctx(duration=FPS * 3))
    assert abs((tilt.end - tilt.start) - FPS * 3) <= 2


def test_motion_is_cut_at_the_end_of_the_shot() -> None:
    clip = MOTIONS["wave"](ctx(start=230, last=239))
    assert clip.end == 239
    assert all(keys[-1].frame == 239 for keys in clip.channels.values())


def test_blinks_are_spaced_and_repeatable() -> None:
    keys = MOTIONS["blink"](ctx(params={"energy": 0.5})).channels[("eyes", "")]
    starts = [k.frame for k in keys if k.value == "half"][::2]
    gaps = [b - a for a, b in pairwise(starts)]
    assert gaps and all(
        int((3.25 - 0.6) * FPS) - 1 <= g <= int((3.25 + 0.6) * FPS) + 1 for g in gaps
    ), gaps
    other = MOTIONS["blink"](ctx(params={"energy": 0.5}, seed="bunny")).channels[("eyes", "")]
    assert [k.frame for k in other] != [
        k.frame for k in keys
    ]  # different characters blink differently


def test_point_aims_at_the_target() -> None:
    # Root at screen (960, 900); a target up and to the viewer's right -> the character's left arm,
    # rotated counter-clockwise from hanging down by more than 90°.
    clip = MOTIONS["point"](ctx(params={"target": [1700, 300]}, root_px=Vec(960, 900)))
    offsets = [k.value for k in clip.channels[("angle", "upper_arm_l")]]
    assert 90 < max(offsets) < 180
    clip = MOTIONS["point"](ctx(params={"target": [200, 700]}, root_px=Vec(960, 900)))
    assert ("angle", "upper_arm_r") in clip.channels


def test_animate_errors_and_clamping() -> None:
    with pytest.raises(MotionError, match="unknown motion 'wavee'"):
        animate(VIEW, [{"motion": "wavee", "start_s": 0}], fps=FPS, n_frames=120)
    with pytest.raises(MotionError, match="after the end"):
        animate(VIEW, [{"motion": "nod", "start_s": 9}], fps=FPS, n_frames=120)
    anim = animate(
        VIEW,
        [{"motion": "head_tilt", "start_s": 0, "params": {"energy": 1}}],
        fps=FPS,
        n_frames=120,
    )
    assert max(abs(w.value.degrees) for w in anim.angles["head"].waypoints) <= 25  # head limit


def test_key_poses_hold_and_interpolate_and_are_clamped() -> None:
    poses = [
        {"time_s": 0.5, "bones": {"head": 10}},
        {"time_s": 1.5, "bones": {"head": -40, "upper_arm_l": 90}},  # head limit is ±25
    ]
    anim = animate(VIEW, [], fps=FPS, n_frames=120, poses=poses)
    head = [(w.frame, w.value.degrees) for w in anim.angles["head"].waypoints]
    assert head == [(12, 10.0), (36, -25.0)]
    assert [(w.frame, w.value.degrees) for w in anim.angles["upper_arm_l"].waypoints] == [
        (36, 90.0)
    ]
    with pytest.raises(MotionError, match="unknown bones"):
        animate(VIEW, [], fps=FPS, n_frames=120, poses=[{"time_s": 0, "bones": {"tail": 5}}])
    with pytest.raises(MotionError, match="after the end"):
        animate(VIEW, [], fps=FPS, n_frames=120, poses=[{"time_s": 9, "bones": {"head": 5}}])


def test_idle_breathing_adds_to_a_wave() -> None:
    actions = [
        {"motion": "idle_breathe", "start_s": 0},
        {"motion": "wave", "start_s": 1, "params": {"side": "right"}},
    ]
    with_idle = animate(VIEW, actions, fps=FPS, n_frames=120)
    plain = animate(VIEW, actions[1:], fps=FPS, n_frames=120)
    a = {w.frame: w.value.degrees for w in with_idle.angles["upper_arm_r"].waypoints}
    b = {w.frame: w.value.degrees for w in plain.angles["upper_arm_r"].waypoints}
    assert set(b) <= set(a) and any(abs(a[f] - b[f]) > 0.01 for f in b)


@pytest.mark.render
@pytest.mark.skipif(not load_config().path("tools", "synfig").exists(), reason="no synfig CLI")
def test_rendered_jump_lifts_the_character(tmp_path: Path) -> None:
    rig = load_rig(PIP)
    (tmp_path / "pip").mkdir()
    for f in rig.folder.glob("parts/*.png"):
        (tmp_path / "pip" / "parts").mkdir(exist_ok=True)
        (tmp_path / "pip" / "parts" / f.name).write_bytes(f.read_bytes())
    anim = animate(
        rig.view(),
        [{"motion": "jump", "start_s": 0, "params": {"energy": 1}}],
        fps=FPS,
        n_frames=40,
    )
    apex = next(w.frame for w in anim.shifts["torso"].waypoints if w.value.y >= 159)
    space = Space(400, 1000, 60)
    built = build_character(
        rig, None, space, file_prefix="pip", offsets=anim.angles, shifts=anim.shifts
    )
    canvas = Canvas(
        width=400,
        height=1000,
        fps=FPS,
        frames=apex + 1,
        ppu=60,
        bones=built.bones,
        layers=[Group("place", transform=Transform(offset=Vec(0, -3)), children=[built.group])],
    )
    frames = render_frames(canvas.save(tmp_path / "j.sif"), tmp_path / "f", begin=0, end=apex)

    def top(path: Path) -> int:
        alpha = Image.open(path).getchannel("A")
        return next(
            y
            for y in range(alpha.height)
            if alpha.crop((0, y, alpha.width, y + 1)).getextrema()[1] > 128
        )

    assert abs((top(frames[0]) - top(frames[-1])) - 160) <= 3  # risen 160 art px (scale 1)


# --------------------------------------------------------------------------- acting motions

ACTING = ("shrug", "bow", "look_around", "sneak", "clap", "laugh", "think")


def _peak(clip: Clip) -> float:
    """The biggest excursion on any channel (degrees for angles, art px for shifts)."""
    peaks = []
    for (kind, _), keys in clip.channels.items():
        if kind == "angle":
            peaks += [abs(k.value) for k in keys]
        elif kind == "shift":
            peaks += [max(abs(k.value.x), abs(k.value.y)) for k in keys]
    return max(peaks)


@pytest.mark.parametrize("name", ACTING)
def test_acting_motions_scale_with_energy_and_stay_inside_joint_limits(name: str) -> None:
    small = MOTIONS[name](ctx(params={"energy": 0.0}))
    big = MOTIONS[name](ctx(params={"energy": 1.0}))
    assert _peak(big) > _peak(small) > 0
    for (kind, bone), keys in big.channels.items():  # the raw clip, before animate() clamps it
        if kind == "angle":
            lim = VIEW["bones"][bone]["limits_deg"]
            assert all(lim["min"] <= k.value <= lim["max"] for k in keys), (name, bone)


@pytest.mark.parametrize(
    ("name", "lo", "hi"),
    [("shrug", 28, 45), ("bow", 36, 50), ("look_around", 35, 60), ("clap", 40, 60),
     ("laugh", 24, 40), ("think", 55, 70), ("sneak", 20, 120)],
)  # fmt: skip
def test_acting_motions_start_on_time_and_have_a_natural_length(
    name: str, lo: int, hi: int
) -> None:
    clip = MOTIONS[name](ctx())
    assert clip.start == 24 and lo <= clip.end - 24 <= hi, clip.end - 24
    assert min(k.frame for keys in clip.channels.values() for k in keys) == 24
    for keys in clip.channels.values():
        assert len(keys) >= 4 and [k.frame for k in keys] == sorted({k.frame for k in keys})


@pytest.mark.parametrize("name", ["shrug", "bow", "think"])
def test_posed_motions_anticipate_hold_and_honour_the_duration(name: str) -> None:
    clip = MOTIONS[name](ctx())
    head = next(k for c, k in clip.channels.items() if c[1] in ("head", "upper_arm_r"))
    vals = [k.value.y if isinstance(k.value, Vec) else k.value for k in head]
    peak_at = max(range(len(vals)), key=lambda i: abs(vals[i]))
    assert vals[1] * vals[peak_at] <= 0  # first move is the opposite one: anticipation
    assert abs(vals[peak_at + 1]) < abs(vals[peak_at])  # a moving hold, not a freeze
    short = MOTIONS[name](ctx(duration=FPS * 2))
    long = MOTIONS[name](ctx(duration=FPS * 4))
    assert long.end - long.start > short.end - short.start
    assert abs((long.end - long.start) - FPS * 4) <= 4


def test_shrug_and_bow_and_think_choose_their_limbs() -> None:
    assert {c[1] for c in MOTIONS["shrug"](ctx()).channels} >= {
        "head",
        "upper_arm_l",
        "upper_arm_r",
    }
    assert {c[1] for c in MOTIONS["bow"](ctx()).channels} == {"torso", "head"}  # bows sink
    think_r = MOTIONS["think"](ctx(params={"side": "right"}))
    think_l = MOTIONS["think"](ctx(params={"side": "left"}))
    assert ("angle", "upper_arm_r") in think_r.channels and (
        "angle",
        "upper_arm_l",
    ) not in think_r.channels
    assert max(k.value for k in think_l.channels[("angle", "upper_arm_l")]) > 60
    assert min(k.value for k in think_r.channels[("angle", "upper_arm_r")]) < -60  # mirrored
    shrug = MOTIONS["shrug"](ctx(params={"side": "right"}))
    assert min(k.value for k in shrug.channels[("angle", "head")]) < 0  # tilts to its right


def test_look_around_glances_both_ways_and_repeats() -> None:
    def xs(**params: object) -> list[float]:
        clip = MOTIONS["look_around"](ctx(params=params))
        return [k.value.x for k in clip.channels[("shift", "head")]]

    left, right = xs(side="left"), xs(side="right")
    assert max(left) > 0 > min(left) and max(left) > -min(left)  # first glance is the bigger
    assert left == [-x for x in right]  # mirrored
    one, two = xs(cycles=1), xs(cycles=2)
    assert len(two) > len(one) and sum(1 for x in two if x > 4) > sum(1 for x in one if x > 4)


def test_clap_counts_its_claps_and_clears_a_big_head() -> None:
    for n in (1, 4):
        fore = MOTIONS["clap"](ctx(params={"cycles": n})).channels[("angle", "forearm_l")]
        together = [k for k in fore if k.value >= 40]
        assert len(together) == n, n
    arms = MOTIONS["clap"](ctx()).channels
    assert 90 <= max(k.value for k in arms[("angle", "upper_arm_l")]) <= 150
    assert arms[("angle", "upper_arm_l")][2].value == -arms[("angle", "upper_arm_r")][2].value


def test_laugh_bounces_squints_and_ends_open() -> None:
    clip = MOTIONS["laugh"](ctx())
    body = [k.value.y for k in clip.channels[("shift", "torso")]]
    assert body.count(0) >= 4 and min(body) < 0 and body[0] == body[-1] == 0
    eyes = [(k.frame, k.value) for k in clip.channels[("eyes", "")]]
    assert [v for _, v in eyes] == ["open", "half", "half", "open"] and eyes[-1][0] == clip.end
    # Headlag: the head's bounce keys sit one frame after the body's (overlap).
    head = [k.frame for k in clip.channels[("shift", "head")]]
    assert head[1] == [k.frame for k in clip.channels[("shift", "torso")]][1] + 1
    assert len(MOTIONS["laugh"](ctx(params={"cycles": 8})).channels[("shift", "torso")]) > len(
        clip.channels[("shift", "torso")]
    )


def test_sneak_is_a_low_small_walk_in_place_and_across_the_frame() -> None:
    place = MOTIONS["sneak"](ctx(params={"energy": 1.0}))
    walk = MOTIONS["walk_cycle"](ctx(params={"energy": 1.0}))
    body = [k.value.y for k in place.channels[("shift", "torso")]]
    assert min(body) < -4 and body[0] == body[-1] == 0  # crouches, and stands up again
    peak = lambda c: max(k.value for k in c.channels[("angle", "thigh_l")])  # noqa: E731
    assert abs(peak(place)) < abs(peak(walk)) or place.end > walk.end
    # Travelling: planted-foot strides cover the distance, still crouched, still ends at rest.
    travel = [min(f, 120) * 2.0 for f in range(240)]  # 2 px per frame for 5 s... then stops
    moving = MOTIONS["sneak"](ctx(start=0, travel=travel, params={"energy": 0.5}))
    assert moving.motion == "sneak"
    ys = [k.value.y for k in moving.channels[("shift", "torso")]]
    assert min(ys) < -2 and ys[0] == 0 and ys[-1] == 0


def test_acting_motions_compose_with_idle_and_blink() -> None:
    for name in ACTING:
        actions = [
            {"motion": "idle_breathe", "start_s": 0},
            {"motion": "blink", "start_s": 0},
            {"motion": name, "start_s": 1},
        ]
        both = animate(VIEW, actions, fps=FPS, n_frames=240, seed="pip")
        alone = animate(VIEW, actions[2:], fps=FPS, n_frames=240, seed="pip")
        assert both.eyes is not None
        assert set(alone.angles) | set(alone.shifts) <= set(both.angles) | set(both.shifts), name
        if name == "laugh":  # the laugh owns the eyes while it lasts, blinks resume after
            window = [w for w in both.eyes.waypoints if 24 <= w.frame <= 24 + 40]
            assert {w.value for w in window} <= {"open", "half"}
        else:
            assert {w.value for w in both.eyes.waypoints} == {"open", "half", "closed"}


def test_point_anticipates_and_overshoots() -> None:
    clip = MOTIONS["point"](ctx(params={"target": [1700, 300]}, root_px=Vec(960, 900)))
    vals = [k.value for k in clip.channels[("angle", "upper_arm_l")]]
    hold = vals[3]  # the settled value
    assert vals[1] < 0  # wind-up the other way first
    assert vals[2] > hold > 90  # flicks past the target (5°), then settles
    assert vals[0] == vals[-1] == 0
