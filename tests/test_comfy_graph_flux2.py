"""The FLUX.2 [klein] edit graph: node types, links and settings, checked without rendering."""

import json

import pytest

from studio_core.comfy_graphs import (
    FLUX2_KLEIN_MODEL,
    FLUX2_TEXT_ENCODER,
    FLUX2_VAE,
    flux2_edit,
)
from studio_core.models import load_manifest

PROMPT = "the same character from image 1, turned to a three-quarter view"


def build(references: list[str], **kwargs) -> dict:
    args = {"width": 768, "height": 1024, "seed": 7} | kwargs
    return flux2_edit(load_manifest(), PROMPT, references=references, **args)


def nodes(wf: dict, class_type: str) -> list[dict]:
    return [n for n in wf.values() if n["class_type"] == class_type]


def only(wf: dict, class_type: str) -> dict:
    found = nodes(wf, class_type)
    assert len(found) == 1, f"expected one {class_type}, found {len(found)}"
    return found[0]


def source(wf: dict, link: list) -> dict:
    """The node a link [node_id, slot] comes from."""
    return wf[link[0]]


def chain(wf: dict, link: list) -> list[dict]:
    """Walk a conditioning chain back through its ReferenceLatent nodes; return them in the
    order they were applied (closest to the text first) plus the node that starts the chain."""
    applied = []
    node = source(wf, link)
    while node["class_type"] == "ReferenceLatent":
        applied.append(node)
        node = source(wf, node["inputs"]["conditioning"])
    return [*reversed(applied), node]


def reference_name(wf: dict, ref_latent: dict) -> str:
    """The LoadImage value behind a ReferenceLatent: latent ← VAEEncode ← scale ← LoadImage."""
    encode = source(wf, ref_latent["inputs"]["latent"])
    assert encode["class_type"] == "VAEEncode"
    scale = source(wf, encode["inputs"]["pixels"])
    assert scale["class_type"] == "ImageScaleToTotalPixels"
    load = source(wf, scale["inputs"]["image"])
    assert load["class_type"] == "LoadImage"
    return load["inputs"]["image"]


@pytest.mark.parametrize("references", [["@front"], ["@front", "@pose"]])
def test_every_link_points_at_an_existing_node(references: list[str]) -> None:
    wf = build(references)
    for node in wf.values():
        for value in node["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                assert value[0] in wf
                assert value[1] == 0  # every node we link from is used by its first output


def test_node_types_follow_the_template() -> None:
    wf = build(["@front", "@pose"])
    counts: dict[str, int] = {}
    for node in wf.values():
        counts[node["class_type"]] = counts.get(node["class_type"], 0) + 1
    assert counts == {
        "UNETLoader": 1,
        "CLIPLoader": 1,
        "VAELoader": 1,
        "CLIPTextEncode": 1,
        "ConditioningZeroOut": 1,
        "LoadImage": 2,
        "ImageScaleToTotalPixels": 2,
        "VAEEncode": 2,
        "ReferenceLatent": 4,  # one per reference on the positive, one on the negative
        "EmptyFlux2LatentImage": 1,
        "Flux2Scheduler": 1,
        "KSamplerSelect": 1,
        "RandomNoise": 1,
        "CFGGuider": 1,
        "SamplerCustomAdvanced": 1,
        "VAEDecode": 1,
        "SaveImage": 1,
    }


def test_model_files_come_from_the_manifest_in_bf16() -> None:
    files = load_manifest().files
    wf = build(["@front"])
    unet = only(wf, "UNETLoader")["inputs"]
    assert unet["unet_name"] == files[FLUX2_KLEIN_MODEL].comfy_name
    assert unet["weight_dtype"] == "default"  # the file's bf16, never fp8 (no fp8 on MPS)
    clip = only(wf, "CLIPLoader")["inputs"]
    assert clip["clip_name"] == files[FLUX2_TEXT_ENCODER].comfy_name
    assert clip["type"] == "flux2"
    assert only(wf, "VAELoader")["inputs"]["vae_name"] == files[FLUX2_VAE].comfy_name
    # The same VAE encodes the references and decodes the result.
    vae_id = next(k for k, n in wf.items() if n["class_type"] == "VAELoader")
    for node in nodes(wf, "VAEEncode") + nodes(wf, "VAEDecode"):
        assert node["inputs"]["vae"] == [vae_id, 0]


def test_references_chain_in_order_on_both_prompts() -> None:
    references = ["@front", "@pose", "@palette"]
    wf = build(references)
    guider = only(wf, "CFGGuider")["inputs"]
    *positive, text = chain(wf, guider["positive"])
    *negative, zeroed = chain(wf, guider["negative"])
    assert text["class_type"] == "CLIPTextEncode" and text["inputs"]["text"] == PROMPT
    assert zeroed["class_type"] == "ConditioningZeroOut"
    assert source(wf, zeroed["inputs"]["conditioning"]) is text
    assert [reference_name(wf, n) for n in positive] == references
    assert [reference_name(wf, n) for n in negative] == references
    # Each reference is encoded once and shared by both prompts.
    for p, n in zip(positive, negative, strict=True):
        assert p["inputs"]["latent"] == n["inputs"]["latent"]


def test_size_seed_and_sampler_settings_land_in_the_right_inputs() -> None:
    wf = build(["@front"], width=832, height=1216, seed=1234, steps=6, filename_prefix="pip_3q")
    assert only(wf, "EmptyFlux2LatentImage")["inputs"] == {
        "width": 832,
        "height": 1216,
        "batch_size": 1,
    }
    assert only(wf, "Flux2Scheduler")["inputs"] == {"steps": 6, "width": 832, "height": 1216}
    assert only(wf, "RandomNoise")["inputs"] == {"noise_seed": 1234}
    assert only(wf, "KSamplerSelect")["inputs"] == {"sampler_name": "euler"}
    assert only(wf, "CFGGuider")["inputs"]["cfg"] == 1.0
    assert only(wf, "SaveImage")["inputs"]["filename_prefix"] == "pip_3q"
    scale = only(wf, "ImageScaleToTotalPixels")["inputs"]
    assert scale["megapixels"] == 1.0 and scale["upscale_method"] == "nearest-exact"
    # The sampler starts from the empty latent and is decoded then saved.
    sampled = only(wf, "SamplerCustomAdvanced")["inputs"]
    assert source(wf, sampled["latent_image"])["class_type"] == "EmptyFlux2LatentImage"
    assert source(wf, sampled["sigmas"])["class_type"] == "Flux2Scheduler"
    assert source(wf, sampled["noise"])["class_type"] == "RandomNoise"
    assert source(wf, sampled["guider"])["class_type"] == "CFGGuider"
    decode = only(wf, "VAEDecode")["inputs"]
    assert source(wf, decode["samples"])["class_type"] == "SamplerCustomAdvanced"
    saved = only(wf, "SaveImage")["inputs"]
    assert source(wf, saved["images"])["class_type"] == "VAEDecode"


def test_same_inputs_give_identical_json() -> None:
    assert json.dumps(build(["@front", "@pose"])) == json.dumps(build(["@front", "@pose"]))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"references": []}, "at least one reference"),
        ({"width": 770}, "width must be a positive multiple of 16"),
        ({"height": 0}, "height must be a positive multiple of 16"),
    ],
)
def test_bad_inputs_are_refused(kwargs: dict, message: str) -> None:
    references = kwargs.pop("references", ["@front"])
    with pytest.raises(ValueError, match=message):
        build(references, **kwargs)
