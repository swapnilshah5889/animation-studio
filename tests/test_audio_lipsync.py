"""Lip-sync (task 3.3): recognizer choice, refusals, the cache, and real Rhubarb runs."""

import json
import shutil
from pathlib import Path

import pytest

from studio_core import shot_spec as ss
from studio_core.audio.lipsync import LipsyncError, _usable, lipsync, recognizer_for
from studio_core.audio.voices import speak
from studio_core.config import expand_path, load_config
from studio_core.schema import validate

FIXTURES = Path(__file__).parent / "fixtures"
CFG = load_config()
has_rhubarb = CFG.path("tools", "rhubarb").exists()
has_kokoro = expand_path(CFG.get("envs", "kokoro")["python"]).exists()


def film_with_fixture_line(root: Path) -> Path:
    dialogue = root / "audio" / "dialogue"
    dialogue.mkdir(parents=True)
    shutil.copy(FIXTURES / "audio" / "pip_line_01.wav", dialogue / "l001.wav")
    shutil.copy(FIXTURES / "audio" / "pip_line_01.txt", dialogue / "l001.txt")
    return root


def test_recognizer_choice() -> None:
    def meta(*ids: str) -> dict:
        return {"voice": {"voices": [{"id": i} for i in ids]}}

    assert recognizer_for(None) == "pocketSphinx"  # Step 0 fixture lines: English
    assert recognizer_for(meta("af_heart", "bf_emma")) == "pocketSphinx"
    assert recognizer_for(meta("af_heart", "ef_dora")) == "phonetic"


def test_refusals(tmp_path: Path) -> None:
    film = film_with_fixture_line(tmp_path)
    with pytest.raises(LipsyncError, match=r"no audio for \['l009'\]; speak the lines first"):
        lipsync(film, ["l001", "l009"])
    with pytest.raises(LipsyncError, match="appears twice"):
        lipsync(film, ["l001", "l001"])


def test_cues_are_reused_only_when_they_match_the_audio(tmp_path: Path) -> None:
    film = film_with_fixture_line(tmp_path)
    wav = film / "audio" / "dialogue" / "l001.wav"
    cues = film / "audio" / "lipsync" / "l001.json"
    assert _usable(cues, wav) is None  # none yet
    cues.parent.mkdir(parents=True)
    data = json.loads((FIXTURES / "audio" / "pip_line_01.rhubarb.json").read_text())
    cues.write_text(json.dumps(data))
    assert _usable(cues, wav) == data
    result = lipsync(film, ["l001"])  # cached: Rhubarb doesn't run (works without it)
    assert result[0].cached and result[0].n_cues == 34 and result[0].shapes == "ABCEFGX"
    data["metadata"]["duration"] = data["mouthCues"][-1]["end"] = 6.2  # made for another take
    cues.write_text(json.dumps(data))
    assert _usable(cues, wav) is None


@pytest.mark.models
@pytest.mark.skipif(not has_rhubarb, reason="no Rhubarb")
def test_rhubarb_reproduces_the_fixture_cues(tmp_path: Path) -> None:
    film = film_with_fixture_line(tmp_path)
    (result,) = lipsync(film, ["l001"])
    assert not result.cached and set(result.shapes) <= set("ABCDEFGHX")
    data = json.loads(result.cues.read_text())
    assert validate("lipsync", data) == []
    assert data["metadata"] == {"soundFile": "../dialogue/l001.wav", "duration": 5.6}
    fixture = json.loads((FIXTURES / "audio" / "pip_line_01.rhubarb.json").read_text())
    assert data["mouthCues"] == fixture["mouthCues"]  # same audio + text → same cues
    assert lipsync(film, ["l001"])[0].cached
    assert not lipsync(film, ["l001"], force=True)[0].cached


@pytest.mark.models
@pytest.mark.skipif(not (has_rhubarb and has_kokoro), reason="no Rhubarb or Kokoro")
def test_spoken_line_is_ready_for_a_shot(tmp_path: Path) -> None:
    """speak (Pip's cast voice) → cues → the line passes every shot check."""
    film_root = tmp_path / "films" / "demo"
    shutil.copytree(FIXTURES / "characters" / "pip", film_root / "characters" / "pip")
    shutil.copytree(FIXTURES / "backgrounds" / "meadow", film_root / "backgrounds" / "meadow")
    (line,) = speak(film_root, "pip", [{"text": "Hi Bunny! Look what I found."}])
    assert line.cues is not None and line.cues.is_file()
    film = ss.FilmFolder.open(tmp_path / "films", "demo")
    ss.create_shot(film, "s01_sh01", 4, "meadow")
    ss.place_character(film, "s01_sh01", "pip", [0.5, 0.92])
    ss.add_action(film, "s01_sh01", "pip", "blink", 0, duration_s=4)
    warnings = ss.add_dialogue(film, "s01_sh01", "pip", line.line_id, 0.5)
    assert warnings == []
    errors, _ = ss.check(film, ss.load(film, "s01_sh01"))
    assert errors == []
