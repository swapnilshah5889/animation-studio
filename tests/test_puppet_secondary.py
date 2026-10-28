"""Ears and tails as bones of their own (puppet/secondary.py, build_puppet(secondary=True)).

Synthetic masks drawn on the skeleton for the detectors' rules (what is accepted, and each
reason for a refusal), then the fixture fox of test_puppet_build.py (a scarf, a tail behind a
leg) with ears added for the whole cut: the rig validates, the default build is untouched,
the bones carry their parts, and at rest the parts compose back to the sheet."""

import json
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw
from test_puppet_build import (
    FUR,
    draw_character,
)

from studio_core.puppet.build import build_puppet, compose
from studio_core.puppet.design import CANVAS
from studio_core.puppet.secondary import add_secondary, find_ears, find_tail, open_disc
from studio_core.puppet.skeleton import turnaround
from studio_core.rig import build_character, load_rig, world_pose
from studio_core.schema import validate
from studio_core.sif import Space

FRONT, SIDE = turnaround(CANVAS)
BLUE = (60, 90, 200)


def head_geometry(sk):
    (nx, ny), (_, ty) = sk.joints["neck"], sk.joints["head_top"]
    r = (ny - ty) / 2
    return nx, ny, ty, r


def head_with(sk, ears=((-1, 0.0), (1, 0.0)), size=1.0, colour=FUR, tuft=False):
    """A head mask and its pixels: a skull ellipse and round ears on its upper corners."""
    nx, ny, ty, r = head_geometry(sk)
    img = Image.new("RGB", CANVAS[::1], (250, 250, 248))
    m = Image.new("L", CANVAS, 0)
    for side, grow in ears:
        er = 0.34 * r * size * (1 + grow)
        cx, cy = nx + side * 0.72 * r, ty + 0.5 * r
        box = [cx - er, cy - er, cx + er, cy + er]
        ImageDraw.Draw(img).ellipse(box, fill=colour)
        ImageDraw.Draw(m).ellipse(box, fill=255)
    for canvas, fill in ((ImageDraw.Draw(img), FUR), (ImageDraw.Draw(m), 255)):
        canvas.ellipse([nx - 0.8 * r, ty + 0.35 * r, nx + 0.8 * r, ny + 0.1 * r], fill=fill)
    if tuft:
        box = [nx - 0.18 * r, ty, nx + 0.18 * r, ty + 0.6 * r]
        ImageDraw.Draw(img).ellipse(box, fill=FUR)
        ImageDraw.Draw(m).ellipse(box, fill=255)
    return np.asarray(m) > 127, np.asarray(img).astype("float32")


# --------------------------------------------------------------------------- ears


def test_two_round_lobes_above_the_skull_are_the_ears() -> None:
    head, rgb = head_with(FRONT)
    ears, note = find_ears(head, rgb, FRONT)
    assert sorted(ears) == ["left", "right"] and note["found"] == ["left", "right"]
    nx = head_geometry(FRONT)[0]
    left, right = ears["left"], ears["right"]
    assert left["joint"][0] > nx > right["joint"][0]  # the character's left is on screen-right
    for ear in ears.values():
        assert ear["mask"].sum() > 0.5 * ear["area"]
        assert ear["tip"][1] < ear["joint"][1]  # points up
        assert (ear["mask"] & head).sum() == ear["mask"].sum()
    assert not (left["mask"] & right["mask"]).any()


def test_a_head_without_ears_gets_none_and_says_so() -> None:
    head, rgb = head_with(FRONT, ears=())
    ears, note = find_ears(head, rgb, FRONT)
    assert ears == {} and "no lobes" in note["reason"]


def test_a_tuft_on_the_midline_is_not_an_ear() -> None:
    head, rgb = head_with(FRONT, ears=(), tuft=True)
    ears, note = find_ears(head, rgb, FRONT)
    assert ears == {} and note["reason"]


def test_a_lone_ear_in_the_front_view_is_refused_but_fine_in_three_quarter() -> None:
    head, rgb = head_with(FRONT, ears=((1, 0.0),))
    ears, note = find_ears(head, rgb, FRONT)
    assert ears == {} and "one ear" in note["reason"]
    head, rgb = head_with(SIDE, ears=((1, 0.0),))
    ears, note = find_ears(head, rgb, SIDE)
    assert list(ears) == ["left"]


def test_ears_of_very_different_sizes_are_refused() -> None:
    head, rgb = head_with(FRONT, ears=((-1, -0.4), (1, 1.2)))
    ears, note = find_ears(head, rgb, FRONT)
    assert ears == {} and note["reason"]


def test_lobes_not_coloured_like_the_skull_are_refused() -> None:
    head, rgb = head_with(FRONT, colour=BLUE)  # a hat's bobbles or bows, not ears
    ears, note = find_ears(head, rgb, FRONT)
    assert ears == {} and "not coloured like the skull" in note["reason"]


def head_with_lobes(sk, lobes):
    """A head with extra round lobes: (dx in head radii from the neck, y in px, radius in radii)."""
    nx, _, _, r = head_geometry(sk)
    head, rgb = head_with(sk, ears=())
    m, im = Image.fromarray(head.astype("uint8") * 255), Image.fromarray(rgb.astype("uint8"))
    for dx, cy, rad in lobes:
        box = [nx + (dx - rad) * r, cy - rad * r, nx + (dx + rad) * r, cy + rad * r]
        ImageDraw.Draw(m).ellipse(box, fill=255)
        ImageDraw.Draw(im).ellipse(box, fill=FUR)
    return np.asarray(m) > 127, np.asarray(im).astype("float32")


def test_lobes_below_the_eyes_are_cheeks_not_ears() -> None:
    eye_y, r = FRONT.joints["l_eye"][1], head_geometry(FRONT)[3]
    head, rgb = head_with_lobes(
        FRONT, [(-1.0, eye_y + 0.3 * r, 0.34), (1.0, eye_y + 0.3 * r, 0.34)]
    )
    ears, note = find_ears(head, rgb, FRONT)
    assert ears == {} and "no lobes above the eyes" in note["reason"]


def test_a_third_lobe_makes_the_head_ambiguous() -> None:
    ty, r = head_geometry(FRONT)[2], head_geometry(FRONT)[3]
    head, rgb = head_with(FRONT)
    nx = head_geometry(FRONT)[0]
    box = [nx - 1.7 * r, ty, nx - 1.1 * r, ty + 0.6 * r]
    m, im = Image.fromarray(head.astype("uint8") * 255), Image.fromarray(rgb.astype("uint8"))
    ImageDraw.Draw(m).ellipse(box, fill=255)
    ImageDraw.Draw(im).ellipse(box, fill=FUR)
    ears, note = find_ears(np.asarray(m) > 127, np.asarray(im).astype("float32"), FRONT)
    assert ears == {} and "3 lobes" in note["reason"]


def test_opening_removes_what_a_disc_cannot_fill() -> None:
    m = np.zeros((60, 60), dtype=bool)
    m[10:50, 10:50] = True
    m[0:10, 28:32] = True  # a thin stalk
    opened = open_disc(m, 5)
    assert opened[30, 30] and not opened[3, 30]


# --------------------------------------------------------------------------- tail


def torso_with(sk, blobs=()):
    """A torso mask: the body polygon plus filled ellipses (x0, y0, x1, y1 as fractions of the
    figure height from the pelvis)."""
    j, h = sk.joints, sk.height_px
    img = Image.new("L", CANVAS, 0)
    d = ImageDraw.Draw(img)
    d.polygon([j["r_shoulder"], j["l_shoulder"], j["l_hip"], j["r_hip"]], fill=255)
    px, py = j["pelvis"]
    for x0, y0, x1, y1 in blobs:
        d.ellipse([px + x0 * h, py + y0 * h, px + x1 * h, py + y1 * h], fill=255)
    m = np.asarray(img) > 127
    rgb = np.full((*m.shape, 3), 250.0, dtype="float32")
    rgb[m] = FUR
    return m, rgb


def test_a_fat_piece_hanging_off_the_hip_is_the_tail_cut_into_segments() -> None:
    torso, rgb = torso_with(FRONT, [(-0.34, -0.02, -0.05, 0.14), (-0.55, -0.06, -0.25, 0.1)])
    tail, note = find_tail(torso, rgb, FRONT)
    assert tail is not None and note["found"] and 1 <= note["segments"] <= 3
    segs = tail["segments"]
    assert len(segs) == len(tail["joints"]) == note["segments"]
    union = np.zeros_like(torso)
    for s in segs:
        assert not (union & s).any()  # the segments partition the tail
        union |= s
    assert (union == tail["mask"]).all()
    assert not (tail["mask"] & ~torso).any()
    xs = [x for x, _ in tail["joints"]] + [tail["tip"][0]]
    assert xs == sorted(xs, reverse=True)  # joints run outward, to the character's right here


def test_a_longer_tail_gets_more_segments() -> None:
    short, _ = torso_with(FRONT, [(-0.25, -0.02, -0.05, 0.1)])
    long, rgb = torso_with(FRONT, [(-0.55, -0.02, -0.05, 0.1)])
    n_short = find_tail(short, rgb, FRONT)[1].get("segments", 0)
    n_long = find_tail(long, rgb, FRONT)[1].get("segments", 0)
    assert 1 <= n_short < n_long <= 3


def test_a_skirt_flaring_on_both_sides_is_clothing() -> None:
    torso, rgb = torso_with(FRONT, [(-0.34, -0.02, -0.05, 0.1), (0.05, -0.02, 0.34, 0.1)])
    tail, note = find_tail(torso, rgb, FRONT)
    assert tail is None and "two similar" in note["reason"]


def test_a_hem_along_the_side_is_refused() -> None:
    torso, rgb = torso_with(FRONT, [(-0.2, -0.28, -0.04, 0.12)])  # attached along its length
    tail, note = find_tail(torso, rgb, FRONT)
    assert tail is None and note["reason"]


def test_a_scarf_end_high_on_the_body_is_not_a_tail() -> None:
    torso, rgb = torso_with(FRONT, [(-0.4, -0.58, -0.1, -0.5)])
    tail, note = find_tail(torso, rgb, FRONT)
    assert tail is None and note["reason"]


def test_a_scarf_end_is_refused_for_being_too_high_not_for_some_other_reason() -> None:
    torso, rgb = torso_with(FRONT, [(-0.4, -0.36, -0.1, -0.24)])
    tail, note = find_tail(torso, rgb, FRONT)
    assert tail is None and "too high" in note["reason"]


def test_the_colour_trim_gives_the_body_coloured_root_back_to_the_torso() -> None:
    torso, rgb = torso_with(FRONT, [(-0.4, -0.02, -0.05, 0.1)])
    whole = find_tail(torso, rgb, FRONT)[0]
    assert whole is not None
    ys, xs = np.nonzero(whole["mask"])
    jx, jy = whole["joints"][0]
    far = np.hypot(xs - jx, ys - jy) > 0.08 * FRONT.height_px
    painted = rgb.copy()
    painted[ys[far], xs[far]] = BLUE  # the tail proper is another colour than the body
    trimmed, note = find_tail(torso, painted, FRONT)  # the root, body-coloured, is given back
    assert trimmed is None and "after the colour trim" in note["reason"]


def test_a_body_with_nothing_outside_has_no_tail() -> None:
    torso, rgb = torso_with(FRONT)
    tail, note = find_tail(torso, rgb, FRONT)
    assert tail is None and "outside the body" in note["reason"]


# --------------------------------------------------------------------------- the cut


def parts_for(head, rgb, torso):
    return {"head": head.copy(), "torso": torso.copy()}


def test_add_secondary_moves_pixels_to_new_parts_and_orders_them() -> None:
    head, rgb = head_with(FRONT)
    torso, trgb = torso_with(FRONT, [(-0.34, -0.02, -0.05, 0.14), (-0.55, -0.06, -0.25, 0.1)])
    figure = head | torso
    parts = {"head": head, "torso": torso}
    masks = {k: v.copy() for k, v in parts.items()}
    pixels = {"head": rgb, "torso": np.where(torso[..., None], trgb, rgb)}
    bones = {"torso": {"parent": None}, "head": {"parent": "torso"}}
    order = ("thigh_r", "torso", "head")
    new_order, report = add_secondary(rgb, figure, parts, masks, pixels, bones, FRONT, order)
    assert report["ears"]["found"] == ["left", "right"] and report["tail"]["found"]
    ear = masks["ear_l"]
    assert ear.sum() > 0 and not (ear & masks["head"] & parts["head"] & ~ear).all()
    assert masks["head"].sum() < head.sum() and masks["torso"].sum() < torso.sum()
    assert bones["ear_l"]["parent"] == "head" and bones["ear_l"]["role"] == "ear"
    assert bones["ear_l"]["side"] == "left" and bones["ear_r"]["side"] == "right"
    tails = [b for b in bones if b.startswith("tail")]
    assert bones[tails[0]]["parent"] == "torso" and all(bones[t]["role"] == "tail" for t in tails)
    assert all(bones[b]["parent"] == a for a, b in pairwise(tails))
    i = new_order.index
    assert i(tails[-1]) < i(tails[0]) < i("thigh_r") < i("torso")  # the tail behind everything
    assert i("ear_r") < i("head") and i("ear_l") < i("head")
    assert (masks["ear_l"] & figure).sum() >= masks["ear_l"].sum()  # the cap stays on the figure
    # the ear's cap reaches into the head, painted with the ear's own colour
    cap = masks["ear_l"] & parts["head"] & ~ears_only(FRONT, head, rgb)["left"]["mask"]
    assert cap.any()
    seg = find_tail(torso, np.where(torso[..., None], trgb, rgb), FRONT)[0]["segments"]
    assert (masks[tails[0]] & masks["torso"]).any()  # the root cap reaches into the body
    assert len(tails) > 1  # at an inner joint both segments hold the pixels around it
    assert (masks[tails[0]] & seg[1]).any() and (masks[tails[1]] & seg[0]).any()


def ears_only(sk, head, rgb):
    return find_ears(head, rgb, sk)[0]


def test_nothing_is_added_for_a_character_without_either() -> None:
    head, rgb = head_with(FRONT, ears=())
    torso, _ = torso_with(FRONT)
    masks = {"head": head.copy(), "torso": torso.copy()}
    bones = {"torso": {"parent": None}, "head": {"parent": "torso"}}
    order = ("torso", "head")
    new_order, report = add_secondary(
        rgb, head | torso, {"head": head, "torso": torso}, masks, {"head": rgb, "torso": rgb},
        bones, FRONT, order,
    )  # fmt: skip
    assert new_order == order and set(bones) == {"torso", "head"}
    assert report["ears"]["reason"] and report["tail"]["reason"]
    assert (masks["head"] == head).all() and (masks["torso"] == torso).all()


# --------------------------------------------------------------------------- whole build


def fox_sheet() -> Image.Image:
    """The fixture fox with a pair of round ears on top of its head, in both views."""
    img = Image.new("RGB", CANVAS, (250, 250, 248))
    draw = ImageDraw.Draw(img)
    for sk in (FRONT, SIDE):
        draw_character(draw, sk)
        nx, _, ty, r = head_geometry(sk)
        lean = (sk.joints["nose"][0] - nx) * 0.5  # the head is turned in the three-quarter view
        for side in (-1, 1):
            cx, cy, er = nx + lean + side * 0.72 * r, ty + 0.3 * r, 0.34 * r
            draw.ellipse([cx - er, cy - er, cx + er, cy + er], fill=FUR)
    return img


def build(root: Path, **kw):
    return build_puppet(root, "kit", sam=False, three_quarter="sheet", **kw)


@pytest.fixture(scope="module")
def fox_builds(tmp_path_factory: pytest.TempPathFactory):
    """The fox cut twice, in two films: the default way and with secondary=True."""
    from studio_core.film import Film
    from studio_core.models import load_manifest

    out = {}
    for tag, kw in (("plain", {}), ("secondary", {"secondary": True})):
        root = tmp_path_factory.mktemp(tag) / "film"
        Film.create(root, "storybook", load_manifest())
        design = root / "characters" / "kit" / "design"
        (design / "c1").mkdir(parents=True)
        fox_sheet().save(design / "c1" / "sheet.png")
        candidate = {
            "id": "c1", "description": "a small fox", "seed": 1, "fast": False,
            "sheet": "c1/sheet.png", "ok": True, "problems": [],
        }  # fmt: skip
        data = {
            "schema_version": 1, "character": "kit", "style": "storybook",
            "chosen": "c1", "candidates": [candidate],
        }  # fmt: skip
        (design / "candidates.json").write_text(json.dumps(data))
        out[tag] = (root, build(root, **kw))
    return out


def test_default_build_has_no_secondary_bones_and_the_same_limbs(fox_builds) -> None:
    (plain_root, plain), (sec_root, both) = fox_builds["plain"], fox_builds["secondary"]
    assert not any(
        b["role"] in ("ear", "tail") for b in plain.rig["views"]["front"]["bones"].values()
    )
    assert "secondary" not in plain.report["views"]["front"]
    for path in (plain_root / "characters/kit/parts/front").glob("*.png"):
        if path.name.startswith(("upper", "fore", "thigh", "shin")):  # cut before any of this
            other = sec_root / "characters/kit/parts/front" / path.name
            assert other.read_bytes() == path.read_bytes()
    assert both.rig["views"]["front"]["bones"]["ear_l"]["role"] == "ear"


def test_secondary_build_makes_a_valid_rig_with_parts_for_every_bone(fox_builds) -> None:
    built = fox_builds["secondary"][1]
    assert validate("rig", built.rig) == []
    rig = load_rig(built.rig_path)  # all part files exist
    for view_name in ("front", "three_quarter"):
        view = rig.view(view_name)
        report = built.report["views"][view_name]["secondary"]
        assert "ears" in report and "tail" in report
        for name, spec in view["bones"].items():
            if spec["role"] in ("ear", "tail"):
                assert view["parts"][name]["bone"] == name and name in view["draw_order"]
        for side in report["ears"].get("found", []):
            ear = f"ear_{side[0]}"
            assert view["draw_order"].index(ear) < view["draw_order"].index("head")
    front = rig.view("front")
    assert built.report["views"]["front"]["secondary"]["ears"]["found"] == ["left", "right"]
    # joints sit inside the parent's part image, so the Synfig rig builds
    sif = build_character(rig, "front", Space(1920, 1080, 120), file_prefix="x")
    assert {"ear_l", "ear_r"} <= set(sif.by_name)
    pose = world_pose(front, {"ear_l": 20})
    rest = world_pose(front)
    assert pose["ear_l"][1] == pytest.approx(rest["ear_l"][1] + 20)
    assert pose["head"] == rest["head"]  # the ear turns, the head does not


def test_at_rest_the_cut_with_ears_composes_back_to_the_default_cut(fox_builds) -> None:
    (plain_root, plain), (sec_root, built) = fox_builds["plain"], fox_builds["secondary"]
    flat = compose(plain.rig["views"]["front"], plain_root / "characters" / "kit")
    split = compose(built.rig["views"]["front"], sec_root / "characters" / "kit")
    a, b = np.asarray(flat)[..., 3] > 127, np.asarray(split)[..., 3] > 127
    assert (a ^ b).sum() < 0.01 * a.sum()  # the silhouette is the same
    assert b.sum() > 0


def test_a_raised_arm_still_clears_the_ears_that_are_now_parts_of_their_own(fox_builds) -> None:
    """The wave and the clap stop the arm where the hand would pass behind the head's art; with
    the ears cut out of the head image they must still count (Kit's pose sweep found 5 seams)."""
    from studio_core.motions import animate

    def arm_keys(built):
        view = load_rig(built.rig_path).view("front")
        action = {"motion": "wave", "start_s": 0.0, "params": {"side": "left", "energy": 1.0}}
        clip = animate(view, [action], fps=24, n_frames=96).clips[0]
        return {k: v for k, v in clip.channels.items() if k[0] == "angle"}

    plain, both = fox_builds["plain"][1], fox_builds["secondary"][1]
    assert arm_keys(both) == arm_keys(plain)


def test_the_arm_raise_stops_at_an_ear_wider_than_the_head() -> None:
    from studio_core.motions import MotionContext
    from studio_core.motions.library import _clear_raise

    rig = json.loads((Path(__file__).parent / "fixtures/characters/pip/rig.json").read_text())
    view = rig["views"]["front"]
    ctx = lambda v: MotionContext(view=v, fps=24, start=0, last_frame=99, seed="x")  # noqa: E731
    bare = _clear_raise(ctx(view), "left", 160.0, 35.0)
    head = view["parts"]["head"]
    view["bones"]["ear_l"] = {
        "role": "ear", "side": "left", "parent": "head", "direction_deg": 60, "length_px": 80,
        "limits_deg": {"min": -35, "max": 35}, "attach": {"part": "head", "at_px": [150, 20]},
    }  # fmt: skip
    view["parts"]["ear_l"] = {
        "file": head["file"], "size_px": [600, 60], "pivot_px": [0, 30], "bone": "ear_l",
    }  # fmt: skip
    assert _clear_raise(ctx(view), "left", 160.0, 35.0) < bare


def test_a_rig_with_a_misplaced_ear_is_refused() -> None:
    rig = json.loads((Path(__file__).parent / "fixtures/characters/pip/rig.json").read_text())
    view = rig["views"]["front"]
    arm = next(n for n, s in view["bones"].items() if s.get("role") == "upper_arm")
    view["bones"]["ear_x"] = {
        "role": "ear", "side": "center", "parent": arm, "direction_deg": 90,
        "attach": {"part": view["bones"][arm].get("attach", {}).get("part", arm), "at_px": [1, 1]},
    }  # fmt: skip
    problems = " ".join(map(str, validate("rig", rig)))
    assert "an ear needs side" in problems and "parent must be the head" in problems
