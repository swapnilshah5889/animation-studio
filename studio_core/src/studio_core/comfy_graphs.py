"""Build ComfyUI workflows (API format) from a style preset instead of hard-coding a checkpoint.

    manifest = load_manifest()
    workflow = txt2img(manifest, "storybook", "a cheerful little rabbit, full body", fast=True)
    paths, seconds = Comfy().run(workflow, out_dir)

The graph is: checkpoint → (VAE) → style LoRAs → (speed LoRA) → prompts → KSampler → decode → save.
Node ids are assigned in order, so the same inputs always produce the same JSON (golden-tested
against comfy_workflows/txt2img_sdxl*.json, which scripts/export_workflows.py regenerates).

`finish_plate` shares that style front half: it upscales a chosen background draft with
Real-ESRGAN and refines it with the style at low denoise (task 4.6).

`flux2_edit` is the other builder: FLUX.2 [klein] 4B redrawing reference images from a prompt
(front → three-quarter view trials, task 4.5, D-052). It doesn't use the style presets.
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


# A link in an API-format graph: [node_id, output_slot] of the node whose output feeds an input.
Link = list[Any]


@dataclass(frozen=True)
class StyleLinks:
    """What a style's front half hands to the rest of a graph: the (LoRA-patched) model for the
    sampler, the VAE for encoding and decoding, and the encoded positive/negative prompts."""

    model: Link
    vae: Link
    positive: Link
    negative: Link


def _add_style(
    g: Graph, manifest: Manifest, style_id: str, prompt: str, *, fast: bool, negative: str
) -> StyleLinks:
    """Add a style's checkpoint → (VAE) → style LoRAs → (speed LoRA) → prompts to `g`.

    Shared by every SDXL builder so a style means the same thing everywhere: the same files,
    LoRA strengths, prompt prefix/suffix and kid-safe negative. The nodes are added in a fixed
    order, which keeps txt2img's JSON (and its golden files) unchanged."""
    style = manifest.styles[style_id]
    files = manifest.files
    settings = style.settings(fast)

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
    return StyleLinks(model=model, vae=vae, positive=[positive, 0], negative=[negative_node, 0])


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
    files = manifest.files
    settings = manifest.styles[style_id].settings(fast)
    g = Graph()
    style = _add_style(g, manifest, style_id, prompt, fast=fast, negative=negative)
    pos, neg = style.positive, style.negative
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
            vae=style.vae,
        )
        pos, neg = [applied, 0], [applied, 1]
    latent = g.add("EmptyLatentImage", width=width, height=height, batch_size=batch_size)
    sampled = g.add(
        "KSampler",
        model=style.model,
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
    image = g.add("VAEDecode", samples=[sampled, 0], vae=style.vae)
    g.add("SaveImage", images=[image, 0], filename_prefix=filename_prefix)
    return g.nodes


def finish_plate(
    manifest: Manifest,
    style_id: str,
    prompt: str,
    *,
    image: str,
    seed: int,
    width: int = 2880,
    height: int = 1080,
    denoise: float = 0.3,
    steps: int = 10,
    negative: str = "",
    upscaler: str = "realesrgan-x4plus-anime-6b",
    filename_prefix: str = "plate",
) -> dict[str, dict[str, Any]]:
    """Finish a chosen background draft into a plate: upscale it, then let SDXL redraw the detail.

    `image` is a LoadImage input value (an uploaded name, or a placeholder such as "@draft"
    that run_graph substitutes): the 1536x576 txt2img draft, task 4.6. The plate is
    `width` x `height` (2880x1080: the 1920x1080 frame plus room for the camera to pan).

    The chain: draft → Real-ESRGAN x4 (`upscaler`, a file id in config/models.toml; 1536x576
    becomes 6144x2304) → lanczos down to the plate size → VAE-encode → KSampler with the
    style's checkpoint, LoRAs and prompts at its *normal* settings and `denoise` → decode → save.

    Why both steps: SDXL can't compose a good 2880x1080 picture directly (it was trained near
    1 MP, and far beyond that it repeats subjects across the frame), so the composition comes
    from the draft at a native bucket. Real-ESRGAN enlarges it cleanly but invents no detail
    (flat areas and edges look soft and plasticky). The refine pass adds that detail.

    Why low denoise: img2img starts from the encoded upscale with only `denoise` worth of noise
    added, so the model can only make small changes. ~0.3 redraws texture, line and shading in
    the style while keeping every shape where the draft put it; the human chose the draft for
    its layout, and the depth split (task 4.7) and the characters' ground line depend on it.
    From about 0.5 up, SDXL starts recomposing at this size: duplicated objects, a moved
    horizon. Note ComfyUI runs the full `steps` either way: it builds a schedule of
    steps/denoise steps and runs the last `steps` of them (25 at 0.3), so low denoise is gentler
    but not faster.

    Memory and time (Mac): 2880x1080 is ~3.1 MP, about 3x the pixels of a 1024x1024 image,
    and attention cost grows faster than that, so expect one plate to take several times the
    ~222 s of a 25-step 1024x1024 image (docs/benchmarks.md) and more memory than a draft. On
    the 24 GB M4 unload Ollama first. ComfyUI falls back to tiled VAE encode/decode if those run
    out of memory; the UNet pass has no such fallback.

    The draft should have the plate's aspect ratio (8:3 by default): ImageScale stretches to
    the exact size (crop "disabled") rather than cutting the edges off. `width` and `height`
    must be multiples of 8 (the SDXL latent is 1/8 of the image; VAEEncode would crop the
    rest, shifting the plate against the draft)."""
    for name, size in (("width", width), ("height", height)):
        if size < 8 or size % 8:
            raise ValueError(f"{name} must be a positive multiple of 8, got {size}")
    if not 0.0 < denoise <= 1.0:
        raise ValueError(f"denoise must be in (0, 1], got {denoise}")
    files = manifest.files
    if upscaler not in files or not files[upscaler].dest.startswith("upscale_models/"):
        raise ValueError(f"{upscaler!r} is not an upscale model in config/models.toml")
    settings = manifest.styles[style_id].settings(fast=False)
    g = Graph()
    style = _add_style(g, manifest, style_id, prompt, fast=False, negative=negative)

    draft = g.add("LoadImage", "draft", image=image)
    esrgan = g.add("UpscaleModelLoader", "upscaler", model_name=files[upscaler].comfy_name)
    upscaled = g.add(
        "ImageUpscaleWithModel", "upscale x4", upscale_model=[esrgan, 0], image=[draft, 0]
    )
    sized = g.add(
        "ImageScale",
        "plate size",
        image=[upscaled, 0],
        upscale_method="lanczos",
        width=width,
        height=height,
        crop="disabled",
    )
    latent = g.add("VAEEncode", pixels=[sized, 0], vae=style.vae)
    sampled = g.add(
        "KSampler",
        "refine",
        model=style.model,
        positive=style.positive,
        negative=style.negative,
        latent_image=[latent, 0],
        seed=seed,
        # ComfyUI runs every step at any denoise; a light refine needs few (the default 10,
        # against the style's 25), which keeps a ~3 MP pass on this Mac to a few minutes.
        steps=steps,
        cfg=settings["cfg"],
        sampler_name=settings["sampler"],
        scheduler=settings["scheduler"],
        denoise=denoise,
    )
    decoded = g.add("VAEDecode", samples=[sampled, 0], vae=style.vae)
    g.add("SaveImage", images=[decoded, 0], filename_prefix=filename_prefix)
    return g.nodes


# FLUX.2 [klein] 4B, distilled (task 4.5 trial, D-052): file ids in config/models.toml.
FLUX2_KLEIN_MODEL = "flux2-klein-4b"
FLUX2_TEXT_ENCODER = "qwen3-4b-text-encoder"
FLUX2_VAE = "flux2-vae"


def flux2_edit(
    manifest: Manifest,
    prompt: str,
    *,
    references: list[str],
    width: int,
    height: int,
    seed: int,
    steps: int = 4,
    reference_megapixels: float = 1.0,
    filename_prefix: str = "flux2_edit",
) -> dict[str, dict[str, Any]]:
    """An image-editing workflow for FLUX.2 [klein] 4B (distilled): redraw the reference
    image(s) as the prompt says, e.g. "the same character, turned to a three-quarter view".

    `references` are LoadImage input values (uploaded names, or placeholders such as "@front"
    that run_graph substitutes). The prompt can name them in order: "image 1", "image 2", ...
    The first is the image being edited; a second can carry a pose or a detail to borrow.

    How klein edits: there is no ControlNet, adapter or img2img denoise. Each reference is
    VAE-encoded and attached to the conditioning by a ReferenceLatent node (several chain, each
    appending one more latent). While sampling, the model turns those latents into extra tokens
    next to the new image's tokens, so attention can copy identity, colours and costume from
    them; the new image still starts from pure noise at `width` x `height`. The chain follows
    Comfy-Org's template (image_flux2_klein_image_edit_4b_distilled): every reference goes on
    the positive prompt and on its zeroed-out copy (the negative), cfg 1, euler, 4 steps, with
    Flux2Scheduler's resolution-aware sigmas. At cfg 1 the negative is never evaluated, so a
    negative prompt (KID_SAFE_NEGATIVE) can't help here: keep the prompt and inputs kid-safe.

    Why bf16: weight_dtype stays "default" (the file's own bf16). The template ships an fp8
    file, but PyTorch's MPS backend has no float8, so fp8 weights don't run on the Mac.

    `width` and `height` must be multiples of 16 (the latent is 1/16 of the image size, and
    EmptyFlux2LatentImage steps by 16). `reference_megapixels` resizes each reference before
    encoding, as the template does (1.0 = about 1024x1024)."""
    if not references:
        raise ValueError("flux2_edit needs at least one reference image")
    for name, size in (("width", width), ("height", height)):
        if size < 16 or size % 16:
            raise ValueError(f"{name} must be a positive multiple of 16, got {size}")
    files = manifest.files
    g = Graph()

    unet = g.add(
        "UNETLoader",
        "FLUX.2 klein 4B",
        unet_name=files[FLUX2_KLEIN_MODEL].comfy_name,
        weight_dtype="default",  # bf16 as stored; never fp8 on MPS
    )
    clip = g.add(
        "CLIPLoader",
        "Qwen3 4B text encoder",
        clip_name=files[FLUX2_TEXT_ENCODER].comfy_name,
        type="flux2",
        device="default",
    )
    vae = g.add("VAELoader", "FLUX.2 VAE", vae_name=files[FLUX2_VAE].comfy_name)
    text = g.add("CLIPTextEncode", "positive", clip=[clip, 0], text=prompt)
    zeroed = g.add("ConditioningZeroOut", "negative (zeroed)", conditioning=[text, 0])
    pos, neg = [text, 0], [zeroed, 0]
    for i, ref in enumerate(references, start=1):
        image = g.add("LoadImage", f"reference {i}", image=ref)
        scaled = g.add(
            "ImageScaleToTotalPixels",
            image=[image, 0],
            upscale_method="nearest-exact",
            megapixels=reference_megapixels,
            resolution_steps=1,
        )
        latent = g.add("VAEEncode", pixels=[scaled, 0], vae=[vae, 0])
        pos = [g.add("ReferenceLatent", conditioning=pos, latent=[latent, 0]), 0]
        neg = [g.add("ReferenceLatent", conditioning=neg, latent=[latent, 0]), 0]

    empty = g.add("EmptyFlux2LatentImage", width=width, height=height, batch_size=1)
    sigmas = g.add("Flux2Scheduler", steps=steps, width=width, height=height)
    sampler = g.add("KSamplerSelect", sampler_name="euler")
    noise = g.add("RandomNoise", noise_seed=seed)
    guider = g.add("CFGGuider", model=[unet, 0], positive=pos, negative=neg, cfg=1.0)
    sampled = g.add(
        "SamplerCustomAdvanced",
        noise=[noise, 0],
        guider=[guider, 0],
        sampler=[sampler, 0],
        sigmas=[sigmas, 0],
        latent_image=[empty, 0],
    )
    decoded = g.add("VAEDecode", samples=[sampled, 0], vae=[vae, 0])
    g.add("SaveImage", images=[decoded, 0], filename_prefix=filename_prefix)
    return g.nodes
