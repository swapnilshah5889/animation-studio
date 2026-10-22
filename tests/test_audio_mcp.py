"""audio_mcp through a real MCP client (task 3.7): tools and schemas, casting, refusals, the
compose cache, a shot's preview mix, speak and find_sfx with real models (marked `models`), and
the stdio transport."""

import asyncio
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from mcp import Client, StdioServerParameters
from test_audio_mix import tone, write
from test_shot import make_film

from audio_mcp.server import create_server
from studio_core import shot_spec as ss
from studio_core.audio.music import MOODS, plan
from studio_core.config import expand_path, load_config

CFG = load_config()
TOOLS = {"describe_audio", "set_voice", "speak", "lipsync", "compose", "find_sfx", "preview_mix"}
FIXTURES = Path(__file__).parent / "fixtures"
has_kokoro = expand_path(CFG.get("envs", "kokoro")["python"]).exists()


def films(tmp_path: Path) -> Path:
    make_film(tmp_path / "demo")
    shutil.copy(
        FIXTURES / "characters" / "pip" / "voice.json", tmp_path / "demo" / "characters" / "pip"
    )
    return tmp_path


def run(root: Path, calls: list[tuple[str, dict[str, Any]]]) -> list[Any]:
    async def go() -> list[Any]:
        async with Client(create_server(root)) as client:
            return [await client.call_tool(name, args) for name, args in calls]

    return asyncio.run(go())


def ok(result: Any) -> dict[str, Any]:
    assert not result.is_error, result.content[0].text
    return result.structured_content


def error(result: Any) -> str:
    assert result.is_error
    return result.content[0].text


def test_tools_are_listed_with_descriptions_and_enums(tmp_path: Path) -> None:
    async def go() -> list[Any]:
        async with Client(create_server(tmp_path)) as client:
            return (await client.list_tools()).tools

    tools = {t.name: t for t in asyncio.run(go())}
    assert set(tools) == TOOLS
    for tool in tools.values():
        assert len(tool.description or "") > 40 and "\n " not in tool.description, tool.name
    assert set(tools["compose"].input_schema["properties"]["mood"]["enum"]) == set(MOODS)


def test_describe_and_cast(tmp_path: Path) -> None:
    results = run(
        films(tmp_path),
        [
            ("describe_audio", {"film": "demo"}),
            ("set_voice", {"film": "demo", "character_id": "pip", "voices": [{"id": "af_bella"}]}),
            ("set_voice", {"film": "demo", "character_id": "pip", "voices": [{"id": "zz_nobody"}]}),
            ("set_voice", {"film": "demo", "character_id": "kit", "voices": [{"id": "af_bella"}]}),
            ("describe_audio", {"film": "demo"}),
        ],
    )
    before = ok(results[0])
    (pip,) = before["characters"]
    assert pip["voice"]["voices"] == [{"id": "af_heart", "weight": 1}]
    assert before["lines"][0]["line_id"] == "l001" and before["lines"][0]["has_mouth_cues"]
    assert "af_heart" in before["installed_voices"]["kokoro"] and "playful" in before["moods"]
    assert ok(results[1])["voice"]["voices"] == [{"id": "af_bella", "weight": 1.0}]
    assert "voices ['zz_nobody'] aren't installed" in error(results[2])
    assert "no character 'kit'; characters: pip" in error(results[3])
    assert ok(results[4])["characters"][0]["voice"]["voices"][0]["id"] == "af_bella"


def test_refusals(tmp_path: Path) -> None:
    results = run(
        films(tmp_path),
        [
            (
                "speak",
                {"film": "demo", "character_id": "pip", "lines": [{"text": "What the hell"}]},
            ),
            ("compose", {"film": "demo", "cue_id": "m01", "mood": "spooky", "duration_s": 5}),
            ("find_sfx", {"queries": ["x"]}),
            ("preview_mix", {"film": "demo", "shot_id": "s01_sh01"}),
        ],
    )
    assert "not for a children's film" in error(results[0])
    assert "spooky" in error(results[1]) and "playful" in error(results[1])
    assert "at least 2 characters" in error(results[2])
    assert "create it with create_scene" in error(results[3]).lower()


def test_compose_returns_a_cached_cue(tmp_path: Path) -> None:
    root = films(tmp_path)
    request = plan("m01", "calm", 4.0)
    music = root / "demo" / "audio" / "music"
    write(
        music / "m01.wav",
        np.repeat(tone(220, 4.0, 48000, 0.1)[:, None], 2, 1).reshape(-1),
        48000,
        2,
    )
    (music / "m01.json").write_text(json.dumps({**request, "cue_id": "m01"}))
    (result,) = run(
        root, [("compose", {"film": "demo", "cue_id": "m01", "mood": "calm", "duration_s": 4})]
    )
    cue = ok(result)
    assert cue["cached"] and cue["peak_memory_gb"] is None and cue["duration_s"] == 4.0


def test_preview_mix_of_a_shot(tmp_path: Path) -> None:
    root = films(tmp_path)
    film = ss.FilmFolder.open(root, "demo")
    ss.create_shot(film, "s01_sh01", 8, "meadow")
    ss.place_character(film, "s01_sh01", "pip", [0.5, 0.92])
    ss.add_dialogue(film, "s01_sh01", "pip", "l001", 1.0)
    music = np.repeat(tone(220, 8.0, 48000, 0.1)[:, None], 2, 1).reshape(-1)
    write(root / "demo" / "audio" / "music" / "m01.wav", music, 48000, 2)
    ss.set_music(film, "s01_sh01", "m01", volume=0.4)
    (result,) = run(root, [("preview_mix", {"film": "demo", "shot_id": "s01_sh01"})])
    mix = ok(result)
    assert Path(mix["mix_path"]).is_file() and mix["integrated_lufs"] == pytest.approx(-14, abs=1)
    assert mix["true_peak_db"] <= -1.0


@pytest.mark.models
@pytest.mark.skipif(not has_kokoro, reason="no Kokoro env")
def test_speak_then_describe(tmp_path: Path) -> None:
    lines = [{"text": "Wow! A kite!"}, {"text": "Let's fly it together."}]
    results = run(
        films(tmp_path),
        [
            ("speak", {"film": "demo", "character_id": "pip", "lines": lines}),
            ("speak", {"film": "demo", "character_id": "pip", "lines": lines[:1]}),
            ("describe_audio", {"film": "demo"}),
        ],
    )
    spoken = ok(results[0])["lines"]
    assert [s["line_id"] for s in spoken] == ["l002", "l003"]
    assert all(Path(s["cues_path"]).is_file() for s in spoken)
    assert ok(results[1])["lines"][0]["cached"]
    described = {line["line_id"]: line for line in ok(results[2])["lines"]}
    assert described["l002"]["character"] == "pip" and described["l003"]["has_mouth_cues"]


@pytest.mark.models
def test_find_sfx_through_mcp(tmp_path: Path) -> None:
    from test_sfx_search import _ready

    if not _ready():
        pytest.skip("sound library not indexed")
    (result,) = run(tmp_path, [("find_sfx", {"queries": ["a door opening", "coins"], "k": 3})])
    found = ok(result)["results"]
    assert [r["query"] for r in found] == ["a door opening", "coins"]
    assert "door" in found[0]["sounds"][0]["sound_id"] and len(found[1]["sounds"]) == 3


def test_stdio_transport_lists_the_tools() -> None:
    params = StdioServerParameters(command=sys.executable, args=["-m", "audio_mcp.server"])

    async def go() -> set[str]:
        async with Client(params) as client:
            return {t.name for t in (await client.list_tools()).tools}

    assert asyncio.run(go()) == TOOLS
