"""Round 2 of the rigged-character spike (D-096): the review's findings, each held by a rule."""

import numpy as np
import pytest
from PIL import Image

from studio_core.motions import smooth
from studio_core.motions.library import MOTIONS, MotionContext
from studio_core.puppet.flat import FlatSpec, build_flat_puppet, build_parts, leg_ratios
from studio_core.rig import load_rig


@pytest.fixture(scope="module")
def parts():
    ps, info = build_parts(FlatSpec())
    return {p.name: p for p in ps}, info


def alpha(part) -> np.ndarray:
    return np.asarray(part.art.done())[..., 3]


def components(mask: np.ndarray) -> int:
    seen, n = np.zeros_like(mask, bool), 0
    for y, x in zip(*np.nonzero(mask), strict=True):
        if seen[y, x]:
            continue
        n += 1
        stack = [(y, x)]
        seen[y, x] = True
        while stack:
            cy, cx = stack.pop()
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if (
                    0 <= ny < mask.shape[0]
                    and 0 <= nx < mask.shape[1]
                    and mask[ny, nx]
                    and not seen[ny, nx]
                ):
                    seen[ny, nx] = True
                    stack.append((ny, nx))
    return n


# --- 1. shot transitions
def test_never_dissolve_two_framings_of_the_character_at_different_scales():
    assert smooth.transition_for(1.0, 1.55, character_in_both=True) == "cut"  # the ghost case
    assert smooth.transition_for(1.55, 1.0, character_in_both=True) == "cut"
    assert smooth.transition_for(1.0, 1.15, character_in_both=True) == "crossfade"  # close scales
    assert (
        smooth.transition_for(1.0, 3.0, character_in_both=False) == "crossfade"
    )  # no character twice


def test_the_clip_uses_one_continuous_camera_not_a_dissolve():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parents[1] / "scripts/spikes"))
    import rigged_character_test as rct

    assert rct.CAM["move"] == "track" and not hasattr(rct, "CUT")
    zooms = [k["zoom"] for k in rct.CAM["keys"]]
    assert zooms == sorted(zooms) and zooms[-1] / zooms[0] > 1.4  # a real push-in


# --- 2. neck
def test_neck_is_narrow_tapered_and_tucked_under_the_collar(parts):
    spec = FlatSpec()
    torso = parts[0]["torso"].art
    img = np.asarray(torso.done()).astype(int)
    skin = np.array([int(spec.palette.skin[i : i + 2], 16) for i in (1, 3, 5)])
    shade = np.array([int(spec.palette.skin_shade[i : i + 2], 16) for i in (1, 3, 5)])
    near = lambda c: (np.abs(img[..., :3] - c).sum(-1) < 24) & (img[..., 3] > 200)  # noqa: E731
    neck = near(skin) | near(shade)
    widths = [int(neck[y].sum()) for y in range(neck.shape[0]) if neck[y].any()]
    assert widths and max(widths) <= 0.16 * spec.head_w  # far narrower than the old 52 px block
    assert near(shade).any()  # an under-chin shade, not a flat block
    rows = np.nonzero(neck.any(1))[0]
    assert int(np.argmax(widths)) >= 0.4 * len(
        widths
    )  # tapers: widest low, where the collar covers it
    assert widths[0] < max(widths)
    collar = np.asarray(torso.done())[..., 3] > 0
    assert collar[rows.max() + 3, torso.w // 2]  # coat continues below the neck: it is tucked in


def test_the_head_image_has_no_neck_block(parts):
    skin = np.asarray(parts[0]["head"].art.done())[..., 3] > 0
    spec = FlatSpec()
    lowest = np.nonzero(skin.any(1))[0].max() + parts[0]["head"].art.y0
    assert lowest <= spec.neck_y + 2  # the face ends at the chin; nothing hangs below it


# --- 3. hair
@pytest.mark.parametrize("name", ["hair_back", "hair_l", "hair_r"])
def test_hair_pieces_are_one_unclipped_shape(parts, name):
    a = alpha(parts[0][name])
    assert a[0].max() == a[-1].max() == a[:, 0].max() == a[:, -1].max() == 0  # nothing clipped
    assert components(a > 128) == 1


def test_fringe_is_unclipped_smooth_and_not_flat_topped(parts):
    over = np.asarray(parts[1]["layers"]["over"].done())[..., 3]
    assert over[0].max() == over[:, 0].max() == over[:, -1].max() == 0
    mask = over > 128
    assert components(mask) == 1  # fringe + side hair are one path, no notch island
    top = np.array(
        [np.nonzero(mask[:, x])[0].min() for x in range(mask.shape[1]) if mask[:, x].any()]
    )
    # a flat clipped top would have a long run of identical top rows; a curved head does not
    longest = max(np.diff(np.nonzero(np.diff(np.r_[-1, top, -1]))[0]))
    assert longest < 0.12 * len(top)
    edges = np.abs(np.diff(top[4:-4]))  # (the two vertical sides are not a step)
    assert edges.max() <= 6  # no stair-step: the outline never jumps more than a few px per column


# --- 4. legs and hands
def test_legs_are_long_enough_and_boots_small_enough():
    r = leg_ratios(FlatSpec())
    assert r["visible_leg"] >= 0.27 and r["boot"] <= 0.10


def test_hand_overlaps_the_cuff_and_is_not_clipped(parts):
    spec = FlatSpec()
    for tag in ("l", "r"):
        img = np.asarray(parts[0][f"forearm_{tag}"].art.done()).astype(int)
        col = lambda h: np.array([int(h[i : i + 2], 16) for i in (1, 3, 5)])  # noqa: E731
        skin = (np.abs(img[..., :3] - col(spec.palette.skin)).sum(-1) < 24) & (img[..., 3] > 200)
        cuff = (np.abs(img[..., :3] - col(spec.palette.coat_trim)).sum(-1) < 24) & (
            img[..., 3] > 200
        )
        grown = np.zeros_like(skin)
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                grown |= np.roll(np.roll(skin, dy, 0), dx, 1)
        assert (grown & cuff).sum() > 30  # skin and cuff touch along a real edge: no gap
        a = img[..., 3]
        assert a[0].max() == a[-1].max() == a[:, 0].max() == a[:, -1].max() == 0  # hand not clipped
        assert components(a > 128) == 1


# --- walk
def test_walk_step_has_foot_lift_knee_bend_bob_and_stays_smooth(tmp_path):
    build_flat_puppet(FlatSpec(), tmp_path)
    view = load_rig(tmp_path / "rig.json").view("front")
    n = 48
    travel = [i * 6.0 for i in range(n + 1)]
    ctx = MotionContext(view, 24, 0, n, duration=n, params={"energy": 0.6}, travel=travel)
    plain = MOTIONS["walk_cycle"](ctx)
    ctx2 = MotionContext(view, 24, 0, n, duration=n, params={"energy": 0.6}, travel=travel)
    clip = MOTIONS["walk_step"](ctx2)
    lift = lambda c, b: max(k.value.y for k in c.channels[("shift", b)])  # noqa: E731
    assert lift(clip, "thigh_l") > 1.15 * lift(plain, "thigh_l")  # a visibly higher foot lift
    knee = [k.value for k in clip.channels[("angle", "shin_l")]]
    assert max(knee) >= 15 and min(knee) >= 0  # the lifted knee bends toward the travel direction
    assert max(abs(b - a) for a, b in zip(knee, knee[1:], strict=False)) < 12  # eased, no pop
    bob = [k.value.y for k in clip.channels[("shift", "torso")]]
    assert max(bob) - min(bob) >= 4  # the body bobs
    lo, hi = clip.limits["shin_r"]
    assert hi >= 15 and lo <= -10  # the clip declares the knee range it needs
