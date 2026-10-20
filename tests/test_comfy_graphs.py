import json

import pytest
from export_workflows import EXPORTS, build

from studio_core.comfy_graphs import KID_SAFE_NEGATIVE, txt2img
from studio_core.config import REPO_ROOT
from studio_core.models import load_manifest


@pytest.mark.parametrize("name", list(EXPORTS))
def test_saved_workflows_match_the_builder(name: str) -> None:
    saved = json.loads((REPO_ROOT / "comfy_workflows" / name).read_text())
    assert saved == build(name), "run: uv run scripts/export_workflows.py"


def nodes(wf: dict, class_type: str) -> list[dict]:
    return [n for n in wf.values() if n["class_type"] == class_type]


@pytest.mark.parametrize("style_id", list(load_manifest().styles))
@pytest.mark.parametrize("fast", [False, True])
def test_every_style_builds_a_valid_graph(style_id: str, fast: bool) -> None:
    manifest = load_manifest()
    wf = txt2img(manifest, style_id, "a red kite", fast=fast)
    style = manifest.styles[style_id]
    # Every link points at an existing node.
    for node in wf.values():
        for value in node["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                assert value[0] in wf
    ckpt = nodes(wf, "CheckpointLoaderSimple")[0]["inputs"]["ckpt_name"]
    assert ckpt == manifest.files[style.data["checkpoint"]].comfy_name
    expected_loras = len(style.data["loras"]) + (1 if style.settings(fast).get("lora") else 0)
    assert len(nodes(wf, "LoraLoader")) == expected_loras
    sampler = nodes(wf, "KSampler")[0]["inputs"]
    assert sampler["steps"] == style.settings(fast)["steps"]
    texts = [n["inputs"]["text"] for n in nodes(wf, "CLIPTextEncode")]
    assert "a red kite" in texts[0] and texts[1].endswith(KID_SAFE_NEGATIVE)


def test_same_inputs_give_identical_json() -> None:
    manifest = load_manifest()
    a = txt2img(manifest, "storybook", "x", seed=7)
    b = txt2img(manifest, "storybook", "x", seed=7)
    assert json.dumps(a) == json.dumps(b)
