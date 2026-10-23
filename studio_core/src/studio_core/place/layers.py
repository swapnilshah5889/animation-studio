"""Split a background plate into parallax layers (task 4.7, D-055).

    path = split_depth_layers(film_root, "meadow")   # backgrounds/meadow/layers.json + layers/

A plate is one flat picture; a pan feels deep only if far things move slower than near ones.
So the plate is cut by distance into a few layers (schemas/background.schema.json), each with
its own parallax factor, and each farther layer is painted *behind* the nearer ones, so that
when a nearer layer slides away during a pan there is something to see.

1. **Nearness** (0 far .. 1 near) from a depth model (comfy_graphs.depth_map).
2. **Sky:** the farthest region connected to the top edge.
3. **Bands:** the rest is cut at depth quantiles into far / middle / ground, each cut moved to
   the nearest valley of the depth histogram so it doesn't run through one object. Tiny bands
   merge into a neighbour; islands of one band inside another join the one around them.
   A **foreground** band is added only when something stands up out of the ground near the
   bottom (clearly nearer than the ground at its own row: grass tufts, a fence post).
4. **Parallax:** each band's median nearness against the ground where characters' feet are
   (row ≈ 0.92 of the height): the ground layer is 1.0 (it moves with the characters), farther
   ones less, the foreground more, but never so much that its edge enters the frame during a
   pan (parallax ≤ 0.9 (width/2 - 960) / PAN_PX: 1.8 on a 2880-wide plate). The sky gets a
   fixed hint of motion.
5. **Fill behind:** a pan shifts a nearer layer against a farther one by at most PAN_PX times
   their difference in parallax (so at most PAN_PX), so each farther layer is repainted (in
   the film's style, comfy_graphs.repaint_fill) wherever nearer layers cover it within that
   reach of its own pixels. The sky is filled everywhere: the frame never shows the backdrop.
6. **Write** layers/<name>.png (RGBA, the plate's size) and layers.json, validated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

from studio_core.comfy_graphs import depth_map, repaint_fill
from studio_core.comfy_runs import film_style, run_graph
from studio_core.config import StudioConfig
from studio_core.models import load_manifest
from studio_core.place.design import NEGATIVE, PlaceError, background_dir, load_plates
from studio_core.puppet.checks import components
from studio_core.scene import PAN_PX
from studio_core.schema import validate

# The depth model and how its picture reads (the one-time comparison, task 4.7, D-055): DA3
# MONO-LARGE at 1512 px (DAv2-Small put the distant tree line as far as the sky). Its map is
# bright = near, the sky exactly 0, linear in depth between percentiles: not disparity, so
# band ratios give a perceptual multiplane spread, not physical parallax.
DEPTH: dict[str, Any] = {"model": "da3", "resolution": 1512}
NEAR_IS_BRIGHT = True
MIN_DEPTH_SPREAD = 0.02  # a flatter map means the depth model failed (out of memory: all black)

FEET_ROW = 0.92  # where characters' feet are, as a share of the height (shot positions)
SKY_PARALLAX = 0.05
SKY_NEARNESS = 0.12  # the sky is nearer than this (0 = the farthest thing in the picture)
QUANTILES = (0.35, 0.7)  # cuts between far / middle / ground, over the non-sky pixels
VALLEY_WINDOW = 0.08  # how far (in nearness) a cut may move to sit in a histogram valley
MIN_BAND = 0.03  # a band smaller than this share of the picture merges into a neighbour
MIN_ISLAND = 0.002  # islands smaller than this share join the band around them
FOREGROUND_STEP = 0.15  # nearer than the ground at its own row by this much = foreground
REACH = PAN_PX + 32  # px a pan can reveal behind a nearer layer, plus a margin
FEATHER = 12  # px over which a fill blends into the plate's own pixels


@dataclass
class Band:
    name: str  # sky, far, middle, ground, foreground
    mask: np.ndarray
    parallax: float = 1.0
    in_front: bool = False
    nearness: float = 0.0  # median


@dataclass
class Split:
    bands: list[Band]  # far to near
    notes: dict[str, Any] = field(default_factory=dict)


def _dilate(mask: np.ndarray, px: int) -> np.ndarray:
    """Grow a mask by `px` (a square), on a 1/4-scale copy for speed at plate sizes."""
    small = Image.fromarray((mask[::4, ::4] * 255).astype("uint8"))
    k = max(1, px // 4)
    grown = np.asarray(small.filter(ImageFilter.MaxFilter(2 * k + 1))) > 127
    big = np.repeat(np.repeat(grown, 4, axis=0), 4, axis=1)[: mask.shape[0], : mask.shape[1]]
    out = np.zeros_like(mask)
    out[: big.shape[0], : big.shape[1]] = big
    return out | mask


def sky_mask(nearness: np.ndarray) -> np.ndarray:
    """The far region connected to the top edge (computed at 1/4 scale, then refined)."""
    far = nearness < SKY_NEARNESS
    small = far[::4, ::4]
    sky = np.zeros_like(small)
    for blob in components(small):
        if blob[0].any():
            sky |= blob
    big = np.repeat(np.repeat(sky, 4, axis=0), 4, axis=1)[: far.shape[0], : far.shape[1]]
    out = np.zeros_like(far)
    out[: big.shape[0], : big.shape[1]] = big
    return out & _dilate(far, 4)


def _valley(values: np.ndarray, cut: float) -> float:
    """Move a cut to the emptiest nearness level within VALLEY_WINDOW of it."""
    hist, edges = np.histogram(values, bins=100, range=(0.0, 1.0))
    lo, hi = max(0, int((cut - VALLEY_WINDOW) * 100)), min(99, int((cut + VALLEY_WINDOW) * 100))
    smooth = np.convolve(hist, np.ones(5) / 5, mode="same")
    best = lo + int(np.argmin(smooth[lo : hi + 1]))
    return float((edges[best] + edges[best + 1]) / 2)


def _join_islands(labels: np.ndarray, n: int) -> np.ndarray:
    """Small islands of one band inside another take the label around them."""
    limit = MIN_ISLAND * labels.size
    small = labels[::2, ::2].copy()
    for value in range(n):
        for blob in components(small == value):
            if blob.sum() * 4 < limit:
                ring = _dilate(blob, 2) & ~blob
                around = small[ring]
                if around.size:
                    small[blob] = np.bincount(around, minlength=n).argmax()
    big = np.repeat(np.repeat(small, 2, axis=0), 2, axis=1)[: labels.shape[0], : labels.shape[1]]
    out = labels.copy()
    out[: big.shape[0], : big.shape[1]] = big
    return out


def _ground_from_the_bottom(labels: np.ndarray, ground: int = 2) -> np.ndarray:
    """The ground layer is what the characters stand on, so it reaches the bottom of the
    picture. Ground-labelled pieces that don't (the top of a near tree's canopy, as bright in
    depth as the lawn) join the band they touch most: otherwise a pan would tear the tree."""
    small = labels[::2, ::2].copy()
    for blob in components(small == ground):
        if blob[-1].any():
            continue
        ring = _dilate(blob, 2) & ~blob
        around = small[ring]
        around = around[around != ground]
        if around.size:
            small[blob] = np.bincount(around, minlength=4).argmax()
    big = np.repeat(np.repeat(small, 2, axis=0), 2, axis=1)[: labels.shape[0], : labels.shape[1]]
    out = labels.copy()
    out[: big.shape[0], : big.shape[1]] = big
    return out


def split_bands(nearness: np.ndarray) -> Split:
    """The plate's bands far to near (sky first), with parallax factors."""
    h, w = nearness.shape
    sky = sky_mask(nearness)
    rest = nearness[~sky]
    cuts = [_valley(rest, float(np.quantile(rest, q))) for q in QUANTILES]
    labels = np.digitize(nearness, cuts)  # 0 far, 1 middle, 2 ground
    labels[sky] = 3  # temporarily: sky
    labels = _join_islands(labels, 4)
    labels = _ground_from_the_bottom(labels)
    names = ["far", "middle", "ground"]
    bands = [Band(n, labels == i) for i, n in enumerate(names)]
    # Merge bands too small to be worth a layer into their nearer neighbour.
    for i in range(len(bands) - 2, -1, -1):
        if bands[i].mask.mean() < MIN_BAND:
            bands[i + 1].mask |= bands[i].mask
            del bands[i]
    feet = nearness[int(FEET_ROW * h), w // 4 : 3 * w // 4]
    ground_at_feet = float(np.median(feet))
    # Foreground: clearly nearer than the ground at the same row, low in the picture.
    rows = np.median(np.where(~sky, nearness, np.nan), axis=1, keepdims=True)
    standing = (nearness > np.nan_to_num(rows) + FOREGROUND_STEP) & ~sky
    standing[: int(0.75 * h)] = False
    if standing.mean() > MIN_ISLAND:
        for b in bands:
            b.mask &= ~standing
        bands.append(Band("foreground", standing, in_front=True))
    # A layer moves PAN_PX x parallax during a pan; past (width/2 - 960) its edge enters the
    # 1920-wide frame. Keep a 10% margin.
    most = round(0.9 * (w / 2 - 960) / PAN_PX, 2)
    for b in bands:
        b.nearness = float(np.median(nearness[b.mask])) if b.mask.any() else 0.0
        b.parallax = round(float(np.clip(b.nearness / max(ground_at_feet, 1e-3), 0.1, most)), 2)
    ground = next(b for b in bands if b.name == "ground")
    ground.parallax = 1.0  # it carries the characters
    for b in bands:
        if not b.in_front and b is not ground:
            b.parallax = min(b.parallax, 0.95)
    sky_band = Band("sky", sky, parallax=SKY_PARALLAX, nearness=0.0)
    notes = {
        "cuts": [round(c, 3) for c in cuts],
        "ground_nearness_at_feet": round(ground_at_feet, 3),
        "shares": {b.name: round(float(b.mask.mean()), 3) for b in [sky_band, *bands]},
    }
    return Split([sky_band, *bands], notes)


def fill_regions(bands: list[Band]) -> list[np.ndarray]:
    """Per band, where it must be painted behind nearer layers: the sky everywhere it isn't,
    others within REACH of their own pixels (what a pan can reveal)."""
    regions = []
    for i, band in enumerate(bands):
        nearer = np.any([b.mask for b in bands[i + 1 :]], axis=0) if i + 1 < len(bands) else None
        if nearer is None:
            regions.append(np.zeros_like(band.mask))
        elif i == 0:
            regions.append(~band.mask)
        else:
            regions.append(nearer & _dilate(band.mask, REACH))
    return regions


def compose_layers(
    plate: np.ndarray,
    bands: list[Band],
    fills: list[np.ndarray | None],
    regions: list[np.ndarray],
) -> list[np.ndarray]:
    """RGBA layer images: the plate's own pixels for each band, the fill (if any) over its
    region, soft 1-px edges where a layer ends against a farther one."""
    layers = []
    for band, fill, region in zip(bands, fills, regions, strict=True):
        rgb = plate.copy()
        if fill is not None:
            # Blend the fill in over a soft edge just past its region: a hard paste shows a
            # line wherever the fill's tones differ slightly from the plate's.
            soft = Image.fromarray((_dilate(region, FEATHER) * 255).astype("uint8"))
            w = np.asarray(soft.filter(ImageFilter.GaussianBlur(FEATHER)), "float32")[..., None]
            w = np.maximum(w / 255.0, region[..., None])
            rgb = w * fill + (1 - w) * plate
        cover = band.mask | region
        alpha = Image.fromarray((cover * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(0.7))
        a = np.asarray(alpha, dtype="float32")
        a[band.mask & ~_dilate(~cover, 1)] = 255  # solid inside
        layers.append(np.dstack([rgb, a]).round().clip(0, 255).astype("uint8"))
    return layers


def write_layers(
    folder: Path,
    background_id: str,
    name: str,
    bands: list[Band],
    layers: list[np.ndarray],
    backdrop: str,
) -> Path:
    """layers/<band>.png and layers.json (validated by the background schema)."""
    out = folder / "layers"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    entries = []
    for band, rgba in zip(bands, layers, strict=True):
        Image.fromarray(rgba, "RGBA").save(out / f"{band.name}.png")
        entry: dict[str, Any] = {
            "name": band.name,
            "file": f"layers/{band.name}.png",
            "parallax": band.parallax,
        }
        if band.in_front:
            entry["in_front"] = True
        entries.append(entry)
    h, w = layers[0].shape[:2]
    data = {
        "schema_version": 1,
        "id": background_id,
        "name": name,
        "size_px": [w, h],
        "backdrop": backdrop,
        "layers": entries,
    }
    issues = validate("background", data)
    if issues:
        raise ValueError("invalid layers.json: " + "; ".join(map(str, issues)))
    path = folder / "layers.json"
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


FILL_SIZE = (1536, 576)  # fills are painted at the draft size (SDXL at ~3 MP is too slow)
# What each layer's fill should show. Not the place's description: its near things (a stream,
# a path) would be drawn again behind the trees. ProMax's repaint mode takes the content from
# the surroundings; the prompt only says how far away it is.
LAYER_PROMPTS = {
    "sky": "a clear sky with a few soft clouds, nothing else",
    "far": "the far distance of the same scene: only far-away scenery, nothing near",
    "middle": "the middle distance of the same scene: open ground and plants, nothing near",
    "ground": "the same open ground, plain and empty",
}
TINTS = {
    "sky": (120, 180, 250), "far": (160, 120, 220), "middle": (250, 170, 60),
    "ground": (90, 200, 90), "foreground": (240, 80, 80),
}  # fmt: skip


def nearness_from_depth(depth: Image.Image, near_is_bright: bool) -> np.ndarray:
    """A depth model's picture (grey, 0-255) as nearness 0 (far) .. 1 (near), plate-sized."""
    grey = np.asarray(depth.convert("L"), dtype="float32") / 255.0
    return grey if near_is_bright else 1.0 - grey


def _fill_with_comfy(
    film_root: Path,
    folder: Path,
    plate: np.ndarray,
    band: Band,
    region: np.ndarray,
    *,
    style: str,
    seed: int,
    cfg: StudioConfig | None,
) -> np.ndarray:
    """The plate repainted over `region` (in the film's style, ProMax repaint), at the draft
    size and scaled back; only the region is used by compose_layers."""
    work = folder / "build" / "fill" / band.name
    work.mkdir(parents=True, exist_ok=True)
    h, w = region.shape
    Image.fromarray(plate.astype("uint8")).resize(FILL_SIZE, Image.Resampling.LANCZOS).save(
        work / "image.png"
    )
    if band.name == "sky":  # beyond a pan's reach the sky's fill is never seen
        region = region & _dilate(band.mask, REACH)
    mask = Image.fromarray((_dilate(region, 8) * 255).astype("uint8")).resize(FILL_SIZE)
    mask.save(work / "mask.png")
    prompt = LAYER_PROMPTS.get(band.name, LAYER_PROMPTS["middle"])
    graph = repaint_fill(
        load_manifest(),
        style,
        prompt,
        image="@image",
        mask="@mask",
        seed=seed,
        width=FILL_SIZE[0],
        height=FILL_SIZE[1],
        negative=NEGATIVE,
        filename_prefix=f"fill_{band.name}",
    )
    run_graph(
        film_root,
        "fill",
        graph,
        out_dir=work / "out",
        params={"layer": band.name, "prompt": prompt},
        seed=seed,
        style=style,
        names=["fill.png"],
        uploads={"@image": work / "image.png", "@mask": work / "mask.png"},
        cfg=cfg,
    )
    filled = (
        Image.open(work / "out" / "fill.png")
        .convert("RGB")
        .resize((w, h), Image.Resampling.LANCZOS)
    )
    out = np.asarray(filled, dtype="float32").copy()
    if band.name == "sky":
        # Asked to paint sky over most of the picture, SDXL invents odd shapes; past the reach
        # a flat colour from the sky's lowest rows does (it stays behind nearer layers).
        ys = np.nonzero(band.mask.any(axis=1))[0]
        low = band.mask.copy()
        low[: max(0, int(ys.max()) - h // 20)] = False
        out[~_dilate(band.mask, REACH)] = np.median(plate[low], axis=0)
    return out


def split_depth_layers(
    film_root: Path,
    background_id: str,
    *,
    fill: bool = True,
    seed: int = 1,
    cfg: StudioConfig | None = None,
) -> Path:
    """Cut backgrounds/<id>/plate.png into parallax layers, fill behind the nearer ones, and
    write layers/ and layers.json (plus build/depth.png, build/bands.png and the report)."""
    folder = background_dir(film_root, background_id)
    plate_path = folder / "plate.png"
    if not plate_path.is_file():
        raise PlaceError(f"{background_id!r} has no plate; choose a draft first")
    data = load_plates(film_root, background_id) or {}
    style = data.get("style") or film_style(film_root, cfg)
    plate = np.asarray(Image.open(plate_path).convert("RGB"), dtype="float32")
    build = folder / "build"
    build.mkdir(exist_ok=True)
    graph = depth_map(load_manifest(), image="@plate", **DEPTH)
    run_graph(
        film_root, "depth", graph, out_dir=build / "depth", params=DEPTH, names=["depth.png"],
        uploads={"@plate": plate_path}, cfg=cfg,
    )  # fmt: skip
    depth = Image.open(build / "depth" / "depth.png").resize(
        (plate.shape[1], plate.shape[0]), Image.Resampling.BILINEAR
    )
    near = nearness_from_depth(depth, NEAR_IS_BRIGHT)
    if float(near.std()) < MIN_DEPTH_SPREAD:
        raise PlaceError("the depth map came back flat (the depth model failed); try again")
    split = split_bands(near)
    regions = fill_regions(split.bands)
    fills: list[np.ndarray | None] = []
    for band, region in zip(split.bands, regions, strict=True):
        if fill and region.any():
            fills.append(
                _fill_with_comfy(
                    film_root, folder, plate, band, region,
                    style=style, seed=seed, cfg=cfg,
                )
            )  # fmt: skip
        else:
            fills.append(None)
    layers = compose_layers(plate, split.bands, fills, regions)
    top = plate[: plate.shape[0] // 8].reshape(-1, 3).mean(axis=0)
    backdrop = "#{:02x}{:02x}{:02x}".format(*(int(v) for v in top))
    name = background_id.replace("_", " ").title()
    path = write_layers(folder, background_id, name, split.bands, layers, backdrop)
    tinted = plate.copy()
    for band in split.bands:
        tinted[band.mask] = 0.5 * plate[band.mask] + 0.5 * np.array(TINTS[band.name])
    Image.fromarray(tinted.astype("uint8")).save(build / "bands.png")
    report = {
        **split.notes,
        "parallax": {b.name: b.parallax for b in split.bands},
        "filled": [b.name for b, f in zip(split.bands, fills, strict=True) if f is not None],
        "depth": DEPTH,
    }
    (build / "layers_report.json").write_text(json.dumps(report, indent=1) + "\n")
    return path
