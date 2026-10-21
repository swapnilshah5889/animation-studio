"""synfig_mcp through a real MCP client: tool listing and schemas, the edit flow, fixable
errors, renders, and the stdio transport (task 2.7)."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import Client, StdioServerParameters
from PIL import Image
from test_shot import make_film

from studio_core.config import load_config
from studio_core.motions import MOTIONS
from synfig_mcp.server import create_server

TOOLS = {
    "describe_film",
    "describe_shot",
    "create_scene",
    "add_character",
    "apply_motion",
    "pose_at",
    "set_expression",
    "apply_lipsync",
    "add_parallax_background",
    "camera_move",
    "remove_from_shot",
    "build_rig",
    "render_preview_frame",
    "render_shot",
}
needs_synfig = pytest.mark.skipif(
    not load_config().path("tools", "synfig").exists(), reason="no synfig CLI"
)


def films(tmp_path: Path) -> Path:
    make_film(tmp_path / "demo")
    return tmp_path


def run(films_root: Path, calls: list[tuple[str, dict[str, Any]]]) -> list[Any]:
    """Call tools in order through an in-process client; returns the CallToolResults."""

    async def go() -> list[Any]:
        async with Client(create_server(films_root)) as client:
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
        assert len(tool.description or "") > 40, tool.name
        assert "synfig" not in json.dumps(tool.input_schema).lower(), tool.name  # D-030
    motion = tools["apply_motion"].input_schema["properties"]["motion"]
    assert set(motion["enum"]) == set(MOTIONS)
    assert tools["describe_shot"].output_schema is not None  # structured results


def test_build_a_shot_step_by_step(tmp_path: Path) -> None:
    shot = {"film": "demo", "shot_id": "s01_sh01"}
    pip = {**shot, "character_id": "pip"}
    results = run(
        films(tmp_path),
        [
            ("describe_film", {"film": "demo"}),
            ("create_scene", {**shot, "duration_s": 10, "background": "meadow"}),
            ("add_character", {**pip, "position": [0.5, 0.92]}),
            ("apply_motion", {**pip, "motion": "blink", "start_s": 0, "duration_s": 10}),
            ("apply_motion", {**pip, "motion": "idle_breathe", "start_s": 0}),
            (
                "apply_motion",
                {**pip, "motion": "wave", "start_s": 1, "side": "left", "energy": 0.7, "cycles": 3},
            ),
            ("set_expression", {**pip, "expr": "happy", "start_s": 0}),
            ("apply_lipsync", {**pip, "line_id": "l001", "start_s": 1.5}),
            ("pose_at", {**pip, "time_s": 8, "bone_angles": {"head": 10}}),
            ("camera_move", {**shot, "move": "slow_pan_right"}),
            ("describe_shot", shot),
        ],
    )
    film = ok(results[0])
    assert film["characters"][0]["views"]["front"][0] == "forearm_l"
    assert film["dialogue_lines"][0]["text"].startswith("Hi Bunny!")
    assert "wave" in film["motions"] and "meadow (1.0)" in film["backgrounds"][0]["layers"]
    for r in results[1:-1]:
        assert ok(r)["warnings"] == [] or r is results[2]  # pip doesn't blink until step 4
    desc = ok(results[-1])
    assert desc["errors"] == [] and desc["warnings"] == [] and desc["n_frames"] == 240
    spec = desc["spec"]
    assert spec["camera"] == {"move": "slow_pan_right"}
    assert [a["motion"] for a in spec["characters"][0]["actions"]] == [
        "blink",
        "idle_breathe",
        "wave",
    ]
    assert spec["characters"][0]["actions"][2]["params"] == {
        "side": "left",
        "energy": 0.7,
        "cycles": 3,
    }
    assert spec["dialogue"][0]["line_id"] == "l001"
    assert desc["files"]["shot.mp4"] is None


def test_errors_are_fixable_messages(tmp_path: Path) -> None:
    shot = {"film": "demo", "shot_id": "s01_sh01"}
    pip = {**shot, "character_id": "pip"}
    results = run(
        films(tmp_path),
        [
            ("describe_film", {"film": "kite"}),
            ("describe_shot", shot),
            ("create_scene", {**shot, "duration_s": 4, "background": "beach"}),
            ("create_scene", {**shot, "duration_s": 4, "background": "meadow"}),
            ("apply_motion", {**pip, "motion": "nod", "start_s": 1}),
            ("add_character", {**pip, "position": [0.5, 0.92]}),
            ("apply_motion", {**pip, "motion": "wavee", "start_s": 1}),
            ("pose_at", {**pip, "time_s": 1, "bone_angles": {"tail": 5}}),
            ("remove_from_shot", {**pip, "kind": "action", "index": 0}),
        ],
    )
    assert error(results[0]).endswith("no film 'kite'; films: demo")
    assert "create it with create_scene" in error(results[1]).lower()
    assert "background 'beach' not found; backgrounds: meadow" in error(results[2])
    ok(results[3])
    assert "add it with add_character first" in error(results[4]).lower()
    ok(results[5])
    assert "wave" in error(results[6]) and "idle_breathe" in error(results[6])  # schema enum
    assert "unknown bones ['tail']" in error(results[7])
    assert "out of range: there are 0" in error(results[8])

    # A spec broken outside the tools (edited by hand) is refused before any rendering.
    spec_file = tmp_path / "demo" / "shots" / "s01_sh01" / "shot.json"
    spec_file.write_text(json.dumps({**json.loads(spec_file.read_text()), "background": "beach"}))
    (r,) = run(tmp_path, [("render_shot", {**shot, "quality": "preview"})])
    assert "fix the shot first: background 'beach' not found" in error(r)


def test_build_rig_placeholder(tmp_path: Path) -> None:
    (r,) = run(films(tmp_path), [("build_rig", {"film": "demo", "character_id": "bunny"})])
    rig = ok(r)
    assert rig["placeholder"] and "head" in rig["views"]["front"]
    assert Path(rig["rig_path"]) == tmp_path / "demo" / "characters" / "bunny" / "rig.json"


@pytest.mark.render
@needs_synfig
def test_render_tools(tmp_path: Path) -> None:
    shot = {"film": "demo", "shot_id": "s01_sh01"}
    pip = {**shot, "character_id": "pip"}
    results = run(
        films(tmp_path),
        [
            ("create_scene", {**shot, "duration_s": 1, "background": "meadow"}),
            ("add_character", {**pip, "position": [0.5, 0.92]}),
            ("apply_motion", {**pip, "motion": "wave", "start_s": 0}),
            ("apply_lipsync", {**pip, "line_id": "l001", "start_s": 0}),
            ("render_preview_frame", {**shot, "time_s": 0.5, "scale": 0.1}),
            ("render_preview_frame", {**shot, "time_s": 3}),
            ("render_shot", {**shot, "quality": "preview"}),
            ("describe_shot", shot),
        ],
    )
    preview = ok(results[4])
    assert preview["frame"] == 12 and Image.open(preview["image_path"]).size == (192, 108)
    assert "time 3.0s is outside the 1.0s shot" in error(results[5])
    video = ok(results[6])
    assert video["frames"] == 24 and video["size"] == [640, 360]
    assert Path(video["video_path"]).is_file() and Path(video["scene_path"]).is_file()
    assert ok(results[7])["files"]["shot.mp4"] == video["video_path"]


def test_stdio_transport_lists_the_tools() -> None:
    params = StdioServerParameters(command=sys.executable, args=["-m", "synfig_mcp.server"])

    async def go() -> set[str]:
        async with Client(params) as client:
            return {t.name for t in (await client.list_tools()).tools}

    assert asyncio.run(go()) == TOOLS
