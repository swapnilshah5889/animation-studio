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

`depth_map` needs no style either: a plate's depth (Depth Anything 3) for its parallax bands
(task 4.7).
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


# The xinsir union ControlNet (ProMax) whose "repaint" mode fills behind layers (D-047).
REPAINT_CONTROLNET = "controlnet-union-sdxl-promax"
# Seam handling for fills, in working-size pixels: the sampler redraws a ring this wide around
# the mask (2 latent cells), and the result fades into the original over the ring.
FILL_REDRAW_PX = 16
FILL_FEATHER_PX = FILL_REDRAW_PX // 2


def repaint_fill(
    manifest: Manifest,
    style_id: str,
    prompt: str,
    *,
    image: str,
    mask: str,
    seed: int,
    width: int,
    height: int,
    steps: int = 20,
    negative: str = "",
    filename_prefix: str = "fill",
) -> dict[str, dict[str, Any]]:
    """Repaint the masked region of a picture in the film's style, matched to its surroundings:
    the content *behind* a nearer depth layer (task 4.7), e.g. sky and hills where trees were.

    `image` and `mask` are LoadImage input values (uploaded names, or placeholders such as
    "@image" and "@mask" that run_graph substitutes). The mask is a plain greyscale picture,
    white = repaint, any size. Both are scaled to `width` x `height` (stretched, not cropped)
    and the result is that size: new pixels over the mask, fading into the input's own over
    the 2 * FILL_FEATHER_PX px around it, and the input's own everywhere else. Dilate the mask
    a few pixels past a layer's soft edge before calling, or the old edge colours stay behind
    as a halo.

    How ProMax is fed (checked against ComfyUI v0.42.1 and comfyui_controlnet_aux):
    - **Control image:** the picture with the masked pixels set to *black*. That is what xinsir
      feeds the repaint mode (ControlNetPlus/promax/controlnet_union_test_inpainting.py zeroes
      the masked pixels and runs an SDXL *inpaint* pipeline, i.e. a masked latent as below),
      and ComfyUI hands an SDXL ControlNet the 0..1 image as it is. InpaintPreprocessor's
      default (-1 in the hole) is the old SD1.5 inpaint ControlNet's convention, so
      `black_pixel_for_xinsir_cn` is on. SetUnionControlNetType picks "repaint" (control type 7)
      so the union model doesn't have to guess the task from the image.
    - **Latent: VAEEncodeForInpaint.** It paints the masked pixels mid-grey before encoding
      and attaches a noise mask grown by FILL_REDRAW_PX, so a ring around the region is
      redrawn too (see the composite). The grey matters even at denoise 1.0: ComfyUI starts
      SDXL's sampling from latent + sigma * noise, so what was under the mask still leaks in
      faintly, and a dark tree-shaped blob invites a tree back. InpaintModelConditioning would
      encode the *original* pixels into the latent for a normal checkpoint (its grey copy goes
      into concat conditioning, which only inpainting checkpoints read), and
      SetLatentNoiseMask likewise; both keep the thing being removed.
    - **Mask: the picture's red channel** (LoadImage, scaled to the working size, ImageToMask),
      so a black-and-white PNG from numpy reads directly, white = 1, and the seam widths below
      are in working-size pixels whatever size the mask was saved at. LoadImage's own MASK
      output is the alpha channel inverted (meant for holes painted in ComfyUI's mask editor)
      and is empty for a picture without alpha.
    - **Sampling:** the style's checkpoint, LoRAs and prompts at its normal cfg, sampler and
      scheduler; denoise 1.0 (the region gets new content); the ControlNet at strength 1.0 for
      every step, since the repaint mode is what ties the fill to the surroundings. The noise
      mask makes the sampler hold everything outside the region to the original (re-noised to
      each step's level), so the fill is painted in context.
    - **Composite:** decoding changes every pixel a little (the VAE round trip), and the noise
      mask works on 8 px latent cells, so ImageCompositeMasked puts the scaled input back
      outside the fill. A hard cut at the mask edge showed as a line wherever the new tones
      differ slightly from the old (a 1536x576 trial on the meadow plate), so the composite
      mask is the region grown by FILL_FEATHER_PX and blurred by as much: the fill fades out
      across the redrawn ring, never over pixels the sampler didn't redraw.

    `width` and `height` must be multiples of 8 (the latent is 1/8 of the image; VAE encoding
    would crop the rest). SDXL works best near 1 MP, e.g. 1536x576 for a 2880x1080 plate."""
    for name, size in (("width", width), ("height", height)):
        if size < 8 or size % 8:
            raise ValueError(f"{name} must be a positive multiple of 8, got {size}")
    if steps < 1:
        raise ValueError(f"steps must be at least 1, got {steps}")
    files = manifest.files
    settings = manifest.styles[style_id].settings(fast=False)
    g = Graph()
    style = _add_style(g, manifest, style_id, prompt, fast=False, negative=negative)

    loaded = g.add("LoadImage", "picture", image=image)
    picture = g.add(
        "ImageScale",
        "working size",
        image=[loaded, 0],
        upscale_method="lanczos",
        width=width,
        height=height,
        crop="disabled",
    )
    mask_picture = g.add("LoadImage", "mask (white = repaint)", image=mask)
    mask_sized = g.add(
        "ImageScale",
        "mask at working size",
        image=[mask_picture, 0],
        upscale_method="bilinear",
        width=width,
        height=height,
        crop="disabled",
    )
    region = g.add("ImageToMask", "region", image=[mask_sized, 0], channel="red")
    hint = g.add(
        "InpaintPreprocessor",
        "control image (masked pixels black)",
        image=[picture, 0],
        mask=[region, 0],
        black_pixel_for_xinsir_cn=True,
    )
    net = g.add(
        "ControlNetLoader", "ControlNet", control_net_name=files[REPAINT_CONTROLNET].comfy_name
    )
    net = g.add("SetUnionControlNetType", control_net=[net, 0], type="repaint")
    applied = g.add(
        "ControlNetApplyAdvanced",
        "apply ControlNet (repaint)",
        positive=style.positive,
        negative=style.negative,
        control_net=[net, 0],
        image=[hint, 0],
        strength=1.0,
        start_percent=0.0,
        end_percent=1.0,
        vae=style.vae,
    )
    latent = g.add(
        "VAEEncodeForInpaint",
        "grey out the region",
        pixels=[picture, 0],
        vae=style.vae,
        mask=[region, 0],
        grow_mask_by=FILL_REDRAW_PX,
    )
    sampled = g.add(
        "KSampler",
        "repaint",
        model=style.model,
        positive=[applied, 0],
        negative=[applied, 1],
        latent_image=[latent, 0],
        seed=seed,
        steps=steps,
        cfg=settings["cfg"],
        sampler_name=settings["sampler"],
        scheduler=settings["scheduler"],
        denoise=1.0,
    )
    decoded = g.add("VAEDecode", samples=[sampled, 0], vae=style.vae)
    # The seam: the region grown by FILL_FEATHER_PX, then blurred by as much, is 1 over the
    # whole region and fades to 0 within 2 * FILL_FEATHER_PX outside it (all inside the
    # redrawn ring), so the new pixels blend into the old ones instead of meeting at a line.
    grown = g.add(
        "GrowMask",
        "seam: grow",
        mask=[region, 0],
        expand=FILL_FEATHER_PX,
        tapered_corners=True,
    )
    grown_picture = g.add("MaskToImage", mask=[grown, 0])
    blurred = g.add(
        "ImageBlur",
        "seam: feather",
        image=[grown_picture, 0],
        blur_radius=FILL_FEATHER_PX,
        sigma=FILL_FEATHER_PX / 2,
    )
    seam = g.add("ImageToMask", "seam", image=[blurred, 0], channel="red")
    merged = g.add(
        "ImageCompositeMasked",
        "keep the pixels outside the mask",
        destination=[picture, 0],
        source=[decoded, 0],
        x=0,
        y=0,
        resize_source=False,
        mask=[seam, 0],
    )
    g.add("SaveImage", images=[merged, 0], filename_prefix=filename_prefix)
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


# Depth for parallax layers (task 4.7, D-047): file ids in config/models.toml.
DA3_MONO_LARGE = "depth-anything-3-mono-large"
DAV2_SMALL = "depth-anything-v2-small"
DEPTH_MODELS = ("da3", "dav2")
# DA3's working size: the longest side in px, a multiple of 14 (its ViT patch). Measured on the
# 2880x1080 meadow plate (model already loaded, M4; loading adds ~1 s): 504 → blocky tree
# edges; 1008 → 1.5 s, thin branches merged; 1512 → 4.8 s, branches separate and edges
# smooth; 2016 → 13 s, no better, with specks of "sky" inside trees; 2520 ran out of GPU
# memory, and ComfyUI saved an all-black map without raising an error. Hence 1512, and a cap
# at 2016.
DA3_RESOLUTION = 1512
DA3_MAX_RESOLUTION = 2016


def depth_map(
    manifest: Manifest,
    *,
    image: str,
    model: str = "da3",
    resolution: int | None = None,
    filename_prefix: str = "depth",
) -> dict[str, dict[str, Any]]:
    """A depth map of a background plate, for cutting it into parallax bands (task 4.7).

    `image` is a LoadImage input value (an uploaded name, or a placeholder such as "@plate"
    that run_graph substitutes). The output is one greyscale PNG (three equal channels) the
    size of the plate: **bright = near, dark = far**, 0..255 (0..1 as a ComfyUI image).

    `model` "da3" (the default, D-047): Depth Anything 3 MONO-LARGE through ComfyUI's core
    nodes, LoadDA3Model → DA3Inference (mono) → DA3Render (depth, "v2_style"). `resolution` is
    the size DA3 works at (longest side, a multiple of 14, up to DA3_MAX_RESOLUTION; None =
    DA3_RESOLUTION); the map is scaled back up to the plate's size. What the values mean:
    - **Sky is exactly 0.** DA3 has a sky head, and v2_style paints every pixel it calls sky
      (probability >= 0.3) black, so the sky is uniformly the farthest thing. Why not
      "min_max": DA3's raw depth in the sky is meaningless (on the meadow it came out *nearer*
      than the trees), so a plain min-max stretch makes the sky bright.
    - **The land is linear in depth**: 1 - (depth - lo) / (hi - lo), with lo and hi the 1st and
      99th percentiles of the non-sky depth, clamped. So the farthest 1% of the land is also 0
      (on the meadow: the distant hills, which then go with the sky) and the nearest 1% is 1.
      Linear in depth, not in 1/depth: cuts at quantiles don't care (any monotonic scale gives
      the same cut), but ratios of these values are not parallax ratios.
    - Not byte-for-byte repeatable: v2_style picks lo and hi from a random sample of 100k
      pixels, so two runs differ by up to 2 levels (measured: mean 0.3 level).

    `model` "dav2" is the comparison the brief asked for (D-047), kept for re-measuring: Depth
    Anything V2 Small through comfyui_controlnet_aux (its node always works at 518 px on the
    short side, so `resolution` must be None). Its values are min-max-stretched relative
    *inverse* depth (disparity), so far things crowd near 0: on the meadow the whole distant
    tree line sat below 0.12 with the sky, and tree edges against the sky were soft (a 2-3 px
    halo). The node returns its own size (short side = 1024 here); a final ImageScale brings
    it back to the plate's size."""
    files = manifest.files
    g = Graph()
    loaded = g.add("LoadImage", "plate", image=image)
    if model == "da3":
        size = DA3_RESOLUTION if resolution is None else resolution
        if not 140 <= size <= DA3_MAX_RESOLUTION or size % 14:
            raise ValueError(
                f"DA3's resolution must be a multiple of 14 in 140..{DA3_MAX_RESOLUTION}, "
                f"got {size}"
            )
        net = g.add(
            "LoadDA3Model",
            "Depth Anything 3 MONO-LARGE",
            model_name=files[DA3_MONO_LARGE].comfy_name,
            weight_dtype="default",  # the file's fp16 on MPS
        )
        geometry = g.add(
            "DA3Inference",
            da3_model=[net, 0],
            image=[loaded, 0],
            resolution=size,
            resize_method="upper_bound_resize",
            mode="mono",
        )
        # DA3Render's `output` is a dynamic combo: the chosen option's own inputs follow as
        # "output.<name>" keys. apply_sky_clip only changes sky depth that v2_style blackens.
        depth = g.add(
            "DA3Render",
            "depth",
            da3_geometry=[geometry, 0],
            output="depth",
            **{"output.normalization": "v2_style", "output.apply_sky_clip": False},
        )
    elif model == "dav2":
        if resolution is not None:
            raise ValueError("DAv2's node always works at 518 px on the short side")
        raw = g.add(
            "DepthAnythingV2Preprocessor",
            "Depth Anything V2 Small",
            image=[loaded, 0],
            # The node takes a bare file name (it finds it under its annotators folder).
            ckpt_name=files[DAV2_SMALL].dest.rsplit("/", 1)[-1],
            resolution=1024,  # its output's short side, not the size the model works at
        )
        plate_size = g.add("GetImageSize", image=[loaded, 0])
        depth = g.add(
            "ImageScale",
            "plate size",
            image=[raw, 0],
            upscale_method="bilinear",
            width=[plate_size, 0],
            height=[plate_size, 1],
            crop="disabled",
        )
    else:
        raise ValueError(f"unknown depth model {model!r}; use one of {DEPTH_MODELS}")
    g.add("SaveImage", images=[depth, 0], filename_prefix=filename_prefix)
    return g.nodes
