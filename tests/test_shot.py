"""Shot assembly: spec → scene.sif → shot.mp4 with dialogue (task 2.6)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from studio_core.config import REPO_ROOT, load_config
from studio_core.shot import (
    ShotError,
    build_shot,
    dialogue_mouth,
    expression_track,
    render_shot,
)
from studio_core.sif import Animated

FIXTURES = REPO_ROOT / "tests" / "fixtures"
SPEC = json.loads((FIXTURES / "schemas" / "shot_s01_sh01.json").read_text())


def make_film(root: Path) -> Path:
    shutil.copytree(FIXTURES / "characters" / "pip", root / "characters" / "pip")
    shutil.copytree(FIXTURES / "backgrounds" / "meadow", root / "backgrounds" / "meadow")
    (root / "audio" / "dialogue").mkdir(parents=True)
    (root / "audio" / "lipsync").mkdir(parents=True)
    shutil.copy(FIXTURES / "audio" / "pip_line_01.wav", root / "audio" / "dialogue" / "l001.wav")
    shutil.copy(FIXTURES / "audio" / "pip_line_01.txt", root / "audio" / "dialogue" / "l001.txt")
    shutil.copy(
        FIXTURES / "audio" / "pip_line_01.rhubarb.json", root / "audio" / "lipsync" / "l001.json"
    )
    return root


def test_expression_track() -> None:
    assert expression_track([], 24) == "neutral"
    assert expression_track([{"expr": "happy", "start_s": 0}], 24) == "happy"
    track = expression_track([{"expr": "sad", "start_s": 2}, {"expr": "happy", "start_s": 0.5}], 24)
    assert isinstance(track, Animated)
    assert [(w.frame, w.value) for w in track.waypoints] == [
        (0, "neutral"),
        (12, "happy"),
        (48, "sad"),
    ]


def test_dialogue_mouth_shifts_cues_to_the_line_start(tmp_path: Path) -> None:
    film = make_film(tmp_path)
    assert dialogue_mouth(film, [], 24) == "X"
    track = dialogue_mouth(film, [{"line_id": "l001", "start_s": 1.5}], 24)
    assert isinstance(track, Animated)
    cues = json.loads((film / "audio" / "lipsync" / "l001.json").read_text())["mouthCues"]
    first_open = next(c for c in cues if c["value"] != "X")
    frames_ = {w.frame: w.value for w in track.waypoints}
    assert frames_[0] == "X"
    assert any(f >= 36 and v == first_open["value"] for f, v in frames_.items())  # 1.5 s = f36
    with pytest.raises(ShotError, match="no mouth cues"):
        dialogue_mouth(film, [{"line_id": "l999", "start_s": 0}], 24)


def test_build_shot_links_assets_relative_to_the_shot_folder(tmp_path: Path) -> None:
    film = make_film(tmp_path)
    built = build_shot(film, SPEC)
    assert built.n_frames == 240 and built.fps == 24
    xml = built.canvas.to_string()
    assert "../../characters/pip/parts/" in xml and "../../backgrounds/meadow/layers/" in xml
    assert built.dialogue == [(film / "audio" / "dialogue" / "l001.wav", 1.5)]


def test_build_shot_errors(tmp_path: Path) -> None:
    film = make_film(tmp_path)
    with pytest.raises(ShotError, match="invalid"):
        build_shot(film, {**SPEC, "duration_s": -1})
    with pytest.raises(ShotError, match="background 'beach' not found"):
        build_shot(film, {**SPEC, "background": "beach"})
    with pytest.raises(ShotError, match="character 'bunny' not found"):
        bunny = [{"id": "bunny", "position": [0.5, 0.9]}]
        build_shot(film, {**SPEC, "characters": bunny, "dialogue": []})
    (film / "audio" / "dialogue" / "l001.wav").unlink()
    with pytest.raises(ShotError, match="no audio"):
        build_shot(film, SPEC)


@pytest.mark.render
@pytest.mark.skipif(not load_config().path("tools", "synfig").exists(), reason="no synfig CLI")
def test_render_shot_end_to_end(tmp_path: Path) -> None:
    film = make_film(tmp_path)
    spec = {**SPEC, "duration_s": 2, "dialogue": [{**SPEC["dialogue"][0], "start_s": 0.25}]}
    spec["characters"] = [{**SPEC["characters"][0], "actions": [{"motion": "wave", "start_s": 0}]}]
    (film / "shots" / spec["id"]).mkdir(parents=True)
    (film / "shots" / spec["id"] / "shot.json").write_text(json.dumps(spec))
    out = render_shot(film, spec["id"], size=(192, 108))
    assert out.sif.name == "scene.sif" and len(out.frames) == 48
    probe = subprocess.run(
        [
            str(load_config().path("tools", "ffprobe")),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,width,height,nb_frames",
            "-of",
            "json",
            str(out.mp4),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    streams = {s["codec_type"]: s for s in json.loads(probe.stdout)["streams"]}
    assert streams["video"]["width"] == 192 and int(streams["video"]["nb_frames"]) == 48
    assert "audio" in streams
