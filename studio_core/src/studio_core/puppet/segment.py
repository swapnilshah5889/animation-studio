"""Character silhouettes with SAM 2.1, prompted by the known skeleton (task 4.4, D-047).

    masks = segment_sheet(film_root, sheet_png, [front, three_quarter], out_dir)
    # out_dir/mask_front.png, out_dir/mask_three_quarter.png  (mode "L", 255 = figure)
    # out_dir/run.json                                         (the graph, prompts, timings)

The colour key in puppet/checks.py cuts a figure off a plain background by colour alone, so a
cream shirt or a white muzzle on a cream background reads as background. SAM 2.1 (Segment
Anything, base+) segments by *shape*: given a box around an object and a few points on it,
it returns the object's mask whatever its colours.

**The prompts are computed, not guessed by a model.** Each view gets:

- its **column** of the sheet (front = left half, three-quarter = right half). SAM only sees
  that crop, so the other view can't leak in, and the figure is larger in SAM's 1024 px input.
- **positive points** on the skeleton's centre line, where a cartoon body is always solid: the
  head's middle, the chest and the belly. Limb joints are left out: a generated arm can drift
  off its skeleton, and a positive point on background makes SAM add the background.
- a **box** around the figure: the skeleton's joints plus the colour key's pixels near them
  (tails and ears reach well past the skeleton), with a small margin, inside the column.
  The box must be *tight*: a box covering most of the crop reads to SAM as "the whole
  picture", and it returns the background too (the c3 front view with a skeleton box padded
  by 20% of the height). The colour key is good at *where* the figure ends even where it is
  bad at *which* pixels inside are figure, so it sizes the box and SAM does the rest.

ComfyUI runs SAM (kijai's ComfyUI-segment-anything-2 pack) through comfy_runs.run_graph, so
the run is recorded in run.json and ComfyUI's copies are cleaned up. Afterwards, in code, each
mask's enclosed holes are filled (a pale shirt inside the outline stays figure), specks
apart from the body are dropped, and the mask is pasted back into the sheet's frame.

Gotchas (see docs/learning/segmentation-sam2.md):

- `precision` must be **fp32**: for any other precision the loader renames the file to
  `*-fp16.safetensors` and downloads it. fp32 also avoids the fp16 MPS bug (D-017).
- `bboxes` is a custom type with no widget; a constant list in API format would be read as a
  link, so it is sent wrapped as `{"__value__": [...]}`, which ComfyUI unwraps.
- ComfyUI caches results: the same graph queued twice is not run again, and the second answer
  names output files run_graph has already deleted. Each run's save prefix is unique.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from studio_core.comfy_graphs import Graph
from studio_core.comfy_runs import run_graph
from studio_core.config import StudioConfig
from studio_core.models import Manifest, load_manifest
from studio_core.puppet.checks import background, components, fill_holes, silhouette
from studio_core.puppet.skeleton import Skeleton

MODEL = "sam2.1-hiera-base-plus"  # file id in config/models.toml
REACH = 0.25  # colour-key pixels this far past the joints (share of the figure's height) count
MARGIN = 0.03  # box margin around the figure, share of the figure's height (about 20 px)
EDGE = 4  # px: the box stays this far inside the view's column
SPECK = 0.001  # islands smaller than this share of the column are dropped (about 23x23 px)

Point = tuple[int, int]


@dataclass(frozen=True)
class ViewPrompt:
    """What SAM is told about one view. Coordinates are sheet pixels (y down)."""

    view: str
    column: tuple[int, int]  # x range [start, end) of the sheet this view owns
    box: tuple[int, int, int, int]  # x0, y0, x1, y1
    positive: tuple[Point, ...]


def colour_key(image: Image.Image) -> np.ndarray:
    """The colour-key silhouette of a sheet (puppet/checks.py): True = far from the
    background colour. Holes are not filled; only its extent is used here."""
    img = np.asarray(image.convert("RGB")).astype("float32")
    bg, _ = background(img)
    return silhouette(img, bg)


def view_prompts(skeletons: list[Skeleton], key: np.ndarray) -> list[ViewPrompt]:
    """One prompt per skeleton. The sheet (`key` is its colour-key mask, height x width) is
    split into equal columns, one per view; each view owns the column its pelvis stands in."""
    height, width = key.shape
    step = width / len(skeletons)
    prompts = []
    for sk in skeletons:
        j = sk.joints
        i = min(int(j["pelvis"][0] // step), len(skeletons) - 1)
        left, right = round(i * step), round((i + 1) * step)
        xs = [x for x, _ in j.values()]
        ys = [y for _, y in j.values()]
        reach, margin = sk.height_px * REACH, sk.height_px * MARGIN
        # The colour key near this skeleton (and in its column) widens the joints' extent.
        x0, x1 = max(left, round(min(xs) - reach)), min(right, round(max(xs) + reach))
        y0, y1 = max(0, round(min(ys) - reach)), min(height, round(max(ys) + reach))
        key_ys, key_xs = np.nonzero(key[y0:y1, x0:x1])
        if key_xs.size:
            xs += [x0 + int(key_xs.min()), x0 + int(key_xs.max())]
            ys += [y0 + int(key_ys.min()), y0 + int(key_ys.max())]
        box = (
            round(max(left + EDGE, min(xs) - margin)),
            round(max(EDGE, min(ys) - margin)),
            round(min(right - 1 - EDGE, max(xs) + margin)),
            round(min(height - 1 - EDGE, max(ys) + margin)),
        )
        (nx, ny), (tx, ty), (px, py) = j["neck"], j["head_top"], j["pelvis"]
        head = ((tx + nx + j["nose"][0]) / 3, (ty + ny) / 2)  # leans toward the nose in 3/4
        chest = (nx + 0.35 * (px - nx), ny + 0.35 * (py - ny))
        belly = (nx + 0.75 * (px - nx), ny + 0.75 * (py - ny))
        points = tuple((round(x), round(y)) for x, y in (head, chest, belly))
        prompts.append(ViewPrompt(sk.view, (left, right), box, points))
    return prompts


def segment_graph(
    manifest: Manifest,
    image: str,
    prompts: list[ViewPrompt],
    *,
    height: int,
    prefix: str = "mask",
    device: str = "mps",
) -> dict[str, dict[str, Any]]:
    """The ComfyUI graph (API format): load the sheet once, then per view crop its column,
    run SAM with the box and points (in crop coordinates) and save the mask as an image.
    `image` is a LoadImage input (an uploaded name, or a placeholder run_graph substitutes).
    Outputs are saved as `<prefix>_<i>_<view>`, so they sort in view order."""
    g = Graph()
    sam = g.add(
        "DownloadAndLoadSAM2Model",
        "SAM 2.1",
        model=manifest.files[MODEL].comfy_name,
        segmentor="single_image",
        device=device,
        precision="fp32",  # anything else makes the node download an fp16 file
    )
    sheet = g.add("LoadImage", "sheet", image=image)
    for i, p in enumerate(prompts):
        left, right = p.column
        crop = g.add(
            "ImageCrop",
            f"{p.view} column",
            image=[sheet, 0],
            width=right - left,
            height=height,
            x=left,
            y=0,
        )
        x0, y0, x1, y1 = p.box
        mask = g.add(
            "Sam2Segmentation",
            f"segment {p.view}",
            sam2_model=[sam, 0],
            image=[crop, 0],
            keep_model_loaded=i < len(prompts) - 1,  # unload after the last view
            coordinates_positive=json.dumps([{"x": x - left, "y": y} for x, y in p.positive]),
            bboxes={"__value__": [[x0 - left, y0, x1 - left, y1]]},  # a list would be a link
            individual_objects=False,
        )
        as_image = g.add("MaskToImage", mask=[mask, 0])
        g.add("SaveImage", images=[as_image, 0], filename_prefix=f"{prefix}_{i}_{p.view}")
    return g.nodes


def clean(mask: np.ndarray) -> np.ndarray:
    """Holes filled, then only the largest piece and pieces bigger than a speck kept."""
    pieces = components(fill_holes(mask))
    kept = [p for i, p in enumerate(pieces) if i == 0 or p.sum() >= SPECK * mask.size]
    return np.any(kept, axis=0) if kept else np.zeros_like(mask)


def to_sheet_mask(
    column_mask: Image.Image, column: tuple[int, int], size: tuple[int, int]
) -> Image.Image:
    """A cleaned mask of one column pasted into the sheet's frame (`size` = width, height), as
    a mode "L" image (255 = figure)."""
    left, right = column
    full = np.zeros((size[1], size[0]), dtype=bool)
    full[:, left:right] = clean(np.asarray(column_mask.convert("L")) > 127)
    return Image.fromarray((full * 255).astype("uint8"))  # 2-D uint8: mode "L"


def segment_sheet(
    film_root: Path,
    sheet: Path,
    skeletons: list[Skeleton],
    out_dir: Path,
    cfg: StudioConfig | None = None,
) -> list[Path]:
    """Figure masks for a design sheet, one per skeleton, in `out_dir` (made fresh) as
    `mask_<view>.png`: mode "L", 255 = figure, the sheet's size. A run.json records the graph
    and the prompts. Starts ComfyUI if needed (Ollama's models are unloaded first)."""
    image = Image.open(sheet)
    prompts = view_prompts(skeletons, colour_key(image))
    prefix = f"segment_{uuid.uuid4().hex[:8]}"  # never a cached result (see the module notes)
    graph = segment_graph(load_manifest(), "@sheet", prompts, height=image.height, prefix=prefix)
    names = [f"mask_{p.view}.png" for p in prompts]
    run_graph(
        film_root,
        "segment",
        graph,
        out_dir=out_dir,
        params={
            "model": MODEL,
            "prompts": [asdict(p) for p in prompts],
            "post": "holes filled, specks dropped",
        },
        names=names,
        uploads={"@sheet": sheet},
        cfg=cfg,
    )
    paths = []
    for name, p in zip(names, prompts, strict=True):
        path = out_dir / name
        to_sheet_mask(Image.open(path), p.column, image.size).save(path)
        paths.append(path)
    return paths
