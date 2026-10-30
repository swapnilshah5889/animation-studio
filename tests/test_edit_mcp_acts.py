"""edit_mcp's project tools through a real MCP client: build a 3-act film, export all acts, edit one
shot and export again (only that act renders), clear every render and get the same film back."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from project_world import make_project, make_workspace
from test_acts import FakeRenderer, frame_hashes

from edit_mcp.server import create_server
from studio_core import shot_spec


@pytest.fixture
def setup(tmp_path):
    ws = make_workspace(tmp_path)
    make_project(ws)
    return ws, FakeRenderer()


def call(ws, fake, calls: list[tuple[str, dict[str, Any]]]) -> list[Any]:
    async def go() -> list[Any]:
        async with Client(create_server(workspace=ws, renderer=fake)) as client:
            return [await client.call_tool(name, args) for name, args in calls]

    return asyncio.run(go())


def ok(result: Any) -> dict[str, Any]:
    assert not result.is_error, result.content[0].text
    return result.structured_content


def error(result: Any) -> str:
    assert result.is_error
    return result.content[0].text


P = {"project": "pip-world", "film": "tale"}


def build_film(ws, fake) -> None:
    results = call(
        ws,
        fake,
        [
            ("create_film", {"film": "tale", "title": "A Tale", "project": "pip-world"}),
            ("add_act", {**P, "title": "Morning", "background": "meadow"}),
            ("add_act", {**P, "title": "Noon", "background": "hill"}),
            ("add_act", {**P, "title": "Night", "background": "pond"}),
        ],
    )
    for r in results:
        ok(r)
    for n, place in enumerate(("meadow", "hill", "pond"), start=1):
        folder = ws.open_film("tale", "pip-world", act=str(n))
        for k in range(1, 4):  # three camera angles per act
            sid = f"s{n:02d}_sh{k:02d}"
            shot_spec.create_shot(folder, sid, 1.0, place)
            shot_spec.place_character(folder, sid, "pip", [0.3 * k, 0.9])


def test_describe_project_and_create_film_use_the_library(setup):
    ws, fake = setup
    info = ok(call(ws, fake, [("describe_project", {"project": "pip-world"})])[0])
    assert info["characters"] == ["pip"] and sorted(info["places"]) == ["hill", "meadow", "pond"]
    build_film(ws, fake)
    acts = ok(call(ws, fake, [("list_acts", {**P, "quality": "preview"})])[0])
    assert [a["title"] for a in acts["acts"]] == ["Morning", "Noon", "Night"]
    assert [len(a["shots"]) for a in acts["acts"]] == [3, 3, 3]
    assert [a["background"] for a in acts["acts"]] == ["meadow", "hill", "pond"]
    assert acts["stale_acts"] == ["Morning", "Noon", "Night"]


def test_three_acts_export_edit_one_shot_clear_and_get_the_same_film(setup):
    ws, fake = setup
    build_film(ws, fake)
    first = ok(call(ws, fake, [("export_movie", {**P, "quality": "preview"})])[0])
    assert first["rendered_acts"] == ["Morning", "Noon", "Night"] and first["checks_passed"]
    assert len(fake.calls) == 9
    movie = Path(first["final_path"])
    before = frame_hashes(movie)

    fake.calls.clear()
    folder = ws.open_film("tale", "pip-world")
    shot_spec.add_expression(folder, "s02_sh02", "pip", "happy", 0.0)
    stale = ok(call(ws, fake, [("list_acts", {**P, "quality": "preview"})])[0])
    assert stale["stale_acts"] == ["Noon"]
    second = ok(call(ws, fake, [("export_movie", {**P, "quality": "preview"})])[0])
    assert second["rendered_acts"] == ["Noon"] and second["reused_acts"] == ["Morning", "Night"]
    assert fake.calls == ["s02_sh01", "s02_sh02", "s02_sh03"]
    edited = frame_hashes(movie)
    assert edited != before  # the edited shot changed the picture

    ok(call(ws, fake, [("render_act", {**P, "act": "Noon", "quality": "preview"})])[0])
    cleared = ok(call(ws, fake, [("clear_renders", P)])[0])
    assert cleared["stale_acts"] == ["Morning", "Noon", "Night"]
    assert not movie.exists()
    fake.calls.clear()
    third = ok(call(ws, fake, [("export_movie", {**P, "quality": "preview"})])[0])
    assert len(fake.calls) == 9 and frame_hashes(Path(third["final_path"])) == edited
    assert (
        third["act_order"] == ["Morning", "Noon", "Night"] and abs(third["duration_s"] - 9.0) < 0.3
    )


def test_editing_acts_and_shots_changes_what_is_stale(setup):
    ws, fake = setup
    build_film(ws, fake)
    ok(call(ws, fake, [("export_movie", {**P, "quality": "preview"})])[0])
    out = call(
        ws,
        fake,
        [
            ("reorder_acts", {**P, "acts": ["Night", "Morning", "Noon"]}),
            ("edit_act", {**P, "act": "Morning", "title": "Dawn"}),  # story only: not stale
        ],
    )
    reordered = ok(out[0])
    assert [a["title"] for a in reordered["acts"]] == ["Night", "Morning", "Noon"]
    assert reordered["stale_acts"] == ["Night", "Morning", "Noon"]  # default quality is final
    q = ok(call(ws, fake, [("list_acts", {**P, "quality": "preview"})])[0])
    assert q["stale_acts"] == [] and [a["title"] for a in q["acts"]][1] == "Dawn"
    shots = ok(
        call(
            ws,
            fake,
            [
                (
                    "reorder_shots",
                    {**P, "act": "Dawn", "shots": ["s01_sh03", "s01_sh01", "s01_sh02"]},
                )
            ],
        )[0]
    )
    assert [s["shot_id"] for s in shots["shots"]] == ["s01_sh03", "s01_sh01", "s01_sh02"]
    assert shots["stale"] is True  # the final-quality view: never rendered; preview below
    removed = ok(call(ws, fake, [("remove_shot", {**P, "act": "Dawn", "shot_id": "s01_sh02"})])[0])
    assert len(removed["shots"]) == 2
    q = ok(call(ws, fake, [("list_acts", {**P, "quality": "preview"})])[0])
    assert q["stale_acts"] == ["Dawn"]
    result = ok(call(ws, fake, [("export_movie", {**P, "quality": "preview"})])[0])
    assert result["act_order"] == ["Night", "Dawn", "Noon"] and result["rendered_acts"] == ["Dawn"]


def test_refusals_say_what_to_fix(setup):
    ws, fake = setup
    build_film(ws, fake)
    r = call(
        ws,
        fake,
        [
            ("export_movie", {"project": "nope", "film": "tale"}),
            ("render_act", {**P, "act": "Dusk"}),
            ("add_act", {**P, "title": "X", "background": "no-such-place"}),
            ("reorder_acts", {**P, "acts": ["Morning"]}),
            ("export_movie", {**P, "start_title": "a bloody mess"}),
        ],
    )
    assert "no project 'nope'" in error(r[0])
    assert "no act 'Dusk'" in error(r[1])
    assert "no-such-place" in error(r[2])
    assert "every act" in error(r[3])
    assert "not suitable" in error(r[4])
