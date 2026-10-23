"""Backgrounds from text (task 4.6): the ground-band checks on synthetic scenes, and drafts,
choice and finishing with a fake ComfyUI (one real draft is marked `models`)."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image, ImageDraw

from studio_core.comfy_runs import RunRecord, free_comfy
from studio_core.config import expand_path, load_config
from studio_core.film import Film
from studio_core.models import load_manifest
from studio_core.place import design
from studio_core.place.checks import check_plate
from studio_core.place.design import (
    PlaceError,
    choose_background,
    generate_background,
    load_plates,
)
from studio_core.schema import validate_file

SKY, HILLS, GRASS, PATH = (160, 210, 240), (110, 170, 110), (120, 190, 90), (215, 190, 140)


def scene(
    size: tuple[int, int] = (1536, 576), *, rocks: int = 0, pond: bool = False
) -> Image.Image:
    """Sky, hills, a grassy ground band with a path; optionally rocks on it."""
    w, h = size
    img = Image.new("RGB", size, SKY)
    draw = ImageDraw.Draw(img)
    draw.polygon([(0, h * 0.5), (w * 0.3, h * 0.35), (w * 0.7, h * 0.45), (w, h * 0.38),
                  (w, h * 0.6), (0, h * 0.6)], fill=HILLS)  # fmt: skip
    draw.rectangle([0, h * 0.6, w, h], fill=GRASS)
    draw.polygon([(w * 0.45, h * 0.6), (w * 0.55, h * 0.6), (w * 0.7, h), (w * 0.3, h)],
                 fill=PATH)  # fmt: skip
    rng = np.random.default_rng(3)
    for _ in range(rocks):
        x, y = rng.uniform(0, w), rng.uniform(0.8 * h, 0.95 * h)
        r = rng.uniform(0.03, 0.06) * h
        draw.ellipse([x - 2 * r, y - r, x + 2 * r, y + r], fill=(130, 130, 140),
                     outline=(40, 40, 50), width=3)  # fmt: skip
    return img


def test_open_ground_passes() -> None:
    report = check_plate(scene())
    assert report.ok, report.problems
    assert report.ground_edges < 0.05 and report.ground_blocked < 0.05


def test_a_rocky_ground_is_busy() -> None:
    report = check_plate(scene(rocks=40))
    assert any("busy" in p for p in report.problems)


def test_big_flowers_in_front_block_the_ground() -> None:
    img = scene()
    draw = ImageDraw.Draw(img)
    colours = [(235, 90, 150), (230, 60, 60), (250, 220, 70), (250, 250, 250), (170, 90, 220)]
    for i, x in enumerate(range(0, 1536, 110)):  # big flowers of mixed colours along the bottom
        draw.ellipse([x, 470, x + 90, 560], fill=colours[i % len(colours)])
    report = check_plate(img)
    assert any("covers" in p for p in report.problems)


def test_a_flat_picture_has_no_depth() -> None:
    report = check_plate(Image.new("RGB", (1536, 576), GRASS))
    assert any("top and the bottom look alike" in p for p in report.problems)


def test_the_check_reads_plates_too() -> None:
    assert check_plate(scene((2880, 1080))).ok


@pytest.fixture
def film(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[dict]]:
    root = tmp_path / "film"
    Film.create(root, "storybook", load_manifest())
    calls: list[dict] = []

    def run_graph(film_root: Path, kind: str, graph: dict, **kw: Any) -> RunRecord:
        calls.append({"kind": kind, "graph": graph, **kw})
        kw["out_dir"].mkdir(parents=True, exist_ok=True)
        size = (2880, 1080) if kind == "plate" else (1536, 576)
        scene(size, rocks=40 if kw["seed"] == 2 and kind == "background" else 0).save(
            kw["out_dir"] / kw["names"][0]
        )
        record = RunRecord(kind, kw.get("style"), kw["seed"], kw["params"], graph, kw["names"], 9.0)
        record.save(kw["out_dir"])
        return record

    monkeypatch.setattr(design, "run_graph", run_graph)
    return root, calls


def test_drafts_are_checked_and_recorded(film: tuple[Path, list[dict]]) -> None:
    root, calls = film
    made = generate_background(root, "meadow", " a sunny meadow by a forest ", n=2, seed=1)
    assert [(d.id, d.seed, d.ok) for d in made] == [("c1", 1, True), ("c2", 2, False)]
    assert any("busy" in p for p in made[1].problems)
    folder = root / "backgrounds" / "meadow" / "design"
    assert validate_file(folder / "plates.json") == []
    text = {n["_meta"]["title"]: n["inputs"] for n in calls[0]["graph"].values() if "_meta" in n}
    assert "a sunny meadow by a forest, seen from a little way off" in text["positive"]["text"]
    latent = next(n for n in calls[0]["graph"].values() if n["class_type"] == "EmptyLatentImage")
    assert (latent["inputs"]["width"], latent["inputs"]["height"]) == (1536, 576)
    again = generate_background(root, "meadow", "a sunny meadow by a forest", n=1, seed=9)
    assert again[0].id == "c3" and len(load_plates(root, "meadow")["candidates"]) == 3


def test_the_chosen_draft_is_finished_into_the_plate(film: tuple[Path, list[dict]]) -> None:
    root, calls = film
    generate_background(root, "meadow", "a sunny meadow by a forest", n=1, seed=1)
    plate = choose_background(root, "meadow", "c1")
    assert plate == root / "backgrounds" / "meadow" / "plate.png"
    assert Image.open(plate).size == (2880, 1080)
    finish = calls[-1]
    assert finish["kind"] == "plate" and finish["uploads"]["@draft"].name == "draft.png"
    data = load_plates(root, "meadow")
    assert data["chosen"] == "c1" and data["candidates"][0]["plate"] == "c1/plate.png"
    c1 = root / "backgrounds" / "meadow" / "design" / "c1"
    assert (c1 / "plate_run.json").is_file() and not (c1 / "finish").exists()
    with pytest.raises(PlaceError, match="no draft 'c7'"):
        choose_background(root, "meadow", "c7")


@pytest.mark.parametrize(
    ("bg_id", "description", "n", "message"),
    [
        ("Meadow!", "a meadow", 2, "background id 'Meadow!'"),
        ("meadow", "a", 2, "3 to 300 characters"),
        ("meadow", "a meadow with a gun", 2, "uses \\['gun'\\]"),
        ("meadow", "a meadow", 9, "n must be 1 to 8"),
    ],
)
def test_bad_requests_are_refused(
    film: tuple[Path, list[dict]], bg_id: str, description: str, n: int, message: str
) -> None:
    root, calls = film
    with pytest.raises(PlaceError, match=message):
        generate_background(root, bg_id, description, n=n)
    assert calls == []


CFG = load_config()


@pytest.mark.models
@pytest.mark.skipif(not expand_path(CFG.get("comfyui", "python")).exists(), reason="no ComfyUI")
def test_one_real_draft(tmp_path: Path) -> None:
    root = tmp_path / "film"
    Film.create(root, "storybook", load_manifest())
    (made,) = generate_background(root, "meadow", "a sunny meadow", n=1, seed=5)
    folder = root / "backgrounds" / "meadow" / "design"
    assert Image.open(folder / made.draft).size == (1536, 576)
    assert json.loads((folder / "c1" / "draft_checks.json").read_text())["depth_contrast"] > 0
    assert free_comfy()
