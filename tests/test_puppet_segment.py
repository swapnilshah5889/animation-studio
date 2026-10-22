"""SAM 2.1 silhouettes (task 4.4): the prompts and the graph without ComfyUI, the clean-up with
a fake run, and one real segmentation of a synthetic sheet (marked `models`)."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image, ImageDraw

from studio_core.comfy_runs import RunRecord, free_comfy
from studio_core.config import expand_path, load_config
from studio_core.models import load_manifest
from studio_core.puppet import segment
from studio_core.puppet.segment import colour_key, segment_graph, segment_sheet, view_prompts
from studio_core.puppet.skeleton import Skeleton, turnaround

CANVAS = (1344, 768)
FRONT, SIDE = turnaround(CANVAS)
BG, FUR = (252, 246, 236), (230, 120, 40)
PALE = (246, 240, 228)  # a cream shirt: close enough to the background to fool the colour key
LIMBS = (
    ("r_shoulder", "r_elbow", "r_wrist", "r_hand"), ("l_shoulder", "l_elbow", "l_wrist", "l_hand"),
    ("r_hip", "r_knee", "r_ankle", "r_foot"), ("l_hip", "l_knee", "l_ankle", "l_foot"),
)  # fmt: skip


def shirt(sk: Skeleton) -> list[float]:
    """A pale rectangle on the belly, wider than the hips: it touches the background."""
    (nx, ny), (px, py), h = sk.joints["neck"], sk.joints["pelvis"], sk.height_px
    cx, cy = (nx + px) / 2, (ny + py) / 2
    return [cx - 0.06 * h, cy - 0.12 * h, cx + 0.06 * h, cy + 0.12 * h]


def draw_figure(draw: ImageDraw.ImageDraw, sk: Skeleton, fur: Any, pale: Any) -> None:
    """A flat cartoon fox on the skeleton: ears and a tail reach past the joints."""
    j, h = sk.joints, sk.height_px
    (nx, ny), (_, ty), (px, py) = j["neck"], j["head_top"], j["pelvis"]
    r = (ny - ty) / 2
    for ear in ("l_ear", "r_ear"):
        ex, ey = j[ear]
        tip = (ex + (ex - nx) * 0.3, ty - 0.02 * h)
        draw.polygon([(ex - 0.08 * h, ey), (ex + 0.08 * h, ey), tip], fill=fur)
    draw.ellipse([nx - 0.8 * r, ty, nx + 0.8 * r, ny + 0.1 * r], fill=fur)
    draw.polygon([j["r_shoulder"], j["l_shoulder"], j["l_hip"], j["r_hip"]], fill=fur)
    draw.line([j["neck"], j["pelvis"]], fill=fur, width=int(h * 0.12))
    for chain in LIMBS:
        draw.line([j[n] for n in chain], fill=fur, width=int(h * 0.05), joint="curve")
    tail = [(px, py), (px - 0.12 * h, py + 0.1 * h), (px - 0.3 * h, py + 0.05 * h)]
    draw.line(tail, fill=fur, width=int(h * 0.06), joint="curve")
    draw.rectangle(shirt(sk), fill=pale)


def sheet() -> Image.Image:
    img = Image.new("RGB", CANVAS, BG)
    for sk in (FRONT, SIDE):
        draw_figure(ImageDraw.Draw(img), sk, FUR, PALE)
    return img


def truth(sk: Skeleton) -> np.ndarray:
    """The drawn figure as a boolean mask (the pale shirt included)."""
    img = Image.new("L", CANVAS, 0)
    draw_figure(ImageDraw.Draw(img), sk, 255, 255)
    return np.asarray(img) > 127


def iou(a: np.ndarray, b: np.ndarray) -> float:
    return float((a & b).sum() / (a | b).sum())


def test_prompts_come_from_the_skeleton_and_the_colour_key() -> None:
    prompts = view_prompts([FRONT, SIDE], colour_key(sheet()))
    assert [(p.view, p.column) for p in prompts] == [
        ("front", (0, 672)),
        ("three_quarter", (672, 1344)),
    ]
    for p, sk in zip(prompts, (FRONT, SIDE), strict=True):
        x0, y0, x1, y1 = p.box
        assert p.column[0] < x0 < x1 < p.column[1] and 0 < y0 < y1 < CANVAS[1]
        ys, xs = np.nonzero(truth(sk))
        assert x0 < xs.min() and xs.max() < x1 and y0 < ys.min() and ys.max() < y1  # tail, ears
        assert xs.min() - x0 < 0.05 * sk.height_px  # tight: a loose box makes SAM take it all
        assert len(p.positive) == 3 and all(truth(sk)[y, x] for x, y in p.positive)


def test_without_a_colour_key_the_box_hugs_the_joints() -> None:
    (p,) = view_prompts([FRONT], np.zeros((CANVAS[1], CANVAS[0]), dtype=bool))
    xs = [x for x, _ in FRONT.joints.values()]
    margin = FRONT.height_px * segment.MARGIN
    assert p.column == (0, 1344) and p.box[0] == round(min(xs) - margin)


def test_the_graph() -> None:
    manifest = load_manifest()
    prompts = view_prompts([FRONT, SIDE], colour_key(sheet()))
    graph = segment_graph(manifest, "@sheet", prompts, height=768, prefix="seg")
    assert json.loads(json.dumps(graph)) == graph  # API format: plain JSON
    assert [n["class_type"] for n in graph.values()] == [
        "DownloadAndLoadSAM2Model", "LoadImage",
        "ImageCrop", "Sam2Segmentation", "MaskToImage", "SaveImage",
        "ImageCrop", "Sam2Segmentation", "MaskToImage", "SaveImage",
    ]  # fmt: skip
    loader = graph["1"]["inputs"]
    assert loader["model"] == manifest.files[segment.MODEL].comfy_name
    assert loader["model"] == "sam2.1_hiera_base_plus.safetensors"
    assert loader["precision"] == "fp32"  # anything else downloads an fp16 file
    assert graph["2"]["inputs"]["image"] == "@sheet"
    side_crop, side_sam = graph["7"]["inputs"], graph["8"]["inputs"]
    assert (side_crop["x"], side_crop["width"], side_crop["height"]) == (672, 672, 768)
    assert side_sam["image"] == ["7", 0] and side_sam["sam2_model"] == ["1", 0]
    points = json.loads(side_sam["coordinates_positive"])
    assert [(p["x"] + 672, p["y"]) for p in points] == list(prompts[1].positive)  # crop coords
    x0, y0, x1, y1 = prompts[1].box
    assert side_sam["bboxes"] == {"__value__": [[x0 - 672, y0, x1 - 672, y1]]}
    assert graph["4"]["inputs"]["keep_model_loaded"] and not side_sam["keep_model_loaded"]
    prefixes = [
        n["inputs"]["filename_prefix"] for n in graph.values() if "filename_prefix" in n["inputs"]
    ]
    assert prefixes == ["seg_0_front", "seg_1_three_quarter"] == sorted(prefixes)


@pytest.fixture
def fake_runs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """run_graph replaced: each column 'mask' is a ring with a hole, plus a speck."""
    calls: list[dict[str, Any]] = []

    def run_graph(film_root: Path, kind: str, graph: dict, **kw: Any) -> RunRecord:
        calls.append({"kind": kind, "graph": graph, **kw})
        kw["out_dir"].mkdir(parents=True)
        for name in kw["names"]:
            img = Image.new("L", (672, 768), 0)
            draw = ImageDraw.Draw(img)
            draw.ellipse([200, 100, 470, 700], outline=255, width=30)  # an outline, hollow
            draw.rectangle([20, 20, 22, 22], fill=255)  # a speck
            img.save(kw["out_dir"] / name)
        return RunRecord(kind, None, None, kw["params"], graph, kw["names"], 1.0)

    monkeypatch.setattr(segment, "run_graph", run_graph)
    return calls


def test_masks_are_filled_cleaned_and_placed(fake_runs: list, tmp_path: Path) -> None:
    path = tmp_path / "sheet.png"
    sheet().save(path)
    masks = segment_sheet(tmp_path, path, [FRONT, SIDE], tmp_path / "masks")
    assert [m.name for m in masks] == ["mask_front.png", "mask_three_quarter.png"]
    for m, left in zip(masks, (0, 672), strict=True):
        img = Image.open(m)
        assert img.mode == "L" and img.size == CANVAS
        a = np.asarray(img)
        assert a[400, left + 335] == 255  # the hole inside the outline is figure
        assert a[21, left + 21] == 0  # the speck is gone
        assert not a[:, 672 - left : 1344 - left].any()  # nothing in the other column
    (call,) = fake_runs
    assert call["kind"] == "segment" and call["uploads"] == {"@sheet": path}
    assert [p["view"] for p in call["params"]["prompts"]] == ["front", "three_quarter"]
    segment_sheet(tmp_path, path, [FRONT, SIDE], tmp_path / "again")
    first, second = (
        {n["inputs"].get("filename_prefix") for n in c["graph"].values()} for c in fake_runs
    )
    assert first.isdisjoint(second - {None})  # a fresh prefix per run: never a cached result


# ------------------------------------------------------------------------------- real ComfyUI

CFG = load_config()
SAM_PRESENT = (
    load_manifest().files[segment.MODEL].is_present(expand_path(CFG.get("comfyui", "models_dir")))
)


@pytest.mark.models
@pytest.mark.skipif(not expand_path(CFG.get("comfyui", "python")).exists(), reason="no ComfyUI")
@pytest.mark.skipif(not SAM_PRESENT, reason="SAM 2.1 base+ isn't downloaded")
def test_sam_cuts_each_figure_with_its_pale_shirt(tmp_path: Path) -> None:
    path = tmp_path / "sheet.png"
    sheet().save(path)
    masks = segment_sheet(tmp_path, path, [FRONT, SIDE], tmp_path / "masks")
    assert json.loads((tmp_path / "masks" / "run.json").read_text())["kind"] == "segment"
    for m, sk in zip(masks, (FRONT, SIDE), strict=True):
        got = np.asarray(Image.open(m)) > 127
        assert iou(got, truth(sk)) > 0.9
        x0, y0, x1, y1 = (round(v) for v in shirt(sk))
        assert got[y0:y1, x0:x1].mean() > 0.9  # the shirt the colour key can't see
    assert free_comfy()
