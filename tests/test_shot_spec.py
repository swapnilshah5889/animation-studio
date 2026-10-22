"""Shot spec editing (studio_core.shot_spec): every edit is checked whole and refused with a
fixable message, leaving the saved spec untouched (task 2.7)."""

import json
import shutil
from pathlib import Path

import pytest
from test_shot import make_film

from studio_core import shot_spec as ss
from studio_core.film import Film
from studio_core.models import load_manifest

SHOT = "s01_sh01"


@pytest.fixture
def film(tmp_path: Path) -> ss.FilmFolder:
    make_film(tmp_path / "films" / "demo")
    return ss.FilmFolder.open(tmp_path / "films", "demo")


@pytest.fixture
def shot(film: ss.FilmFolder) -> ss.FilmFolder:
    ss.create_shot(film, SHOT, 4, "meadow")
    ss.place_character(film, SHOT, "pip", [0.5, 0.92])
    return film


def saved(film: ss.FilmFolder) -> dict:
    return json.loads(film.shot_file(SHOT).read_text())


def test_open_film_errors(tmp_path: Path) -> None:
    make_film(tmp_path / "demo")
    with pytest.raises(ss.SpecError, match="not a film name"):
        ss.FilmFolder.open(tmp_path, "../etc")
    with pytest.raises(ss.SpecError, match=r"no film 'kite'; films: demo"):
        ss.FilmFolder.open(tmp_path, "kite")


def test_inventory(film: ss.FilmFolder) -> None:
    assert film.characters() == ["pip"] and film.backgrounds() == ["meadow"]
    assert film.lines() == ["l001"] and film.shots() == []


def test_create_shot(film: ss.FilmFolder) -> None:
    ss.create_shot(film, SHOT, 4, "meadow", {"move": "push_in"})
    assert saved(film)["camera"] == {"move": "push_in"} and saved(film)["characters"] == []
    with pytest.raises(ss.SpecError, match="already exists"):
        ss.create_shot(film, SHOT, 4, "meadow")
    ss.create_shot(film, SHOT, 6, "meadow", replace=True)
    assert saved(film)["duration_s"] == 6
    with pytest.raises(ss.SpecError, match=r"background 'beach' not found; backgrounds: meadow"):
        ss.create_shot(film, "s01_sh02", 4, "beach")
    assert not film.shot_file("s01_sh02").exists()  # refused edits save nothing
    with pytest.raises(ss.SpecError, match=r"no shot 's09_sh09'.*shots: s01_sh01"):
        ss.load(film, "s09_sh09")


def test_place_character_adds_then_moves(shot: ss.FilmFolder) -> None:
    ss.add_action(shot, SHOT, "pip", "wave", 1)
    ss.place_character(shot, SHOT, "pip", [0.3, 0.9], facing="left")
    (pip,) = saved(shot)["characters"]
    assert pip["position"] == [0.3, 0.9] and pip["facing"] == "left" and pip["actions"]
    with pytest.raises(ss.SpecError, match=r"character 'bunny' not found; characters: pip"):
        ss.place_character(shot, SHOT, "bunny", [0.5, 0.9])


def test_add_action_checks(shot: ss.FilmFolder) -> None:
    before = saved(shot)
    with pytest.raises(ss.SpecError, match="'wavee' is not one of"):
        ss.add_action(shot, SHOT, "pip", "wavee", 1)
    with pytest.raises(ss.SpecError, match="not inside the 4s shot"):
        ss.add_action(shot, SHOT, "pip", "nod", 5)
    with pytest.raises(ss.SpecError, match="runs past the end"):
        ss.add_action(shot, SHOT, "pip", "nod", 3, duration_s=2)
    with pytest.raises(ss.SpecError, match="'bunny' is not in shot s01_sh01; in the shot: pip"):
        ss.add_action(shot, SHOT, "bunny", "nod", 1)
    assert saved(shot) == before
    ss.add_action(shot, SHOT, "pip", "wave", 1, params={"side": "left", "energy": 0.7})
    assert saved(shot)["characters"][0]["actions"] == [
        {"motion": "wave", "start_s": 1, "params": {"side": "left", "energy": 0.7}}
    ]


def test_poses_and_expressions_replace_at_the_same_time(shot: ss.FilmFolder) -> None:
    ss.add_pose(shot, SHOT, "pip", 1, {"head": 10})
    ss.add_pose(shot, SHOT, "pip", 0.5, {"head": -5})
    ss.add_pose(shot, SHOT, "pip", 1, {"head": 20})
    poses = saved(shot)["characters"][0]["poses"]
    assert poses == [{"time_s": 0.5, "bones": {"head": -5}}, {"time_s": 1, "bones": {"head": 20}}]
    with pytest.raises(ss.SpecError, match=r"unknown bones \['tail'\]"):
        ss.add_pose(shot, SHOT, "pip", 2, {"tail": 5})
    ss.add_expression(shot, SHOT, "pip", "happy", 0)
    ss.add_expression(shot, SHOT, "pip", "sad", 0)
    assert saved(shot)["characters"][0]["expressions"] == [{"expr": "sad", "start_s": 0}]


def test_dialogue(shot: ss.FilmFolder) -> None:
    warnings = ss.add_dialogue(shot, SHOT, "pip", "l001", 0.5)
    (line,) = saved(shot)["dialogue"]
    assert line["text"].startswith("Hi Bunny!") and line["start_s"] == 0.5
    assert any("ends at 6.10s, after the 4s shot" in w for w in warnings)  # 5.6 s line
    ss.add_dialogue(shot, SHOT, "pip", "l001", 0.0, text="Hi!")
    assert saved(shot)["dialogue"] == [
        {"character": "pip", "line_id": "l001", "text": "Hi!", "start_s": 0.0}
    ]
    with pytest.raises(ss.SpecError, match=r"line 'l002' has no audio .*lines: l001"):
        ss.add_dialogue(shot, SHOT, "pip", "l002", 0, text="Bye")
    (shot.root / "audio" / "lipsync" / "l001.json").unlink()
    with pytest.raises(ss.SpecError, match="no mouth cues"):
        ss.add_dialogue(shot, SHOT, "pip", "l001", 0)


def test_warnings_and_camera(shot: ss.FilmFolder) -> None:
    _, warnings = ss.check(shot, saved(shot))
    assert warnings == ["pip never blinks; add the 'blink' motion for the whole shot"]
    assert ss.add_action(shot, SHOT, "pip", "blink", 0, duration_s=4) == []
    ss.set_camera(shot, SHOT, "slow_pan_left", start_s=1)
    assert saved(shot)["camera"] == {"move": "slow_pan_left", "start_s": 1}
    with pytest.raises(ss.SpecError, match="camera move runs past the end"):
        ss.set_camera(shot, SHOT, "push_in", start_s=3, duration_s=2)


def test_motions_a_rig_cannot_do_are_refused(shot: ss.FilmFolder) -> None:
    rig_file = shot.rig_file("pip")
    rig = json.loads(rig_file.read_text())
    view = rig["views"]["front"]
    for part, spec in list(view["parts"].items()):  # drop the left arm entirely
        if spec["bone"] in ("upper_arm_l", "forearm_l"):
            del view["parts"][part]
            view["draw_order"].remove(part)
    del view["bones"]["forearm_l"], view["bones"]["upper_arm_l"]
    rig_file.write_text(json.dumps(rig))
    with pytest.raises(ss.SpecError, match="pip: "):
        ss.add_action(shot, SHOT, "pip", "wave", 1, params={"side": "left"})


def test_remove_item(shot: ss.FilmFolder) -> None:
    ss.add_action(shot, SHOT, "pip", "wave", 1)
    ss.add_action(shot, SHOT, "pip", "nod", 2)
    removed, _ = ss.remove_item(shot, SHOT, "action", character_id="pip", index=0)
    assert removed["motion"] == "wave"
    assert [a["motion"] for a in saved(shot)["characters"][0]["actions"]] == ["nod"]
    with pytest.raises(ss.SpecError, match="index 3 is out of range: there are 1"):
        ss.remove_item(shot, SHOT, "action", character_id="pip", index=3)
    with pytest.raises(ss.SpecError, match="needs character_id"):
        ss.remove_item(shot, SHOT, "pose", index=0)
    ss.add_dialogue(shot, SHOT, "pip", "l001", 0)
    ss.remove_item(shot, SHOT, "character", character_id="pip")
    assert saved(shot)["characters"] == [] and saved(shot)["dialogue"] == []


def test_register_rig(film: ss.FilmFolder) -> None:
    path, placeholder = ss.register_rig(film, "bunny")
    rig = json.loads(path.read_text())
    assert placeholder and rig["id"] == "bunny" and rig["name"] == "Bunny"
    assert film.characters() == ["bunny", "pip"]
    with pytest.raises(ss.SpecError, match="already has a rig"):
        ss.register_rig(film, "bunny")

    broken = {**rig, "id": "bunny"}
    broken["views"] = json.loads(json.dumps(rig["views"]))
    next(iter(broken["views"]["front"]["parts"].values()))["file"] = "parts/missing.png"
    with pytest.raises(
        ss.SpecError, match=r"rig.json: part files not found: \['parts/missing.png'\]"
    ):
        ss.register_rig(film, "bunny", broken)
    assert not (path.parent / "rig.json.new").exists()
    assert json.loads(path.read_text()) == rig  # the good rig is untouched
    with pytest.raises(ss.SpecError, match="the rig's id is 'bunny' but the character id is 'kit'"):
        ss.register_rig(film, "kit", rig)


def test_register_rig_records_the_character_in_film_json(tmp_path: Path) -> None:
    Film.create(tmp_path / "kite-day", "storybook", load_manifest())
    film = ss.FilmFolder.open(tmp_path, "kite-day")
    ss.register_rig(film, "pip")
    assert Film.load(film.root).data["characters"] == ["pip"]


# --------------------------------------------------------------------------- audio (Step 3)

FIXTURES = Path(__file__).parent / "fixtures"


def test_line_metadata_and_mouth_cues_are_checked(shot: ss.FilmFolder) -> None:
    ss.add_dialogue(shot, SHOT, "pip", "l001", 0)
    line = json.loads((FIXTURES / "schemas" / "line_l001.json").read_text())
    voice = {**line["voice"], "character": "bunny"}
    shot.line_meta("l001").write_text(json.dumps({**line, "character": "bunny", "voice": voice}))
    errors, _ = ss.check(shot, saved(shot))
    assert errors == ["line 'l001' was recorded in bunny's voice, but pip says it"]
    shot.line_meta("l001").write_text(json.dumps(line))
    assert ss.check(shot, saved(shot))[0] == []

    cues_file = shot.line_files("l001")[1]
    cues = json.loads(cues_file.read_text())
    for c in cues["mouthCues"]:  # cues made for a shorter take of the line
        c["start"], c["end"] = round(c["start"] * 0.9, 3), round(c["end"] * 0.9, 3)
    cues["metadata"]["duration"] = cues["mouthCues"][-1]["end"]
    cues_file.write_text(json.dumps(cues))
    errors, _ = ss.check(shot, saved(shot))
    assert errors == [
        "line 'l001' mouth cues were made for 5.04s of audio, but the audio is 5.60s; "
        "run lipsync on it again"
    ]
    cues["mouthCues"][3]["value"] = "Z"
    cues_file.write_text(json.dumps(cues))
    assert "mouthCues[3].value" in ss.check(shot, saved(shot))[0][0]


def test_sound_effects_and_music_are_checked(shot: ss.FilmFolder, tmp_path: Path) -> None:
    library = tmp_path / "sfx"
    library.mkdir()
    film = ss.FilmFolder(shot.root, sfx_root=library)
    spec = {**saved(shot), "sfx": [{"query": "a squeaky toy", "start_s": 1}]}
    errors, warnings = ss.check(film, spec)
    assert errors == []
    assert "sound effect 'a squeaky toy' at 1s has no sound chosen yet" in " ".join(warnings)

    spec["sfx"][0]["sound"] = "bsb_toy_squeak_0427"
    (error,) = ss.check(film, spec)[0]
    assert "not in the library (0 sounds); search with find_sfx" in error
    (library / "manifest.json").write_text((FIXTURES / "schemas" / "sfx_library.json").read_text())
    assert ss.check(film, spec)[0] == []
    (library / "manifest.json").write_text('{"schema_version": 1}')
    assert "the sound library is broken" in ss.check(film, spec)[0][0]

    spec = {**saved(shot), "music_cue": "m01"}
    assert ss.check(film, spec)[0] == ["music cue 'm01' not found; cues: none"]
    film.music_file("m01").parent.mkdir(parents=True)
    shutil.copy(FIXTURES / "audio" / "pip_line_01.wav", film.music_file("m01"))
    assert ss.check(film, spec)[0] == [] and film.music_cues() == ["m01"]
