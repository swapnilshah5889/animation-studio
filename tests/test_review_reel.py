"""scripts/review_reel.py: the pure parts (beat plan, captions, crop box) without any render."""

from __future__ import annotations

import importlib.util
import itertools
import sys
from pathlib import Path

from PIL import Image

from studio_core.face import EXPRESSIONS
from studio_core.motions import MOTIONS

SCRIPT = Path(__file__).parent.parent / "scripts" / "review_reel.py"
spec = importlib.util.spec_from_file_location("review_reel", SCRIPT)
reel = importlib.util.module_from_spec(spec)
sys.modules["review_reel"] = reel
spec.loader.exec_module(reel)


def test_beats_cover_everything_the_task_lists() -> None:
    names = {b.name for b in reel.plan_beats(hands=True)}
    assert set(EXPRESSIONS) <= names
    assert set(MOTIONS) - {"idle_breathe", "blink"} <= names
    hands = [b.name for b in reel.plan_beats(hands=True) if b.kind == "hand"]
    assert hands == list(reel.HAND_POSES)
    assert not [b for b in reel.plan_beats(hands=False) if b.kind == "hand"]


def test_beats_are_back_to_back_and_fit_a_shot() -> None:
    beats = reel.plan_beats(hands=True)
    assert beats[0].start_s == 0
    for a, b in itertools.pairwise(beats):
        assert abs(a.end_s - b.start_s) < 1e-6
    assert beats[-1].end_s <= 60  # the shot schema's maximum


def test_shared_beats_start_at_the_same_time_in_both_videos() -> None:
    plain = reel.plan_beats(hands=False)
    with_hands = reel.plan_beats(hands=True)
    assert [(b.label, b.start_s) for b in plain] == [
        (b.label, b.start_s) for b in with_hands[: len(plain)]
    ]


def test_beat_at_and_key_time_stay_inside_the_beat() -> None:
    beats = reel.plan_beats(hands=True)
    for b in beats:
        assert reel.beat_at(beats, b.start_s) is b
        assert b.start_s < reel.key_time(b) < b.end_s
    assert reel.beat_at(beats, 999) is beats[-1]


def test_caption_names_the_view_and_the_march() -> None:
    walk = next(b for b in reel.plan_beats(hands=False) if b.kind == "walk")
    assert "marches in place" in reel.caption_text("kit", "default", "front", walk)
    text = reel.caption_text("kit", "4b-options", "three_quarter", walk)
    assert "three-quarter" in text and "marches" not in text


def test_character_box_has_even_sides(tmp_path: Path) -> None:
    blank = Image.new("RGB", (200, 100), (10, 10, 10))
    frame = blank.copy()
    frame.paste((250, 250, 250), (50, 20, 73, 41))  # 23 x 21: odd
    blank.save(tmp_path / "b.png")
    frame.save(tmp_path / "f.png")
    x0, y0, x1, y1 = reel.character_box([tmp_path / "f.png"], tmp_path / "b.png", margin=5)
    assert (x1 - x0) % 2 == 0 and (y1 - y0) % 2 == 0
    assert x0 <= 50 and y0 <= 20 and x1 >= 72 and y1 >= 40
