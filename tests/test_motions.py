"""Motion library: timeline maths, composition rules, and per-motion timing (task 2.5)."""

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
