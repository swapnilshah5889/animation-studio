"""Build ComfyUI workflows (API format) from a style preset instead of hard-coding a checkpoint.

    manifest = load_manifest()
    workflow = txt2img(manifest, "storybook", "a cheerful little rabbit, full body", fast=True)
    paths, seconds = Comfy().run(workflow, out_dir)

The graph is: checkpoint → (VAE) → style LoRAs → (speed LoRA) → prompts → KSampler → decode → save.
Node ids are assigned in order, so the same inputs always produce the same JSON (golden-tested
against comfy_workflows/txt2img_sdxl*.json, which scripts/export_workflows.py regenerates).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from studio_core.models import Manifest

# Always appended to the negative prompt, whatever the style (D-013: children's content).
KID_SAFE_NEGATIVE = (
    "nsfw, nude, scary, horror, violent, blood, weapon, text, watermark, signature, blurry, "
    "extra limbs, deformed"
)


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}

    def add(self, class_type: str, title: str | None = None, **inputs: Any) -> str:
        node_id = str(len(self.nodes) + 1)
        node: dict[str, Any] = {"class_type": class_type, "inputs": inputs}
        if title:
            node["_meta"] = {"title": title}
        self.nodes[node_id] = node
        return node_id


@dataclass(frozen=True)
class Control:
    """A ControlNet condition: `image` is a LoadImage input (an uploaded name, or a placeholder
    run_graph substitutes); `type` picks a union model's mode ("openpose", "depth", "repaint",
    ...; "auto" leaves it unset)."""

    model: str  # file id in config/models.toml
    image: str
    type: str = "auto"
    strength: float = 1.0
    start: float = 0.0
    end: float = 1.0


def join_prompt(*parts: str) -> str:
    return ", ".join(p.strip() for p in parts if p and p.strip())


def txt2img(
    manifest: Manifest,
    style_id: str,
    prompt: str,
    *,
    fast: bool = False,
    negative: str = "",
    seed: int = 42,
    width: int = 1024,
    height: int = 1024,
    filename_prefix: str = "txt2img",
    controls: list[Control] | None = None,
    batch_size: int = 1,
) -> dict[str, dict[str, Any]]:
    """A text-to-image workflow for one style. `fast` uses the style's few-step settings.
    `controls` condition the image (ControlNet), e.g. a pose skeleton drawn in code."""
    style = manifest.styles[style_id]
    files = manifest.files
    settings = style.settings(fast)
    g = Graph()

    ckpt = g.add(
        "CheckpointLoaderSimple",
        f"checkpoint ({style_id})",
        ckpt_name=files[style.data["checkpoint"]].comfy_name,
    )
    model, clip, vae = [ckpt, 0], [ckpt, 1], [ckpt, 2]
    if vae_id := style.data.get("vae"):
        vae = [g.add("VAELoader", "VAE", vae_name=files[vae_id].comfy_name), 0]
    for lora in style.data.get("loras", []):
        node = g.add(
            "LoraLoader",
            "style LoRA",
            model=model,
            clip=clip,
            lora_name=files[lora["file"]].comfy_name,
            strength_model=lora["strength"],
            strength_clip=lora["strength"],
        )
        model, clip = [node, 0], [node, 1]
    if speed := settings.get("lora"):
        node = g.add(
            "LoraLoader",
            "speed LoRA",
            model=model,
            clip=clip,
            lora_name=files[speed].comfy_name,
            strength_model=1.0,
            strength_clip=1.0,
        )
        model, clip = [node, 0], [node, 1]

    positive_text = join_prompt(
        style.data.get("prompt_prefix", ""), prompt, style.data.get("prompt_suffix", "")
    )
    negative_text = join_prompt(style.data.get("negative", ""), negative, KID_SAFE_NEGATIVE)
    positive = g.add("CLIPTextEncode", "positive", clip=clip, text=positive_text)
    negative_node = g.add("CLIPTextEncode", "negative", clip=clip, text=negative_text)
    pos, neg = [positive, 0], [negative_node, 0]
    loaded: dict[str, str] = {}  # one loader per ControlNet file, shared by its conditions
    for c in controls or []:
        if c.model not in loaded:
            loaded[c.model] = g.add(
                "ControlNetLoader", "ControlNet", control_net_name=files[c.model].comfy_name
            )
        net = loaded[c.model]
        if c.type != "auto":
            net = g.add("SetUnionControlNetType", control_net=[net, 0], type=c.type)
        image = g.add("LoadImage", "control image", image=c.image)
        applied = g.add(
            "ControlNetApplyAdvanced",
            f"apply ControlNet ({c.type})",
            positive=pos,
            negative=neg,
            control_net=[net, 0],
            image=[image, 0],
            strength=c.strength,
            start_percent=c.start,
            end_percent=c.end,
            vae=vae,
        )
        pos, neg = [applied, 0], [applied, 1]
    latent = g.add("EmptyLatentImage", width=width, height=height, batch_size=batch_size)
    sampled = g.add(
        "KSampler",
        model=model,
        positive=pos,
        negative=neg,
        latent_image=[latent, 0],
        seed=seed,
        steps=settings["steps"],
        cfg=settings["cfg"],
        sampler_name=settings["sampler"],
        scheduler=settings["scheduler"],
        denoise=1.0,
    )
    image = g.add("VAEDecode", samples=[sampled, 0], vae=vae)
    g.add("SaveImage", images=[image, 0], filename_prefix=filename_prefix)
    return g.nodes
