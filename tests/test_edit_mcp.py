"""edit_mcp end to end: two tiny generated shots (ffmpeg test pattern + tone, like finished
shot.mp4 files) are assembled with a title card and a cross-fade, rendered by melt, and
checked with ffprobe, through a real in-process MCP client."""

import asyncio
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from edit_mcp.server import create_server
from studio_core.audio import ffmpeg
from studio_core.config import load_config
from studio_core.edit.render import probe

CFG = load_config()


def make_shot(film: Path, shot_id: str, seconds: int, hz: int, size: str = "640x360") -> None:
    out = film / "shots" / shot_id / "shot.mp4"
    out.parent.mkdir(parents=True)
    ffmpeg.run(
        [
            *("-f", "lavfi", "-i", f"testsrc2=size={size}:rate=24:duration={seconds}"),
            *("-f", "lavfi", "-i", f"sine=frequency={hz}:sample_rate=48000:duration={seconds}"),
            *("-ac", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)),
        ],
        CFG,
    )


def call(root: Path, calls: list[tuple[str, dict[str, Any]]]) -> list[Any]:
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


def test_tools_are_listed() -> None:
    async def go() -> list[Any]:
        async with Client(create_server(Path("/nonexistent"))) as client:
            return (await client.list_tools()).tools

    tools = {t.name: t for t in asyncio.run(go())}
    assert set(tools) == {
        "create_film",
        "describe_edit",
        "assemble",
        "render_film",
        # projects and acts (Step 5C)
        "describe_project",
        "list_acts",
        "add_act",
        "edit_act",
        "reorder_acts",
        "remove_act",
        "reorder_shots",
        "remove_shot",
        "render_act",
        "export_movie",
        "clear_renders",
    }
    assert all(len(t.description or "") > 40 for t in tools.values())


def test_create_film_writes_film_json_and_refuses_an_existing_film(tmp_path: Path) -> None:
    made, again, bad = call(
        tmp_path,
        [
            ("create_film", {"film": "kite-day", "title": "Kite Day", "style": "storybook"}),
            ("create_film", {"film": "kite-day", "title": "Again"}),
            ("create_film", {"film": "../escape", "title": "No"}),
        ],
    )
    data = ok(made)
    film_json = json.loads(Path(data["film_json_path"]).read_text())
    assert film_json["title"] == "Kite Day" and film_json["style"] == "storybook"
    assert Path(data["film_path"]) == tmp_path / "kite-day"
    assert "already exists" in error(again)
    assert bad.is_error


def test_errors_say_what_to_fix(tmp_path: Path) -> None:
    call(tmp_path, [("create_film", {"film": "f", "title": "F"})])
    nofilm, noshot, nothing, dup = call(
        tmp_path,
        [
            ("describe_edit", {"film": "nope"}),
            ("assemble", {"film": "f", "shots": ["s01_sh01"]}),
            ("render_film", {"film": "f"}),
            ("assemble", {"film": "f", "shots": ["s01_sh01", "s01_sh01"]}),
        ],
    )
    assert "no film 'nope'" in error(nofilm)
    assert "no rendered shot.mp4" in error(noshot)
    assert "run assemble first" in error(nothing)
    assert "twice" in error(dup)


def test_two_shots_become_a_film_with_a_title_card(tmp_path: Path) -> None:
    call(tmp_path, [("create_film", {"film": "mini", "title": "Mini"})])
    film = tmp_path / "mini"
    make_shot(film, "s01_sh01", 3, 440)
    make_shot(film, "s01_sh02", 2, 660)

    (described,) = call(tmp_path, [("describe_edit", {"film": "mini"})])
    d = ok(described)
    assert [s["shot_id"] for s in d["rendered_shots"]] == ["s01_sh01", "s01_sh02"]
    assert d["rendered_shots"][0]["duration_s"] == pytest.approx(3.0, abs=0.1)
    assert d["edit"] is None

    assembled, again, rendered, after = call(
        tmp_path,
        [
            (
                "assemble",
                {
                    "film": "mini",
                    "shots": ["s01_sh01", "s01_sh02"],
                    "titles": [{"text": "Mini Film", "subtitle": "a test", "duration_s": 2}],
                    "transitions": [{"into": "s01_sh02", "type": "crossfade", "duration_s": 0.5}],
                },
            ),
            ("describe_edit", {"film": "mini"}),
            ("render_film", {"film": "mini", "quality": "preview"}),
            ("describe_edit", {"film": "mini"}),
        ],
    )
    a = ok(assembled)
    # 2 s card + 3 s + 2 s shot, one half-second overlap
    assert a["duration_s"] == 6.5 and a["n_frames"] == 156
    assert [c["kind"] for c in a["clips"]] == ["title", "shot", "shot"]
    assert [c["transition_in"] for c in a["clips"]] == [None, "cut", "crossfade"]
    assert Path(a["mlt_path"]).is_file() and Path(a["spec_path"]).is_file()
    assert ok(again)["edit"]["duration_s"] == 6.5

    r = ok(rendered)
    final = Path(r["final_path"])
    assert final == film / "edit" / "final.mp4"
    p = probe(final, CFG)
    assert p.has_video and p.has_audio
    assert (p.width, p.height) == (640, 360)
    assert p.duration_s == pytest.approx(6.5, abs=0.15)
    assert r["checks_passed"], r["problems"]
    loud = ffmpeg.measure(final, CFG)
    assert not math.isinf(loud.integrated_lufs)
    assert abs(loud.integrated_lufs - (-14.0)) <= 1.0  # in range, by gain if the mix was off
    assert ok(after)["edit"]["final_path"] == str(final)


def test_melt_reads_the_project_and_unsuitable_titles_are_refused(tmp_path: Path) -> None:
    call(tmp_path, [("create_film", {"film": "mini", "title": "Mini"})])
    make_shot(tmp_path / "mini", "s01_sh01", 1, 440)
    bad, good = call(
        tmp_path,
        [
            (
                "assemble",
                {"film": "mini", "shots": ["s01_sh01"], "titles": [{"text": "what the hell"}]},
            ),
            ("assemble", {"film": "mini", "shots": ["s01_sh01"]}),
        ],
    )
    assert "not suitable for children" in error(bad)
    mlt = Path(ok(good)["mlt_path"])
    proc = subprocess.run(
        [str(CFG.path("tools", "melt")), str(mlt), "-consumer", "null", "terminate_on_pause=1"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
