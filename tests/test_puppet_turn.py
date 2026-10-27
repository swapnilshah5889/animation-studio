"""The three-quarter view redrawn by FLUX.2 klein (D-053): ground shadows dropped, the figure
placed where the rig's three-quarter view goes, the best seed chosen by the cut's own checks,
and the result reused. ComfyUI is faked: "klein" returns synthetic redrawn figures."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image, ImageDraw
from test_puppet_build import BG, draw_character, sheet

from studio_core.comfy_runs import RunRecord
from studio_core.film import Film
from studio_core.models import load_manifest
from studio_core.puppet import turn
from studio_core.puppet.design import CANVAS
from studio_core.puppet.skeleton import place as place_skeleton
from studio_core.puppet.skeleton import turnaround
from studio_core.puppet.turn import drop_shadow, figure_mask, place, turn_design

FRONT, SIDE = turnaround(CANVAS)
KLEIN_BG = (236, 232, 224)  # klein's background is a slightly different cream


def redrawn(sk_view: str = "three_quarter", shadow: bool = True, hat: bool = False) -> np.ndarray:
    """A 'klein' picture: the character on klein's own background, maybe with a ground shadow
    or a hat, at klein's size."""
    sk = place_skeleton(sk_view, height_px=880, feet_px=(448, 980))
    img = Image.new("RGB", turn.SIZE, KLEIN_BG)
    draw = ImageDraw.Draw(img)
    if shadow:
        x, y = sk.joints["sole"]
        draw.ellipse([x - 200, y - 18, x + 200, y + 18], fill=(205, 203, 199))
    draw_character(draw, sk)
    if hat:
        x, y = sk.joints["head_top"]
        draw.ellipse([x - 50, y + 5, x + 50, y + 70], fill=(90, 60, 200))
    return np.asarray(img).astype("float32")


def test_the_ground_shadow_is_dropped() -> None:
    img = redrawn()
    mask, bg = figure_mask(img)
    kept = drop_shadow(img, mask, bg)
    x, y = 448 + 170, 980  # on the shadow, beside the feet
    assert mask[y, x] and not kept[y, x]
    foot = place_skeleton("three_quarter", height_px=880, feet_px=(448, 980)).joints["r_foot"]
    assert kept[int(foot[1]) - 4, int(foot[0])]  # the shoe stays
    assert drop_shadow(redrawn(shadow=False), *figure_mask(redrawn(shadow=False))).sum() == (
        figure_mask(redrawn(shadow=False))[0].sum()
    )  # nothing to drop: nothing dropped


def test_the_redrawn_figure_lands_on_the_three_quarter_skeleton() -> None:
    original = np.asarray(sheet()).astype("float32")
    placed = place(original, redrawn(), height=SIDE.height_px, sk=SIDE)
    half = CANVAS[0] // 2
    assert np.array_equal(placed[:, :half], original[:, :half])  # the front is untouched
    right = placed[:, half:]
    figure = np.linalg.norm(right - np.array(BG, dtype="float32"), axis=2) > 45
    ys = np.nonzero(figure.any(axis=1))[0]
    assert abs(ys.max() - SIDE.joints["sole"][1]) < 4  # soles on the sole
    assert abs((ys.max() - ys.min()) - SIDE.height_px) < 6  # the asked height
    border = np.concatenate([right[:10].reshape(-1, 3), right[-10:].reshape(-1, 3)])
    assert np.abs(border - np.array(BG)).max() < 2  # the sheet's background, not klein's


@pytest.fixture
def film(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[int]]:
    root = tmp_path / "film"
    Film.create(root, "storybook", load_manifest())
    design = root / "characters" / "kit" / "design"
    (design / "c1").mkdir(parents=True)
    sheet().save(design / "c1" / "sheet.png")
    candidate = {
        "id": "c1", "description": "a small fox", "seed": 1, "fast": False,
        "sheet": "c1/sheet.png", "ok": True, "problems": [],
    }  # fmt: skip
    (design / "candidates.json").write_text(json.dumps({
        "schema_version": 1, "character": "kit", "style": "storybook", "chosen": "c1",
        "candidates": [candidate],
    }))  # fmt: skip
    runs: list[int] = []
    pictures = {1: redrawn(hat=True), 2: redrawn(), 3: redrawn("front")}  # hat / good / unturned
    pictures |= {4: redrawn("front"), 5: redrawn("front"), 6: redrawn()}  # the extra seeds

    def run_graph(film_root: Path, kind: str, graph: dict, **kw: Any) -> RunRecord:
        runs.append(kw["seed"])
        kw["out_dir"].mkdir(parents=True, exist_ok=True)
        Image.fromarray(pictures[kw["seed"]].astype("uint8")).save(kw["out_dir"] / "edit.png")
        return RunRecord(kind, None, kw["seed"], kw["params"], graph, ["edit.png"], 150.0)

    monkeypatch.setattr(turn, "run_graph", run_graph)
    return root, runs


def test_the_best_seed_is_chosen_by_the_checks(film: tuple[Path, list[int]]) -> None:
    root, runs = film
    turned = turn_design(root, "kit")
    assert runs == [1, 2, 3]
    assert turned.choice["chosen_seed"] == 2  # not the hat, not the unturned one
    seeds = turned.choice["seeds"]
    assert any(p.startswith("head:") for p in seeds["s1"]["problems"])
    assert seeds["s3"]["turn"] < 0.5 <= seeds["s2"]["turn"]
    assert turned.sheet.is_file() and (turned.sheet.parent / "choice.json").is_file()


def test_the_result_is_reused_unless_asked(film: tuple[Path, list[int]]) -> None:
    root, runs = film
    first = turn_design(root, "kit", seeds=(2,))
    again = turn_design(root, "kit", seeds=(2,))
    assert runs == [2] and again.choice == first.choice
    turn_design(root, "kit", seeds=(2,), regenerate=True)
    assert runs == [2, 2]


def test_the_face_inside_survives_placement() -> None:
    """A pale face inside the head's outline, as pale as the background, is figure: the eye
    inside it must not become a loose island that is dropped."""
    img = Image.new("RGB", turn.SIZE, KLEIN_BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([380, 420, 520, 980], fill=(230, 120, 40), outline=(60, 40, 30), width=5)
    draw.ellipse([300, 100, 600, 420], fill=(230, 120, 40), outline=(60, 40, 30), width=5)
    draw.ellipse([380, 180, 540, 360], fill=KLEIN_BG, outline=(60, 40, 30), width=4)  # face
    draw.ellipse([430, 250, 444, 264], fill=(20, 20, 20))  # an eye
    pic = np.asarray(img).astype("float32")
    mask, bg = figure_mask(pic)
    assert mask[300, 500] and mask[257, 437]  # the face and the eye
    assert drop_shadow(pic, mask, bg)[257, 437]


def test_replace_reuses_the_edits(film: tuple[Path, list[int]]) -> None:
    root, runs = film
    turn_design(root, "kit", seeds=(2, 3))
    turned = turn_design(root, "kit", seeds=(2, 3), replace=True)
    assert runs == [2, 3] and turned.choice["chosen_seed"] == 2


def test_more_seeds_are_tried_until_one_turns_the_figure(film: tuple[Path, list[int]]) -> None:
    root, runs = film
    turned = turn_design(root, "kit", seeds=(3,))  # unturned
    assert runs == [3, 4, 5, 6]  # one extra at a time, stopping at the first that turns enough
    assert turned.choice["chosen_seed"] == 6
    turn_design(root, "kit", seeds=(3,))
    assert runs == [3, 4, 5, 6]  # kept: no more edits


def test_extra_seeds_are_not_tried_when_one_turned_enough(film: tuple[Path, list[int]]) -> None:
    root, runs = film
    turn_design(root, "kit")
    assert runs == [1, 2, 3]


def test_a_kept_result_short_of_the_turn_is_extended(film: tuple[Path, list[int]]) -> None:
    root, _runs = film
    first = turn_design(root, "kit", seeds=(3,), regenerate=True)
    assert first.choice["chosen_seed"] == 6
    # an older result that stopped at the unturned seed: extended the next time it is asked for
    choice = json.loads((first.sheet.parent / "choice.json").read_text())
    for seed in (4, 5, 6):
        del choice["seeds"][f"s{seed}"]
    choice["chosen_seed"] = 3
    (first.sheet.parent / "choice.json").write_text(json.dumps(choice))
    again = turn_design(root, "kit", seeds=(3,))
    assert again.choice["chosen_seed"] == 6
