"""The background plate graph (task 4.6): node types, links and settings, checked without
rendering, plus a byte-level check that sharing the style front half left txt2img unchanged."""

import json

import pytest
from export_workflows import EXPORTS, build

from studio_core.comfy_graphs import KID_SAFE_NEGATIVE, finish_plate, txt2img
from studio_core.config import REPO_ROOT
from studio_core.models import load_manifest

PROMPT = "a sunny meadow with a winding path and round trees, wide landscape"
STYLES = list(load_manifest().styles)


def plate(style_id: str = "storybook", **kwargs) -> dict:
    args = {"image": "@draft", "seed": 7} | kwargs
    return finish_plate(load_manifest(), style_id, PROMPT, **args)


def nodes(wf: dict, class_type: str) -> list[dict]:
    return [n for n in wf.values() if n["class_type"] == class_type]


def only(wf: dict, class_type: str) -> dict:
    found = nodes(wf, class_type)
    assert len(found) == 1, f"expected one {class_type}, found {len(found)}"
    return found[0]


def source(wf: dict, link: list) -> dict:
    """The node a link [node_id, slot] comes from."""
    return wf[link[0]]


@pytest.mark.parametrize("style_id", STYLES)
def test_every_link_points_at_an_existing_node(style_id: str) -> None:
    wf = plate(style_id)
    for node in wf.values():
        for value in node["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                assert value[0] in wf


def test_node_types() -> None:
    counts: dict[str, int] = {}
    for node in plate("storybook").values():
        counts[node["class_type"]] = counts.get(node["class_type"], 0) + 1
    assert counts == {
        "CheckpointLoaderSimple": 1,
        "VAELoader": 1,
        "LoraLoader": 1,  # the style LoRA; never the speed LoRA (normal settings)
        "CLIPTextEncode": 2,
        "LoadImage": 1,
        "UpscaleModelLoader": 1,
        "ImageUpscaleWithModel": 1,
        "ImageScale": 1,
        "VAEEncode": 1,
        "KSampler": 1,
        "VAEDecode": 1,
        "SaveImage": 1,
    }  # no EmptyLatentImage: the sampler starts from the draft


def test_the_draft_flows_through_upscale_scale_encode_sample_decode_save() -> None:
    wf = plate(filename_prefix="meadow_plate")
    saved = only(wf, "SaveImage")["inputs"]
    assert saved["filename_prefix"] == "meadow_plate"
    decode = source(wf, saved["images"])
    assert decode["class_type"] == "VAEDecode"
    sampler = source(wf, decode["inputs"]["samples"])
    assert sampler["class_type"] == "KSampler"
    encode = source(wf, sampler["inputs"]["latent_image"])
    assert encode["class_type"] == "VAEEncode"
    scale = source(wf, encode["inputs"]["pixels"])
    assert scale["class_type"] == "ImageScale"
    upscale = source(wf, scale["inputs"]["image"])
    assert upscale["class_type"] == "ImageUpscaleWithModel"
    assert source(wf, upscale["inputs"]["upscale_model"])["class_type"] == "UpscaleModelLoader"
    load = source(wf, upscale["inputs"]["image"])
    assert load["class_type"] == "LoadImage" and load["inputs"]["image"] == "@draft"


@pytest.mark.parametrize("upscaler", ["realesrgan-x4plus-anime-6b", "realesrgan-x4plus"])
def test_upscaler_comes_from_the_manifest(upscaler: str) -> None:
    files = load_manifest().files
    wf = plate(upscaler=upscaler)
    loader = only(wf, "UpscaleModelLoader")["inputs"]
    assert loader["model_name"] == files[upscaler].comfy_name


def test_the_default_upscaler_is_the_anime_model() -> None:
    files = load_manifest().files
    wf = plate()
    loader = only(wf, "UpscaleModelLoader")["inputs"]
    assert loader["model_name"] == files["realesrgan-x4plus-anime-6b"].comfy_name


@pytest.mark.parametrize(("width", "height"), [(2880, 1080), (2400, 1080)])
def test_scale_goes_to_the_plate_size_with_lanczos(width: int, height: int) -> None:
    wf = plate(width=width, height=height)
    scale = only(wf, "ImageScale")["inputs"]
    assert scale["width"] == width and scale["height"] == height
    assert scale["upscale_method"] == "lanczos"
    assert scale["crop"] == "disabled"


@pytest.mark.parametrize("style_id", STYLES)
def test_sampler_uses_the_styles_normal_settings_with_denoise(style_id: str) -> None:
    style = load_manifest().styles[style_id]
    sampler = only(plate(style_id, seed=1234, denoise=0.35), "KSampler")["inputs"]
    normal = style.settings(fast=False)
    assert sampler["steps"] == 10  # a light refine: fewer steps than the style's own
    assert sampler["cfg"] == normal["cfg"]
    assert sampler["sampler_name"] == normal["sampler"]
    assert sampler["scheduler"] == normal["scheduler"]
    assert sampler["denoise"] == 0.35
    assert sampler["seed"] == 1234


def test_default_denoise_is_low() -> None:
    assert only(plate(), "KSampler")["inputs"]["denoise"] == 0.3


@pytest.mark.parametrize("style_id", STYLES)
def test_style_model_loras_vae_and_prompts(style_id: str) -> None:
    manifest = load_manifest()
    style, files = manifest.styles[style_id], manifest.files
    wf = plate(style_id, negative="rain clouds")
    ckpt = only(wf, "CheckpointLoaderSimple")["inputs"]["ckpt_name"]
    assert ckpt == files[style.data["checkpoint"]].comfy_name
    loras = [n["inputs"]["lora_name"] for n in nodes(wf, "LoraLoader")]
    assert loras == [files[lora["file"]].comfy_name for lora in style.data["loras"]]
    # The sampler's model is the end of the LoRA chain (or the checkpoint when there is none).
    sampler = only(wf, "KSampler")["inputs"]
    expected = "LoraLoader" if loras else "CheckpointLoaderSimple"
    assert source(wf, sampler["model"])["class_type"] == expected
    # The style's VAE both encodes the upscale and decodes the result.
    vae_id = next(k for k, n in wf.items() if n["class_type"] == "VAELoader")
    assert wf[vae_id]["inputs"]["vae_name"] == files[style.data["vae"]].comfy_name
    assert only(wf, "VAEEncode")["inputs"]["vae"] == [vae_id, 0]
    assert only(wf, "VAEDecode")["inputs"]["vae"] == [vae_id, 0]
    positive = source(wf, sampler["positive"])["inputs"]["text"]
    negative = source(wf, sampler["negative"])["inputs"]["text"]
    assert PROMPT in positive
    assert "rain clouds" in negative and negative.endswith(KID_SAFE_NEGATIVE)


@pytest.mark.parametrize("style_id", STYLES)
def test_the_style_front_half_is_the_same_as_txt2img(style_id: str) -> None:
    """Both builders go through one helper, so a style means the same files and prompts in
    both: the plate graph starts with exactly txt2img's (normal settings) first nodes."""
    t2i = txt2img(load_manifest(), style_id, PROMPT, negative="rain")
    wf = plate(style_id, negative="rain")
    front: list[str] = []  # txt2img's nodes up to its empty latent (no ControlNets here)
    for node_id, node in t2i.items():
        if node["class_type"] == "EmptyLatentImage":
            break
        front.append(node_id)
    assert [t2i[k]["class_type"] for k in front][-2:] == ["CLIPTextEncode", "CLIPTextEncode"]
    assert {k: wf[k] for k in front} == {k: t2i[k] for k in front}


@pytest.mark.parametrize("name", list(EXPORTS))
def test_txt2img_golden_files_are_byte_identical(name: str) -> None:
    """Stronger than the dict comparison in test_comfy_graphs.py: key order and formatting too,
    so the shared helper can't have reordered inputs in the saved workflows."""
    saved = (REPO_ROOT / "comfy_workflows" / name).read_text()
    assert json.dumps(build(name), indent=2) + "\n" == saved


def test_same_inputs_give_identical_json() -> None:
    assert json.dumps(plate()) == json.dumps(plate())


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"width": 2884}, "width must be a positive multiple of 8"),
        ({"height": 0}, "height must be a positive multiple of 8"),
        ({"denoise": 0.0}, r"denoise must be in \(0, 1\]"),
        ({"denoise": 1.2}, r"denoise must be in \(0, 1\]"),
        ({"upscaler": "sdxl-base-1.0"}, "not an upscale model"),
        ({"upscaler": "no-such-file"}, "not an upscale model"),
    ],
)
def test_bad_inputs_are_refused(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        plate(**kwargs)
