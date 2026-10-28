"""Swappable hand poses: schema, shapes, switch tracks, motion hooks, set_hand, and renders."""

import copy
import dataclasses
import hashlib
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from studio_core.config import REPO_ROOT, load_config
from studio_core.hands import (
    DEFAULT_LINE,
    DRAWN,
    HAND_POSES,
    CutHand,
    HandGeometry,
    add_hands,
    colour_distance,
    hand_attachments,
    hand_bone,
    hand_outline,
    hand_switch,
    hand_track,
    measure_cut_hand,
    measure_hand,
    pose_layers,
)
from studio_core.motions import MotionError, animate
from studio_core.rig import Rig, build_character, load_rig, world_pose
from studio_core.schema import validate
from studio_core.shot import ShotError, build_shot
from studio_core.shot_spec import FilmFolder, SpecError, add_hand
from studio_core.sif import (
    Animated,
    Canvas,
    Group,
    Interp,
    Outline,
    Region,
    Space,
    Switch,
    Transform,
    Vec,
    Waypoint,
)
from studio_core.sif.render import render_frames

FIXTURES = REPO_ROOT / "tests" / "fixtures"
PIP = FIXTURES / "characters" / "pip"
SPACE = Space(1920, 1080, 60)
SYNFIG = pytest.mark.skipif(not load_config().path("tools", "synfig").exists(), reason="no synfig")


def pip_with_hands(poses: tuple[str, ...] = HAND_POSES) -> Rig:
    rig = load_rig(PIP / "rig.json")
    return Rig(add_hands(rig, poses), rig.folder)


def view_of(rig: Rig) -> dict:
    return rig.view()


# --------------------------------------------------------------------------- schema


def test_a_rig_with_hands_validates_and_one_without_still_does() -> None:
    rig = pip_with_hands()
    assert validate("rig", rig.data) == []
    assert validate("rig", json.loads((PIP / "rig.json").read_text())) == []
    hands = rig.view()["hands"]
    assert set(hands) == {"forearm_l", "forearm_r"}
    assert hands["forearm_l"]["poses"] == list(HAND_POSES) and hands["forearm_l"]["size_px"] > 0


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda h: h["forearm_l"].update(poses=["fist"]), "must include 'rest'"),
        (lambda h: h["forearm_l"].update(wrist_px=[500, 5]), "outside"),
        (lambda h: h["forearm_l"].update(part="head"), "carried by"),
        (lambda h: h["forearm_l"].update(part="nope"), "unknown part"),
        (lambda h: h.update(thigh_l=h.pop("forearm_l")), "not a forearm"),
        (lambda h: h.update(wing=h.pop("forearm_l")), "unknown bone"),
        (lambda h: h["forearm_l"].update(size_px=0), "size_px"),
        (lambda h: h["forearm_l"].update(poses=["rest", "thumbs_up"]), "thumbs_up"),
        (lambda h: h["forearm_l"].update(fill="red"), "fill"),
    ],
)
def test_bad_hands_are_refused(edit, message: str) -> None:
    data = copy.deepcopy(pip_with_hands().data)
    edit(data["views"]["front"]["hands"])
    issues = " | ".join(map(str, validate("rig", data)))
    assert message in issues, issues


# --------------------------------------------------------------------------- shapes


def geometry(side: str = "left", poses: tuple[str, ...] = HAND_POSES) -> HandGeometry:
    view = view_of(pip_with_hands(poses))
    return HandGeometry.from_view(view, f"forearm_{side[0]}", SPACE)


def _points(layers) -> list[Vec]:
    out = []
    for layer in layers:
        out += [p.point for p in layer.spline.points]
    return out


@pytest.mark.parametrize("pose", DRAWN)
def test_each_pose_stays_near_the_wrist_in_the_character_colours(pose: str) -> None:
    g = geometry()
    layers = pose_layers(g, pose)
    reach = {"fist": 1.3, "open": 1.9, "wave": 1.9, "point": 2.1}[pose] * g.size
    for p in _points(layers):  # (the stroke ends; the line width adds a little)
        assert math.hypot(p.x - g.wrist.x, p.y - g.wrist.y) <= reach + g.size * 0.3, pose
    colours = {(type(layer).__name__, layer.desc, layer.color) for layer in layers}
    assert ("Region", "fill", g.fill) in colours or ("Outline", "fill", g.fill) in colours
    assert all(layer.color in (g.fill, g.outline) for layer in layers)
    assert g.outline != g.fill
    # outlines first (drawn under), then the fills: the outline colour shows as a rim
    outlines = [layer for layer in layers if layer.desc == "outline"]
    fills = [layer for layer in layers if layer.desc == "fill"]
    assert outlines and fills and {layer.color for layer in outlines} == {g.outline}
    assert {layer.color for layer in fills} == {g.fill}
    assert layers.index(outlines[-1]) < layers.index(fills[0])
    assert any(isinstance(layer, (Outline, Region)) for layer in layers)


def test_the_poses_are_different_drawings() -> None:
    g = geometry()
    xmls = {p: repr(pose_layers(g, p)) for p in DRAWN}
    assert len(set(xmls.values())) == len(DRAWN)


def test_the_waving_hand_is_the_open_hand_tipped() -> None:
    g = geometry()

    def tip_angle(pose: str) -> float:
        far = max(
            _points(pose_layers(g, pose)),
            key=lambda p: math.hypot(p.x - g.wrist.x, p.y - g.wrist.y),
        )
        return math.degrees(math.atan2(far.y - g.wrist.y, far.x - g.wrist.x))

    assert abs(tip_angle("wave") - tip_angle("open")) > 8


def test_the_point_reaches_further_than_the_fist() -> None:
    g = geometry()

    def reach(pose: str) -> float:
        return max(
            math.hypot(p.x - g.wrist.x, p.y - g.wrist.y) for p in _points(pose_layers(g, pose))
        )

    assert reach("point") > 1.4 * reach("fist")


def test_the_thumb_is_on_the_side_of_the_body() -> None:
    left, right = geometry("left"), geometry("right")
    assert left.mirror != right.mirror
    # Both hang down: the left hand's thumb points toward the body (the image's other side).
    tips = []
    for g in (left, right):
        pts = _points(pose_layers(g, "open"))
        tips.append(max(pts, key=lambda p: abs(p.x - g.wrist.x)).x - g.wrist.x)
    assert tips[0] * tips[1] < 0


def test_the_outline_colour_defaults_to_the_face_line_and_can_be_set() -> None:
    rig = pip_with_hands()
    view = rig.view()
    line = view["face"]["colors"]["line"]
    g = HandGeometry.from_view(view, "forearm_l", SPACE)
    from studio_core.sif import Color

    assert g.outline == Color.hex(line)
    view["hands"]["forearm_l"]["outline"] = "#112233"
    assert HandGeometry.from_view(view, "forearm_l", SPACE).outline == Color.hex("#112233")
    # no hand outline and a face line that is not the default: the face line, not the default
    del view["hands"]["forearm_l"]["outline"]
    view["face"]["colors"]["line"] = "#abcdef"
    assert HandGeometry.from_view(view, "forearm_l", SPACE).outline == Color.hex("#abcdef")
    del view["face"]["colors"]["line"]
    assert HandGeometry.from_view(view, "forearm_l", SPACE).outline == Color.hex(DEFAULT_LINE)


def arm_image(path: Path, ring: int = 9) -> None:
    """A 30 px wide arm pointing down, an orange fill with a thick dark outline all round."""
    img = Image.new("RGBA", (120, 200), (0, 0, 0, 0))
    px = img.load()
    for y in range(20, 180):
        for x in range(40, 70):
            edge = x < 40 + ring or x >= 70 - ring or y >= 180 - ring
            rim = x in (40, 69) or y in (20, 179)  # a pale 1 px anti-aliasing fringe
            px[x, y] = (
                (240, 240, 240, 255) if rim else (20, 20, 20, 255) if edge else (200, 120, 40, 255)
            )
    img.save(path)


def test_the_fill_is_the_interior_not_a_median_dragged_dark_by_the_outline(tmp_path: Path) -> None:
    arm_image(tmp_path / "forearm.png")  # the outline is more than half of the hand's pixels
    cut = measure_cut_hand(tmp_path / "forearm.png", -90)
    assert cut.fill == "#c87828"
    flat = Image.new("RGBA", (120, 200), (0, 0, 0, 0))
    flat.paste((10, 200, 90, 255), (40, 20, 70, 180))
    flat.save(tmp_path / "flat.png")
    assert measure_hand(tmp_path / "flat.png", -90)[2] == "#0ac85a"


def test_the_edge_colour_is_the_cut_hands_own_dark_outline(tmp_path: Path) -> None:
    arm_image(tmp_path / "forearm.png")
    assert measure_cut_hand(tmp_path / "forearm.png", -90).edge == "#141414"
    flat = Image.new("RGBA", (120, 200), (0, 0, 0, 0))  # no outline: nothing darker at the rim
    flat.paste((200, 120, 40, 255), (40, 20, 70, 180))
    flat.save(tmp_path / "flat.png")
    cut = measure_cut_hand(tmp_path / "flat.png", -90)
    assert cut.edge == cut.fill == "#c87828"


def test_the_cover_contains_every_pixel_of_the_hand_beyond_the_wrist(tmp_path: Path) -> None:
    arm_image(tmp_path / "forearm.png")
    cut = measure_cut_hand(tmp_path / "forearm.png", -90)
    xs = [p[0] for p in cut.cover]
    ys = [p[1] for p in cut.cover]
    assert min(xs) <= 40 and max(xs) >= 70 and max(ys) >= 180  # the hand's corners are inside
    assert min(ys) >= cut.wrist[1] - 14  # ... and it starts at the wrist, not up the arm

    def inside(x: float, y: float) -> bool:  # convex, so the signs of the edge cross products agree
        sides = [
            (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])
            for a, b in zip(cut.cover, cut.cover[1:] + cut.cover[:1], strict=True)
        ]
        return all(v >= -1e-6 for v in sides) or all(v <= 1e-6 for v in sides)

    assert all(
        inside(x + 0.5, y + 0.5) for x in range(40, 70) for y in range(int(cut.wrist[1]) + 1, 180)
    )
    assert not inside(10, 100)


def test_the_outline_is_the_cut_hands_edge_only_when_the_face_line_is_far_from_it() -> None:
    assert hand_outline("#3a241c", "#874b29", "#503c34") == "#3a241c"  # Kit: the line is a halo
    assert hand_outline("#3a241c", "#3b2520", "#503c34") is None  # the line already matches it
    assert (
        hand_outline("#503c34", "#e0c0a0", "#503c34") is None
    )  # no darker edge: no outline to match
    assert hand_outline(None, "#874b29", "#503c34") is None
    assert colour_distance("#000000", "#ffffff") == pytest.approx(441.67, abs=0.1)


def test_add_hands_stores_the_cut_edge_as_the_outline_and_the_cover(monkeypatch) -> None:
    import studio_core.hands as hands_module

    real = hands_module.measure_cut_hand

    def fake(path: Path, direction: float, edge: str | None) -> CutHand:
        return dataclasses.replace(real(path, direction), edge=edge, fill="#503c34")

    rig = load_rig(PIP / "rig.json")
    line = rig.view()["face"]["colors"]["line"]
    for edge, expected in (("#101010", "#101010"), (line, None), (None, None)):
        monkeypatch.setattr(hands_module, "measure_cut_hand", lambda p, d, e=edge: fake(p, d, e))
        hand = add_hands(rig)["views"]["front"]["hands"]["forearm_l"]
        assert hand.get("outline") == expected
        assert hand["fill"] == "#503c34"
        assert len(hand["cover_px"]) >= 3  # the real cover is stored, and validates
    assert validate("rig", add_hands(rig)) == []


def width_of(layer: Region) -> float:
    xs = [p.point.x for p in layer.spline.points]
    return max(xs) - min(xs)


def test_every_pose_is_drawn_on_the_cut_hands_cover() -> None:
    g = geometry()
    assert len(g.cover) >= 3
    for pose in DRAWN:
        layers = pose_layers(g, pose)
        backs = [
            layer
            for layer in layers
            if isinstance(layer, Region) and len(layer.spline.points) == len(g.cover)
        ]
        assert {layer.color for layer in backs} == {g.fill, g.outline}, pose
        outline_back, fill_back = backs  # the rim first, a little bigger than the fill on top
        assert width_of(outline_back) > width_of(fill_back) > 0
        assert layers.index(outline_back) < layers.index(fill_back)
        for c, p in zip(g.cover, fill_back.spline.points, strict=True):
            assert (p.point.x, p.point.y) == pytest.approx((c.x, c.y))  # the fill is the cover
    bare = copy.deepcopy(view_of(pip_with_hands()))
    del bare["hands"]["forearm_l"]["cover_px"]
    assert not HandGeometry.from_view(bare, "forearm_l", SPACE).cover  # optional: no backing then


def test_the_hand_width_comes_from_the_cut_hand(tmp_path: Path) -> None:
    img = Image.new("RGBA", (120, 200), (0, 0, 0, 0))
    px = img.load()
    for y in range(20, 180):
        for x in range(40, 90):  # a 50 px wide arm, pointing down
            px[x, y] = (200, 120, 40, 255)
    img.save(tmp_path / "forearm.png")
    wrist, width, fill = measure_hand(tmp_path / "forearm.png", -90)
    assert width == pytest.approx(50, abs=1) and fill == "#c87828"
    assert wrist[0] == pytest.approx(64.5, abs=1) and wrist[1] == pytest.approx(
        180 - 0.95 * 50, abs=3
    )


# --------------------------------------------------------------------------- the switch


def test_the_switch_has_a_child_per_pose_and_rest_is_empty() -> None:
    g = geometry()
    sw = hand_switch(g, "forearm_l", "fist")
    assert isinstance(sw, Switch) and [c.desc for c in sw.children] == list(HAND_POSES)
    assert sw.children[0].children == [] and all(c.children for c in sw.children[1:])
    only = hand_switch(geometry(poses=("rest", "fist")), "forearm_l", "rest")
    assert [c.desc for c in only.children] == ["rest", "fist"]


def test_a_pose_the_hand_does_not_have_is_refused() -> None:
    g = geometry(poses=("rest", "fist"))
    with pytest.raises(ValueError, match=r"no hand pose.*point"):
        hand_switch(g, "forearm_l", "point")


def test_the_track_is_constant_keys_from_rest() -> None:
    track = hand_track([(5, "fist"), (9, "rest"), (12, "rest"), (20, "wave")])
    assert isinstance(track, Animated)
    assert [(w.frame, w.value, w.interp) for w in track.waypoints] == [
        (0, "rest", Interp.CONSTANT),
        (5, "fist", Interp.CONSTANT),
        (9, "rest", Interp.CONSTANT),
        (20, "wave", Interp.CONSTANT),
    ]
    assert hand_track([]) == "rest" and hand_track([(3, "rest")]) == "rest"


def test_attachments_ride_on_the_forearm_part_and_vanish_at_rest() -> None:
    view = view_of(pip_with_hands())
    assert hand_attachments(view, SPACE, {}) == {}
    assert hand_attachments(view, SPACE, {"forearm_l": "rest"}) == {}
    out = hand_attachments(view, SPACE, {"forearm_l": hand_track([(4, "point")])})
    assert list(out) == ["forearm_l"] and out["forearm_l"][0].desc == "hand forearm_l"
    assert hand_attachments(load_rig(PIP / "rig.json").view(), SPACE, {"forearm_l": "fist"}) == {}


def test_hand_bone_finds_the_forearm_by_side() -> None:
    view = view_of(pip_with_hands())
    assert hand_bone(view, "left") == "forearm_l" and hand_bone(view, "right") == "forearm_r"
    assert hand_bone(load_rig(PIP / "rig.json").view(), "left") is None


# --------------------------------------------------------------------------- motions


def hand_tracks(view: dict, actions: list[dict], n_frames: int = 400) -> dict:
    anim = animate(view, actions, fps=24, n_frames=n_frames, seed="t")
    return {b: [(w.frame, w.value) for w in t.waypoints] for b, t in anim.hands.items()}


def test_wave_waves_the_hand_it_raises_and_lowers_it_to_rest() -> None:
    view = view_of(pip_with_hands())
    for side, bone in (("right", "forearm_r"), ("left", "forearm_l")):
        tracks = hand_tracks(view, [{"motion": "wave", "start_s": 1, "params": {"side": side}}])
        assert set(tracks) == {bone}
        poses = [v for _, v in tracks[bone]]
        assert poses == ["rest", "wave", "rest"] and tracks[bone][0][0] == 24


def test_point_uses_the_pointing_hand_for_the_hold() -> None:
    view = view_of(pip_with_hands())
    tracks = hand_tracks(view, [{"motion": "point", "start_s": 0, "params": {"side": "left"}}])
    assert [v for _, v in tracks["forearm_l"]] == ["rest", "point", "rest"]
    (_, _), (f1, _), (f2, _) = tracks["forearm_l"]
    assert f2 - f1 > 20  # held through the hold, not a blip


def test_talking_gestures_alternate_open_and_rest() -> None:
    view = view_of(pip_with_hands())
    tracks = hand_tracks(view, [{"motion": "talk_gesture", "start_s": 0, "params": {"cycles": 3}}])
    poses = [v for _, v in tracks["forearm_r"]]
    assert poses == ["rest", "open", "rest", "open", "rest", "open", "rest"]


def test_clap_opens_both_hands_and_think_makes_a_fist() -> None:
    view = view_of(pip_with_hands())
    clap = hand_tracks(view, [{"motion": "clap", "start_s": 0}])
    assert set(clap) == {"forearm_l", "forearm_r"}
    assert all("open" in [v for _, v in t] for t in clap.values())
    think = hand_tracks(view, [{"motion": "think", "start_s": 0, "params": {"side": "left"}}])
    assert [v for _, v in think["forearm_l"]] == ["rest", "fist", "rest"]


def test_a_pose_the_rig_lacks_becomes_rest_and_a_rig_without_hands_has_no_track() -> None:
    fist_only = view_of(pip_with_hands(("rest", "fist")))
    assert hand_tracks(fist_only, [{"motion": "wave", "start_s": 0}]) == {}  # nothing to show
    assert "forearm_l" in hand_tracks(
        fist_only, [{"motion": "think", "start_s": 0, "params": {"side": "left"}}]
    )
    plain = load_rig(PIP / "rig.json").view()
    anim = animate(plain, [{"motion": "wave", "start_s": 0}], fps=24, n_frames=100)
    assert anim.hands == {}


def test_manual_hand_poses_override_and_hold() -> None:
    view = view_of(pip_with_hands())
    anim = animate(
        view,
        [{"motion": "wave", "start_s": 0, "params": {"side": "right"}}],
        fps=24,
        n_frames=200,
        hand_poses=[{"bone": "forearm_r", "pose": "fist", "start_s": 5}],
    )
    track = [(w.frame, w.value) for w in anim.hands["forearm_r"].waypoints]
    assert track[-1] == (120, "fist")
    with pytest.raises(MotionError, match="after the end"):
        animate(
            view,
            [],
            fps=24,
            n_frames=24,
            hand_poses=[{"bone": "forearm_r", "pose": "fist", "start_s": 5}],
        )


# --------------------------------------------------------------------------- set_hand and the shot


def make_film(tmp_path: Path, hands: bool) -> FilmFolder:
    root = tmp_path / "film"
    shutil.copytree(PIP, root / "characters" / "pip")
    shutil.copytree(FIXTURES / "backgrounds" / "meadow", root / "backgrounds" / "meadow")
    if hands:
        rig = load_rig(PIP / "rig.json")
        (root / "characters" / "pip" / "rig.json").write_text(json.dumps(add_hands(rig)))
    spec = json.loads((FIXTURES / "schemas" / "shot_s01_sh01.json").read_text())
    spec.update(duration_s=4, dialogue=[])
    spec["characters"][0]["actions"] = []
    (root / "shots" / spec["id"]).mkdir(parents=True)
    (root / "shots" / spec["id"] / "shot.json").write_text(json.dumps(spec))
    return FilmFolder(root)


def test_set_hand_refuses_a_character_without_hands_with_a_fixable_message(tmp_path: Path) -> None:
    film = make_film(tmp_path, hands=False)
    with pytest.raises(SpecError, match=r"no right hand poses.*add_hands"):
        add_hand(film, "s01_sh01", "pip", "fist", 1.0, "right")
    assert "hands" not in json.loads(film.shot_file("s01_sh01").read_text())["characters"][0]


def test_set_hand_records_and_the_shot_builds_with_the_switch(tmp_path: Path) -> None:
    film = make_film(tmp_path, hands=True)
    add_hand(film, "s01_sh01", "pip", "point", 1.0, "left")
    add_hand(film, "s01_sh01", "pip", "fist", 0.5, "left")
    add_hand(film, "s01_sh01", "pip", "open", 1.0, "left")  # replaces the one at 1.0
    spec = json.loads(film.shot_file("s01_sh01").read_text())
    assert spec["characters"][0]["hands"] == [
        {"side": "left", "pose": "fist", "start_s": 0.5},
        {"side": "left", "pose": "open", "start_s": 1.0},
    ]
    xml = build_shot(film.root, spec).canvas.to_string()
    assert 'desc="hand forearm_l"' in xml and 'desc="hand forearm_r"' not in xml
    with pytest.raises(SpecError, match=r"no 'thumbs_up' pose"):
        add_hand(film, "s01_sh01", "pip", "thumbs_up", 1.0, "left")


def test_a_hand_pose_in_a_spec_for_a_rig_without_hands_stops_the_build(tmp_path: Path) -> None:
    film = make_film(tmp_path, hands=False)
    spec = json.loads(film.shot_file("s01_sh01").read_text())
    spec["characters"][0]["hands"] = [{"side": "left", "pose": "fist", "start_s": 1}]
    with pytest.raises(ShotError, match="no left hand poses"):
        build_shot(film.root, spec)


# --------------------------------------------------------------------------- Pip is unchanged

# sha256 of the scene.sif text of tests/fixtures shot_s01_sh01 and of a longer shot with wave,
# point, talk_gesture, clap and think, taken at the commit before hands existed.
PLAIN_SHOT_HASHES = (
    "1f4f745b5f79c53151181f63675e5a1035ae35ba261cc44f20dd5531a6f705d1",
    "2004f78602a49b82d26f55982737a24f207d62a1827bcdbb407908b6989a06d9",
)


def test_a_character_without_hands_builds_a_byte_identical_scene(tmp_path: Path) -> None:
    from test_shot import SPEC
    from test_shot import make_film as shot_film

    film = shot_film(tmp_path)
    busy = json.loads(json.dumps(SPEC))
    busy.update(duration_s=14, dialogue=[])
    busy["characters"][0]["actions"] = [
        {"motion": "wave", "start_s": 0.2},
        {"motion": "point", "start_s": 3, "params": {"target": [0.8, 0.4]}},
        {"motion": "talk_gesture", "start_s": 6},
        {"motion": "clap", "start_s": 8},
        {"motion": "think", "start_s": 11},
    ]
    got = tuple(
        hashlib.sha256(build_shot(film, s).canvas.to_string().encode()).hexdigest()
        for s in (SPEC, busy)
    )
    assert got == PLAIN_SHOT_HASHES
    # ... and the same busy shot with hands is a different scene (the switch is there)
    rig = load_rig(film / "characters" / "pip" / "rig.json")
    (film / "characters" / "pip" / "rig.json").write_text(json.dumps(add_hands(rig)))
    with_hands = build_shot(film, busy).canvas.to_string()
    assert hashlib.sha256(with_hands.encode()).hexdigest() != PLAIN_SHOT_HASHES[1]
    assert 'desc="hand forearm_r"' in with_hands


# --------------------------------------------------------------------------- renders

CANVAS = (900, 1100)
ROOT = (450, 500)  # the root joint, canvas px


def render_poses(rig: Rig, tmp_path: Path, bone: str, poses: list[str]) -> list[np.ndarray]:
    """One frame per pose, the hand switched at frame i; the character stands at rest."""
    folder = tmp_path / "char"
    shutil.copytree(rig.folder, folder, ignore=shutil.ignore_patterns("build", "design"))
    space = Space(*CANVAS, 60)
    view = rig.view()
    track = Animated("string", tuple(Waypoint(i, p, Interp.CONSTANT) for i, p in enumerate(poses)))
    attachments = hand_attachments(view, space, {bone: track}) or None
    built = build_character(rig, None, space, file_prefix="char", attachments=attachments)
    place = Group(
        "place",
        transform=Transform(
            offset=Vec((ROOT[0] - CANVAS[0] / 2) / 60, (CANVAS[1] / 2 - ROOT[1]) / 60)
        ),
        children=[built.group],
    )
    canvas = Canvas(
        width=CANVAS[0], height=CANVAS[1], fps=24, frames=len(poses), ppu=60,
        layers=[place], bones=built.bones,
    )  # fmt: skip
    files = render_frames(canvas.save(tmp_path / "hands.sif"), tmp_path / "out")
    return [np.asarray(Image.open(f).convert("RGB")).astype(int) for f in files]


def wrist_canvas(rig: Rig, bone: str) -> tuple[float, float, float]:
    view = rig.view()
    hand = view["hands"][bone]
    part = view["parts"][hand["part"]]
    joint = world_pose(view)[bone][0]
    return (
        ROOT[0] + joint.x + hand["wrist_px"][0] - part["pivot_px"][0],
        ROOT[1] - joint.y + hand["wrist_px"][1] - part["pivot_px"][1],
        hand["size_px"],
    )


def cut_hand_peeking(rig: Rig, tmp_path: Path, bone: str) -> dict[str, int]:
    """Per drawn pose: how many pixels near the wrist change when the cut hand is erased from the
    forearm image, i.e. cut-hand pixels that show beside or under the drawn hand."""
    view = rig.view()
    hand = view["hands"][bone]
    part = view["parts"][hand["part"]]
    hidden = tmp_path / "hidden_rig"
    shutil.copytree(rig.folder, hidden, ignore=shutil.ignore_patterns("build", "design"))
    img = np.array(Image.open(hidden / part["file"]).convert("RGBA"))
    ys, xs = np.mgrid[0 : img.shape[0], 0 : img.shape[1]]
    d = math.radians(view["bones"][bone]["direction_deg"])
    beyond = (xs - hand["wrist_px"][0]) * math.cos(d) - (ys - hand["wrist_px"][1]) * math.sin(d) > 0
    img[beyond, 3] = 0
    Image.fromarray(img).save(hidden / part["file"])
    poses = ["rest", *DRAWN]
    shown = render_poses(rig, tmp_path / "shown", bone, poses)
    gone = render_poses(Rig(rig.data, hidden), tmp_path / "gone", bone, poses)
    x, y, size = wrist_canvas(rig, bone)
    yy, xx = np.mgrid[0 : CANVAS[1], 0 : CANVAS[0]]
    near = np.hypot(xx - x, yy - y) < 1.6 * size
    counts = {
        p: int(((np.abs(a - b).sum(axis=2) > 30) & near).sum())
        for p, a, b in zip(poses, shown, gone, strict=True)
    }
    assert counts["rest"] > 300, counts  # the cut hand is there to be covered
    return counts


def check_poses_differ_in_the_hand_area(rig: Rig, plain: Rig, tmp_path: Path, bone: str) -> None:
    counts = cut_hand_peeking(rig, tmp_path / "peek", bone)
    for pose in DRAWN:
        assert counts[pose] <= 0.01 * counts["rest"], (pose, counts)  # none of the cut hand shows
    poses = ["rest", *DRAWN]
    frames = render_poses(rig, tmp_path / "hands", bone, poses)
    # `rest` with the switch in the scene is exactly the render of the rig without hands
    (nothing,) = render_poses(plain, tmp_path / "plain", bone, ["rest"])
    assert np.array_equal(frames[0], nothing)
    x, y, size = wrist_canvas(rig, bone)
    for i in range(1, len(frames)):
        diff = np.abs(frames[i] - frames[0]).sum(axis=2) > 30
        assert diff.sum() > 150, poses[i]  # a drawn hand shows
        ys, xs = np.nonzero(diff)
        assert xs.min() >= x - 2.3 * size and xs.max() <= x + 2.3 * size, poses[i]
        assert ys.min() >= y - 1.3 * size and ys.max() <= y + 2.6 * size, poses[i]
        for j in range(i + 1, len(frames)):
            assert (np.abs(frames[i] - frames[j]).sum(axis=2) > 30).sum() > 60, (poses[i], poses[j])


@pytest.mark.render
@SYNFIG
def test_pips_poses_differ_in_the_hand_area_and_rest_is_todays_render(tmp_path: Path) -> None:
    check_poses_differ_in_the_hand_area(
        pip_with_hands(), load_rig(PIP / "rig.json"), tmp_path, "forearm_l"
    )


@pytest.mark.render
@SYNFIG
def test_the_fox_poses_differ_in_the_hand_area(tmp_path: Path) -> None:
    from test_puppet_build import sheet

    from studio_core.film import Film
    from studio_core.models import load_manifest
    from studio_core.puppet.build import build_puppet

    root = tmp_path / "foxfilm"
    Film.create(root, "storybook", load_manifest())
    design = root / "characters" / "kit" / "design"
    (design / "c1").mkdir(parents=True)
    sheet().save(design / "c1" / "sheet.png")
    candidate = {
        "id": "c1", "description": "a small fox with a scarf", "seed": 1, "fast": False,
        "sheet": "c1/sheet.png", "ok": True, "problems": [],
    }  # fmt: skip
    (design / "candidates.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "character": "kit",
                "style": "storybook",
                "chosen": "c1",
                "candidates": [candidate],
            }
        )
    )
    built = build_puppet(root, "kit", name="Kit", sam=False, three_quarter="sheet")
    plain = load_rig(built.rig_path)
    rig = Rig(add_hands(plain), plain.folder)
    assert validate("rig", rig.data) == []
    check_poses_differ_in_the_hand_area(rig, plain, tmp_path, "forearm_l")
