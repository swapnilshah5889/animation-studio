"""A character moving across the frame (placement path) and walking while it does (task 4B.6)."""

import itertools
import json
import math
from pathlib import Path

import pytest
from PIL import Image
from test_rig import COLORS, synthetic_rig
from test_scene import centroid_x, needs_synfig, stripe_background
from test_shot import make_film

from studio_core import placement
from studio_core import shot_spec as ss
from studio_core.config import REPO_ROOT
from studio_core.motions import animate
from studio_core.motions.library import MAX_STRIDE, STRIDE, foot_angle, stride_plan
from studio_core.rig import build_character, ground_offset_px, load_rig, world_pose
from studio_core.scene import DESIGN, PlacedCharacter, build_scene, load_background
from studio_core.schema import validate
from studio_core.shot import build_shot, render_shot
from studio_core.sif import Angle
from studio_core.sif.render import render_frames
from studio_core.sif.units import frames

PIP = REPO_ROOT / "tests" / "fixtures" / "characters" / "pip" / "rig.json"
SHOT = "s01_sh01"
WALK = [{"motion": "walk_cycle", "start_s": 0}]


def path_to(x: float, seconds: float = 4.0, ease: str = "ease_in_out") -> list[dict]:
    return [{"time_s": seconds, "position": [x, 0.9], "ease": ease}]


# --------------------------------------------------------------------------- the track itself


def test_position_follows_the_waypoints_with_each_easing() -> None:
    start = [0.2, 0.9]
    path = [
        {"time_s": 1, "position": [0.2, 0.9], "ease": "linear"},  # hold
        {"time_s": 3, "position": [0.6, 0.9], "ease": "linear"},
        {"time_s": 4, "position": [0.8, 0.8], "ease": "ease_in_out"},
    ]
    at = placement.position_at
    assert at(start, path, 0.5) == (0.2, 0.9)
    assert at(start, path, 2) == pytest.approx((0.4, 0.9))
    assert at(start, path, 3.5) == pytest.approx((0.7, 0.85))
    assert at(start, path, 9) == (0.8, 0.8)
    assert at(start, [], 1) == (0.2, 0.9)
    # ease_in is slow first, ease_out is slow last, ease_in_out is both, linear is neither
    for name, quarter in (("linear", 0.25), ("ease_in", 0.0625), ("ease_out", 0.4375)):
        assert placement.ease(name, 0.25) == pytest.approx(quarter)
    assert placement.ease("ease_in_out", 0.25) < 0.25 < placement.ease("ease_in_out", 0.75) - 0.5


def test_schema_and_semantic_checks_of_the_path() -> None:
    def spec(path: list[dict]) -> dict:
        char = {"id": "pip", "position": [0.2, 0.9], "path": path}
        return {"id": SHOT, "duration_s": 4, "background": "meadow", "characters": [char]}

    assert validate("shot", spec(path_to(0.8))) == []
    assert validate("shot", spec(path_to(0.8, 4.5)))  # past the end of the 4 s shot
    assert validate("shot", spec([*path_to(0.8, 3), *path_to(0.9, 2)]))  # not in time order
    assert validate("shot", spec([*path_to(0.8, 3), *path_to(0.9, 3)]))  # same time twice
    assert validate("shot", spec(path_to(0.8, 0)))  # must start after 0
    assert validate("shot", spec(path_to(2.5)))  # nowhere near the frame
    assert validate("shot", spec(path_to(0.8, ease="bounce")))


def test_a_shot_without_a_path_is_unchanged() -> None:
    char = {"id": "pip", "position": [0.5, 0.9]}
    assert (
        validate("shot", {"id": SHOT, "duration_s": 2, "background": "m", "characters": [char]})
        == []
    )
    positions = placement.frame_positions([0.5, 0.9], [], 24, 48)
    assert set(positions) == {(0.5, 0.9)}


def test_facing_follows_travel_only_while_walking() -> None:
    path = [
        {"time_s": 1, "position": [0.8, 0.9], "ease": "linear"},
        {"time_s": 2, "position": [0.2, 0.9], "ease": "linear"},
    ]
    pos = placement.frame_positions([0.2, 0.9], path, 24, 48)
    walking = placement.walking_frames([{"motion": "walk_cycle", "start_s": 0}], 24, 48)
    face = placement.facing_frames("right", pos, walking)
    assert face[0] == "right" and face[10] == "right" and face[30] == "left"
    glide = placement.facing_frames("right", pos, [False] * 48)
    assert set(glide) == {"right"}
    # forward travel counts only distance in the facing direction, in art px
    travel = placement.forward_travel(pos, face, width_px=1920, height_px=1080, scale=2.0)
    assert travel[24] == pytest.approx(0.6 * 1920 / 2.0, rel=0.02)
    assert travel[-1] > travel[24]  # keeps counting on the way back, facing left


def test_move_character_verb(tmp_path: Path) -> None:
    film = ss.FilmFolder.open(make_film(tmp_path / "films" / "demo").parent, "demo")
    ss.create_shot(film, SHOT, 6, "meadow")
    ss.place_character(film, SHOT, "pip", [0.2, 0.9])
    ss.move_character(film, SHOT, "pip", [0.8, 0.9], 1, 2)
    path = ss.load(film, SHOT)["characters"][0]["path"]
    assert [(k["time_s"], k["position"]) for k in path] == [(1, [0.2, 0.9]), (3, [0.8, 0.9])]
    ss.move_character(film, SHOT, "pip", [0.5, 0.8], 4, 1, "linear")  # a hold, then a move
    path = ss.load(film, SHOT)["characters"][0]["path"]
    assert [k["time_s"] for k in path] == [1, 3, 4, 5]
    assert path[2]["position"] == [0.8, 0.9]
    with pytest.raises(ss.SpecError, match="still moving until 5s"):
        ss.move_character(film, SHOT, "pip", [0.1, 0.9], 2, 1)
    with pytest.raises(ss.SpecError, match="unknown ease 'bounce'"):
        ss.move_character(film, SHOT, "pip", [0.1, 0.9], 5, 1, "bounce")
    with pytest.raises(ss.SpecError, match="past the 6s shot"):
        ss.move_character(film, SHOT, "pip", [0.1, 0.9], 5.5, 1)
    with pytest.raises(ss.SpecError, match="not in shot"):
        ss.move_character(film, SHOT, "kit", [0.1, 0.9], 5, 0.5)
    assert len(ss.load(film, SHOT)["characters"][0]["path"]) == 4  # refusals saved nothing
    removed, _ = ss.remove_item(film, SHOT, "movement", character_id="pip")
    assert len(removed["path"]) == 4 and "path" not in ss.load(film, SHOT)["characters"][0]


# --------------------------------------------------------------------------- the gait


def test_stride_plan_and_foot_angle() -> None:
    steps, stride = stride_plan(1152, 236)  # 0.6 of 1920 px
    assert steps == 6 and stride == pytest.approx(192) and stride / 236 <= MAX_STRIDE
    assert stride_plan(50, 236)[0] == 1  # a short move is one stride, never zero
    assert stride_plan(5000, 236)[1] / 236 <= MAX_STRIDE
    assert STRIDE < MAX_STRIDE
    # the angle that puts a foot (offset 0, 100 below the hip) 50 px ahead: asin(0.5) = 30 deg
    assert foot_angle(0, 100, 50, -35, 35) == pytest.approx(30, abs=1e-6)
    assert foot_angle(0, 100, 99, -35, 35) == 35  # clamped to the joint limit


def pip_walk(x1: float = 0.8, seconds: float = 4.0, ease: str = "ease_in_out"):
    """Pip's tracks and per-frame forward travel for a walk from x=0.2 to x1, at scale 1."""
    view = load_rig(PIP).view()
    fps, n = 24, frames(seconds, 24) + 12
    path = [{"time_s": seconds, "position": [x1, 0.9], "ease": ease}]
    pos = placement.frame_positions([0.2, 0.9], path, fps, n)
    face = placement.facing_frames("right", pos, placement.walking_frames(WALK, fps, n))
    travel = placement.forward_travel(pos, face, width_px=1920, height_px=1080, scale=1.0)
    anim = animate(view, WALK, fps=fps, n_frames=n, travel=travel)
    return view, anim, travel, n


def foot_world(view: dict, anim, side: str, f: int) -> tuple[float, float]:
    """The bottom-centre of the shin on one side at frame f, root at x = 0 (FK from the rig)."""
    offsets = {b: a.waypoints for b, a in anim.angles.items()}
    angles = {}
    for bone, wps in offsets.items():
        before = [w for w in wps if w.frame <= f]
        angles[bone] = before[-1].value.degrees if before else 0.0
    pose = world_pose(view, angles)
    joint, direction = pose[f"shin_{side[0]}"]
    shin = view["parts"][f"shin_{side[0]}"]
    reach = shin["size_px"][1] - shin["pivot_px"][1]
    r = math.radians(direction)
    shift = {w.frame: w.value.y for w in anim.shifts[f"thigh_{side[0]}"].waypoints}
    lift = shift.get(f, 0.0)  # the swinging leg is raised by shifting its thigh joint
    return joint.x + reach * math.cos(r), joint.y + reach * math.sin(r) + lift


def test_planted_feet_do_not_slide_in_the_rig(tmp_path: Path) -> None:
    view, anim, travel, n = pip_walk()
    assert isinstance(anim.angles["thigh_l"].waypoints[0].value, Angle)
    drop = {w.frame: w.value.y for w in anim.shifts["torso"].waypoints}
    low = foot_world(view, anim, "left", 0)[1]  # the foot at rest, on the ground
    slide, planted_frames = 0.0, 0
    for f in range(n - 1):
        for side in ("left", "right"):
            x0, y0 = foot_world(view, anim, side, f)
            x1, y1 = foot_world(view, anim, side, f + 1)
            # on the ground = at rest height after the body drops by `drop`
            on_ground = (
                abs(y0 + drop.get(f, 0.0) - low) < 0.5
                and abs(y1 + drop.get(f + 1, 0.0) - low) < 0.5
            )
            if on_ground and (x0 != x1 or travel[f] != travel[f + 1]):
                # the foot's world x is the hip's travel + its offset from the hip
                slide = max(slide, abs((travel[f + 1] + x1) - (travel[f] + x0)))
                planted_frames += 1
    assert planted_frames > 50
    assert slide < 0.3, slide  # art px (about a tenth of a pixel in 640x360)


def test_without_travel_walk_cycle_still_marches_in_place() -> None:
    view = load_rig(PIP).view()
    a = animate(view, WALK, fps=24, n_frames=96)
    b = animate(view, WALK, fps=24, n_frames=96, travel=[0.0] * 96)
    assert {k: v.waypoints for k, v in a.angles.items()} == {
        k: v.waypoints for k, v in b.angles.items()
    }
    assert len(a.shifts["thigh_l"].waypoints) < 20  # a few march keys, not one per frame


def test_the_walk_starts_and_ends_at_rest_and_steps_with_the_distance() -> None:
    _view, anim, _travel, _n = pip_walk()
    for bone in ("thigh_l", "thigh_r"):
        wps = anim.angles[bone].waypoints
        assert wps[0].value.degrees == pytest.approx(0, abs=1e-6)
        assert wps[-1].value.degrees == pytest.approx(0, abs=1e-6)

    # a longer move takes more steps: count sign changes of the left thigh
    def swings(x1: float) -> int:
        a = pip_walk(x1)[1].angles["thigh_l"].waypoints
        vals = [w.value.degrees for w in a]
        return sum(1 for p, q in itertools.pairwise(vals) if p * q < 0)

    assert swings(0.8) > swings(0.5) >= 1


# --------------------------------------------------------------------------- renders


@pytest.mark.render
@needs_synfig[1]
def test_placement_track_moves_the_character_in_the_render(tmp_path: Path) -> None:
    bg = load_background(stripe_background(tmp_path / "bg"))
    rig = load_rig(synthetic_rig(tmp_path / "synth", ["upper", "lower", "body"]))
    built = build_character(rig, None, DESIGN, file_prefix="synth")
    ground = ground_offset_px(rig.view())
    start, path = [0.2, 0.75], [{"time_s": 2, "position": [0.7, 0.6], "ease": "ease_in_out"}]
    track = placement.frame_positions(start, path, 24, 49)
    canvas = build_scene(
        fps=24,
        n_frames=49,
        background=bg,
        background_prefix="bg",
        characters=[PlacedCharacter(built, tuple(start), 1.0, "right", ground, track=track)],
    )
    sif = canvas.save(tmp_path / "c.sif")
    for f in (0, 10, 24, 40, 48):
        img = Image.open(
            render_frames(sif, tmp_path / f"f{f}", begin=f, end=f, size=(480, 270))[0]
        ).convert("RGB")
        x, y = placement.position_at(start, path, f / 24)
        assert abs(centroid_x(img, COLORS["body"]) - x * 480) < 1.5, f
        rows = [
            r
            for r in range(img.height)
            for c in range(0, 480)
            if all(
                abs(a - b) < 40 for a, b in zip(img.getpixel((c, r)), COLORS["lower"], strict=True)
            )
            and abs(c - x * 480) < 60
            and not 225 < c < 255  # the background's centre stripes
        ]
        assert abs(max(rows) + 1 - y * 270) < 1.5, f


def thin_legged_pip_film(root: Path) -> Path:
    """Pip with narrow red legs, so a rendered foot is a point (a wide foot's corner would shift
    as the leg tilts) on a plain white background."""
    film = make_film(root)
    for name, h in (("thigh", 130), ("shin", 150)):
        img = Image.new("RGBA", (64, h), (0, 0, 0, 0))
        img.paste((200, 0, 0, 255), (29, 0, 35, h))
        img.save(film / "characters" / "pip" / "parts" / f"{name}.png")
    bg = film / "backgrounds" / "plain"
    (bg / "layers").mkdir(parents=True)
    Image.new("RGBA", (1920, 1080), (255, 255, 255, 255)).save(bg / "layers" / "all.png")
    (bg / "layers.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "plain",
                "size_px": [1920, 1080],
                "backdrop": "#ffffff",
                "layers": [{"name": "all", "file": "layers/all.png", "parallax": 1.0}],
            }
        )
    )
    return film


def planted_feet(img: Image.Image, ground_y: int) -> list[float]:
    """x of each foot touching the ground line (red pixels in the last 2 rows above it)."""
    xs = sorted(
        x
        for y in range(ground_y - 2, ground_y)
        for x in range(img.width)
        if (p := img.getpixel((x, y)))[0] > 150 and p[1] < 110 and p[2] < 110
    )
    groups: list[list[int]] = []
    for x in xs:
        if groups and x - groups[-1][-1] <= 6:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [sum(g) / len(g) for g in groups]


def foot_slide(tmp_path: Path, actions: list[dict], x1: float, seconds: float, ease: str):
    """Render Pip walking (or gliding) from x=0.2 to x1 at 640x360; return the largest
    frame-to-frame movement of the most still planted foot (px), and the body's travel (px)."""
    film = thin_legged_pip_film(tmp_path)
    spec = {
        "schema_version": 1,
        "id": SHOT,
        "duration_s": seconds + 0.5,
        "background": "plain",
        "characters": [
            {
                "id": "pip",
                "position": [0.2, 0.9],
                "path": path_to(x1, seconds, ease),
                "actions": actions,
            }
        ],
    }
    (film / "shots" / SHOT).mkdir(parents=True)
    (film / "shots" / SHOT / "shot.json").write_text(json.dumps(spec))
    out = render_shot(film, SHOT, size=(640, 360), audio=False)
    feet = [planted_feet(Image.open(f).convert("RGB"), round(0.9 * 360)) for f in out.frames]
    worst, steps = 0.0, 0
    for a, b in itertools.pairwise(feet):
        pairs = [abs(p - q) for p in a for q in b if abs(p - q) < 12]
        if a and b and pairs:
            worst = max(worst, min(pairs))
            steps += 1
    return worst, steps, feet


@pytest.mark.render
@needs_synfig[1]
def test_pip_walks_across_the_frame_without_sliding(tmp_path: Path) -> None:
    worst, steps, feet = foot_slide(tmp_path, WALK, 0.8, 4.0, "ease_in_out")
    assert steps > 80
    assert worst <= 1.0, worst  # px at 640x360; a gliding body moves 4-6 px per frame
    # the walk really crossed the frame: feet ended near x = 0.8 * 640
    assert abs(feet[-1][0] - 0.8 * 640) < 20, feet[-1]


@pytest.mark.render
@needs_synfig[1]
def test_gliding_without_a_walk_slides_so_the_measure_can_fail(tmp_path: Path) -> None:
    worst, _, _ = foot_slide(tmp_path, [], 0.8, 2.0, "linear")
    assert worst > 4, worst


def test_a_walk_to_the_left_turns_the_character_around(tmp_path: Path) -> None:
    film = make_film(tmp_path)
    char = {"id": "pip", "position": [0.8, 0.9], "path": path_to(0.2), "actions": WALK}
    spec = {"schema_version": 1, "id": SHOT, "duration_s": 4, "background": "meadow"}
    spec["characters"] = [char]
    world = build_shot(film, spec).canvas.layers[1]
    place = next(g for g in world.children[-2].children if g.desc.startswith("place"))
    scale = place.transform.scale
    assert [w.value.x < 0 for w in scale.waypoints] == [True]  # faces left from the first frame
    still = {**spec, "characters": [{**char, "actions": []}]}  # gliding keeps the base facing
    world = build_shot(film, still).canvas.layers[1]
    place = next(g for g in world.children[-2].children if g.desc.startswith("place"))
    assert place.transform.scale.x > 0
