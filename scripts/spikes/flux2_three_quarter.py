"""Spike (task 4.5, D-052): can FLUX.2 [klein] 4B turn a front view into a true three-quarter view
of the same character?

    uv run scripts/spikes/flux2_three_quarter.py [--film step4-demo --character kit] [--seeds 1 2]

Input: the front figure of the character's chosen design sheet. Two prompts per seed:

- **text:** the front figure is the only reference; the prompt asks for the turn.
- **pose:** a second reference, the three-quarter skeleton drawn as a mannequin, so the turn
  (and where the limbs go) is shown, not only described.

Each result is placed where the sheet's three-quarter figure goes (same height as the front
figure, feet on the skeleton's sole, legs centred on its pelvis), then measured exactly like
the SDXL turnaround's own three-quarter figure:

- consistency with the front view (puppet/consistency.py): paint only one view has, head
  size, and the **turn** (how far the drawn nose sits off the head's centre line, against what
  the skeleton asks for)
- the sheet checks (puppet/checks.py): does the figure sit on the three-quarter skeleton the
  rig will use (joints on the figure, height)?

Writes renders/spikes/flux2-three-quarter/<film>-<character>/<round>/: each edit, its sheet, a
labelled comparison grid and results.json. Safe to re-run (a round's outputs are replaced).
Frees ComfyUI after. `--round round1` repeats the first prompts (the turn only); round2 also
asks for the arms held out (the rig's pose) and no ground shadow.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from studio_core.comfy_graphs import flux2_edit
from studio_core.comfy_runs import free_comfy, run_graph
from studio_core.config import REPO_ROOT
from studio_core.models import load_manifest
from studio_core.puppet import build
from studio_core.puppet.checks import background, check_sheet, components, fill_holes, silhouette
from studio_core.puppet.consistency import ViewCut, compare_views
from studio_core.puppet.design import CANVAS, design_dir, load_candidates
from studio_core.puppet.skeleton import mannequin_image, turnaround

OUT = REPO_ROOT / "renders" / "spikes" / "flux2-three-quarter"
SIZE = (896, 1024)  # the front crop's aspect (672x768) at ~0.9 MP, multiples of 16
ROUNDS = {
    # Round 1: the turn only.
    "round1": {
        "text": (
            "Turn this cartoon character to a three-quarter view facing to the right. The same "
            "character with the same face, ears, clothes, scarf, colours and flat storybook art "
            "style. Full body, standing upright, arms hanging slightly away from the body, plain "
            "light background, nothing else in the picture."
        ),
        "pose": (
            "Redraw the cartoon character from image 1 in the pose and view of the grey figure in "
            "image 2: a three-quarter view facing to the right. Keep the same character, face, "
            "ears, clothes, scarf, colours and flat storybook art style. Full body, plain light "
            "background, nothing else in the picture."
        ),
    },
    # Round 2: round 1 turned the character well but rested the arms against the body (the
    # rig's three-quarter skeleton has them 25 degrees out) and sometimes drew a ground shadow.
    "round2": {
        "text": (
            "Turn this cartoon character to a three-quarter view facing to the right. The same "
            "character with the same face, ears, clothes, scarf, colours and flat storybook art "
            "style. Full body, standing upright with the legs slightly apart and both arms held "
            "out from the body at about 25 degrees, the hands well away from the hips, so there "
            "is a gap of background between each arm and the body. Plain light background, no "
            "shadow on the ground, nothing else in the picture."
        ),
        "pose": (
            "Redraw the cartoon character from image 1 in exactly the pose of the grey figure in "
            "image 2: a three-quarter view facing to the right, legs slightly apart, both arms "
            "held out from the body like the grey figure's, with a gap of background between "
            "each arm and the body. Keep the same character, face, ears, clothes, scarf, colours "
            "and flat storybook art style. Full body, plain light background, no shadow on the "
            "ground, nothing else in the picture."
        ),
    },
}


def figure_only(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The largest figure on a plain background (colour key, holes filled) and the bg colour."""
    bg, _ = background(img)
    mask = silhouette(img, bg)
    small = fill_holes(mask[::4, ::4])
    blobs = components(small)
    keep = np.repeat(np.repeat(blobs[0], 4, axis=0), 4, axis=1)[: mask.shape[0], : mask.shape[1]]
    full = np.zeros_like(mask)
    full[: keep.shape[0], : keep.shape[1]] = keep
    return mask & build._grow(full, 2), bg


def place(sheet: np.ndarray, edited: np.ndarray, height: float, sk) -> np.ndarray:
    """The sheet with its three-quarter half replaced by the edited figure, scaled to `height`
    with its soles on the skeleton's sole and its legs centred on the skeleton's pelvis."""
    mask, _ = figure_only(edited)
    x0, y0, x1, y1 = build._bbox(mask)
    scale = height / (y1 - y0)
    fig = Image.fromarray(edited[y0:y1, x0:x1].astype("uint8"))
    alpha = Image.fromarray((mask[y0:y1, x0:x1] * 255).astype("uint8"))
    size = (round((x1 - x0) * scale), round((y1 - y0) * scale))
    fig, alpha = fig.resize(size, Image.Resampling.LANCZOS), alpha.resize(size)
    legs = np.asarray(alpha)[int(size[1] * 0.75) :] > 127  # the bottom quarter: legs and feet
    legs_x = float(np.nonzero(legs)[1].mean()) if legs.any() else size[0] / 2
    bg, _ = background(sheet)
    out = Image.fromarray(sheet.astype("uint8"))
    ImageDraw.Draw(out).rectangle([CANVAS[0] // 2, 0, CANVAS[0], CANVAS[1]], fill=tuple(
        int(c) for c in bg))  # fmt: skip
    px, sole = sk.joints["pelvis"][0], sk.joints["sole"][1]
    out.paste(fig, (round(px - legs_x), round(sole - size[1])), alpha)
    return np.asarray(out).astype("float32")


def measure(sheet: np.ndarray) -> dict:
    """The same numbers the turnaround's own three-quarter figure gets."""
    skeletons = list(turnaround(CANVAS))
    checks = check_sheet(Image.fromarray(sheet.astype("uint8")), skeletons)
    cuts = {}
    for sk in skeletons:
        figure, _ = build.figure_mask(sheet, sk)
        head = build.head_mask(sheet, figure, sk)
        bones = build.rig_bones(sk)
        fits = {n: build.limb_fit(figure, sk, bones[n]) for n in build.LIMBS}
        parts = build.assign_parts(sheet, figure, head, bones, fits)
        cuts[sk.view] = ViewCut(sk, parts)
    consistency = compare_views(sheet, cuts)
    tq = checks.figures[1]
    return {
        "turn": consistency["turn"]["fraction"],
        "consistency_problems": consistency["problems"],
        "head_share": consistency["head_share"],
        "three_quarter_joints_on_figure": tq.joints_inside,
        "three_quarter_joints_off": tq.joints_off,
        "three_quarter_height_ratio": tq.height_ratio,
        "sheet_problems": checks.problems,
    }


def label(img: Image.Image, text: str) -> Image.Image:
    out = Image.new("RGB", (img.width, img.height + 44), "white")
    out.paste(img, (0, 44))
    draw = ImageDraw.Draw(out)
    for i, line in enumerate(text.split("\n")[:2]):
        draw.text((8, 4 + 18 * i), line, fill=(30, 30, 30))
    return out


def report(out: Path, sheet: np.ndarray, seconds: dict[str, float]) -> None:
    """results.json and comparison.png for a round, from the edits already in `out`."""
    half = CANVAS[0] // 2
    results = {"sdxl": {"seconds": None, **measure(sheet)}}
    tiles = [
        label(Image.fromarray(sheet[:, :half].astype("uint8")), "front (c3, SDXL)"),
        label(
            Image.fromarray(sheet[:, half:].astype("uint8")),
            f"SDXL three-quarter\nturn {results['sdxl']['turn']}",
        ),
    ]
    for edit in sorted(out.glob("*_s*/sheet.png")):
        key = edit.parent.name
        placed = np.asarray(Image.open(edit).convert("RGB")).astype("float32")
        results[key] = {"seconds": seconds.get(key), **measure(placed)}
        r = results[key]
        joints = r["three_quarter_joints_on_figure"]
        print(f"{key}: turn {r['turn']}, joints {joints}, {r['consistency_problems']}", flush=True)
        took = f" ({seconds[key]}s)" if key in seconds else ""
        tile = Image.fromarray(placed[:, half:].astype("uint8"))
        tiles.append(label(tile, f"klein {key}{took}\nturn {r['turn']}, joints {joints}"))
    (out / "results.json").write_text(json.dumps(results, indent=1) + "\n")
    grid = Image.new("RGB", (sum(t.width for t in tiles), max(t.height for t in tiles)), "white")
    x = 0
    for t in tiles:
        grid.paste(t, (x, 0))
        x += t.width
    grid.save(out / "comparison.png")
    print(out / "comparison.png")


PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>Three-quarter trial</title>
<style>
:root {{ --bg: #faf8f4; --fg: #222; --muted: #666; --card: #fff; --line: #e4e0d8; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #17171a; --fg: #eee; --muted: #aaa; --card: #222226; --line: #34343a; }}
}}
body {{ margin: 0; padding: 24px 16px; background: var(--bg); color: var(--fg);
       font: 15px/1.5 -apple-system, system-ui, sans-serif; }}
main {{ max-width: 1500px; margin: 0 auto; }}
.row {{ display: flex; gap: 14px; overflow-x: auto; padding-bottom: 8px; }}
figure {{ margin: 0; background: var(--card); border: 1px solid var(--line); border-radius: 10px;
         padding: 8px; flex: 0 0 auto; width: min(80vw, 380px); }}
figure img {{ width: 100%; height: auto; border-radius: 6px; background: #fff; }}
figcaption {{ font-size: 13px; color: var(--muted); }}
figcaption b {{ color: var(--fg); }}
figcaption ul {{ margin: 4px 0 0; padding-left: 16px; }}
p {{ color: var(--muted); font-size: 13px; }}
</style></head><body><main>
<h1>FLUX.2 klein 4B: front → three-quarter (Kit)</h1>
<p>{intro}</p>
{sections}
</main></body></html>"""


def review_page(folder: Path) -> Path:
    """review.html: every round's edits, placed where the rig's three-quarter view goes, with
    their numbers and prompts. Self-contained (images embedded)."""
    import base64
    import html
    import io

    def uri(path: Path, height: int = 420) -> str:
        im = Image.open(path).convert("RGB")
        im = im.resize((round(im.width * height / im.height), height), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

    sections = []
    for rnd in sorted(p for p in folder.iterdir() if p.is_dir() and (p / "results.json").is_file()):
        results = json.loads((rnd / "results.json").read_text())
        seconds = (
            json.loads((rnd / "seconds.json").read_text())
            if (rnd / "seconds.json").is_file()
            else {}
        )
        front = uri(rnd / "inputs" / "front.png")
        cards = [f'<figure><img src="{front}"><figcaption>front (SDXL c3)</figcaption></figure>']
        for key, r in results.items():
            if key == "sdxl":
                continue
            problems = "".join(f"<li>{html.escape(x)}</li>" for x in r["consistency_problems"])
            took = f", {seconds[key]:.0f} s" if key in seconds else ""
            joints = r["three_quarter_joints_on_figure"]
            cards.append(
                f'<figure><img src="{uri(rnd / key / "edit.png")}"><figcaption><b>{key}</b>{took}'
                f"<br>turn {r['turn']:.0%} of asked, joints on figure {joints:.0%}"
                f"<ul>{problems}</ul></figcaption></figure>"
            )
        prompts = "".join(
            f"<p><b>{k}:</b> {html.escape(v)}</p>" for k, v in ROUNDS[rnd.name].items()
        )
        sections.append(f"<h2>{rnd.name}</h2><div class=row>{''.join(cards)}</div>{prompts}")
    sdxl = json.loads(next(folder.glob("*/results.json")).read_text())["sdxl"]
    intro = (
        f"For comparison, SDXL's own three-quarter figure (c3) turned {sdxl['turn']:.0%} of what "
        "the skeleton asks and wears a hat the front lacks. <i>Joints on figure</i> is the share "
        "of the rig's three-quarter skeleton joints that land on the drawn figure (the cut uses "
        "them)."
    )
    page = PAGE.format(intro=intro, sections="".join(sections))
    out = folder / "review.html"
    out.write_text(page)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--film", default="step4-demo")
    ap.add_argument("--character", default="kit")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2])
    ap.add_argument("--round", choices=sorted(ROUNDS), default="round2")
    ap.add_argument("--remeasure", action="store_true", help="re-measure existing edits only")
    ap.add_argument("--page", action="store_true", help="only (re)write review.html")
    args = ap.parse_args()

    root = REPO_ROOT / "films" / args.film
    data = load_candidates(root, args.character)
    sheet_path = design_dir(root, args.character) / data["chosen"] / "sheet.png"
    sheet = np.asarray(Image.open(sheet_path).convert("RGB")).astype("float32")
    out = OUT / f"{args.film}-{args.character}" / args.round
    timings = out / "seconds.json"
    if args.page:
        print(review_page(out.parent))
        return
    if args.remeasure:
        report(out, sheet, json.loads(timings.read_text()) if timings.is_file() else {})
        print(review_page(out.parent))
        return
    front, tq = turnaround(CANVAS)
    if out.exists():
        shutil.rmtree(out)
    (out / "inputs").mkdir(parents=True)
    half = CANVAS[0] // 2
    Image.fromarray(sheet[:, :half].astype("uint8")).save(out / "inputs" / "front.png")
    pose = mannequin_image([tq], CANVAS).crop((half, 0, CANVAS[0], CANVAS[1]))
    Image.fromarray(255 - np.asarray(pose)).save(out / "inputs" / "pose.png")  # grey on white
    front_mask, _ = build.figure_mask(sheet, front)
    ys = np.nonzero(front_mask.any(axis=1))[0]
    front_height = float(ys.max() - ys.min())
    manifest = load_manifest()
    seconds: dict[str, float] = {}
    for seed in args.seeds:
        for name, prompt in ROUNDS[args.round].items():
            refs = ["@front"] + (["@pose"] if name == "pose" else [])
            graph = flux2_edit(
                manifest, prompt, references=refs, width=SIZE[0], height=SIZE[1], seed=seed
            )
            key = f"{name}_s{seed}"
            started = time.monotonic()
            inputs = {"@front": out / "inputs" / "front.png", "@pose": out / "inputs" / "pose.png"}
            run_graph(
                root,
                "flux2-edit",
                graph,
                out_dir=out / key,
                seed=seed,
                params={"prompt": prompt, "references": refs, "size": SIZE},
                names=["edit.png"],
                uploads={k: v for k, v in inputs.items() if k in refs},
            )
            seconds[key] = round(time.monotonic() - started, 1)
            edited = np.asarray(Image.open(out / key / "edit.png").convert("RGB")).astype("float32")
            placed = place(sheet, edited, front_height, tq)
            Image.fromarray(placed.astype("uint8")).save(out / key / "sheet.png")
    free_comfy()
    timings.write_text(json.dumps(seconds, indent=1) + "\n")
    report(out, sheet, seconds)
    print(review_page(out.parent))


if __name__ == "__main__":
    main()
