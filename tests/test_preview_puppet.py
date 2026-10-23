"""studio_core.preview.puppet: the timeline, placement, key frames and the refusals. The render
itself is checked by running scripts/preview_puppet.py (owner checkpoint 3); no test renders."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from studio_core.audio.voices import VoiceError
from studio_core.preview import PreviewError
from studio_core.preview.common import matched_scale, rest_box
from studio_core.preview.puppet import (
    PIP_AT,
    SUBJECT_AT,
    Timeline,
    arm_toward,
    facing_toward,
    key_frames,
    output_name,
    pick_view,
    plan_actions,
    preview_puppet,
    screen_box,
    wave_side,
)
from studio_core.rig import Rig, ground_offset_px, load_rig
from studio_core.scene import DESIGN
from studio_core.shot_spec import FPS, FilmFolder, SpecError, register_rig
from studio_core.sif import frames

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def pip() -> dict[str, Any]:
    return load_rig(FIXTURES / "characters" / "pip" / "rig.json").view()


def cues() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "audio" / "pip_line_01.rhubarb.json").read_text())["mouthCues"]


def scaled(view: dict[str, Any], k: float) -> dict[str, Any]:
    """The same rig drawn k times bigger."""
    big = copy.deepcopy(view)
    for part in big["parts"].values():
        part["size_px"] = [v * k for v in part["size_px"]]
        part["pivot_px"] = [v * k for v in part["pivot_px"]]
    for bone in big["bones"].values():
        if "attach" in bone:
            bone["attach"]["at_px"] = [v * k for v in bone["attach"]["at_px"]]
    return big


def kit_rig(front: dict[str, Any], three_quarter: dict[str, Any] | None = None) -> Rig:
    """A rig in memory (no files): the front view, and a three-quarter view if given."""
    views = {"front": front} | ({"three_quarter": three_quarter} if three_quarter else {})
    return Rig({"id": "kit", "default_view": "front", "views": views}, Path("."))


def test_duration_fits_the_line_and_rounds_up_to_half_seconds() -> None:
    tl = Timeline()
    assert tl.duration(2.18) == 7.0  # 3.6 + 2.18 + 1.2 = 6.98
    assert tl.duration(2.3) == 7.5
    assert tl.duration(0.5) == 6.0  # never shorter than the minimum
    for line_s in (0.5, 2.18, 3.0, 4.2):
        assert tl.nod_s(line_s) < tl.duration(line_s) - 0.8  # Pip's nod finishes in the shot


def test_matched_scale_makes_both_stand_equally_tall(pip: dict[str, Any]) -> None:
    assert matched_scale(pip, pip) == 1.0
    assert matched_scale(scaled(pip, 2), pip) == 0.5
    assert matched_scale(scaled(pip, 0.1), pip) == 3.0  # clamped to the shot schema's range


def test_screen_box_stands_on_the_feet(pip: dict[str, Any]) -> None:
    left, top, right, bottom = screen_box(pip, SUBJECT_AT, 0.8)
    assert bottom == pytest.approx(SUBJECT_AT[1] * DESIGN.height)
    _, low, _, high = rest_box(pip)
    assert bottom - top == pytest.approx((high - low) * 0.8)
    assert left < SUBJECT_AT[0] * DESIGN.width < right
    hl, ht, hr, hb = screen_box(pip, SUBJECT_AT, 0.8, part="head")
    assert left <= hl < hr <= right and top == pytest.approx(ht) and hb < bottom


def test_wave_side_prefers_the_arm_toward_pip(pip: dict[str, Any]) -> None:
    assert wave_side(pip) == "left"
    one_armed = copy.deepcopy(pip)
    del one_armed["bones"]["forearm_l"]
    assert wave_side(one_armed) == "right"
    del one_armed["bones"]["forearm_r"]
    with pytest.raises(SpecError, match="no arm"):
        wave_side(one_armed)


def test_key_frames_come_in_the_planned_order(pip: dict[str, Any]) -> None:
    tl = Timeline()
    line = cues()
    line_s = line[-1]["end"]
    n_frames = frames(tl.duration(line_s), FPS)
    subject, _ = plan_actions(tl, line_s, "left")
    keys = dict(key_frames(pip, subject, line, tl, n_frames))
    # The fixture line has no D (wide open), so the widest mouth it has is C.
    assert list(keys) == ["rest", "wave peak", "eyes closed", "mouth open (C)"]
    rest, peak, closed, mouth = keys.values()
    assert rest < frames(tl.wave_s, FPS) < peak < closed < frames(tl.talk_s, FPS) <= mouth
    assert mouth < frames(tl.talk_s + line_s, FPS)


def test_key_frames_refuse_a_line_that_never_opens_the_mouth(pip: dict[str, Any]) -> None:
    tl = Timeline()
    subject, _ = plan_actions(tl, 1.0, "left")
    closed = [{"start": 0.0, "end": 1.0, "value": "A"}]
    with pytest.raises(ValueError, match="never open"):
        key_frames(pip, subject, closed, tl, frames(tl.duration(1.0), FPS))


# --------------------------------------------------------------------------- views and facing


def test_output_folder_adds_the_view_except_for_front() -> None:
    assert output_name("step4-demo", "kit", "front") == "step4-demo-kit"
    assert output_name("step4-demo", "kit", "three_quarter") == "step4-demo-kit-three_quarter"


def test_pick_view_returns_that_view_or_names_the_views_the_rig_has(pip: dict[str, Any]) -> None:
    side = scaled(pip, 1.25)
    both = kit_rig(pip, side)
    assert pick_view(both, "front") is pip
    assert pick_view(both, "three_quarter") is side
    with pytest.raises(SpecError, match=r"kit has no three_quarter view \(its views: front\)"):
        pick_view(kit_rig(pip), "three_quarter")
    only_side = Rig(
        {"id": "kit", "default_view": "three_quarter", "views": {"three_quarter": side}}, Path(".")
    )
    with pytest.raises(SpecError, match="no front view"):  # explicit: never the default view
        pick_view(only_side, "front")


def test_the_puppet_faces_pip_and_waves_the_arm_on_his_side(pip: dict[str, Any]) -> None:
    assert facing_toward(SUBJECT_AT, PIP_AT) == "right"  # Kit stands left of Pip: art as drawn
    assert facing_toward(PIP_AT, SUBJECT_AT) == "left"  # standing to his right, it is mirrored
    # The character's left is on the viewer's right, so it is the arm toward Pip when unmirrored
    # and the far arm in the three-quarter view; mirrored, the viewer's right is its right.
    assert arm_toward("right") == "left" and arm_toward("left") == "right"
    assert wave_side(pip, arm_toward("left")) == "right"


def test_a_three_quarter_view_is_placed_by_its_own_size_and_feet(pip: dict[str, Any]) -> None:
    side = scaled(pip, 1.25)  # a taller three-quarter drawing of the same character
    assert matched_scale(side, pip) == 0.8
    assert ground_offset_px(side) == pytest.approx(ground_offset_px(pip) * 1.25)
    _, top, _, bottom = screen_box(side, SUBJECT_AT, 0.8)
    _, pip_top, _, pip_bottom = screen_box(pip, SUBJECT_AT, 1.0)
    assert bottom == pytest.approx(SUBJECT_AT[1] * DESIGN.height)  # feet on the ground
    assert bottom - top == pytest.approx(pip_bottom - pip_top)  # as tall as Pip on screen


def test_screen_box_mirrors_about_the_root_when_facing_left(pip: dict[str, Any]) -> None:
    left, top, right, bottom = screen_box(pip, SUBJECT_AT, 0.8, facing="right")
    mleft, mtop, mright, mbottom = screen_box(pip, SUBJECT_AT, 0.8, facing="left")
    root_x = SUBJECT_AT[0] * DESIGN.width
    assert (mtop, mbottom) == (top, bottom)
    assert mleft - root_x == pytest.approx(-(right - root_x))
    assert mright - root_x == pytest.approx(-(left - root_x))


# --------------------------------------------------------------------------- refusals


def files(root: Path) -> list[Path]:
    return sorted(root.rglob("*"))


@pytest.fixture
def empty_film(tmp_path: Path) -> FilmFolder:
    """A film folder with nothing in it: no Pip, no background, no voices."""
    (tmp_path / "films" / "demo").mkdir(parents=True)
    return FilmFolder.open(tmp_path / "films", "demo")


def test_a_character_without_a_rig_is_refused(empty_film: FilmFolder) -> None:
    with pytest.raises(PreviewError, match=r"kit has no rig at .* \(characters: none\)"):
        preview_puppet(empty_film, "kit")
    assert files(empty_film.root) == []


def test_pip_is_never_the_subject(empty_film: FilmFolder) -> None:
    register_rig(empty_film, "pip")
    with pytest.raises(PreviewError, match="Pip is the reference puppet"):
        preview_puppet(empty_film, "pip")


def test_a_character_without_a_voice_is_refused_before_anything_is_written(
    empty_film: FilmFolder,
) -> None:
    register_rig(empty_film, "kit")  # the placeholder puppet, without Pip's voice
    before = files(empty_film.root)
    with pytest.raises(PreviewError, match=r"kit has no voice yet; cast one first \(audio_mcp"):
        preview_puppet(empty_film, "kit")
    assert files(empty_film.root) == before  # no Pip, no meadow, no voice.json, no shot


def test_a_missing_view_or_background_is_refused_before_anything_is_written(
    empty_film: FilmFolder,
) -> None:
    register_rig(empty_film, "kit")
    before = files(empty_film.root)
    with pytest.raises(SpecError, match="kit has no three_quarter view"):
        preview_puppet(empty_film, "kit", view="three_quarter", cast_placeholder=True)
    with pytest.raises(PreviewError, match="no view 'side'"):
        preview_puppet(empty_film, "kit", view="side", cast_placeholder=True)
    with pytest.raises(SpecError, match="no background 'lake'"):
        preview_puppet(empty_film, "kit", background="lake", cast_placeholder=True)
    with pytest.raises(VoiceError, match="web or email address"):
        preview_puppet(empty_film, "kit", line="Visit www.example.com", cast_placeholder=True)
    assert files(empty_film.root) == before
