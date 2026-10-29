"""Schemas + semantic checks: the valid examples pass; each kind of mistake gets a precise issue."""

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from studio_core.config import REPO_ROOT
from studio_core.schema import SCHEMAS, Issue, validate, validate_file

FIX = REPO_ROOT / "tests" / "fixtures"
EXAMPLES = {
    "rig": "schemas/rig_pip.json",
    "shot": "schemas/shot_s01_sh01.json",
    "shotlist": "schemas/shotlist_kite_day.json",
    "film": "schemas/film_kite_day.json",
    "background": "backgrounds/meadow/layers.json",
    "voice": "schemas/voice_pip.json",
    "line": "schemas/line_l001.json",
    "lipsync": "audio/pip_line_01.rhubarb.json",  # real Rhubarb output (Step 0)
    "music": "schemas/music_m01.json",
    "sfx_library": "schemas/sfx_library.json",
    "design": "schemas/design_kit.json",
    "plates": "schemas/plates_meadow.json",
    "edit": "schemas/edit_kite_day.json",
}


def example(name: str) -> dict[str, Any]:
    return json.loads((FIX / EXAMPLES[name]).read_text())


def test_every_schema_has_an_example() -> None:
    assert set(EXAMPLES) == set(SCHEMAS)


def cue(i: int) -> Callable[[dict], dict]:
    return lambda d: d["mouthCues"][i]


@pytest.mark.parametrize("name", list(EXAMPLES))
def test_examples_are_valid(name: str) -> None:
    assert validate(name, example(name)) == []


def front(rig: dict) -> dict:
    return rig["views"]["front"]


Mutation = Callable[[dict], None]
CASES: list[tuple[str, str, Mutation, str, str]] = [
    # (schema, case, mutation, expected path fragment, expected message fragment)
    ("rig", "bad id", lambda r: r.update(id="Pip!"), "id", "does not match"),
    (
        "rig",
        "missing front view",
        lambda r: r["views"].pop("front"),
        "views",
        "'front' is a required",
    ),
    ("rig", "extra field", lambda r: r.update(colour="red"), "", "Additional properties"),
    (
        "rig",
        "two roots",
        lambda r: front(r)["bones"]["head"].update(parent=None),
        "views.front.root",
        "exactly one bone",
    ),
    (
        "rig",
        "unknown parent",
        lambda r: front(r)["bones"]["forearm_l"].update(parent="elbow"),
        "forearm_l.parent",
        "unknown bone",
    ),
    (
        "rig",
        "joint on the wrong part",
        lambda r: front(r)["bones"]["forearm_l"]["attach"].update(part="torso"),
        "forearm_l.attach.part",
        "must attach to a part of the parent bone",
    ),
    (
        "rig",
        "joint outside the image",
        lambda r: front(r)["bones"]["head"]["attach"].update(at_px=[900, 18]),
        "head.attach.at_px",
        "outside",
    ),
    (
        "rig",
        "cycle",
        lambda r: (
            front(r)["bones"]["upper_arm_l"].update(parent="forearm_l"),
            front(r)["bones"]["upper_arm_l"]["attach"].update(part="forearm_l"),
        ),
        "upper_arm_l.parent",
        "cycle",
    ),
    (
        "rig",
        "draw order missing a part",
        lambda r: front(r)["draw_order"].remove("head"),
        "draw_order",
        "missing ['head']",
    ),
    (
        "rig",
        "face anchor off the head",
        lambda r: front(r)["face"]["mouth"].update(at_px=[110, 999]),
        "face.mouth.at_px",
        "outside",
    ),
    (
        "shot",
        "unknown motion",
        lambda s: s["characters"][0]["actions"][2].update(motion="wavee"),
        "actions[2].motion",
        "is not one of",
    ),
    (
        "shot",
        "unknown param",
        lambda s: s["characters"][0]["actions"][2]["params"].update(speed=2),
        "actions[2].params",
        "Additional",
    ),
    (
        "shot",
        "position far outside",
        lambda s: s["characters"][0].update(position=[3, 0.9]),
        "characters[0].position[0]",
        "maximum",
    ),
    ("shot", "bad shot id", lambda s: s.update(id="shot1"), "id", "does not match"),
    (
        "shot",
        "action after the end",
        lambda s: s["characters"][0]["actions"][2].update(start_s=12),
        "actions[2].start_s",
        "not inside",
    ),
    (
        "shot",
        "action runs past the end",
        lambda s: s["characters"][0]["actions"][2].update(duration_s=9.5),
        "actions[2].duration_s",
        "past the end",
    ),
    (
        "shot",
        "speaker not in shot",
        lambda s: s["dialogue"][0].update(character="bunny"),
        "dialogue[0].character",
        "not in this shot",
    ),
    (
        "shot",
        "camera past the end",
        lambda s: s["camera"].update(start_s=8, duration_s=4),
        "camera",
        "past the end",
    ),
    (
        "shotlist",
        "duplicate shot ids",
        lambda d: d["shots"][1].update(id="s01_sh01"),
        "shots",
        "used twice",
    ),
    (
        "shotlist",
        "bad shot inside list",
        lambda d: d["shots"][1]["characters"][0]["actions"][0].update(motion="dance"),
        "shots[1].characters[0].actions[0].motion",
        "is not one of",
    ),
    (
        "film",
        "bad stage status",
        lambda f: f["stages"].update(story="finished"),
        "stages.story",
        "is not one of",
    ),
    # ----------------------------------------------------------------- audio (Step 3)
    ("shot", "bad sound id", lambda s: s["sfx"][0].update(sound="Boing!"), "sfx[0].sound", "match"),
    ("shot", "music too loud", lambda s: s.update(music_volume=2), "music_volume", "maximum"),
    ("voice", "unknown engine", lambda v: v.update(engine="siri"), "engine", "is not one of"),
    ("voice", "no voices", lambda v: v.update(voices=[]), "voices", "should be non-empty"),
    (
        "voice",
        "bad voice id",
        lambda v: v["voices"][0].update(id="Heart"),
        "voices[0].id",
        "does not match",
    ),
    (
        "voice",
        "same voice twice",
        lambda v: v["voices"].append({"id": "af_heart"}),
        "voices",
        "listed twice",
    ),
    (
        "voice",
        "pitch too high",
        lambda v: v.update(pitch_semitones=7),
        "pitch_semitones",
        "maximum",
    ),
    ("line", "bad line id", lambda d: d.update(line_id="line1"), "line_id", "does not match"),
    ("line", "blank text", lambda d: d.update(text="   "), "text", "blank"),
    (
        "line",
        "someone else's voice",
        lambda d: d.update(character="bunny"),
        "voice.character",
        "belongs to 'pip'",
    ),
    ("line", "bad hash", lambda d: d.update(hash="abc"), "hash", "does not match"),
    (
        "lipsync",
        "unknown shape",
        lambda d: cue(3)(d).update(value="Z"),
        "mouthCues[3].value",
        "is not one of",
    ),
    (
        "lipsync",
        "late first cue",
        lambda d: cue(0)(d).update(start=0.1),
        "mouthCues[0].start",
        "start at 0",
    ),
    (
        "lipsync",
        "gap between cues",
        lambda d: cue(2)(d).update(start=cue(2)(d)["start"] + 0.03),
        "mouthCues[2].start",
        "a gap",
    ),
    (
        "lipsync",
        "overlapping cues",
        lambda d: cue(2)(d).update(start=cue(2)(d)["start"] - 0.03),
        "mouthCues[2].start",
        "an overlap",
    ),
    (
        "lipsync",
        "cues end early",
        lambda d: d["metadata"].update(duration=7.0),
        "end",
        "but the audio lasts 7.0s",
    ),
    (
        "music",
        "instrument twice",
        lambda m: m["instruments"].append("ukulele"),
        "instruments",
        "listed twice",
    ),
    ("music", "odd sample rate", lambda m: m.update(sample_rate=22050), "sample_rate", "one of"),
    (
        "sfx_library",
        "not CC0",
        lambda d: d["sounds"][0].update(license="CC-BY-4.0"),
        "sounds[0].license",
        "'CC0-1.0' was expected",
    ),
    (
        "sfx_library",
        "not a WAV",
        lambda d: d["sounds"][0].update(file="kenney/a.ogg"),
        "sounds[0].file",
        "does not match",
    ),
    (
        "sfx_library",
        "license page over http",
        lambda d: d["sounds"][0].update(url="http://kenney.nl"),
        "sounds[0].url",
        "does not match",
    ),
    (
        "sfx_library",
        "duplicate id",
        lambda d: d["sounds"][1].update(id=d["sounds"][0]["id"]),
        "sounds",
        "the same id appears more than once",
    ),
    (
        "sfx_library",
        "same audio twice",
        lambda d: d["sounds"][1].update(sha256=d["sounds"][0]["sha256"]),
        "sounds",
        "the same audio appears more than once",
    ),
    ("plates", "unknown choice", lambda d: d.update(chosen="c9"), "chosen", "unknown draft"),
    (
        "plates",
        "plate elsewhere",
        lambda d: d["candidates"][1].update(plate="c1/plate.png"),
        "candidates[1].plate",
        "should be c2/plate.png",
    ),
    ("design", "unknown choice", lambda d: d.update(chosen="c9"), "chosen", "unknown candidate"),
    (
        "design",
        "duplicate candidate",
        lambda d: d["candidates"][1].update(id="c1", sheet="c1/sheet.png"),
        "candidates",
        "'c1' appears more than once",
    ),
    (
        "design",
        "ok with problems",
        lambda d: d["candidates"][0].update(ok=True),
        "candidates[0].ok",
        "exactly when problems is empty",
    ),
    (
        "design",
        "sheet elsewhere",
        lambda d: d["candidates"][1].update(sheet="c1/sheet.png"),
        "candidates[1].sheet",
        "should be c2/sheet.png",
    ),
]


@pytest.mark.parametrize(
    ("name", "case", "mutate", "path", "message"), CASES, ids=[c[1] for c in CASES]
)
def test_mistakes_are_reported_precisely(
    name: str, case: str, mutate: Mutation, path: str, message: str
) -> None:
    data = copy.deepcopy(example(name))
    mutate(data)
    issues = validate(name, data)
    assert issues, f"{case}: expected an issue"
    assert any(path in i.path and message in i.message for i in issues), [str(i) for i in issues]


def test_issue_text_is_readable() -> None:
    assert str(Issue("characters[0].position", "too big")) == "characters[0].position: too big"
    assert str(Issue("", "not valid JSON")) == "(root): not valid JSON"


def test_unknown_schema_name() -> None:
    with pytest.raises(ValueError):
        validate("storyboard", {})


def test_audio_files_are_recognized_by_folder(tmp_path: Path) -> None:
    for folder, name in (("dialogue", "line"), ("lipsync", "lipsync"), ("music", "music")):
        path = tmp_path / folder / "x.json"
        path.parent.mkdir()
        path.write_text(json.dumps(example(name)))
        assert validate_file(path) == [], folder
    voice = tmp_path / "voice.json"
    voice.write_text(json.dumps(example("voice")))
    assert validate_file(voice) == []
