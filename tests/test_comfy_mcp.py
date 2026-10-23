"""comfy_mcp through a real MCP client (task 4.8): tools and schemas, describe_art's next steps,
design and background rounds (ComfyUI faked at run_graph, so the real round code runs), builds,
layers and previews mapped to results (their studio_core functions faked), refusals, one art job
at a time, progress heartbeats, and the stdio transport. The real art jobs run in task 4.9's
scripted client."""

import asyncio
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from mcp import Client, StdioServerParameters
from PIL import Image
from test_place import scene
from test_puppet_design import FRONT, SIDE, sheet
from test_shot import make_film

from comfy_mcp import server as comfy_server
from comfy_mcp.server import create_server
from studio_core.comfy_runs import RunRecord
from studio_core.place import design as place_design
from studio_core.preview.background import BackgroundPreview, Hole
from studio_core.preview.puppet import PuppetPreview
from studio_core.puppet import design as puppet_design
from studio_core.puppet.build import Built

TOOLS = {
    "describe_art",
    "design_character",
    "choose_design",
    "build_puppet",
    "preview_puppet",
    "generate_background",
    "choose_background",
    "split_depth_layers",
    "preview_background",
}
FIXTURES = Path(__file__).parent / "fixtures"
ID_KIT = {"film": "demo", "character_id": "kit"}
ID_PLACE = {"film": "demo", "background_id": "lake"}
ENGINES = ("synfig", "opentoonz", "comfy", "sdxl", "flux")  # D-030: none in what the model sees


def films(tmp_path: Path) -> Path:
    root = make_film(tmp_path / "demo")
    (root / "film.json").write_text(json.dumps({"style": "storybook"}))
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


def describe(root: Path) -> dict[str, Any]:
    return ok(run(root, [("describe_art", {"film": "demo"})])[0])


@pytest.fixture
def fake_comfy(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """run_graph replaced for design sheets, drafts and plates: writes synthetic images."""
    kinds: list[str] = []

    def run_graph(film_root: Path, kind: str, graph: dict, **kw: Any) -> RunRecord:
        kinds.append(kind)
        kw["out_dir"].mkdir(parents=True, exist_ok=True)
        if kind == "design":
            image = sheet(FRONT, SIDE)
        else:
            image = scene((2880, 1080) if kind == "plate" else (1536, 576))
        image.save(kw["out_dir"] / kw["names"][0])
        record = RunRecord(kind, kw.get("style"), kw["seed"], kw["params"], graph, kw["names"], 2.0)
        record.save(kw["out_dir"])
        return record

    monkeypatch.setattr(puppet_design, "run_graph", run_graph)
    monkeypatch.setattr(place_design, "run_graph", run_graph)
    return kinds


def test_tools_are_listed_with_descriptions_and_no_engine_names(tmp_path: Path) -> None:
    async def go() -> list[Any]:
        async with Client(create_server(tmp_path)) as client:
            return (await client.list_tools()).tools

    tools = {t.name: t for t in asyncio.run(go())}
    assert set(tools) == TOOLS
    for t in tools.values():
        assert t.description and len(t.description) > 80, t.name
        assert "ctx" not in t.input_schema["properties"], t.name
        seen = (t.name + t.description + json.dumps(t.input_schema)).lower()
        assert not [e for e in ENGINES if e in seen], t.name
    moves = tools["preview_background"].input_schema["properties"]["move"]["enum"]
    assert "slow_pan_right" in moves
    assert tools["choose_design"].input_schema["properties"]["candidate_id"]["pattern"]


def test_describe_a_film_with_hand_made_art(tmp_path: Path) -> None:
    art = describe(films(tmp_path))
    assert art["style"] == "storybook" and art["style_locked"]
    assert {"storybook", "cutecartoon"} <= {s["id"] for s in art["styles"]}
    (pip,) = art["characters"]
    assert pip["id"] == "pip" and pip["views"] and not pip["candidates"]
    assert pip["next_step"].startswith("ready (a hand-made puppet)")
    (meadow,) = art["backgrounds"]
    assert meadow["layers"] and meadow["next_step"].startswith("ready (a hand-made background)")
    assert Path(meadow["layers"][0]["image_path"]).is_file()


def test_design_round_choose_and_next_steps(tmp_path: Path, fake_comfy: list[str]) -> None:
    root = films(tmp_path)
    news: list[str] = []

    async def go() -> Any:
        async with Client(create_server(root)) as client:

            async def progress(p: float, total: float | None, message: str | None) -> None:
                news.append(message or "")

            args = {"film": "demo", "character_id": "kit", "description": "a small fox", "n": 2}
            return await client.call_tool("design_character", args, progress_callback=progress)

    made = ok(asyncio.run(go()))
    assert [c["candidate_id"] for c in made["candidates"]] == ["c1", "c2"]
    assert all(Path(c["image_path"]).is_file() for c in made["candidates"])
    assert made["all_candidates"] == ["c1", "c2"] and made["style"] == "storybook"
    assert any(m.startswith("c1 drawn") for m in news) and any("c2 drawn" in m for m in news)
    kit = next(c for c in describe(root)["characters"] if c["id"] == "kit")
    assert kit["next_step"] == "look at the sheets, then choose_design" and kit["rig_path"] is None

    chosen = ok(run(root, [("choose_design", {**ID_KIT, "candidate_id": "c2"})])[0])
    assert chosen["image_path"].endswith("design/c2/sheet.png") and chosen["ok"]
    kit = next(c for c in describe(root)["characters"] if c["id"] == "kit")
    assert kit["chosen"] == "c2" and kit["next_step"] == "build_puppet (from c2)"
    assert fake_comfy == ["design", "design"]


def test_background_round_and_plate(tmp_path: Path, fake_comfy: list[str]) -> None:
    root = films(tmp_path)
    args = {**ID_PLACE, "description": "a calm lake with hills", "n": 1, "seed": 4}
    made, plate = run(
        root,
        [
            ("generate_background", args),
            ("choose_background", {**ID_PLACE, "candidate_id": "c1"}),
        ],
    )
    drafts = ok(made)
    assert [d["candidate_id"] for d in drafts["drafts"]] == ["c1"] and drafts["drafts"][0][
        "seed"
    ] == 4
    finished = ok(plate)
    assert Image.open(finished["plate_path"]).size == (2880, 1080)
    assert finished["plate_path"] == str(root / "demo/backgrounds/lake/plate.png")
    lake = next(b for b in describe(root)["backgrounds"] if b["id"] == "lake")
    assert lake["chosen"] == "c1" and lake["next_step"] == "split_depth_layers"
    assert lake["drafts"][0]["plate_path"].endswith("c1/plate.png")
    assert fake_comfy == ["background", "plate"]


def fake_build(film_root: Path, character_id: str, *, name: str | None = None) -> Built:
    """Pip's rig registered under the new id, with a build report like a real one."""
    folder = film_root / "characters" / character_id
    pip = FIXTURES / "characters" / "pip"
    for item in ("parts", "rig.json"):
        src = pip / item
        if src.is_dir():
            shutil.copytree(src, folder / item, dirs_exist_ok=True)
        else:
            shutil.copy(src, folder / item)
    rig = json.loads((folder / "rig.json").read_text())
    rig.update(id=character_id, name=name or character_id.title())
    (folder / "rig.json").write_text(json.dumps(rig))
    view = {"limbs_ok": False, "limbs": {"forearm_l": {"ok": False}, "shin_l": {"ok": True}}}
    report = {
        "candidate": "c2",
        "three_quarter_source": {"method": "redrawn from the front"},
        "views": {v: {**view, "face": {"eyes_found": ["left"]}} for v in rig["views"]},
        "consistency": {"ok": True, "problems": []},
    }
    (folder / "build").mkdir(exist_ok=True)
    (folder / "build" / "report.json").write_text(json.dumps(report))
    return Built(rig, folder / "rig.json", report)


def test_build_puppet_result(
    tmp_path: Path, fake_comfy: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = films(tmp_path)
    monkeypatch.setattr(comfy_server, "run_build", fake_build)
    calls = [
        ("design_character", {**ID_KIT, "description": "a small fox", "n": 2}),
        ("choose_design", {**ID_KIT, "candidate_id": "c2"}),
        ("build_puppet", {**ID_KIT, "name": "Kit"}),
    ]
    built = ok(run(root, calls)[-1])
    assert built["name"] == "Kit" and built["candidate"] == "c2"
    assert built["rig_path"] == str(root / "demo/characters/kit/rig.json")
    view = built["views"][0]
    assert view["bones"] and view["parts"] > 0 and not view["limbs_ok"]
    assert view["loose_limbs"] == ["forearm_l"] and view["eyes_found"] == ["left"]
    assert built["views_consistent"] and built["three_quarter_from"] == "redrawn from the front"
    kit = next(c for c in describe(root)["characters"] if c["id"] == "kit")
    assert kit["built_from"] == "c2" and kit["views"]
    assert kit["next_step"].startswith("ready: add_character; cast a voice")


def fake_split(film_root: Path, background_id: str, **kw: Any) -> Path:
    folder = film_root / "backgrounds" / background_id
    shutil.copytree(FIXTURES / "backgrounds" / "meadow", folder, dirs_exist_ok=True)
    (folder / "build").mkdir(exist_ok=True)
    (folder / "build" / "layers_report.json").write_text(json.dumps({"filled": ["sky", "far"]}))
    return folder / "layers.json"


def test_split_depth_layers_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = films(tmp_path)
    monkeypatch.setattr(comfy_server, "run_split", fake_split)
    layers = ok(run(root, [("split_depth_layers", ID_PLACE)])[0])
    assert layers["layers_path"] == str(root / "demo/backgrounds/lake/layers.json")
    assert layers["layers"][0]["name"] == "sky" and layers["filled"] == ["sky", "far"]
    assert layers["bands_image"].endswith("lake/build/bands.png")


def test_previews_report_inside_the_film(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = films(tmp_path)
    shot = root / "demo" / "shots"
    seen: dict[str, Any] = {}

    def puppet(film: Any, cid: str, **kw: Any) -> PuppetPreview:
        seen["puppet"] = kw
        kw["log"]("rendering")
        return PuppetPreview(
            shot_id="s00_sh01", video=shot / "s00_sh01/shot.mp4",
            contact_sheet=shot / "s00_sh01/contact_sheet.png", shot_dir=shot / "s00_sh01",
            view=kw["view"], facing="right", scale=1.1, duration_s=7.0, line_id="l002",
            line_cached=True, voice="af_bella", key_frames=[("rest", 0), ("wave peak", 40)],
            warnings=[], seconds=42.0,
        )  # fmt: skip

    def place(film: Any, bid: str, **kw: Any) -> BackgroundPreview:
        seen["place"] = kw
        return BackgroundPreview(
            shot_id="s00_sh02", video=shot / "s00_sh02/shot.mp4",
            contact_sheet=shot / "s00_sh02/contact_sheet.png", shot_dir=shot / "s00_sh02",
            background_id=bid, move=kw["move"], seconds_long=kw["seconds"],
            character=kw["character"], scale=None, sentinel="#ff00ff", sampled=40,
            holes=[Hole(12, 300, (0, 0, 10, 30))], edges=[], verdicts=["holes: 1 frame"],
            layer_table=["sky 0.05 ..."], warnings=[], seconds=30.0,
        )  # fmt: skip

    monkeypatch.setattr(comfy_server, "run_preview_puppet", puppet)
    monkeypatch.setattr(comfy_server, "run_preview_background", place)
    args = {"film": "demo", "background_id": "meadow", "move": "slow_pan_left", "duration_s": 4}
    p, b = run(
        root,
        [
            ("preview_puppet", {**ID_KIT, "view": "three_quarter"}),
            ("preview_background", {**args, "character_id": "kit", "quality": "final"}),
        ],
    )
    puppet_out, place_out = ok(p), ok(b)
    assert puppet_out["video_path"].startswith(str(root / "demo"))
    assert puppet_out["key_frames"][1] == {"label": "wave peak", "frame": 40}
    assert seen["puppet"]["size"] == (640, 360) and seen["puppet"]["view"] == "three_quarter"
    assert not place_out["ok"] and place_out["holes"] == [{"frame": 12, "pixels": 300}]
    assert seen["place"]["size"] == (1920, 1080) and seen["place"]["character"] == "kit"
    assert place_out["move"] == "slow_pan_left" and place_out["duration_s"] == 4


def test_refusals_say_what_to_fix(tmp_path: Path, fake_comfy: list[str]) -> None:
    root = films(tmp_path)
    results = run(
        root,
        [
            ("describe_art", {"film": "nope"}),
            ("design_character", {**ID_KIT, "description": "a bloody fox"}),
            ("design_character", {"film": "demo", "character_id": "pip", "description": "a fox"}),
            ("design_character", {"film": "demo", "character_id": "Kit!", "description": "a fox"}),
            ("choose_design", {**ID_KIT, "candidate_id": "c1"}),
            ("build_puppet", ID_KIT),
            ("generate_background", {**ID_PLACE, "description": "a lake", "n": 9}),
            ("choose_background", {**ID_PLACE, "candidate_id": "c1"}),
            ("split_depth_layers", ID_PLACE),
            ("preview_puppet", {"film": "demo", "character_id": "pip"}),
            ("preview_puppet", ID_KIT),
            ("preview_background", ID_PLACE),
        ],
    )
    texts = [error(r) for r in results]
    assert "no film 'nope'" in texts[0]
    assert "bloody" in texts[1] and "children" in texts[1]
    assert "hand-made puppet" in texts[2]
    assert "character_id" in texts[3]
    assert "no design candidates" in texts[4] and "design_character" in texts[4]
    assert "design_character" in texts[5]
    assert "less than or equal to 8" in texts[6]
    assert "no drafts" in texts[7] and "generate_background" in texts[7]
    assert "no plate" in texts[8] and "choose_background" in texts[8]
    assert "reference puppet" in texts[9]
    assert "no rig" in texts[10] and "build the puppet first" in texts[10]
    assert "no background 'lake'" in texts[11]
    assert fake_comfy == []  # nothing reached the GPU


def test_art_jobs_run_one_at_a_time_with_heartbeats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = films(tmp_path)
    spans: list[tuple[float, float]] = []

    def slow_split(film_root: Path, background_id: str, **kw: Any) -> Path:
        start = time.monotonic()
        time.sleep(0.4)
        path = fake_split(film_root, background_id)
        spans.append((start, time.monotonic()))
        return path

    monkeypatch.setattr(comfy_server, "run_split", slow_split)
    monkeypatch.setattr(comfy_server, "HEARTBEAT_S", 0.1)
    news: dict[str, list[tuple[float, str]]] = {"lake": [], "pond": []}

    async def go() -> list[Any]:
        async with Client(create_server(root)) as client:

            def call(bid: str) -> Any:
                async def progress(p: float, total: float | None, message: str | None) -> None:
                    news[bid].append((p, message or ""))

                args = {"film": "demo", "background_id": bid}
                return client.call_tool("split_depth_layers", args, progress_callback=progress)

            return list(await asyncio.gather(call("lake"), call("pond")))

    results = asyncio.run(go())
    assert all(not r.is_error for r in results)
    first, second = sorted(spans)
    assert first[1] <= second[0]  # the second job started after the first ended
    for bid in news:
        values = [p for p, _ in news[bid]]
        assert len(values) >= 3 and values == sorted(values)  # heartbeats, increasing
    waited = [m for bid in news for _, m in news[bid] if m.startswith("waiting for")]
    assert waited  # the second job said it was waiting


def test_stdio_transport_lists_the_tools() -> None:
    params = StdioServerParameters(command=sys.executable, args=["-m", "comfy_mcp.server"])

    async def go() -> set[str]:
        async with Client(params) as client:
            return {t.name for t in (await client.list_tools()).tools}

    assert asyncio.run(go()) == TOOLS
