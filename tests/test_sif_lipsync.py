import pytest

from studio_core.config import REPO_ROOT
from studio_core.sif.lipsync import load_cues, mouth_track

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "audio" / "pip_line_01.rhubarb.json"


def track(cues, **kw):  # (frame, shape) pairs for readable asserts
    return [(w.frame, w.value) for w in mouth_track(cues, 24, **kw).waypoints]


def test_cues_become_step_waypoints_on_frame_boundaries() -> None:
    cues = [
        {"start": 0.0, "end": 0.28, "value": "X"},
        {"start": 0.28, "end": 0.42, "value": "C"},  # 0.28 s * 24 = 6.72 -> frame 7
        {"start": 0.42, "end": 0.5, "value": "A"},  # 10.08 -> frame 11
    ]
    assert track(cues) == [(0, "X"), (7, "C"), (11, "A")]
    assert all(w.interp == "constant" for w in mouth_track(cues, 24).waypoints)


def test_same_frame_later_cue_wins_and_repeats_collapse() -> None:
    cues = [
        {"start": 0.0, "value": "X"},
        {"start": 0.50, "value": "B"},  # frame 12
        {"start": 0.51, "value": "D"},  # 12.24 -> frame 13
        {"start": 0.52, "value": "E"},  # 12.48 -> frame 13: wins over D
        {"start": 1.0, "value": "E"},  # same shape again: collapsed
    ]
    assert track(cues) == [(0, "X"), (12, "B"), (13, "E")]


def test_shape_map_and_start_offset() -> None:
    cues = [
        {"start": 0.0, "value": "X"},
        {"start": 1.0, "value": "C"},
        {"start": 2.0, "value": "A"},
    ]
    out = track(cues, start_frame=12, shape_map={"C": "E"})
    assert out == [(12, "X"), (36, "E"), (60, "A")]


def test_unknown_shape_rejected() -> None:
    with pytest.raises(ValueError):
        mouth_track([{"start": 0.0, "value": "Q"}], 24)


def test_real_rhubarb_fixture() -> None:
    wps = mouth_track(load_cues(FIXTURE), 24).waypoints
    frames = [w.frame for w in wps]
    assert frames == sorted(set(frames)) and frames[0] == 0
    assert wps[-1].value == "X" and frames[-1] < 5.6 * 24 + 1
