"""The depth-map graph (task 4.7): node types, links and settings for both models, checked
without ComfyUI, plus one real run per model (marked `models`) on a small drawn landscape that
checks the convention: the sky at the top is far (dark), the ground at the bottom near (bright)."""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from studio_core.comfy_graphs import (
    DA3_MAX_RESOLUTION,
    DA3_MONO_LARGE,
    DA3_RESOLUTION,
    DAV2_SMALL,
    DEPTH_MODELS,
    depth_map,
)
from studio_core.comfy_runs import free_comfy, run_graph
from studio_core.config import expand_path, load_config
from studio_core.models import load_manifest

MANIFEST = load_manifest()


def graph(**kwargs) -> dict:
    return depth_map(MANIFEST, **({"image": "@plate"} | kwargs))


def only(wf: dict, class_type: str) -> dict:
    found = [n for n in wf.values() if n["class_type"] == class_type]
    assert len(found) == 1, f"expected one {class_type}, found {len(found)}"
    return found[0]


def source(wf: dict, link: list) -> dict:
    """The node a link [node_id, slot] comes from."""
    return wf[link[0]]


def counts(wf: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for node in wf.values():
        out[node["class_type"]] = out.get(node["class_type"], 0) + 1
    return out


@pytest.mark.parametrize("model", DEPTH_MODELS)
def test_every_link_points_at_an_existing_node(model: str) -> None:
    wf = graph(model=model)
    for node in wf.values():
        for value in node["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                assert value[0] in wf


@pytest.mark.parametrize("model", DEPTH_MODELS)
def test_same_inputs_same_json(model: str) -> None:
    assert json.dumps(graph(model=model)) == json.dumps(graph(model=model))


def test_da3_chain() -> None:
    wf = graph(filename_prefix="meadow_depth")
    assert counts(wf) == {
        "LoadImage": 1,
        "LoadDA3Model": 1,
        "DA3Inference": 1,
        "DA3Render": 1,
        "SaveImage": 1,
    }
    assert only(wf, "LoadImage")["inputs"]["image"] == "@plate"  # run_graph substitutes it
    loader = only(wf, "LoadDA3Model")["inputs"]
    assert loader["model_name"] == MANIFEST.files[DA3_MONO_LARGE].comfy_name
    assert loader["model_name"] == "depth_anything_3_mono_large.safetensors"

    inference = only(wf, "DA3Inference")["inputs"]
    assert source(wf, inference["da3_model"])["class_type"] == "LoadDA3Model"
    assert source(wf, inference["image"])["class_type"] == "LoadImage"
    assert inference["resolution"] == DA3_RESOLUTION
    assert inference["mode"] == "mono"  # MONO-LARGE has no multi-view head
    assert inference["resize_method"] == "upper_bound_resize"

    render = only(wf, "DA3Render")["inputs"]
    assert source(wf, render["da3_geometry"])["class_type"] == "DA3Inference"
    # A dynamic combo: the option, then its own inputs as dotted keys. v2_style blackens the
    # sky; min_max would make it bright (DA3's raw sky depth is meaningless).
    assert render["output"] == "depth"
    assert render["output.normalization"] == "v2_style"
    assert render["output.apply_sky_clip"] is False

    save = only(wf, "SaveImage")["inputs"]
    assert source(wf, save["images"])["class_type"] == "DA3Render"
    assert save["filename_prefix"] == "meadow_depth"


def test_da3_default_resolution_is_a_patch_multiple_within_the_cap() -> None:
    assert DA3_RESOLUTION % 14 == 0
    assert DA3_RESOLUTION <= DA3_MAX_RESOLUTION


@pytest.mark.parametrize("size", [504, 1008, 1512, DA3_MAX_RESOLUTION])
def test_da3_resolution_is_passed_through(size: int) -> None:
    assert only(graph(resolution=size), "DA3Inference")["inputs"]["resolution"] == size


@pytest.mark.parametrize("size", [1000, 126, 2520])
def test_da3_refuses_bad_resolutions(size: int) -> None:
    # Not a multiple of 14; below the node's minimum; above the cap (2520 ran out of GPU
    # memory on the Mac and came back all black, without an error).
    with pytest.raises(ValueError, match="multiple of 14"):
        graph(resolution=size)


def test_dav2_chain() -> None:
    wf = graph(model="dav2")
    assert counts(wf) == {
        "LoadImage": 1,
        "DepthAnythingV2Preprocessor": 1,
        "GetImageSize": 1,
        "ImageScale": 1,
        "SaveImage": 1,
    }
    pre = only(wf, "DepthAnythingV2Preprocessor")["inputs"]
    assert source(wf, pre["image"])["class_type"] == "LoadImage"
    # Small only: the node's default (vitl) and Base are non-commercial (CC-BY-NC-4.0).
    assert pre["ckpt_name"] == "depth_anything_v2_vits.pth"
    assert MANIFEST.files[DAV2_SMALL].dest.endswith("/" + pre["ckpt_name"])

    # The node returns its own size; the map is scaled back to the plate's exact size.
    scale = only(wf, "ImageScale")["inputs"]
    assert source(wf, scale["image"])["class_type"] == "DepthAnythingV2Preprocessor"
    size = only(wf, "GetImageSize")["inputs"]
    assert source(wf, size["image"])["class_type"] == "LoadImage"
    size_id = scale["width"][0]
    assert wf[size_id]["class_type"] == "GetImageSize"
    assert scale["width"] == [size_id, 0] and scale["height"] == [size_id, 1]
    assert scale["crop"] == "disabled"
    assert source(wf, only(wf, "SaveImage")["inputs"]["images"])["class_type"] == "ImageScale"


def test_dav2_has_no_resolution_setting() -> None:
    with pytest.raises(ValueError, match="518"):
        graph(model="dav2", resolution=1512)


def test_unknown_model() -> None:
    with pytest.raises(ValueError, match="unknown depth model"):
        graph(model="midas")


# ------------------------------------------------------------------------------- real ComfyUI

CFG = load_config()
MODELS_DIR = expand_path(CFG.get("comfyui", "models_dir"))
HAS_COMFY = expand_path(CFG.get("comfyui", "python")).exists()
FILE_IDS = {"da3": DA3_MONO_LARGE, "dav2": DAV2_SMALL}


def landscape(width: int = 672, height: int = 252) -> Image.Image:
    """A simple drawn landscape: a pale sky with a cloud, a row of round trees on the horizon,
    and a meadow whose grass tufts grow bigger toward the bottom (perspective)."""
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    horizon = int(height * 0.45)
    for y in range(horizon):  # sky: deeper blue at the top
        t = y / horizon
        draw.line([(0, y), (width, y)], fill=(int(120 + 100 * t), int(180 + 60 * t), 245))
    draw.ellipse([width * 0.6, height * 0.08, width * 0.75, height * 0.18], fill=(250, 250, 250))
    for y in range(horizon, height):  # meadow: lighter far away, deeper green close up
        t = (y - horizon) / (height - horizon)
        draw.line([(0, y), (width, y)], fill=(int(170 - 90 * t), int(210 - 50 * t), 90))
    for x in range(10, width, 48):  # trees on the horizon
        draw.rectangle([x + 9, horizon - 14, x + 13, horizon + 2], fill=(110, 75, 45))
        draw.ellipse([x, horizon - 38, x + 22, horizon - 12], fill=(70, 140, 60))
    rng = np.random.default_rng(3)
    for _ in range(160):  # grass tufts: size grows with nearness
        y = int(rng.uniform(horizon + 6, height))
        s = 1 + 8 * (y - horizon) / (height - horizon)
        x = rng.uniform(0, width)
        draw.line([(x, y), (x - s / 2, y - 2 * s)], fill=(50, 110, 40), width=max(1, int(s / 3)))
        draw.line([(x, y), (x + s / 2, y - 2 * s)], fill=(50, 110, 40), width=max(1, int(s / 3)))
    return img


@pytest.mark.models
@pytest.mark.skipif(not HAS_COMFY, reason="no ComfyUI env")
@pytest.mark.parametrize("model", DEPTH_MODELS)
def test_top_is_far_and_bottom_is_near(tmp_path: Path, model: str) -> None:
    if not MANIFEST.files[FILE_IDS[model]].is_present(MODELS_DIR):
        pytest.skip(f"{FILE_IDS[model]} isn't downloaded")
    picture = tmp_path / f"depth_test_{model}.png"
    landscape().save(picture)
    wf = depth_map(MANIFEST, image="@plate", model=model)
    out = tmp_path / "depth"
    record = run_graph(tmp_path, "depth", wf, out_dir=out, uploads={"@plate": picture})
    (name,) = record.outputs
    depth = Image.open(out / name)
    assert depth.size == (672, 252)  # the plate's own size
    rgb = np.asarray(depth.convert("RGB")).astype(float) / 255
    assert np.allclose(rgb[..., 0], rgb[..., 1]) and np.allclose(rgb[..., 1], rgb[..., 2])
    near = rgb[..., 0]
    top, ground, bottom = near[:40].mean(), near[150:190].mean(), near[-25:].mean()
    assert top < ground < bottom, (top, ground, bottom)
    assert top < 0.15 and bottom > 0.6, (top, bottom)  # bright = near, dark = far
    assert free_comfy()
