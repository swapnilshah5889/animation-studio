"""Character designs (task 4.3): the pixel checks on synthetic sheets drawn from the skeleton,
the bookkeeping of design rounds with a fake ComfyUI, and one real candidate (marked `models`)."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageOps

from studio_core.comfy_runs import RunRecord, free_comfy
from studio_core.config import expand_path, load_config
from studio_core.puppet import design
from studio_core.puppet.checks import check_sheet, fill_holes, silhouette
from studio_core.puppet.design import (
    DesignError,
    choose_design,
    design_character,
    load_candidates,
    recheck,
)
from studio_core.puppet.skeleton import Skeleton, mannequin_image, place, turnaround
from studio_core.schema import validate_file

CANVAS = design.CANVAS
FRONT, SIDE = turnaround(CANVAS)
FUR = (230, 120, 40)
SEGMENTS = (
    ("r_shoulder", "r_elbow"), ("r_elbow", "r_wrist"), ("r_wrist", "r_hand"),
    ("l_shoulder", "l_elbow"), ("l_elbow", "l_wrist"), ("l_wrist", "l_hand"),
    ("r_hip", "r_knee"), ("r_knee", "r_ankle"), ("r_ankle", "r_foot"),
    ("l_hip", "l_knee"), ("l_knee", "l_ankle"), ("l_ankle", "l_foot"),
)  # fmt: skip


def draw_figure(draw: ImageDraw.ImageDraw, sk: Skeleton) -> None:
    """A flat cartoon body on the skeleton: oval head, torso quad, thick limbs."""
    j = sk.joints
    (nx, ny), (_, ty) = j["neck"], j["head_top"]
    r = (ny - ty) / 2
    draw.ellipse([nx - 0.8 * r, ty, nx + 0.8 * r, ny + 0.1 * r], fill=FUR)
    draw.polygon([j["r_shoulder"], j["l_shoulder"], j["l_hip"], j["r_hip"]], fill=FUR)
    draw.line([j["neck"], j["pelvis"]], fill=FUR, width=int(sk.height_px * 0.1))
    for a, b in SEGMENTS:
        draw.line([j[a], j[b]], fill=FUR, width=int(sk.height_px * 0.05))


def sheet(*skeletons: Skeleton) -> Image.Image:
    img = Image.new("RGB", CANVAS, (250, 250, 248))
    draw = ImageDraw.Draw(img)
    for sk in skeletons:
        draw_figure(draw, sk)
    return img


def test_a_clean_sheet_passes() -> None:
    report = check_sheet(sheet(FRONT, SIDE), [FRONT, SIDE])
    assert report.problems == []
    assert report.background_plain == 1.0 and report.background_rgb == (250, 250, 248)
    for fig in report.figures:
        assert fig.found and 0.95 < fig.height_ratio < 1.1 and fig.joints_inside == 1.0
        assert fig.joints_off == []
    assert report.figures[0].limbs_clear is True and report.figures[1].limbs_clear is None


def test_light_clothes_split_the_silhouette_not_the_figure() -> None:
    img = sheet(FRONT, SIDE)
    j = FRONT.joints
    shirt = [j["r_shoulder"][0] - 30, j["neck"][1] + 20, j["l_shoulder"][0] + 30, j["pelvis"][1]]
    ImageDraw.Draw(img).rectangle(shirt, fill=(244, 244, 240))  # near the background colour
    report = check_sheet(img, [FRONT, SIDE])
    assert report.problems == [] and report.figures[0].joints_inside > 0.85


def test_background_seen_through_the_figure_stays_open() -> None:
    """Legs whose feet touch enclose a gap of background: it isn't figure. A pale chest (cream
    on a cream background, like Kit's white fur) is enclosed too, and it is figure."""
    bg = np.array([250, 245, 238], dtype="float32")
    img = np.full((120, 100, 3), bg, dtype="float32")
    img[10:60, 20:80] = (200, 120, 60)  # the body
    img[25:45, 35:65] = (226, 212, 196)  # a pale chest, about 40 from the background
    img[60:110, 20:35] = img[60:110, 65:80] = (200, 120, 60)  # two legs
    img[100:110, 35:65] = (200, 120, 60)  # the feet touch
    img[70:95, 45:55] = bg + 4  # a speck of the gap in a slightly different tone
    img[12:22, 62:76] = bg  # a face as pale as the background, with an eye in it
    img[16:18, 66:68] = (30, 30, 30)
    mask = silhouette(img, bg)
    filled = fill_holes(mask, img, bg)
    assert filled[35, 50] and not filled[80, 50]  # the chest is figure, the gap is not
    assert filled[13, 64]  # the pale face surrounds its eye: figure
    assert fill_holes(mask)[80, 50]  # without the colours, every enclosed region fills


def test_white_clothes_just_off_the_background_are_figure() -> None:
    """A white shirt and sleeves on a near-white background (Pim, the bird: 13-15 from it)
    are enclosed by their outline and surround nothing, but they are figure, not a gap."""
    bg = np.array([242, 242, 240], dtype="float32")
    img = np.full((120, 100, 3), bg, dtype="float32")
    img[10:20, 20:80] = (200, 120, 60)  # the outline's top
    img[100:110, 20:80] = (200, 120, 60)  # and bottom
    img[10:110, 20:30] = img[10:110, 70:80] = (200, 120, 60)  # and sides
    img[20:100, 30:70] = (252, 245, 233)  # the shirt: about 13 from the background
    mask = silhouette(img, bg)
    assert fill_holes(mask, img, bg)[60, 50]


def test_a_busy_background_is_reported() -> None:
    img = np.asarray(sheet(FRONT, SIDE)).copy()
    noise = np.random.default_rng(1).integers(0, 255, img.shape, dtype=np.uint8)
    img[:40], img[-40:] = noise[:40], noise[-40:]
    report = check_sheet(Image.fromarray(img), [FRONT, SIDE])
    assert any("background isn't plain" in p for p in report.problems)


def test_an_arm_against_the_body_is_reported() -> None:
    img = sheet(FRONT, SIDE)
    j = FRONT.joints
    ImageDraw.Draw(img).line([j["l_wrist"], j["l_hip"]], fill=FUR, width=40)  # hand on hip
    report = check_sheet(img, [FRONT, SIDE])
    assert report.problems == [
        "front: an arm or hand touches the body or tail (it can't be cut free)"
    ]


def test_a_missing_view_is_reported() -> None:
    report = check_sheet(sheet(FRONT), [FRONT, SIDE])
    assert report.problems == ["three_quarter: no figure where the skeleton is"]


def test_a_figure_off_the_pose_is_reported() -> None:
    small = place("three_quarter", height_px=FRONT.height_px * 0.6, feet_px=SIDE.joints["sole"])
    report = check_sheet(sheet(FRONT, small), [FRONT, SIDE])
    side = report.figures[1]
    assert side.height_ratio < 0.7 and side.joints_inside < 0.85
    assert any(p.startswith("three_quarter: figure height is") for p in report.problems)
    assert any("the pose wasn't followed" in p for p in report.problems)


def test_an_extra_shape_is_reported() -> None:
    img = sheet(FRONT, SIDE)
    ImageDraw.Draw(img).ellipse([600, 300, 740, 440], fill=(40, 160, 60))  # between the views
    report = check_sheet(img, [FRONT, SIDE])
    assert report.problems == [
        "1 extra shape(s) away from the figures (props, text, shadows or clutter)"
    ]


def test_clutter_is_reported() -> None:
    img = sheet(FRONT, SIDE)
    draw = ImageDraw.Draw(img)
    for i in range(5):  # small leaves in the gap between the views and above them
        x, y = 620 + (i % 2) * 60, 120 + i * 110
        draw.ellipse([x, y, x + 30, y + 22], fill=(90, 150, 60))
    report = check_sheet(img, [FRONT, SIDE])
    assert report.problems == [
        "5 extra shape(s) away from the figures (props, text, shadows or clutter)"
    ]


def test_the_mannequin_itself_passes_the_checks() -> None:
    """The body-shape condition is cuttable: on white, it passes every sheet check."""
    img = ImageOps.invert(mannequin_image([FRONT, SIDE], CANVAS))
    report = check_sheet(img, [FRONT, SIDE])
    assert report.problems == [] and report.figures[0].limbs_clear
    assert [f.joints_inside for f in report.figures] == [1.0, 1.0]


# ------------------------------------------------------------------ design rounds (fake ComfyUI


@pytest.fixture
def fake_runs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """run_graph replaced: records the call and writes a clean synthetic sheet."""
    calls: list[dict[str, Any]] = []

    def run_graph(film_root: Path, kind: str, graph: dict, **kw: Any) -> RunRecord:
        calls.append({"graph": graph, **kw})
        kw["out_dir"].mkdir(parents=True, exist_ok=True)
        sheet(FRONT, SIDE).save(kw["out_dir"] / "sheet.png")
        return RunRecord(kind, kw["style"], kw["seed"], kw["params"], graph, ["sheet.png"], 2.5)

    monkeypatch.setattr(design, "run_graph", run_graph)
    return calls


def film(tmp_path: Path, style: str = "storybook") -> Path:
    root = tmp_path / "film"
    root.mkdir()
    (root / "film.json").write_text(json.dumps({"style": style}))
    return root


def test_a_round_makes_checked_candidates(fake_runs: list, tmp_path: Path) -> None:
    root = film(tmp_path)
    made = design_character(root, "kit", "  a cheerful young fox with a green scarf ", n=2, seed=50)
    assert [(c.id, c.seed, c.ok) for c in made] == [("c1", 50, True), ("c2", 51, True)]
    folder = root / "characters" / "kit" / "design"
    assert (folder / "pose.png").is_file() and (folder / "c2" / "checks.json").is_file()
    assert validate_file(folder / "candidates.json") == []
    call = fake_runs[0]
    assert call["uploads"] == {"@pose": folder / "pose.png", "@mannequin": folder / "mannequin.png"}
    assert call["names"] == ["sheet.png"]
    texts = {n["_meta"]["title"]: n["inputs"] for n in call["graph"].values() if "_meta" in n}
    assert (
        "turnaround sheet of a cheerful young fox with a green scarf," in texts["positive"]["text"]
    )
    assert "facial features" in texts["negative"]["text"]
    assert texts["apply ControlNet (openpose)"]["strength"] == design.POSE.strength
    assert texts["apply ControlNet (depth)"]["end_percent"] == design.MANNEQUIN.end
    loaders = [n for n in call["graph"].values() if n["class_type"] == "ControlNetLoader"]
    assert len(loaders) == 1  # both conditions share one loaded ControlNet


def test_rounds_add_candidates(fake_runs: list, tmp_path: Path) -> None:
    root = film(tmp_path)
    design_character(root, "kit", "a small fox", n=2, seed=1)
    made = design_character(root, "kit", "a small fox in a blue coat", n=1, seed=9)
    assert [c.id for c in made] == ["c3"]
    data = load_candidates(root, "kit")
    assert [(c["id"], c["seed"]) for c in data["candidates"]] == [("c1", 1), ("c2", 2), ("c3", 9)]
    assert data["candidates"][2]["description"] == "a small fox in a blue coat"


def test_choose_design(fake_runs: list, tmp_path: Path) -> None:
    root = film(tmp_path)
    design_character(root, "kit", "a small fox", n=2, seed=1)
    sheet_path = choose_design(root, "kit", "c2")
    assert sheet_path == root / "characters/kit/design/c2/sheet.png" and sheet_path.is_file()
    assert load_candidates(root, "kit")["chosen"] == "c2"
    with pytest.raises(DesignError, match="no candidate 'c7'"):
        choose_design(root, "kit", "c7")


def test_recheck_updates_the_records(fake_runs: list, tmp_path: Path) -> None:
    root = film(tmp_path)
    design_character(root, "kit", "a small fox", n=1, seed=1)
    folder = root / "characters" / "kit" / "design"
    sheet(FRONT).save(folder / "c1" / "sheet.png")  # as if the sheet had lost a view
    data = recheck(root, "kit")
    assert data["candidates"][0]["problems"] == ["three_quarter: no figure where the skeleton is"]
    assert json.loads((folder / "c1" / "checks.json").read_text())["ok"] is False
    assert load_candidates(root, "kit") == data and len(fake_runs) == 1


@pytest.mark.parametrize(
    ("character", "description", "n", "message"),
    [
        ("Kit!", "a small fox", 4, "character id 'Kit!'"),
        ("kit", "a", 4, "3 to 300 characters"),
        ("kit", "a fox with a gun", 4, "uses ['gun']"),
        ("kit", "a small fox", 9, "n must be 1 to 8"),
    ],
)
def test_bad_requests_are_refused(
    fake_runs: list, tmp_path: Path, character: str, description: str, n: int, message: str
) -> None:
    with pytest.raises(DesignError, match=message.replace("[", r"\[").replace("(", r"\(")):
        design_character(film(tmp_path), character, description, n=n)
    assert fake_runs == []


def test_a_changed_style_is_refused(fake_runs: list, tmp_path: Path) -> None:
    root = film(tmp_path)
    design_character(root, "kit", "a small fox", n=1)
    (root / "film.json").write_text(json.dumps({"style": "cutecartoon"}))
    with pytest.raises(DesignError, match="designed in style 'storybook'"):
        design_character(root, "kit", "a small fox", n=1)


# ------------------------------------------------------------------------------- real ComfyUI

CFG = load_config()


@pytest.mark.models
@pytest.mark.skipif(not expand_path(CFG.get("comfyui", "python")).exists(), reason="no ComfyUI")
def test_one_real_candidate(tmp_path: Path) -> None:
    root = film(tmp_path)
    (made,) = design_character(root, "kit", "a small round bear cub", n=1, seed=3, fast=True)
    folder = root / "characters" / "kit" / "design"
    assert Image.open(folder / made.sheet).size == CANVAS
    checks = json.loads((folder / "c1" / "checks.json").read_text())
    assert [f["view"] for f in checks["figures"]] == ["front", "three_quarter"]
    assert all(f["found"] for f in checks["figures"])  # the pose put a figure in each half
    assert free_comfy()
