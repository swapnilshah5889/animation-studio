"""studio_core.qa: the code checks on synthetic frames (each defect is caught), the rubric
prompts and answer parsing, key-frame choice, and the runner with a fake model (no Ollama)."""

import json
from pathlib import Path

import numpy as np
import pytest
from test_shot import SPEC, make_film

from studio_core.config import load_config
from studio_core.qa import frame_checks, rubric, runner

W, H = 960, 540
MAGENTA = (255, 0, 255)


def backdrop() -> np.ndarray:
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = MAGENTA
    return img


def blob(img: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    img[y0:y1, x0:x1] = (200, 120, 40)
    return img


def kinds(findings: list[frame_checks.Finding]) -> set[str]:
    return {f.kind for f in findings}


def test_a_whole_character_in_the_frame_has_no_findings() -> None:
    assert frame_checks.probe_findings("pip", blob(backdrop(), 400, 100, 600, 500)) == []


def test_a_hole_in_the_figure_is_found() -> None:
    img = blob(backdrop(), 400, 100, 600, 500)
    img[250:270, 480:500] = MAGENTA  # a 20x20 hole
    assert "hole" in kinds(frame_checks.probe_findings("pip", img))


def test_a_narrow_slot_between_limbs_is_not_a_hole() -> None:
    img = blob(backdrop(), 400, 100, 600, 500)
    img[300:400, 495:507] = MAGENTA  # 12 x 100: the gap between two legs, closed at both ends
    assert "hole" not in kinds(frame_checks.probe_findings("pip", img))


def test_a_character_cut_off_by_the_frame_edge_is_found() -> None:
    found = frame_checks.probe_findings("pip", blob(backdrop(), 0, 100, 150, 500))
    assert kinds(found) == {"cropped"} and "left" in found[0].detail


def test_a_character_off_screen_is_missing() -> None:
    found = frame_checks.probe_findings("pip", backdrop())
    assert kinds(found) == {"missing"} and found[0].character == "pip"


def test_a_detached_piece_is_found() -> None:
    img = blob(backdrop(), 400, 100, 600, 500)
    blob(img, 700, 300, 760, 360)  # a hand floating away from the body
    assert "detached" in kinds(frame_checks.probe_findings("pip", img))


def test_a_black_frame_is_found_and_a_painted_one_is_not() -> None:
    assert kinds(frame_checks.black_frame(np.zeros((H, W, 3), np.uint8))) == {"black_frame"}
    assert frame_checks.black_frame(blob(backdrop(), 400, 100, 600, 500)) == []


def test_rubric_prompt_names_every_category_and_the_age() -> None:
    p = rubric.safety_prompt(text="The fox ran home.")
    assert "3 to 8" in p and "The fox ran home." in p
    assert all(c in p for c in rubric.SAFETY_CATEGORIES)
    assert "attached picture" in rubric.safety_prompt(has_image=True)


def test_shot_facts_pick_the_expression_and_motions_active_at_the_time() -> None:
    shot = {
        "background": "meadow",
        "camera": {"move": "static"},
        "characters": [
            {
                "id": "pip",
                "position": [0.3, 0.9],
                "actions": [
                    {"motion": "wave", "start_s": 1.0, "duration_s": 1.0},
                    {"motion": "blink", "start_s": 0.0},
                ],
                "expressions": [{"expr": "happy", "start_s": 0}, {"expr": "sad", "start_s": 2}],
            }
        ],
    }
    early = rubric.shot_facts(shot, 0.5)["characters"][0]
    assert early["motions"] == ["blink"] and early["expression"] == "happy"
    mid = rubric.shot_facts(shot, 1.5)["characters"][0]
    assert mid["motions"] == ["wave", "blink"]
    assert rubric.shot_facts(shot, 2.5)["characters"][0]["expression"] == "sad"
    prompt = rubric.frame_prompt(rubric.shot_facts(shot, 1.5), 1.5)
    assert "pip" in prompt and "wave" in prompt and "'meadow'" in prompt


def test_frame_answer_parsing_marks_a_character_the_model_skipped_as_missing() -> None:
    raw = json.dumps(
        {
            "description": "a meadow",
            "characters": [
                {"id": "pip", "present": True, "expression_plausible": True, "reason": "x"}
            ],
            "background_present": True,
            "background_reason": "green hills",
            "problems": [],
        }
    )
    parsed = rubric.parse_frame(raw, ["pip", "bunny"])
    assert [c["present"] for c in parsed["characters"]] == [True, False]
    with pytest.raises(rubric.ModelAnswerError):
        rubric.parse_frame("not json", ["pip"])


def test_safety_parsing_drops_unknown_categories() -> None:
    raw = json.dumps({"categories": ["violence", "banana"], "reasons": ["hits"], "unsure": False})
    assert rubric.parse_safety(raw) == (["violence"], ["hits"], False)


class FakeVision:
    model = "fake-vl"

    def __init__(self, answer: dict | str) -> None:
        self.answer = answer
        self.calls: list[str] = []
        self.unloaded = 0

    def ask(self, prompt: str, schema: dict, image_png: bytes | None) -> str:
        self.calls.append(prompt)
        return self.answer if isinstance(self.answer, str) else json.dumps(self.answer)

    def unload(self) -> None:
        self.unloaded += 1


def test_text_safety_combines_the_word_check_and_the_model() -> None:
    fine = FakeVision({"categories": [], "reasons": [], "unsure": False})
    assert runner.check_text_safety("The bunny hopped.", fine).ok
    # the blocklist alone is enough to refuse, even when the model likes the text
    bad = runner.check_text_safety("You stupid ass.", fine)
    assert not bad.ok and bad.blocked_words == ["ass"]
    # model hits are refused, and an unsure model asks for a human
    hit = FakeVision({"categories": ["violence"], "reasons": ["hitting"], "unsure": False})
    assert runner.check_text_safety("He hit him.", hit).categories == ["violence"]
    unsure = runner.check_text_safety(
        "Hmm.", FakeVision({"categories": [], "reasons": [], "unsure": True})
    )
    assert not unsure.ok and unsure.needs_human
    broken = runner.check_text_safety("Hmm.", FakeVision("nonsense"))
    assert not broken.ok and broken.needs_human


def test_key_times_follow_the_real_action_not_blink_and_breathe() -> None:
    shot = {
        "duration_s": 10.0,
        "characters": [
            {
                "id": "pip",
                "actions": [
                    {"motion": "blink", "start_s": 0, "duration_s": 10},
                    {"motion": "wave", "start_s": 2.0, "duration_s": 1.0},
                    {"motion": "jump", "start_s": 6.0},
                ],
            }
        ],
    }
    assert runner.key_times(shot) == [2.25, 4.58, 6.9]
    quiet = {"duration_s": 4.0, "characters": [{"id": "a", "actions": []}]}
    assert runner.key_times(quiet) == [0.1, 2.0, 3.9]


def test_film_texts_reads_the_premise_and_dialogue(tmp_path: Path) -> None:
    (tmp_path / "shots" / "s01_sh01").mkdir(parents=True)
    (tmp_path / "shots" / "s01_sh01" / "shot.json").write_text(json.dumps(SPEC))
    (tmp_path / "film.json").write_text(json.dumps({"premise": "A kite day."}))
    premise, lines = runner.film_texts(tmp_path, ["s01_sh01"])
    assert premise == "A kite day." and lines and "pip" in lines[0][0]


@pytest.mark.render
@pytest.mark.skipif(not load_config().path("tools", "synfig").exists(), reason="no synfig CLI")
def test_check_frame_end_to_end_with_a_fake_model(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "make_room", lambda cfg, model: [])
    film = make_film(tmp_path)
    spec = {**SPEC, "duration_s": 2, "dialogue": []}
    spec["characters"] = [{**SPEC["characters"][0], "actions": [{"motion": "wave", "start_s": 0}]}]
    (film / "shots" / spec["id"]).mkdir(parents=True)
    (film / "shots" / spec["id"] / "shot.json").write_text(json.dumps(spec))
    answer = {
        "description": "Pip waves in a meadow.",
        "characters": [
            {"id": "pip", "present": True, "expression_plausible": True, "reason": "ok"}
        ],
        "background_present": True,
        "background_reason": "meadow",
        "problems": [],
    }
    model = FakeVision(answer)
    report = runner.check_frame(film, spec["id"], 0.5, model)
    assert report.code_ok and report.ok and Path(report.frame_path).is_file()
    assert model.unloaded == 1 and len(model.calls) == 1
    # a character moved off-frame is a fact the code finds, whatever the model says
    spec["characters"][0]["position"] = [-0.5, 0.92]
    (film / "shots" / spec["id"] / "shot.json").write_text(json.dumps(spec))
    broken = runner.check_frame(film, spec["id"], 0.5, model)
    assert not broken.ok and broken.code_findings[0].kind == "missing" and broken.model_ok
