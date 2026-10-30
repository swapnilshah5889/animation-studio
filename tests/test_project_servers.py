"""The MCP servers on a project film: shots become camera angles of acts, art is published to the
project library as versions, recordings are kept in the project and make their act stale, and old
film folders keep working (their own tests). Models and the render engine are faked."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from mcp import Client
from project_world import make_project, make_workspace
from test_audio_mix import tone, write
from test_comfy_mcp import fake_build, fake_split

from audio_mcp.server import create_server as audio_server
from comfy_mcp import server as comfy_server
from comfy_mcp.server import create_server as comfy_create
from qa_mcp.server import create_server as qa_server
from studio_core import acts
from studio_core.acts import Target
from studio_core.audio.music import plan
from studio_core.config import load_config
from synfig_mcp.server import create_server as synfig_server

P = {"project": "pip-world", "film": "three-acts"}
CFG = load_config()
has_synfig = CFG.path("tools", "synfig").exists()


def run(factory, ws, calls: list[tuple[str, dict[str, Any]]]) -> list[Any]:
    async def go() -> list[Any]:
        async with Client(factory(workspace=ws)) as client:
            return [await client.call_tool(name, args) for name, args in calls]

    return asyncio.run(go())


def ok(result: Any) -> dict[str, Any]:
    assert not result.is_error, result.content[0].text
    return result.structured_content


def error(result: Any) -> str:
    assert result.is_error
    return result.content[0].text


@pytest.fixture
def world(tmp_path):
    ws = make_workspace(tmp_path)
    project = make_project(ws)
    film = project.create_film(
        "Tale", slug="three-acts", cast=["pip"], places=["meadow", "hill", "pond"]
    )
    for n, place in enumerate(("meadow", "hill", "pond"), start=1):
        project.add_act(film["id"], f"Act {n}", background=place)
    return ws, project, film


# ------------------------------------------------------------------------ synfig_mcp


def test_synfig_shots_become_camera_angles_of_acts(world):
    ws, project, film = world
    r = run(
        synfig_server,
        ws,
        [
            ("create_scene", {**P, "shot_id": "s01_sh01", "duration_s": 2, "background": "meadow"}),
            (
                "create_scene",
                {
                    **P,
                    "shot_id": "s01_sh01",
                    "duration_s": 2,
                    "background": "meadow",
                    "act": "Act 1",
                },
            ),
            (
                "create_scene",
                {**P, "shot_id": "s01_sh02", "duration_s": 2, "background": "meadow", "act": "1"},
            ),
            (
                "create_scene",
                {**P, "shot_id": "s02_sh01", "duration_s": 3, "background": "hill", "act": "Act 2"},
            ),
            (
                "add_character",
                {**P, "shot_id": "s02_sh01", "character_id": "pip", "position": [0.5, 0.9]},
            ),
            (
                "apply_motion",
                {
                    **P,
                    "shot_id": "s02_sh01",
                    "character_id": "pip",
                    "motion": "blink",
                    "start_s": 0,
                    "duration_s": 3,
                },
            ),
            (
                "create_scene",
                {
                    "project": "pip-world",
                    "film": "nope",
                    "shot_id": "s03_sh01",
                    "duration_s": 1,
                    "background": "pond",
                },
            ),
        ],
    )
    assert "several acts" in error(r[0])
    ok(r[1]), ok(r[2]), ok(r[3]), ok(r[4]), ok(r[5])
    assert "no film 'nope' in project pip-world" in error(r[6])
    acts_ = project.list_acts(film["id"])
    assert [len(a["shot_ids"]) for a in acts_] == [2, 1, 0]
    shot = project.list_shots(film["id"], acts_[1]["id"])[0]
    assert shot["spec"]["characters"][0]["actions"][0]["motion"] == "blink"
    # an edit through the tools is an edit of the document: only that act goes stale
    for a in acts_:
        project.record_render(film["id"], a["id"], "e")
    ok(
        run(
            synfig_server,
            ws,
            [
                (
                    "add_character",
                    {**P, "shot_id": "s01_sh02", "character_id": "pip", "position": [0.3, 0.9]},
                )
            ],
        )[0]
    )
    assert [a["title"] for a in project.stale_acts(film["id"], "e")] == ["Act 1"]
    described = ok(run(synfig_server, ws, [("describe_film", P)])[0])
    assert [c["id"] for c in described["characters"]] == ["pip"] and len(described["shots"]) == 3


def test_a_placeholder_rig_is_published_to_the_library(world):
    ws, project, film = world
    ok(run(synfig_server, ws, [("build_rig", {**P, "character_id": "newbie"})])[0])
    assert {c["slug"] for c in project.list_characters()} == {"pip", "newbie"}
    assert {r["id"] for r in project.get_film(film["id"])["cast"]} == {
        project.resolve_character("pip").id,
        project.resolve_character("newbie").id,
    }


@pytest.mark.render
@pytest.mark.skipif(not has_synfig, reason="no synfig CLI")
def test_a_project_film_renders_with_the_real_engine(world):
    ws, _project, _film = world
    run(
        synfig_server,
        ws,
        [
            (
                "create_scene",
                {
                    **P,
                    "shot_id": "s01_sh01",
                    "duration_s": 1,
                    "background": "meadow",
                    "act": "Act 1",
                },
            ),
            (
                "add_character",
                {**P, "shot_id": "s01_sh01", "character_id": "pip", "position": [0.5, 0.9]},
            ),
        ],
    )
    folder = ws.open_film("three-acts", "pip-world")
    result = acts.render_act(
        folder, "Act 1", Target("synfig", "preview"), acts.synfig_renderer(CFG), CFG
    )
    assert result["rendered"] and Path(result["video_path"]).stat().st_size > 1000


# ------------------------------------------------------------------------- audio_mcp


def test_audio_is_kept_in_the_project_and_a_changed_cue_makes_the_act_stale(world):
    ws, project, film = world
    run(
        synfig_server,
        ws,
        [
            (
                "create_scene",
                {
                    **P,
                    "shot_id": "s01_sh01",
                    "duration_s": 4,
                    "background": "meadow",
                    "act": "Act 1",
                },
            )
        ],
    )
    folder = ws.open_film("three-acts", "pip-world")
    music = folder.root / "audio" / "music"
    music.mkdir(parents=True)
    wav = np.repeat(tone(220, 4.0, 48000, 0.1)[:, None], 2, 1).reshape(-1)
    write(music / "m01.wav", wav, 48000, 2)
    (music / "m01.json").write_text(json.dumps({**plan("m01", "calm", 4.0), "cue_id": "m01"}))
    cast = run(
        audio_server,
        ws,
        [
            ("compose", {**P, "cue_id": "m01", "mood": "calm", "duration_s": 4}),  # cached: syncs
            (
                "set_voice",
                {
                    **P,
                    "character_id": "pip",
                    "voices": [{"id": "af_bella"}],
                    "speed": 1.0,
                },
            ),
        ],
    )
    ok(cast[0]), ok(cast[1])
    ok(run(synfig_server, ws, [("set_music", {**P, "shot_id": "s01_sh01", "cue_id": "m01"})])[0])
    act = project.list_acts(film["id"])[0]
    shot = project.list_shots(film["id"], act["id"])[0]
    assert set(shot["audio"]["music"]) == {"m01"}
    for a in project.list_acts(film["id"]):
        project.record_render(film["id"], a["id"], "e")
    # the same cue name with different music: the spec is untouched, the act is stale
    write(music / "m01.wav", wav * 0.5, 48000, 2)  # what a re-composed cue does in the folder
    folder.link.sync_audio()  # ... and what the audio tools do after every call
    assert [a["title"] for a in project.stale_acts(film["id"], "e")] == ["Act 1"]
    # the voice and the cue survive losing the working folder
    shutil.rmtree(ws.work_root)
    again = ws.open_film("three-acts", "pip-world")
    assert (again.root / "audio" / "music" / "m01.wav").is_file()
    assert json.loads((again.root / "characters" / "pip" / "voice.json").read_text())["voices"] == [
        {"id": "af_bella", "weight": 1}
    ]


# ------------------------------------------------------------------------- comfy_mcp


def test_built_art_is_published_to_the_library_and_the_next_film_can_use_it(world, monkeypatch):
    ws, project, _film = world
    monkeypatch.setattr(comfy_server, "run_build", fake_build)
    monkeypatch.setattr(comfy_server, "run_split", fake_split)
    built = ok(
        run(comfy_create, ws, [("build_puppet", {**P, "character_id": "luna", "name": "Luna"})])[0]
    )
    assert built["library_version"] == 1
    again = ok(
        run(comfy_create, ws, [("build_puppet", {**P, "character_id": "luna", "name": "Luna"})])[0]
    )
    assert again["library_version"] == 1  # same files: no new version
    layers = ok(run(comfy_create, ws, [("split_depth_layers", {**P, "background_id": "lake"})])[0])
    assert layers["library_version"] == 1
    assert {c["slug"] for c in project.list_characters()} == {"pip", "luna"}
    assert "lake" in {b["slug"] for b in project.list_backgrounds()}
    art = ok(run(comfy_create, ws, [("describe_art", P)])[0])
    assert set(art["library"]["characters"]) == {"pip", "luna"} and art["library"]["films"] == [
        "three-acts"
    ]
    # a second film of the project starts with the library: no copying, same asset ids
    second = project.create_film("Tale two", slug="tale-two", cast=["luna", "pip"], places=["lake"])
    folder = ws.open_film("tale-two", "pip-world")
    assert folder.characters() == ["luna", "pip"] and folder.backgrounds() == ["lake"]
    assert (
        project.resolve_character("luna").files["rig.json"]["id"]
        == project.resolve_ref("character", second["cast"][0]).files["rig.json"]["id"]
    )


# --------------------------------------------------------------------------- qa_mcp


def test_qa_names_what_exists_in_a_project(world):
    ws, _project, _film = world
    r = run(
        qa_server,
        ws,
        [
            (
                "check_frame",
                {"project": "nope", "film": "three-acts", "shot_id": "s01_sh01", "time_s": 0},
            ),
            ("check_frame", {**P, "shot_id": "s09_sh09", "time_s": 0}),
        ],
    )
    assert "no project 'nope'" in error(r[0])
    assert "no shot 's09_sh09'" in error(r[1])
