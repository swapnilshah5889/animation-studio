"""Rowan front-only rig test (D-107), stage 1: the art layers, made locally with ComfyUI. Safe to re-run.

    uv run --project studio_core python scripts/spikes/rowan_rig_test.py gen [job ...]

Jobs (each writes PNGs to ~/ai-studio/scratch/rowan-rig-test/gen/<job>/):
  figure  SAM 2.1 mask of Rowan in the approved canonical
  plate   wide 1824x1024 background: the canonical shrunk to 0.7, Rowan painted out, the sides outpainted
  mouth   three mouth variants (talk "A", round "O", smile) inpainted on the canonical, low denoise
  eyes    eyes gently closed, inpainted on the canonical
  wave    the far arm raised in a wave with an open hand (two seeds)
Same model and style as the canonical (SDXL Base 1.0 + StorybookRedmondV2, D-106). Coordinates are in the
canonical's 832x1216 frame, read from a gridded crop.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from studio_core.comfy import Comfy
from studio_core.comfy_graphs import Graph
from studio_core.puppet.segment import clean

CANON = Path.home() / "ai-studio/scratch/character-art-proof/canonical/rowan-canonical.png"
OUT = Path.home() / "ai-studio/scratch/rowan-rig-test"
CKPT = "sd_xl_base_1.0.safetensors"
LORA = "StorybookRedmondV2-KidsBook-KidsRedmAF.safetensors"
STYLE = "KidsRedmAF, hand-painted watercolor and ink children's storybook illustration, soft paper texture"
NEG = (
    "photorealistic, 3d render, plastic, anime, text, watermark, extra fingers, extra limbs, extra eyes, "
    "deformed hands, scary, multiple people, tongue out, sticking out tongue, teeth"
)
ROWAN = "a 9 year old child with a rust red cap, chestnut wavy hair, pale teal shirt, olive vest"

EYES = [(300, 260), (405, 267)]  # centres; each eye is about 30x23 px
MOUTH = (345, 330)
PLATE_W, PLATE_H = 1824, 1024


def _mask_png(path: Path, mask: np.ndarray, feather: int = 0) -> Path:
    img = Image.fromarray((mask > 0).astype(np.uint8) * 255, "L")
    if feather:
        img = img.filter(ImageFilter.GaussianBlur(feather))
    img.convert("RGB").save(path)
    return path


def _ellipses(shape: tuple[int, int], items: list[tuple[int, int, int, int]]) -> np.ndarray:
    img = Image.new("L", (shape[1], shape[0]), 0)
    d = ImageDraw.Draw(img)
    for cx, cy, rx, ry in items:
        d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=255)
    return np.array(img)


def _model(g: Graph) -> tuple[str, str]:
    ck = g.add("CheckpointLoaderSimple", ckpt_name=CKPT)
    lo = g.add(
        "LoraLoader",
        model=[ck, 0],
        clip=[ck, 1],
        lora_name=LORA,
        strength_model=0.9,
        strength_clip=0.9,
    )
    return ck, lo


def inpaint_graph(
    image: str, mask: str, prompt: str, seeds: list[int], denoise: float, prefix: str
) -> dict:
    """Inpaint `mask` (white = repaint) and paste the result back onto the untouched image."""
    g = Graph()
    ck, lo = _model(g)
    pos = g.add("CLIPTextEncode", text=f"{STYLE}, {prompt}", clip=[lo, 1])
    neg = g.add("CLIPTextEncode", text=NEG, clip=[lo, 1])
    img = g.add("LoadImage", image=image)
    m = g.add("LoadImageMask", image=mask, channel="red")
    if denoise >= 1.0:
        lat = g.add(
            "VAEEncodeForInpaint", pixels=[img, 0], vae=[ck, 2], mask=[m, 0], grow_mask_by=12
        )
    else:
        enc = g.add("VAEEncode", pixels=[img, 0], vae=[ck, 2])
        lat = g.add("SetLatentNoiseMask", samples=[enc, 0], mask=[m, 0])
    for s in seeds:
        k = g.add(
            "KSampler",
            model=[lo, 0],
            positive=[pos, 0],
            negative=[neg, 0],
            latent_image=[lat, 0],
            seed=s,
            steps=30,
            cfg=6.0,
            sampler_name="dpmpp_2m",
            scheduler="karras",
            denoise=denoise,
        )
        dec = g.add("VAEDecode", samples=[k, 0], vae=[ck, 2])
        comp = g.add(
            "ImageCompositeMasked",
            destination=[img, 0],
            source=[dec, 0],
            x=0,
            y=0,
            resize_source=False,
            mask=[m, 0],
        )
        g.add("SaveImage", images=[comp, 0], filename_prefix=f"{prefix}_{s}")
    return g.nodes


def sam_graph(image: str, box: list[int], points: list[tuple[int, int]], prefix: str) -> dict:
    g = Graph()
    sam = g.add(
        "DownloadAndLoadSAM2Model",
        model="sam2.1_hiera_base_plus.safetensors",
        segmentor="single_image",
        device="mps",
        precision="fp32",
    )
    img = g.add("LoadImage", image=image)
    mask = g.add(
        "Sam2Segmentation",
        sam2_model=[sam, 0],
        image=[img, 0],
        keep_model_loaded=False,
        coordinates_positive=json.dumps([{"x": x, "y": y} for x, y in points]),
        bboxes={"__value__": [box]},
        individual_objects=False,
    )
    as_img = g.add("MaskToImage", mask=[mask, 0])
    g.add("SaveImage", images=[as_img, 0], filename_prefix=prefix)
    return g.nodes


def run(comfy: Comfy, job: str, graph: dict) -> list[Path]:
    out = OUT / "gen" / job
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    paths, secs = comfy.run(graph, out)
    print(f"{job}: {len(paths)} image(s) in {secs:.0f} s")
    return paths


def figure(comfy: Comfy) -> None:
    pts = [
        (360, 120),
        (340, 250),
        (235, 300),
        (370, 560),
        (520, 600),
        (380, 800),
        (300, 1080),
        (460, 1080),
    ]
    run(comfy, "figure", sam_graph(comfy.upload_image(CANON), [180, 70, 565, 1180], pts, "figure"))


def plate(comfy: Comfy) -> None:
    """A whole new wide plate in the canonical's airy palette (a kept canonical patch showed as a box)."""
    g = Graph()
    ck, lo = _model(g)
    text = (
        f"{STYLE}, light airy watercolor with lots of cream paper white space, a quiet forest clearing, a few "
        "slender pale brown trees, soft sage green leafy plants and ferns at the sides, a soft mossy grassy "
        "ground in the middle, gentle warm morning light, empty scene, no people, no characters"
    )
    pos = g.add("CLIPTextEncode", text=text, clip=[lo, 1])
    neg = g.add(
        "CLIPTextEncode", text=NEG + ", person, child, animal, dark, saturated", clip=[lo, 1]
    )
    lat = g.add("EmptyLatentImage", width=PLATE_W, height=PLATE_H, batch_size=1)
    k = g.add(
        "KSampler",
        model=[lo, 0],
        positive=[pos, 0],
        negative=[neg, 0],
        latent_image=[lat, 0],
        seed=5102,
        steps=30,
        cfg=6.0,
        sampler_name="dpmpp_2m",
        scheduler="karras",
        denoise=1.0,
    )
    dec = g.add("VAEDecode", samples=[k, 0], vae=[ck, 2])
    g.add("SaveImage", images=[dec, 0], filename_prefix="plate")
    run(comfy, "plate", g.nodes)


FACE_BOX = (
    225,
    200,
    465,
    380,
)  # x0, y0, x1, y1 in the canonical; inpainted 4x up, then pasted back
FACE_UP = 4


def face_variant(
    comfy: Comfy, job: str, mask: np.ndarray, text: str, seed: int, denoise: float
) -> None:
    """Detailer-style inpaint: enlarge the face crop so the model has room, repaint, shrink, paste."""
    x0, y0, x1, y1 = FACE_BOX
    w, h = (x1 - x0) * FACE_UP, (y1 - y0) * FACE_UP
    crop = Image.open(CANON).convert("RGB").crop(FACE_BOX).resize((w, h), Image.LANCZOS)
    crop_path = OUT / f"{job}_crop.png"
    crop.save(crop_path)
    m = Image.fromarray((mask[y0:y1, x0:x1] > 0).astype(np.uint8) * 255).resize((w, h))
    mask_path = OUT / f"{job}_cropmask.png"
    m.filter(ImageFilter.GaussianBlur(8)).convert("RGB").save(mask_path)
    g = inpaint_graph(
        comfy.upload_image(crop_path), comfy.upload_image(mask_path), text, [seed], denoise, job
    )
    (big,) = run(comfy, job, g)
    small = Image.open(big).convert("RGB").resize((x1 - x0, y1 - y0), Image.LANCZOS)
    alpha = Image.fromarray((mask[y0:y1, x0:x1] > 0).astype(np.uint8) * 255).filter(
        ImageFilter.GaussianBlur(2)
    )
    full = Image.open(CANON).convert("RGB")
    full.paste(small, (x0, y0), alpha)
    full.save(big.with_name(f"{job}_full.png"))
    crop_path.unlink()
    mask_path.unlink()


def mouth(comfy: Comfy) -> None:
    """Bold mouth drawings (review 1: the 0.85-denoise ones all read as the same pout)."""
    m = _ellipses((1216, 832), [(MOUTH[0], MOUTH[1] + 4, 32, 22)])
    face = "close-up of a child's face, symmetrical, centred mouth, clearly drawn mouth"
    variants = {
        # review 2: "tongue visible" gave a tongue sticking out, and the open smile read as a gasp
        "A": "the child is talking, a small open mouth mid-word, a soft dark oval inside, lips relaxed",
        "O": "mouth open in a clear round O shape saying oh, dark red round inside",
        "smile": "a sweet happy closed-mouth smile, lips closed, both corners curving up evenly, cheerful",
    }
    seeds = {"A": 7331, "O": 7321, "smile": 7331}
    for name, text in variants.items():
        face_variant(comfy, f"mouth_{name}", m, f"{face}, {text}", seeds[name], 1.0)


def eyes(comfy: Comfy) -> None:
    m = _ellipses((1216, 832), [(x, y, 26, 20) for x, y in EYES])
    text = (
        "close-up of a child's face, both eyes closed in the same way, two matching closed eyelids drawn as "
        "soft downward curved lines with short lashes, symmetrical, peaceful"
    )
    face_variant(comfy, "eyes", m, text, 7411, 0.9)


def wave(comfy: Comfy) -> None:
    img = Image.new("L", (832, 1216), 0)
    ImageDraw.Draw(img).polygon(
        [
            (470, 365),
            (540, 330),
            (640, 140),
            (790, 120),
            (790, 330),
            (640, 470),
            (548, 470),
            (540, 610),
            (470, 610),
        ],
        fill=255,
    )
    head = _ellipses((1216, 832), [(370, 230, 175, 150)])
    m = (np.array(img) > 0) & ~(head > 0)
    mp = comfy.upload_image(_mask_png(OUT / "wave_mask.png", m))
    text = (
        f"{ROWAN}, the child raises one arm high beside the head and waves hello with an open hand, palm "
        "facing forward, five small fingers spread, pale teal shirt sleeve"
    )
    run(
        comfy, "wave", inpaint_graph(comfy.upload_image(CANON), mp, text, [8101, 8102], 1.0, "wave")
    )


WAVE_PICK = "wave_8101"  # the better of the two wave candidates, by eye


def wave_image() -> Path:
    return next((OUT / "gen" / "wave").glob(f"{WAVE_PICK}_*.png"))


def waveseg(comfy: Comfy) -> None:
    """Two SAM masks on the wave drawing: the whole figure, and the raised arm alone."""
    up = comfy.upload_image(wave_image())
    pts = [
        (360, 120),
        (340, 250),
        (235, 300),
        (370, 560),
        (380, 800),
        (300, 1080),
        (460, 1080),
        (572, 340),
    ]
    run(comfy, "wave_figure", sam_graph(up, [180, 70, 700, 1180], pts, "wave_figure"))
    run(
        comfy,
        "wave_arm",
        sam_graph(up, [490, 170, 660, 470], [(572, 340), (617, 207), (530, 400)], "wave_arm"),
    )


JOBS = {
    "figure": figure,
    "plate": plate,
    "mouth": mouth,
    "eyes": eyes,
    "wave": wave,
    "waveseg": waveseg,
}

NECK_Y, HEAD_BOTTOM = (
    340,
    375,
)  # torso keeps y >= NECK_Y, head keeps y < HEAD_BOTTOM (an overlap band)


def _mask(job: str) -> np.ndarray:
    """A SAM mask with holes filled and stray specks (background leaves) dropped."""
    return clean(np.array(Image.open(next((OUT / "gen" / job).glob("*.png"))).convert("L")) > 127)


def _rgba(rgb_path: Path, mask: np.ndarray, out: Path, feather: float = 1.0) -> None:
    rgb = Image.open(rgb_path).convert("RGB")
    a = Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(feather))
    rgb.putalpha(a)
    rgb.save(out)


def layers() -> None:
    """Cut the RGBA layers the Blender rig stacks (all in the canonical's 832x1216 frame)."""
    lay = OUT / "layers"
    lay.mkdir(exist_ok=True)
    rows = np.arange(1216)[:, None] * np.ones((1, 832), bool)
    fig = _mask("figure")
    head_zone = (rows < HEAD_BOTTOM) & _ellipses((1216, 832), [(370, 215, 190, 175)]).astype(bool)
    _rgba(CANON, fig & (rows >= NECK_Y), lay / "body_rest.png")
    _rgba(CANON, fig & head_zone, lay / "head.png")
    arm = _mask("wave_arm")
    wfig = _mask("wave_figure") | arm
    _rgba(wave_image(), wfig & (rows >= NECK_Y) & ~arm, lay / "body_wave.png")
    _rgba(wave_image(), arm & ~head_zone, lay / "arm_wave.png", feather=0.7)
    eyes = _ellipses((1216, 832), [(x, y, 24, 18) for x, y in EYES]).astype(bool)
    _rgba(OUT / "gen" / "eyes" / "eyes_full.png", eyes, lay / "eyes_closed.png", feather=3)
    mouth_m = _ellipses((1216, 832), [(MOUTH[0], MOUTH[1] + 4, 31, 21)]).astype(bool)
    for name in ("A", "O", "smile"):
        _rgba(
            OUT / "gen" / f"mouth_{name}" / f"mouth_{name}_full.png",
            mouth_m,
            lay / f"mouth_{name}.png",
            3,
        )
    Image.open(next((OUT / "gen" / "plate").glob("*.png"))).convert("RGB").save(lay / "plate.png")
    print("layers:", sorted(p.name for p in lay.glob("*.png")))


def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["layers"]:
        layers()
        return
    if not args or args[0] != "gen":
        sys.exit(__doc__)
    comfy = Comfy()
    for job in args[1:] or [j for j in JOBS if j != "waveseg"] + ["waveseg"]:
        JOBS[job](comfy)
    comfy.free_memory()


if __name__ == "__main__":
    main()
