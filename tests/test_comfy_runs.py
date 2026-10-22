"""ComfyUI plumbing (task 4.1): style choice, the memory guard, uploads, outputs and run records
with a fake ComfyUI, and one real run (marked `models`: starts ComfyUI if needed)."""

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from studio_core import comfy_runs
from studio_core.comfy import ComfyError
from studio_core.comfy_graphs import txt2img
from studio_core.comfy_runs import ImageJobError, film_style, free_comfy, run_graph
from studio_core.config import expand_path, load_config
from studio_core.models import load_manifest

CFG = load_config()
has_comfy = expand_path(CFG.get("comfyui", "python")).exists()


class FakeComfy:
    def __init__(self, fail: bool = False) -> None:
        self.uploaded: list[Path] = []
        self.ran: dict[str, Any] = {}
        self.fail = fail

    def upload_image(self, path: Path) -> str:
        self.uploaded.append(path)
        return f"uploaded_{path.name}"

    def run(self, graph: dict, out_dir: Path) -> tuple[list[Path], float]:
        if self.fail:
            raise ComfyError("node errors: missing model")
        self.ran = graph
        paths = []
        for name in ("b_00001_.png", "a_00001_.png"):
            Image.new("RGB", (8, 8)).save(out_dir / name)
            paths.append(out_dir / name)
        return paths, 1.25

    def system_stats(self) -> dict:
        return {"system": {"comfyui_version": "0.42.1"}}


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeComfy:
    comfy = FakeComfy()
    monkeypatch.setattr(comfy_runs, "make_room_for_images", lambda cfg: [])
    monkeypatch.setattr(comfy_runs, "ensure_comfy", lambda cfg: comfy)
    monkeypatch.setattr(comfy_runs, "comfy_dirs", lambda cfg: None)  # never the real folders
    return comfy


def test_film_style(tmp_path: Path) -> None:
    assert film_style(tmp_path) == CFG.get("comfyui", "default_style")
    (tmp_path / "film.json").write_text(json.dumps({"style": "cutecartoon"}))
    assert film_style(tmp_path) == "cutecartoon"


def test_refused_while_composing_music(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(comfy_runs, "composing_music", lambda: True)
    with pytest.raises(ImageJobError, match="music is being composed"):
        comfy_runs.make_room_for_images(CFG)


def test_run_graph_uploads_renames_and_records(fake: FakeComfy, tmp_path: Path) -> None:
    src = tmp_path / "pose.png"
    Image.new("RGB", (8, 8)).save(src)
    graph = {"1": {"class_type": "LoadImage", "inputs": {"image": "@pose"}}}
    out = tmp_path / "film" / "characters" / "kit" / "design"
    (out).mkdir(parents=True)
    (out / "stale.png").write_text("old")  # a fresh folder every run
    record = run_graph(
        tmp_path,
        "design",
        graph,
        out_dir=out,
        params={"description": "a small fox"},
        seed=7,
        style="storybook",
        names=["candidate_1.png", "candidate_2.png"],
        uploads={"@pose": src},
    )
    assert fake.uploaded == [src]
    assert fake.ran["1"]["inputs"]["image"] == "uploaded_pose.png"
    assert graph["1"]["inputs"]["image"] == "@pose"  # the caller's graph is untouched
    assert sorted(p.name for p in out.iterdir()) == [
        "candidate_1.png",
        "candidate_2.png",
        "run.json",
    ]
    saved = json.loads((out / "run.json").read_text())
    assert saved["kind"] == "design" and saved["seed"] == 7 and saved["style"] == "storybook"
    assert saved["params"] == {"description": "a small fox"} and saved["comfyui"] == "0.42.1"
    assert saved["outputs"] == ["candidate_1.png", "candidate_2.png"] and record.seconds == 1.25


def test_comfys_copies_are_deleted(
    fake: FakeComfy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    comfy_in, comfy_out = tmp_path / "in", tmp_path / "out"
    for folder, names in ((comfy_in, ["uploaded_pose.png", "other.png"]), (comfy_out, [
        "a_00001_.png", "b_00001_.png", "older_00001_.png"])):  # fmt: skip
        folder.mkdir()
        for name in names:
            (folder / name).write_text("x")
    monkeypatch.setattr(comfy_runs, "comfy_dirs", lambda cfg: (comfy_in, comfy_out))
    src = tmp_path / "pose.png"
    Image.new("RGB", (8, 8)).save(src)
    graph = {"1": {"class_type": "LoadImage", "inputs": {"image": "@pose"}}}
    run_graph(tmp_path, "design", graph, out_dir=tmp_path / "run", uploads={"@pose": src})
    assert sorted(p.name for p in comfy_in.iterdir()) == ["other.png"]  # only this run's files
    assert sorted(p.name for p in comfy_out.iterdir()) == ["older_00001_.png"]
    assert len(list((tmp_path / "run").glob("*.png"))) == 2


def test_comfy_errors_become_job_errors(fake: FakeComfy, tmp_path: Path) -> None:
    fake.fail = True
    with pytest.raises(ImageJobError, match="ComfyUI refused the design graph: node errors"):
        run_graph(tmp_path, "design", {}, out_dir=tmp_path / "out")


@pytest.mark.models
@pytest.mark.skipif(not has_comfy, reason="no ComfyUI env")
def test_real_run(tmp_path: Path) -> None:
    graph = txt2img(
        load_manifest(),
        "storybook",
        "a small round red ball on a plain white background",
        fast=True,
        seed=11,
        width=512,
        height=512,
    )
    out = tmp_path / "run"
    record = run_graph(tmp_path, "test", graph, out_dir=out, seed=11, style="storybook")
    (name,) = record.outputs
    assert Image.open(out / name).size == (512, 512)
    saved = json.loads((out / "run.json").read_text())["graph"]
    for node_id, node in graph.items():  # the graph as run: save prefixes carry a run token
        if node["class_type"] == "SaveImage":
            prefix = node["inputs"]["filename_prefix"]
            assert saved[node_id]["inputs"]["filename_prefix"].startswith(prefix + "_")
            saved[node_id]["inputs"]["filename_prefix"] = prefix
    assert saved == graph
    assert free_comfy()
