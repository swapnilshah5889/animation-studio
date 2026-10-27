"""studio_core.preview.sweep: the frame checks on synthetic frames (each defect type is caught,
and a clean figure and legitimate silhouette features are not), the extreme-frame sampling, and
a fast sweep of the Pip fixture character through the Synfig backend (CPU)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from studio_core.motions.timeline import Clip, Key
from studio_core.preview.sweep import (
    SENTINEL,
    Thresholds,
    check_frame,
    extreme_frames,
    motion_variants,
    scratch_film,
    sweep_character,
)
from studio_core.rig import load_rig
from studio_core.sif import Vec

FIXTURES = Path(__file__).parent / "fixtures"
BODY = (200, 120, 90)


def frame() -> np.ndarray:
    """A 960x540 magenta backdrop with a clean figure: body, head and two arms touching it."""
    img = np.empty((540, 960, 3), dtype=np.uint8)
    img[:] = SENTINEL
    for x0, y0, x1, y1 in (
        (420, 200, 540, 420),  # body
        (440, 120, 520, 200),  # head
        (380, 210, 420, 330),  # arm, touching the body
        (540, 210, 580, 330),
        (420, 420, 470, 500),  # legs with a wide gap
        (490, 420, 540, 500),
    ):
        img[y0:y1, x0:x1] = BODY
    return img


def kinds(img: np.ndarray) -> list[str]:
    return sorted(d.kind for d in check_frame(img))


def test_a_clean_figure_passes():
    assert check_frame(frame()) == []


def test_an_enclosed_hole_is_caught():
    img = frame()
    img[300:308, 470:478] = SENTINEL  # a hole in the body
    assert kinds(img) == ["hole"]


def test_a_large_gap_in_the_pose_is_not_a_hole():
    img = frame()
    img[240:360, 440:520] = SENTINEL  # 20% of the figure: an enclosed pose gap, not a defect
    assert kinds(img) == []


def test_an_enclosed_sliver_is_a_seam():
    img = frame()
    img[250:290, 480:482] = SENTINEL  # 2 px wide, 40 long, in the middle of the body
    assert kinds(img) == ["seam"]


def test_a_long_open_slit_is_a_seam_and_a_notch_is_not():
    img = frame()
    img[330:420, 478:480] = SENTINEL  # a slit from the legs' gap up into the body: 90 long
    assert kinds(img) == ["seam"]
    img = frame()
    img[350:352, 420:432] = SENTINEL  # a short notch in the body's side
    assert kinds(img) == []


def test_a_detached_piece_is_caught_and_a_speck_is_not():
    img = frame()
    img[300:330, 700:730] = BODY  # a part floating away from the body
    assert kinds(img) == ["detached"]
    img = frame()
    img[300:304, 700:704] = BODY
    assert kinds(img) == []


def test_a_part_touching_the_body_is_not_detached():
    img = frame()
    img[330:360, 380:420] = BODY  # a hand hanging off the arm
    assert kinds(img) == []


def test_thresholds_are_in_the_report_and_change_the_verdict():
    img = frame()
    img[300:308, 470:478] = SENTINEL
    assert check_frame(img, Thresholds(hole_min_px=200)) == []


def test_extreme_frames_are_where_each_channel_peaks():
    clip = Clip(
        "wave",
        0,
        20,
        {
            ("angle", "arm"): [Key(0, 0.0), Key(5, 90.0), Key(10, -20.0), Key(20, 0.0)],
            ("shift", "hip"): [Key(0, Vec(0, 0)), Key(8, Vec(3, -4)), Key(20, Vec(0, 0))],
            ("angle", "still"): [Key(0, 5.0), Key(20, 5.0)],
        },
    )
    found = extreme_frames(clip)
    assert found[5] == ["arm angle max"] and found[10] == ["arm angle min"]
    assert "hip shift x max" in found[8] and "hip shift y min" in found[8]
    assert all("still" not in r for rs in found.values() for r in rs)


def test_every_motion_the_rig_can_do_is_swept_per_side():
    view = load_rig(FIXTURES / "characters" / "pip" / "rig.json").view()
    labels = [label for label, _, _ in motion_variants(view)]
    assert "blink" not in labels
    assert {"wave[left]", "wave[right]", "walk_cycle", "jump"} <= set(labels)


def test_pip_sweep_renders_and_checks_frames(tmp_path):
    film = scratch_film(tmp_path, {"pip": FIXTURES / "characters" / "pip"})
    report = sweep_character(film, "pip", views=["front"], only_motions=["nod"], size=(480, 270))
    assert report.results, "no extreme frame was rendered"
    assert {r.motion for r in report.results} == {"nod"}
    assert all(r.view == "front" for r in report.results)
    for d in report.defects:  # a defect names its character, view, motion and frame
        assert d.message().startswith(f"pip front nod frame {d.frame}:")
    assert "front nod" in report.to_json()["counts"]
