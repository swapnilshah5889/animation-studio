"""A true three-quarter view drawn from the front one, with FLUX.2 klein (task 4.5, D-052, D-053).

    turned = turn_design(film_root, "kit")   # the chosen candidate's front, redrawn turned
    turned.sheet                              # design/<cand>/three_quarter/sheet.png
    turned.choice["chosen_seed"], turned.choice["seeds"]

SDXL's turnaround draws both views in one image, but its three-quarter figure is often barely
turned and adds things the front lacks (Kit's c3: 6% of the turn asked, and a hat). FLUX.2
klein redraws the front figure turned, keeping the costume (56-102% of the turn in the trial,
D-052). For each seed:

1. **Edit:** the front figure (the sheet's left half) is the reference; the prompt asks for a
   three-quarter view facing right, arms held out from the body, no ground shadow (the trial's
   round-2 prompt).
2. **Drop the ground shadow:** klein still draws one about half the time. Shadow pixels are
   pale and colourless, in the bottom strip of the figure; they become background.
3. **Place** the redrawn figure where the sheet's three-quarter figure goes: as tall as the
   front figure, soles on the skeleton's sole, legs centred on its pelvis. Its edges are
   unmixed from klein's background and laid on the sheet's, so no fringe is left.
4. **Score** the resulting sheet with the checks the cut itself uses: the turn and the paint
   only one view has (puppet/consistency.py), the head size, and how much of the three-quarter
   skeleton lands on the figure once its limbs are fitted to the drawing (puppet/fit.py).

The best seed's sheet is saved as design/<candidate>/three_quarter/sheet.png, with every seed's
edit, run.json and scores (choice.json). It is made once: build_puppet reuses it unless asked
to regenerate.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from studio_core.comfy_graphs import flux2_edit
from studio_core.comfy_runs import run_graph
from studio_core.config import StudioConfig
from studio_core.models import load_manifest
from studio_core.puppet import build
from studio_core.puppet.checks import (
    background,
    check_sheet,
    components,
    fill_holes,
    silhouette,
)
from studio_core.puppet.consistency import ViewCut, compare_views
from studio_core.puppet.design import CANVAS, design_dir, load_candidates
from studio_core.puppet.fit import fit_limbs
from studio_core.puppet.skeleton import Skeleton, turnaround

SEEDS = (1, 2, 3)
EXTRA_SEEDS = (4, 5, 6)  # tried one by one when no seed turned the figure enough (Mia, Bolt)
MIN_TURN = 0.5  # the three-quarter figure must turn at least this much of what was asked
SIZE = (896, 1024)  # the front half's aspect (672x768) at ~0.9 MP, multiples of 16
# The character's own description goes in, so the edit keeps what it wears and adds nothing.
# (The first version named a scarf, Kit's, and gave Bo, a bear cub, a scarf too.)
PROMPT = (
    "Turn this cartoon character, {description}, to a clear three-quarter view facing to the "
    "right: the whole body, the hips and the feet are turned about 45 degrees, so the far "
    "shoulder and the far leg sit partly behind the near ones, and the face is seen in "
    "three-quarter profile, with the far cheek and the far eye smaller than the near ones. "
    "The same character with the same face, ears, clothes, colours and flat storybook art "
    "style, wearing only what it wears in the picture. Full body, standing upright with the "
    "legs slightly apart and both arms held out from the body at about 25 degrees, the hands "
    "well away from the hips, so there "
    "is a gap of background between each arm and the body. Plain light background, no "
    "shadow on the ground, nothing else in the picture."
)
SHADOW_STRIP = 0.12  # share of the figure's height, at its feet, where shadows are looked for
SHADOW_CHROMA = 22  # max(R,G,B) - min(R,G,B) below this is colourless (grey)


@dataclass
class Turned:
    sheet: Path  # the composite: the SDXL front + the chosen klein three-quarter
    choice: dict[str, Any]


def turn_dir(film_root: Path, character_id: str, candidate: str) -> Path:
    return design_dir(film_root, character_id) / candidate / "three_quarter"


def figure_mask(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The largest figure on a plain background, with its enclosed holes filled, and that
    background's colour. The holes matter: a cream face on a cream background reads as
    background, and without it the eyes and mouth inside it would be loose islands."""
    bg, _ = background(img)
    mask = silhouette(img, bg)
    blobs = components(fill_holes(mask[::4, ::4], img[::4, ::4], bg))
    if not blobs:
        raise build.BuildError("the redrawn picture has no figure on its background")
    keep = np.repeat(np.repeat(blobs[0], 4, axis=0), 4, axis=1)[: mask.shape[0], : mask.shape[1]]
    full = np.zeros_like(mask)
    full[: keep.shape[0], : keep.shape[1]] = keep
    # The figure's own pixels near the blob, plus the blob's interior (its filled holes, at
    # 1/4 scale, shrunk back so the outline stays the colour key's).
    return (mask & build._grow(full, 2)) | build._shrink(full, 3), bg


def drop_shadow(img: np.ndarray, mask: np.ndarray, bg: np.ndarray) -> np.ndarray:
    """The figure mask without a ground shadow: colourless pixels lighter than an outline and
    darker than the background, in the strip at the figure's feet."""
    ys = np.nonzero(mask.any(axis=1))[0]
    top, bottom = ys.min(), ys.max()
    strip = np.zeros_like(mask)
    strip[int(bottom - SHADOW_STRIP * (bottom - top)) :] = True
    chroma = img.max(axis=2) - img.min(axis=2)
    luma = img @ np.array([0.299, 0.587, 0.114], dtype="float32")
    bg_luma = float(bg @ np.array([0.299, 0.587, 0.114]))
    shadow = mask & strip & (chroma < SHADOW_CHROMA) & (luma > 100) & (luma < bg_luma - 4)
    shadow = build._grow(shadow, 1) & mask & strip & (chroma < SHADOW_CHROMA + 10)
    kept = mask & ~shadow
    # Specks the shadow alone tied to the figure go too; real pieces it touched (shoes drawn
    # apart from the legs, a tail tip on the ground) are far bigger and stay.
    blobs = components(kept[::2, ::2])
    if blobs:
        pieces = [b for b in blobs if b.sum() >= 0.003 * blobs[0].sum()]
        keep = np.repeat(np.repeat(np.any(pieces, axis=0), 2, axis=0), 2, axis=1)
        kept &= build._grow(keep[: kept.shape[0], : kept.shape[1]], 1)
    return kept


def place(sheet: np.ndarray, edited: np.ndarray, height: float, sk: Skeleton) -> np.ndarray:
    """The sheet with its three-quarter half replaced by the redrawn figure: scaled to `height`,
    soles on the skeleton's sole, legs centred on its pelvis. The figure's edges are unmixed
    from klein's background and laid on the sheet's."""
    mask, edit_bg = figure_mask(edited)
    mask = drop_shadow(edited, mask, edit_bg)
    alpha = build._alpha(edited, mask, edit_bg)
    colour = build._unmix(edited, alpha, edit_bg)
    x0, y0, x1, y1 = build._bbox(mask)
    scale = height / (y1 - y0)
    size = (round((x1 - x0) * scale), round((y1 - y0) * scale))
    rgba = np.dstack([colour[y0:y1, x0:x1], alpha[y0:y1, x0:x1] * 255]).round().astype("uint8")
    figure = Image.fromarray(rgba, "RGBA").resize(size, Image.Resampling.LANCZOS)
    legs = np.asarray(figure)[int(size[1] * 0.75) :, :, 3] > 127  # the bottom quarter
    legs_x = float(np.nonzero(legs)[1].mean()) if legs.any() else size[0] / 2
    bg, _ = background(sheet)
    out = Image.fromarray(sheet.astype("uint8")).convert("RGBA")
    half = Image.new("RGBA", (CANVAS[0] - CANVAS[0] // 2, CANVAS[1]), (*map(int, bg), 255))
    out.paste(half, (CANVAS[0] // 2, 0))
    px, sole = sk.joints["pelvis"][0], sk.joints["sole"][1]
    out.alpha_composite(figure, (round(px - legs_x), round(sole - size[1])))
    return np.asarray(out.convert("RGB")).astype("float32")


def score(sheet: np.ndarray) -> dict[str, Any]:
    """The cut's own checks on a sheet whose three-quarter figure was redrawn."""
    front, tq = turnaround(CANVAS)
    cuts = {}
    for sk in (front, tq):
        figure, _ = build.figure_mask(sheet, sk)
        head = build.head_mask(sheet, figure, sk)
        bones = build.rig_bones(sk)
        fits = {n: build.limb_fit(figure, sk, bones[n]) for n in build.LIMBS}
        cuts[sk.view] = ViewCut(sk, build.assign_parts(sheet, figure, head, bones, fits))
    consistency = compare_views(sheet, cuts)
    figure, _ = build.figure_mask(sheet, tq)
    fitted, limbs = fit_limbs(figure, tq)
    image = Image.fromarray(sheet.astype("uint8"))
    joints = check_sheet(image, [front, fitted]).figures[1].joints_inside
    turn = consistency["turn"]["fraction"] or 0.0
    paint = [p for p in consistency["problems"] if p.startswith(("head:", "torso:", "arms:"))]
    return {
        "turn": turn,
        "joints_on_figure": joints,
        "limbs_fitted": {limb: r.get("changed", False) for limb, r in limbs.items()},
        "problems": consistency["problems"],
        # Best: turned enough, no paint only one view has, the most skeleton on the figure,
        # then the turn nearest to what was asked.
        "rank": [turn >= 0.5, -len(paint), round(joints, 2), -abs(1 - turn)],
    }


def turn_design(
    film_root: Path,
    character_id: str,
    *,
    candidate: str | None = None,
    seeds: tuple[int, ...] = SEEDS,
    regenerate: bool = False,
    replace: bool = False,
    cfg: StudioConfig | None = None,
) -> Turned:
    """The chosen design with its three-quarter figure redrawn by FLUX.2 klein from the front
    (best of `seeds`). Reuses an existing result unless `regenerate` (new edits) or `replace`
    (the existing edits placed and scored again, e.g. after this code changed; no model).

    If no seed turned the figure enough (`MIN_TURN`), the `EXTRA_SEEDS` are tried one by one
    until one does, so a stubborn character costs more edits, not a failed build. A result that
    was kept short of the turn is extended the same way the next time it is asked for."""
    data = load_candidates(film_root, character_id)
    if data is None:
        raise build.BuildError(f"{character_id!r} has no design candidates")
    candidate = candidate or data.get("chosen")
    if not candidate:
        raise build.BuildError(f"no design chosen for {character_id!r}; choose one first")
    folder = turn_dir(film_root, character_id, candidate)
    if (folder / "sheet.png").is_file() and not (regenerate or replace):
        kept = json.loads((folder / "choice.json").read_text())
        tried = kept["seeds"]
        turned_enough = any(r["turn"] >= MIN_TURN for r in tried.values())
        if turned_enough or all(f"s{s}" in tried for s in EXTRA_SEEDS):
            return Turned(folder / "sheet.png", kept)
    if regenerate and folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)
    source = design_dir(film_root, character_id) / candidate / "sheet.png"
    sheet = np.asarray(Image.open(source).convert("RGB")).astype("float32")
    front, tq = turnaround(CANVAS)
    half = CANVAS[0] // 2
    reference = folder / "front.png"
    Image.fromarray(sheet[:, :half].astype("uint8")).save(reference)
    by_id = {c["id"]: c for c in data["candidates"]}
    prompt = PROMPT.format(description=by_id[candidate]["description"])
    front_figure, _ = build.figure_mask(sheet, front)
    ys = np.nonzero(front_figure.any(axis=1))[0]
    height = float(ys.max() - ys.min())
    manifest = load_manifest()
    results: dict[str, dict[str, Any]] = {}
    pending = list(seeds)
    while pending:
        seed = pending.pop(0)
        graph = flux2_edit(
            manifest, prompt, references=["@front"], width=SIZE[0], height=SIZE[1], seed=seed
        )
        out = folder / f"s{seed}"
        if (out / "edit.png").is_file() and not regenerate:
            run = out / "run.json"
            seconds = json.loads(run.read_text()).get("seconds") if run.is_file() else None
        else:
            seconds = run_graph(
                film_root,
                "turn",
                graph,
                out_dir=out,
                params={"prompt": prompt, "size": SIZE, "candidate": candidate},
                seed=seed,
                names=["edit.png"],
                uploads={"@front": reference},
                cfg=cfg,
            ).seconds
        edited = np.asarray(Image.open(out / "edit.png").convert("RGB")).astype("float32")
        placed = place(sheet, edited, height, tq)
        Image.fromarray(placed.astype("uint8")).save(out / "sheet.png")
        results[f"s{seed}"] = {"seconds": seconds, **score(placed)}
        if not pending and not any(r["turn"] >= MIN_TURN for r in results.values()):
            pending = [s for s in EXTRA_SEEDS if f"s{s}" not in results][:1]
    chosen = max(results, key=lambda k: results[k]["rank"])
    shutil.copy(folder / chosen / "sheet.png", folder / "sheet.png")
    choice = {
        "candidate": candidate,
        "model": "flux2-klein-4b",
        "prompt": prompt,
        "chosen_seed": int(chosen[1:]),
        "seeds": results,
    }
    (folder / "choice.json").write_text(json.dumps(choice, indent=1) + "\n")
    return Turned(folder / "sheet.png", choice)
