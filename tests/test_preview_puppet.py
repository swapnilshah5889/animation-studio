"""The pure parts of scripts/preview_puppet.py: the timeline, placement and key frames.
The render itself is checked by running the script (owner checkpoint 3)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from preview_puppet import (
    FPS,
    SUBJECT_AT,
    Timeline,
    key_frames,
    matched_scale,
    plan_actions,
    rest_box,
    screen_box,
    wave_side,
)

from studio_core.rig import load_rig
from studio_core.scene import DESIGN
from studio_core.shot_spec import SpecError
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
