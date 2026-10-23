"""The pure parts of scripts/preview_background.py: the hole counter, the camera and edge
geometry, the sentinel colour and the probe copy. The render itself is checked by running the
script (owner checkpoint 4); no test here renders."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from preview_background import (
    PIXEL_TOL,
    SENTINELS,
    EdgeEntry,
    Hole,
    LayerArt,
    Report,
    camera_poses,
    edge_entries,
    edge_slack,
    find_hole,
    hex_rgb,
    inspect_layer,
    key_indices,
    make_probe,
    near_colour,
    pick_sentinel,
    probe_id,
    sample_indices,
    spare_px,
    summary_lines,
)

from studio_core.scene import PAN_PX, SceneError, load_background

MEADOW = Path(__file__).parent / "fixtures" / "backgrounds" / "meadow"
FPS = 24
PAN_RIGHT = {"move": "slow_pan_right"}


def art(
    name: str = "layer",
    parallax: float = 1.0,
    size: tuple[int, int] = (2880, 1080),
    drawn: bool = True,
    clashes: frozenset[str] = frozenset(),
) -> LayerArt:
    return LayerArt(
        name, parallax, size, dict.fromkeys(("left", "right", "top", "bottom"), drawn), clashes
    )


# --------------------------------------------------------------------------- the hole counter


def test_find_hole_counts_the_sentinel_pixels_and_boxes_them() -> None:
    frame = np.full((20, 30, 3), (40, 120, 60), dtype=np.uint8)
    assert find_hole(frame, hex_rgb("#ff00ff"), PIXEL_TOL) is None
    frame[5:9, 22:30] = (255, 0, 255)  # 4 rows x 8 columns against the right edge
    assert find_hole(frame, hex_rgb("#ff00ff"), PIXEL_TOL, frame=7) == Hole(7, 32, (22, 5, 30, 9))


def test_find_hole_matches_within_the_tolerance_only() -> None:
    frame = np.full((4, 4, 3), (250, 4, 252), dtype=np.uint8)  # a few levels off pure magenta
    assert find_hole(frame, (255, 0, 255), tol=6) is not None
    assert find_hole(frame, (255, 0, 255), tol=3) is None  # antialiased blends aren't holes
    assert find_hole(np.full((4, 4, 3), 255, dtype=np.uint8), (255, 0, 255), tol=6) is None


def test_near_colour_does_not_wrap_around_uint8() -> None:
    rgb = np.array([[[255, 0, 255], [0, 255, 0]]], dtype=np.uint8)
    assert near_colour(rgb, (0, 255, 0), tol=0).tolist() == [[False, True]]


def test_sampled_frames_include_the_key_frames_and_the_last_frame() -> None:
    assert key_indices(144) == [0, 36, 72, 107, 143]  # start, 1/4, 1/2, 3/4, end
    picked = sample_indices(144, every=4)
    assert picked[0] == 0 and picked[-1] == 143 and 107 in picked
    assert picked == sorted(set(picked))
    assert sample_indices(10, every=100) == [0, 2, 4, 7, 9]  # the key frames and nothing else
    with pytest.raises(ValueError, match="at least 1"):
        sample_indices(10, every=0)


# --------------------------------------------------------------------------- the camera


def test_slow_pan_runs_from_rest_to_the_pan_distance_without_going_back() -> None:
    poses = camera_poses(PAN_RIGHT, FPS, 144)
    pans = [pan for pan, _ in poses]
    assert pans[0] == 0 and pans[-1] == PAN_PX
    assert pans == sorted(pans)
    assert {zoom for _, zoom in poses} == {1.0}
    left = camera_poses({"move": "slow_pan_left"}, FPS, 144)
    assert left[-1][0] == -PAN_PX


def test_static_camera_and_zoom_moves() -> None:
    assert camera_poses(None, FPS, 5) == [(0.0, 1.0)] * 5
    assert camera_poses({"move": "static", "zoom": 1.5}, FPS, 3) == [(0.0, 1.5)] * 3
    push = camera_poses({"move": "push_in"}, FPS, 48)
    assert push[0] == (0.0, 1.0) and push[-1][1] == pytest.approx(1.25)


def test_a_late_pan_holds_still_until_it_starts() -> None:
    poses = camera_poses({"move": "slow_pan_right", "start_s": 1.0}, FPS, 72)
    pans = [pan for pan, _ in poses]
    assert pans[:25] == [0.0] * 25 and pans[-1] == PAN_PX


# --------------------------------------------------------------------------- the edges


def test_edge_slack_for_a_wide_layer_during_the_default_pan() -> None:
    slack = edge_slack((2880, 1080), 1.4, pan=PAN_PX, zoom=1.0)
    assert slack["left"] == pytest.approx(1440 + 336 - 960)
    assert slack["right"] == pytest.approx(1440 - 336 - 960)  # 144 px to spare
    assert slack["top"] == slack["bottom"] == 0  # 1080 px tall = an exact fit


def test_zooming_out_shows_the_top_and_bottom_edges() -> None:
    slack = edge_slack((2880, 1080), 1.0, pan=0, zoom=0.8)
    assert slack["top"] == slack["bottom"] == pytest.approx(540 - 675)


def test_a_layer_as_wide_as_the_frame_shows_its_edge_as_soon_as_the_pan_moves() -> None:
    poses = camera_poses(PAN_RIGHT, FPS, 144)
    (entry,) = edge_entries([art("meadow", 1.0, size=(1920, 1080))], poses)
    assert (entry.layer, entry.side, entry.drawn) == ("meadow", "right", True)
    assert 0 < entry.first_frame < 20 and entry.worst_px == pytest.approx(PAN_PX)
    assert edge_entries([art("meadow", 1.0)], poses) == []  # 2880 px has the room


def test_the_pan_direction_decides_which_edge_enters() -> None:
    left = camera_poses({"move": "slow_pan_left"}, FPS, 144)
    (entry,) = edge_entries([art(size=(1920, 1080))], left)
    assert entry.side == "left"


def test_the_nearest_layers_run_out_of_room_first() -> None:
    poses = camera_poses(PAN_RIGHT, FPS, 144)
    spare = {p: spare_px(art(parallax=p), poses) for p in (0.0, 1.0, 2.0, 2.5)}
    assert spare == {0.0: 480, 1.0: 240, 2.0: 0, 2.5: -120}  # 2880 px: safe up to parallax 2


def test_an_edge_without_art_along_it_is_harmless() -> None:
    poses = camera_poses(PAN_RIGHT, FPS, 144)
    entries = edge_entries([art("fg", 3.0, drawn=False)], poses)
    assert entries and not any(e.drawn for e in entries)
    assert not Report(10, [], entries).failed
    assert Report(10, [], [EdgeEntry("fg", "right", 4, 9.0, True)]).failed
    assert Report(10, [Hole(3, 1, (0, 0, 1, 1))], []).failed


# --------------------------------------------------------------------------- the art


def write_layer(
    path: Path, size: tuple[int, int], *pixels: tuple[int, int, tuple[int, ...]]
) -> None:
    """A transparent PNG with single pixels (x, y, rgba) drawn on it."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    for x, y, rgba in pixels:
        img.putpixel((x, y), rgba)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def test_inspect_layer_finds_where_the_art_touches_the_edges(tmp_path: Path) -> None:
    write_layer(tmp_path / "a.png", (40, 30), (0, 10, (9, 9, 9, 255)), (20, 29, (9, 9, 9, 5)))
    layer = {"name": "a", "file": "a.png", "parallax": 0.5}
    found = inspect_layer(layer, tmp_path, (40, 30))
    # Left column has art; the bottom pixel is too faint to count as drawn.
    assert found.visible_edges == {"left": True, "right": False, "top": False, "bottom": False}
    assert (found.name, found.parallax, found.size_px) == ("a", 0.5, (40, 30))


def test_inspect_layer_refuses_an_image_of_the_wrong_size(tmp_path: Path) -> None:
    write_layer(tmp_path / "a.png", (40, 30))
    layer = {"name": "a", "file": "a.png", "parallax": 1}
    with pytest.raises(SceneError, match=r"layer 'a' is 40x30 px .* every layer is 80x30"):
        inspect_layer(layer, tmp_path, (80, 30))


def test_art_that_contains_a_sentinel_colour_rules_it_out(tmp_path: Path) -> None:
    write_layer(tmp_path / "a.png", (8, 8), (3, 3, (255, 0, 255, 255)), (4, 4, (0, 255, 0, 0)))
    layer = {"name": "a", "file": "a.png", "parallax": 1}
    found = inspect_layer(layer, tmp_path, (8, 8))
    assert found.clashes == {"#ff00ff"}  # the transparent green pixel isn't art
    assert pick_sentinel([found]) == "#00ff00"
    assert pick_sentinel([art(clashes=frozenset(SENTINELS))]) is None
    assert pick_sentinel([art(), art()]) == SENTINELS[0]


def test_the_fixture_art_contains_its_own_backdrop_colour() -> None:
    """Why the render uses a probe backdrop: counting the real backdrop colour would report holes
    in a frame that has none."""
    background = load_background(MEADOW / "layers.json")
    sky = np.asarray(Image.open(MEADOW / "layers" / "sky.png").convert("RGBA"))
    drawn = sky[..., 3] >= 8
    backdrop = hex_rgb(background.data["backdrop"])
    assert near_colour(sky[..., :3][drawn], backdrop, PIXEL_TOL).sum() > 0


def test_the_fixture_has_room_for_the_default_pan() -> None:
    background = load_background(MEADOW / "layers.json")
    size = tuple(background.data["size_px"])
    arts = [inspect_layer(lay, MEADOW, size) for lay in background.data["layers"]]  # type: ignore[arg-type]
    poses = camera_poses(PAN_RIGHT, FPS, 144)
    assert edge_entries(arts, poses) == []
    assert [spare_px(a, poses) for a in arts] == [468, 396, 240, 144]
    assert pick_sentinel(arts) == "#ff00ff"


# --------------------------------------------------------------------------- the probe copy


def test_the_probe_copy_has_the_sentinel_backdrop_and_leaves_the_original_alone(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "backgrounds" / "meadow"
    folder.mkdir(parents=True)
    for layer in json.loads((MEADOW / "layers.json").read_text())["layers"]:
        (folder / layer["file"]).parent.mkdir(exist_ok=True)
        (folder / layer["file"]).write_bytes((MEADOW / layer["file"]).read_bytes())
    original = (MEADOW / "layers.json").read_text()
    (folder / "layers.json").write_text(original)

    probe = make_probe(load_background(folder / "layers.json"), "#00ff00")

    assert probe == tmp_path / "backgrounds" / "meadow_probe"
    copy = load_background(probe / "layers.json")  # a valid background, files and all
    assert copy.data["backdrop"] == "#00ff00" and copy.id == "meadow_probe"
    assert [lay["file"] for lay in copy.data["layers"]] == [
        lay["file"] for lay in json.loads(original)["layers"]
    ]
    assert (folder / "layers.json").read_text() == original


def test_the_probe_id_is_still_a_background_id() -> None:
    assert probe_id("meadow") == "meadow_probe"
    assert len(probe_id("a" * 40)) == 39


# --------------------------------------------------------------------------- the verdicts


def test_the_summary_says_ok_or_fails_with_the_worst_frame() -> None:
    clean = summary_lines(Report(38, [], []))
    assert all(line.startswith("ok") for line in clean) and "38 sampled frames" in clean[0]
    holes = [Hole(28, 100, (0, 0, 5, 20)), Hole(140, 6372, (76, 473, 1739, 546))]
    lines = summary_lines(Report(38, holes, [EdgeEntry("hills", "left", 7, 84.0, True)]))
    assert lines[0].startswith("FAIL holes in 2 of 38")
    assert "first at frame 28, worst at frame 140: 6372 px" in lines[0]
    assert any("'hills'" in line and "left edge" in line and "frame 7" in line for line in lines)
    note = summary_lines(Report(3, [], [EdgeEntry("fg", "right", 7, 9.0, False)]))
    assert note[0].startswith("ok") and note[-1].startswith("note")
