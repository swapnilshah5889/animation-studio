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
    image: str, mask: str, prompt: str, seeds: list[int], denoise: float, prefix: str, neg: str = ""
) -> dict:
    """Inpaint `mask` (white = repaint) and paste the result back onto the untouched image."""
    g = Graph()
    ck, lo = _model(g)
    pos = g.add("CLIPTextEncode", text=f"{STYLE}, {prompt}", clip=[lo, 1])
    neg = g.add("CLIPTextEncode", text=f"{NEG}, {neg}" if neg else NEG, clip=[lo, 1])
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
    comfy: Comfy,
    job: str,
    mask: np.ndarray,
    text: str,
    seed: int | list[int],
    denoise: float,
    box: tuple[int, int, int, int] = FACE_BOX,
    up: float = FACE_UP,
    neg: str = "",
) -> None:
    """Detailer-style inpaint: enlarge the crop so the model has room, repaint, shrink, paste.
    One seed saves <job>_full.png; several save <job>_<seed>_full.png."""
    seeds = seed if isinstance(seed, list) else [seed]
    x0, y0, x1, y1 = box
    w, h = round((x1 - x0) * up), round((y1 - y0) * up)
    crop = Image.open(CANON).convert("RGB").crop(box).resize((w, h), Image.LANCZOS)
    crop_path = OUT / f"{job}_crop.png"
    crop.save(crop_path)
    m = Image.fromarray((mask[y0:y1, x0:x1] > 0).astype(np.uint8) * 255).resize((w, h))
    mask_path = OUT / f"{job}_cropmask.png"
    m.filter(ImageFilter.GaussianBlur(8)).convert("RGB").save(mask_path)
    g = inpaint_graph(
        comfy.upload_image(crop_path), comfy.upload_image(mask_path), text, seeds, denoise, job, neg
    )
    alpha = Image.fromarray((mask[y0:y1, x0:x1] > 0).astype(np.uint8) * 255).filter(
        ImageFilter.GaussianBlur(2)
    )
    for s, big in zip(seeds, sorted(run(comfy, job, g)), strict=True):
        small = Image.open(big).convert("RGB").resize((x1 - x0, y1 - y0), Image.LANCZOS)
        full = Image.open(CANON).convert("RGB")
        full.paste(small, (x0, y0), alpha)
        name = f"{job}_full.png" if len(seeds) == 1 else f"{job}_{s}_full.png"
        full.save(big.with_name(name))
    crop_path.unlink()
    mask_path.unlink()


ARM_NEG = (
    "face, head, eyes, person, people, child, character, hat, cap, hair, shoulders, extra arm, feet, toes"
)
ARM_BOX = (424, 328, 680, 760)  # the far arm and the space beside it; 2.5x up is 640x1080


ARM_TOP, ARM_WRIST = (510, 392), (598, 690)  # the sleeve's centre line in the arm mask


def _arm_shape() -> np.ndarray:
    """Try 2 filled a wide mask with a wide sleeve: the mask is a slim sleeve (about the near sleeve's
    60 px) from the shoulder to the wrist, plus a hand-sized oval below it."""
    img = Image.new("L", (832, 1216), 0)
    d = ImageDraw.Draw(img)
    d.line([ARM_TOP, ARM_WRIST], fill=255, width=62)
    d.ellipse([(483, 368), (545, 420)], fill=255)  # rounded shoulder
    d.ellipse([(570, 680), (640, 768)], fill=255)  # hand
    return np.array(img)


def arm_neutral(comfy: Comfy) -> None:
    """The far arm redrawn rig-ready (repair brief T2): hanging relaxed a little away from the body,
    a slim sleeve like the near one, a cuff, and an open hand, so SAM can cut it whole."""
    # Try 2 filled a wide mask with a wide sleeve: the mask is now a slim sleeve (about the near sleeve's
    # 60 px) from the shoulder to the wrist, plus a hand-sized oval below it.
    # Try 1 described Rowan, and the model painted a whole small child in the mask: describe only the arm.
    text = (
        "close-up detail of one arm hanging straight down at the side, a slim pale teal shirt sleeve with soft "
        "folds, a buttoned cuff at the wrist, a small simple storybook child's hand below the cuff, four "
        "fingers together and a thumb, rounded mitten-like shape"
    )
    face_variant(comfy, "arm_neutral", _arm_shape(), text, [9105, 9106, 9107, 9108], 1.0, ARM_BOX, 2.5, ARM_NEG)


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



SLEEVE_PICK, HAND_PICK = 9107, 9105  # by eye: 9107 has a slim on-model sleeve with a cuff, 9105 a good hand


def _arm_image(seed: int) -> Path:
    return OUT / "gen" / "arm_neutral" / f"arm_neutral_{seed}_full.png"


def armseg(comfy: Comfy) -> None:
    """SAM masks for the sleeve (from one candidate) and the hand (from another)."""
    pts = [(505, 400), (528, 494), (560, 580), (585, 645)]
    up = comfy.upload_image(_arm_image(SLEEVE_PICK))
    run(comfy, "arm_sleeve", sam_graph(up, [470, 355, 630, 672], pts, "arm_sleeve"))
    up = comfy.upload_image(_arm_image(HAND_PICK))
    run(comfy, "arm_hand", sam_graph(up, [545, 600, 625, 705], [(578, 634), (592, 665)], "arm_hand"))

JOBS = {
    "figure": figure,
    "arm_neutral": arm_neutral,
    "armseg": armseg,
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
    arm_pieces(lay)
    print("layers:", sorted(p.name for p in lay.glob("*.png")))


def arm_pieces(lay: Path) -> None:
    """Repair brief T3: the sleeve split at the elbow into upper arm and forearm (overlapping, with a
    round elbow cap in the sleeve's own colour), and the hand moved under the cuff. Pivots go to
    arm_pivots.json in canonical pixels."""
    # The model painted the sleeve hugging the body, not along the mask's line, so the SAM sleeve is used
    # whole and the arm's axis comes from it; the hand keeps only skin colours (SAM also took a leaf).
    sleeve = _mask("arm_sleeve")
    hrgb = np.array(Image.open(_arm_image(HAND_PICK)).convert("RGB")).astype(int)
    r, g, b = hrgb[..., 0], hrgb[..., 1], hrgb[..., 2]
    skin = (r > 150) & (r > g + 10) & (g > b) & (r - b < 120)
    hand = clean(_mask("arm_hand") & skin)
    sy, sx = np.nonzero(sleeve)
    ax, ay = sx[sy <= sy.min() + 10].mean(), float(sy.min())
    bx, by = sx[sy >= sy.max() - 6].mean(), float(sy.max())
    ys, xs = np.mgrid[0:1216, 0:832]
    t = ((xs - ax) * (bx - ax) + (ys - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)
    elbow = (round(ax + 0.5 * (bx - ax)), round(ay + 0.5 * (by - ay)))
    rgb = np.array(Image.open(_arm_image(SLEEVE_PICK)).convert("RGB"))
    band = sleeve & (abs(t - 0.5) < 0.06)
    colour = tuple(int(c) for c in np.median(rgb[band], axis=0))
    cap = _ellipses((1216, 832), [(elbow[0], elbow[1], 26, 26)]).astype(bool) & ~sleeve
    upper_rgb = rgb.copy()
    upper_rgb[cap] = colour
    Image.fromarray(upper_rgb).save(lay / "_upper_src.png")
    _rgba(lay / "_upper_src.png", (sleeve & (t <= 0.56)) | cap, lay / "arm_upper.png")
    _rgba(_arm_image(SLEEVE_PICK), sleeve & (t >= 0.44), lay / "arm_fore.png")
    (lay / "_upper_src.png").unlink()
    # The cuff's bottom centre (wrist) on the sleeve, and the hand's top centre: line them up, 8 px overlap.
    wrist = (round(bx), round(by))
    hy, hx = np.nonzero(hand)
    top = (int(hx[hy <= hy.min() + 6].mean()), int(hy.min()))
    dx, dy = wrist[0] - top[0], wrist[1] - 8 - top[1]
    src = Image.open(_arm_image(HAND_PICK)).convert("RGB")
    moved = Image.new("RGB", src.size)
    moved.paste(src, (dx, dy))
    hand_moved = np.zeros_like(hand)
    hand_moved[max(dy, 0) :, max(dx, 0) :] = hand[: 1216 - max(dy, 0), : 832 - max(dx, 0)]
    moved.save(lay / "_hand_src.png")
    _rgba(lay / "_hand_src.png", hand_moved, lay / "arm_hand.png", feather=0.7)
    (lay / "_hand_src.png").unlink()
    pivots = {"shoulder": [round(ax), round(ay) + 18], "elbow": list(elbow), "wrist": list(wrist)}
    (lay / "arm_pivots.json").write_text(json.dumps(pivots))
    print("arm pivots", pivots, "elbow cap colour", colour, "hand moved by", (dx, dy))


def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["layers"]:
        layers()
        return
    if not args or args[0] != "gen":
        sys.exit(__doc__)
    comfy = Comfy()
    for job in args[1:] or [j for j in JOBS if j not in ("waveseg", "arm_neutral", "armseg")] + ["waveseg"]:
        JOBS[job](comfy)
    comfy.free_memory()


if __name__ == "__main__":
    main()
