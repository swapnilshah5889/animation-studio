"""qa_mcp through a real MCP client (in-process, a fake model: no Ollama), plus one real call to
qwen3-vl:8b-instruct (marked `models`)."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from test_qa_checks import FakeVision
from test_shot import SPEC, make_film

from qa_mcp.server import create_server
from studio_core.config import load_config
from studio_core.ollama import Ollama
from studio_core.qa import runner

TOOLS = {"check_frame", "check_safety", "check_film"}
ANSWER = {
    "description": "Pip waves in a meadow.",
    "characters": [{"id": "pip", "present": True, "expression_plausible": True, "reason": "ok"}],
    "background_present": True,
    "background_reason": "meadow",
    "problems": [],
}
CFG = load_config()
has_synfig = CFG.path("tools", "synfig").exists()


class Router(FakeVision):
    def __init__(self) -> None:
        super().__init__({})

    """Answers frame prompts with the frame answer and rubric prompts with a safety answer."""

    def ask(self, prompt: str, schema: dict, image_png: bytes | None) -> str:
        self.calls.append(prompt)
        if "categories" in schema["properties"]:
            hit = "stole" in prompt
            return json.dumps(
                {
                    "categories": ["violence"] if hit else [],
                    "reasons": ["a crime"] if hit else [],
                    "unsure": False,
                }
            )
        return json.dumps(ANSWER)


@pytest.fixture(autouse=True)
def no_room(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "make_room", lambda cfg, model: [])


def film_with_shot(root: Path) -> Path:
    film = make_film(root / "demo")
    spec = {**SPEC, "duration_s": 2, "dialogue": []}
    spec["characters"] = [{**SPEC["characters"][0], "actions": [{"motion": "wave", "start_s": 0}]}]
    (film / "shots" / spec["id"]).mkdir(parents=True)
    (film / "shots" / spec["id"] / "shot.json").write_text(json.dumps(spec))
    (film / "film.json").write_text(json.dumps({"premise": "Pip flies a kite."}))
    return root


def run(root: Path, model: Any, calls: list[tuple[str, dict[str, Any]]]) -> list[Any]:
    async def go() -> list[Any]:
        async with Client(create_server(root, client=model)) as client:
            return [await client.call_tool(name, args) for name, args in calls]

    return asyncio.run(go())


def test_tools_have_schemas_and_cleaned_docstrings(tmp_path: Path) -> None:
    async def go() -> list[Any]:
        async with Client(create_server(tmp_path, client=Router())) as client:
            return (await client.list_tools()).tools

    tools = asyncio.run(go())
    assert {t.name for t in tools} == TOOLS
    assert all(t.description and "\n    " not in t.description for t in tools)


def test_check_safety_text_through_the_client(tmp_path: Path) -> None:
    model = Router()
    fine, bad, nothing, mixed = run(
        tmp_path,
        model,
        [
            ("check_safety", {"text": "The bunny hops home."}),
            ("check_safety", {"text": "The fox stole the kite."}),
            ("check_safety", {}),
            ("check_safety", {"film": "demo"}),
        ],
    )
    assert fine.structured_content["ok"] is True
    assert bad.structured_content["ok"] is False
    assert bad.structured_content["text"]["categories"] == ["violence"]
    assert nothing.is_error and "give `text`" in nothing.content[0].text
    assert mixed.is_error and "go together" in mixed.content[0].text
    assert model.unloaded >= 2  # unloaded after every call


def test_ids_are_validated_and_unknown_things_say_what_exists(tmp_path: Path) -> None:
    root = film_with_shot(tmp_path)
    bad_id, no_film, no_shot, late = run(
        root,
        Router(),
        [
            ("check_frame", {"film": "demo", "shot_id": "../x", "time_s": 0}),
            ("check_frame", {"film": "nope", "shot_id": "s01_sh01", "time_s": 0}),
            ("check_frame", {"film": "demo", "shot_id": "s09_sh09", "time_s": 0}),
            ("check_frame", {"film": "demo", "shot_id": "s01_sh01", "time_s": 5}),
        ],
    )
    assert all(r.is_error for r in (bad_id, no_film, no_shot, late))
    assert "no film 'nope'" in no_film.content[0].text
    assert "shots:" in no_shot.content[0].text
    assert "outside the 2" in late.content[0].text


@pytest.mark.render
@pytest.mark.skipif(not has_synfig, reason="no synfig CLI")
def test_check_frame_and_check_film_with_a_fake_model(tmp_path: Path) -> None:
    root = film_with_shot(tmp_path)
    model = Router()
    frame, film = run(
        root,
        model,
        [
            ("check_frame", {"film": "demo", "shot_id": "s01_sh01", "time_s": 0.5}),
            ("check_film", {"film": "demo"}),
        ],
    )
    got = frame.structured_content
    assert got["ok"] and got["code_ok"] and Path(got["frame_path"]).is_file()
    assert {m["what"] for m in got["matches"]} >= {"pip present", "background"}
    whole = film.structured_content
    assert whole["ok"] and whole["premise"]["ok"]
    assert 1 <= len(whole["shots"][0]["frames"]) <= 3
    assert whole["model"] == "fake-vl"


@pytest.mark.models
@pytest.mark.render
@pytest.mark.skipif(not has_synfig, reason="no synfig CLI")
def test_one_real_call_to_the_vision_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # the real make_room: ComfyUI must be idle
    try:
        Ollama(CFG.get("services", "ollama_url")).loaded()
    except OSError:
        pytest.skip("Ollama is not running")
    root = film_with_shot(tmp_path)
    ok, sentence = run(
        root,
        None,
        [
            ("check_frame", {"film": "demo", "shot_id": "s01_sh01", "time_s": 0.5}),
            ("check_safety", {"text": "The bunny and the fox share a carrot and wave goodbye."}),
        ],
    )
    assert not ok.is_error, ok.content[0].text
    assert ok.structured_content["code_ok"] and ok.structured_content["model_seconds"] > 0
    assert sentence.structured_content["ok"] is True
