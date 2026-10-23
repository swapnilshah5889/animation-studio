"""The fill-behind graph (task 4.7): ProMax in its repaint mode, the mask's path through the
graph and the film's style, checked without rendering; plus a byte-level check that adding
the builder left txt2img unchanged."""

import json

import pytest
from export_workflows import EXPORTS, build

from studio_core.comfy_graphs import (
    FILL_FEATHER_PX,
    FILL_REDRAW_PX,
    KID_SAFE_NEGATIVE,
    REPAINT_CONTROLNET,
    repaint_fill,
    txt2img,
)
from studio_core.config import REPO_ROOT
from studio_core.models import load_manifest

PROMPT = "a sunny meadow, the sky and the distant hills continuing behind"
STYLES = list(load_manifest().styles)


def fill(style_id: str = "storybook", **kwargs) -> dict:
    args = {"image": "@image", "mask": "@mask", "seed": 7, "width": 1536, "height": 576}
    return repaint_fill(load_manifest(), style_id, PROMPT, **(args | kwargs))


def nodes(wf: dict, class_type: str) -> list[dict]:
    return [n for n in wf.values() if n["class_type"] == class_type]


def only(wf: dict, class_type: str) -> dict:
    found = nodes(wf, class_type)
    assert len(found) == 1, f"expected one {class_type}, found {len(found)}"
    return found[0]


def source(wf: dict, link: list) -> dict:
    """The node a link [node_id, slot] comes from."""
    return wf[link[0]]


def titled(wf: dict, title: str) -> list:
    """The link to the one node titled `title` (its output 0)."""
    ids = [k for k, n in wf.items() if n.get("_meta", {}).get("title") == title]
    assert len(ids) == 1, f"expected one node titled {title!r}, found {len(ids)}"
    return [ids[0], 0]


def link_to(wf: dict, class_type: str, slot: int = 0) -> list:
    """The link to the one node of `class_type` (its output `slot`)."""
    ids = [k for k, n in wf.items() if n["class_type"] == class_type]
    assert len(ids) == 1, f"expected one {class_type}, found {len(ids)}"
    return [ids[0], slot]


@pytest.mark.parametrize("style_id", STYLES)
def test_every_link_points_at_an_existing_node(style_id: str) -> None:
    wf = fill(style_id)
    for node in wf.values():
        for value in node["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                assert value[0] in wf


def test_node_types() -> None:
    counts: dict[str, int] = {}
    for node in fill("storybook").values():
        counts[node["class_type"]] = counts.get(node["class_type"], 0) + 1
    assert counts == {
        "CheckpointLoaderSimple": 1,
        "VAELoader": 1,
        "LoraLoader": 1,  # the style LoRA; never the speed LoRA (normal settings)
        "CLIPTextEncode": 2,
        "LoadImage": 2,  # the picture and the mask
        "ImageScale": 2,  # both to the working size
        "ImageToMask": 2,  # the region, and the feathered seam
        "InpaintPreprocessor": 1,
        "ControlNetLoader": 1,
        "SetUnionControlNetType": 1,
        "ControlNetApplyAdvanced": 1,
        "VAEEncodeForInpaint": 1,
        "KSampler": 1,
        "VAEDecode": 1,
        "GrowMask": 1,
        "MaskToImage": 1,
        "ImageBlur": 1,
        "ImageCompositeMasked": 1,
        "SaveImage": 1,
    }  # no EmptyLatentImage: the sampler starts from the (greyed) picture


def test_promax_runs_in_repaint_mode_on_both_prompts() -> None:
    files = load_manifest().files
    wf = fill()
    loader = only(wf, "ControlNetLoader")["inputs"]
    assert loader["control_net_name"] == files[REPAINT_CONTROLNET].comfy_name
    assert "promax" in loader["control_net_name"]
    mode = only(wf, "SetUnionControlNetType")["inputs"]
    assert mode["type"] == "repaint"
    assert mode["control_net"] == link_to(wf, "ControlNetLoader")
    applied = only(wf, "ControlNetApplyAdvanced")["inputs"]
    assert applied["control_net"] == link_to(wf, "SetUnionControlNetType")
    assert (applied["strength"], applied["start_percent"], applied["end_percent"]) == (1, 0, 1)
    # The sampler sees the ControlNet-conditioned prompts, not the bare ones.
    sampler = only(wf, "KSampler")["inputs"]
    assert sampler["positive"] == link_to(wf, "ControlNetApplyAdvanced", 0)
    assert sampler["negative"] == link_to(wf, "ControlNetApplyAdvanced", 1)
    assert source(wf, applied["positive"])["_meta"]["title"] == "positive"
    assert source(wf, applied["negative"])["_meta"]["title"] == "negative"


def test_the_control_image_is_the_picture_with_the_masked_pixels_black() -> None:
    wf = fill()
    hint = only(wf, "InpaintPreprocessor")["inputs"]
    assert hint["black_pixel_for_xinsir_cn"] is True  # xinsir's convention, not -1
    assert only(wf, "ControlNetApplyAdvanced")["inputs"]["image"] == link_to(
        wf, "InpaintPreprocessor"
    )
    assert hint["image"] == titled(wf, "working size")
    assert hint["mask"] == titled(wf, "region")


def test_the_mask_is_the_red_channel_at_the_working_size() -> None:
    wf = fill(width=1024, height=384)
    region = wf[titled(wf, "region")[0]]
    assert region["class_type"] == "ImageToMask"
    assert region["inputs"]["channel"] == "red"  # a plain grey PNG, white = repaint
    sized = source(wf, region["inputs"]["image"])
    assert sized["class_type"] == "ImageScale"
    assert (sized["inputs"]["width"], sized["inputs"]["height"]) == (1024, 384)
    assert sized["inputs"]["upscale_method"] == "bilinear"
    assert sized["inputs"]["crop"] == "disabled"
    loaded = source(wf, sized["inputs"]["image"])
    assert loaded["class_type"] == "LoadImage" and loaded["inputs"]["image"] == "@mask"


def test_one_region_drives_the_control_image_the_latent_and_the_seam() -> None:
    wf = fill()
    region = titled(wf, "region")
    assert only(wf, "InpaintPreprocessor")["inputs"]["mask"] == region
    assert only(wf, "VAEEncodeForInpaint")["inputs"]["mask"] == region
    assert only(wf, "GrowMask")["inputs"]["mask"] == region


def test_the_picture_is_scaled_to_the_working_size() -> None:
    wf = fill(width=1024, height=384)
    scale = wf[titled(wf, "working size")[0]]["inputs"]
    loaded = source(wf, scale["image"])
    assert loaded["class_type"] == "LoadImage" and loaded["inputs"]["image"] == "@image"
    assert (scale["width"], scale["height"]) == (1024, 384)
    assert scale["upscale_method"] == "lanczos" and scale["crop"] == "disabled"


def test_sampling_starts_from_the_greyed_picture_at_full_denoise() -> None:
    wf = fill()
    encode = only(wf, "VAEEncodeForInpaint")["inputs"]
    assert encode["pixels"] == titled(wf, "working size")
    assert encode["grow_mask_by"] == FILL_REDRAW_PX == 16  # a ring of 2 latent cells
    sampler = only(wf, "KSampler")["inputs"]
    assert sampler["latent_image"] == link_to(wf, "VAEEncodeForInpaint")
    assert sampler["denoise"] == 1.0


def test_the_fill_fades_into_the_picture_across_the_redrawn_ring() -> None:
    wf = fill(filename_prefix="fill_far")
    saved = only(wf, "SaveImage")["inputs"]
    assert saved["filename_prefix"] == "fill_far"
    composite = source(wf, saved["images"])
    assert composite["class_type"] == "ImageCompositeMasked"
    inputs = composite["inputs"]
    assert inputs["destination"] == titled(wf, "working size")  # the input's own pixels
    decode = source(wf, inputs["source"])
    assert decode["class_type"] == "VAEDecode"
    assert decode["inputs"]["samples"] == link_to(wf, "KSampler")
    assert (inputs["x"], inputs["y"], inputs["resize_source"]) == (0, 0, False)
    # The composite mask: region → grow → (as a picture) blur → red channel.
    seam = source(wf, inputs["mask"])
    assert seam["class_type"] == "ImageToMask" and seam["inputs"]["channel"] == "red"
    blur = source(wf, seam["inputs"]["image"])
    assert blur["class_type"] == "ImageBlur"
    as_picture = source(wf, blur["inputs"]["image"])
    assert as_picture["class_type"] == "MaskToImage"
    grow = source(wf, as_picture["inputs"]["mask"])
    assert grow["class_type"] == "GrowMask"
    assert grow["inputs"]["expand"] == FILL_FEATHER_PX
    assert blur["inputs"]["blur_radius"] == FILL_FEATHER_PX
    # Grown plus blurred stays inside the ring the sampler redraws.
    assert 2 * FILL_FEATHER_PX <= FILL_REDRAW_PX


@pytest.mark.parametrize("style_id", STYLES)
def test_style_model_loras_vae_prompts_and_settings(style_id: str) -> None:
    manifest = load_manifest()
    style, files = manifest.styles[style_id], manifest.files
    wf = fill(style_id, negative="tree trunks", seed=1234)
    ckpt = only(wf, "CheckpointLoaderSimple")["inputs"]["ckpt_name"]
    assert ckpt == files[style.data["checkpoint"]].comfy_name
    loras = [n["inputs"]["lora_name"] for n in nodes(wf, "LoraLoader")]
    assert loras == [files[lora["file"]].comfy_name for lora in style.data["loras"]]
    sampler = only(wf, "KSampler")["inputs"]
    expected = "LoraLoader" if loras else "CheckpointLoaderSimple"
    assert source(wf, sampler["model"])["class_type"] == expected
    normal = style.settings(fast=False)
    assert sampler["cfg"] == normal["cfg"]
    assert sampler["sampler_name"] == normal["sampler"]
    assert sampler["scheduler"] == normal["scheduler"]
    assert sampler["seed"] == 1234
    # One VAE encodes, decodes and is handed to the ControlNet.
    vae = [k for k, n in wf.items() if n["class_type"] in ("VAELoader", "CheckpointLoaderSimple")]
    vae_link = only(wf, "VAEDecode")["inputs"]["vae"]
    assert vae_link[0] in vae
    assert only(wf, "VAEEncodeForInpaint")["inputs"]["vae"] == vae_link
    assert only(wf, "ControlNetApplyAdvanced")["inputs"]["vae"] == vae_link
    applied = only(wf, "ControlNetApplyAdvanced")["inputs"]
    positive = source(wf, applied["positive"])["inputs"]["text"]
    negative = source(wf, applied["negative"])["inputs"]["text"]
    assert PROMPT in positive
    assert "tree trunks" in negative and negative.endswith(KID_SAFE_NEGATIVE)


def test_steps_default_and_override() -> None:
    assert only(fill(), "KSampler")["inputs"]["steps"] == 20
    assert only(fill(steps=30), "KSampler")["inputs"]["steps"] == 30


@pytest.mark.parametrize("style_id", STYLES)
def test_the_style_front_half_is_the_same_as_txt2img(style_id: str) -> None:
    t2i = txt2img(load_manifest(), style_id, PROMPT, negative="rain")
    wf = fill(style_id, negative="rain")
    front: list[str] = []  # txt2img's nodes up to its empty latent (no ControlNets there)
    for node_id, node in t2i.items():
        if node["class_type"] == "EmptyLatentImage":
            break
        front.append(node_id)
    assert {k: wf[k] for k in front} == {k: t2i[k] for k in front}


@pytest.mark.parametrize("name", list(EXPORTS))
def test_txt2img_golden_files_are_byte_identical(name: str) -> None:
    saved = (REPO_ROOT / "comfy_workflows" / name).read_text()
    assert json.dumps(build(name), indent=2) + "\n" == saved


def test_same_inputs_give_identical_json() -> None:
    assert json.dumps(fill()) == json.dumps(fill())


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"width": 1540}, "width must be a positive multiple of 8"),
        ({"height": 0}, "height must be a positive multiple of 8"),
        ({"steps": 0}, "steps must be at least 1"),
    ],
)
def test_bad_inputs_are_refused(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        fill(**kwargs)
