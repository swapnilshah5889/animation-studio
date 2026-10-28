"""Spike 4B: swappable hand poses for a generated character (docs/spikes/hand-poses.md).

Three ways to get a fist, a point, an open hand and a wave, tried on Kit, Bo and the girl in
the yellow raincoat ("child"; there is no Mia in films/step4-cast), on the image-left arm only:

  A  procedural   the hand cut from the forearm part, squashed / stretched / rotated
  B  AI redraw    FLUX.2 klein edits a 200 px crop of the character's front sheet around the
                  hand (prompt per pose, N seeds), the new hand is cut out with the colour key
                  and attached at the wrist
  C  code         the hand drawn as vector shapes (capsules) in the character's fill and outline

Each is attached to the same forearm stub at the same wrist point, so the tiles compare.
The wrist row per character is picked by hand here (WRIST); in production it would come from the
fitted skeleton. Only the image-left arm is done; a real hand set is made once per character.

Run:  uv run --project studio_core python scripts/spikes/hand_poses.py [a] [c] [b] [sheets]
      (no argument = a c sheets; b needs ComfyUI and the GPU, ~30 s per hand on the M4)
Out:  renders/spikes/hand-poses/ (git-ignored): work/, sheet-ac.png, sheet-b.png, results.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
FILM = ROOT / "films" / "step4-cast"
OUT = ROOT / "renders" / "spikes" / "hand-poses"
WORK = OUT / "work"
POSES = ("fist", "point", "open", "wave")
SEEDS = (1, 2)
CHARS = ("kit", "bo", "child")
# Hand-picked row of the forearm part where the wrist is (see the module docstring).
WRIST = {"kit": 138, "bo": 150, "child": 152}
# Width of the drawn hand (the cut hand is narrower than the forearm; Bo has no distinct hand).
HAND_W = {"kit": 52, "bo": 64, "child": 40}
NOUN = {"kit": "paw", "bo": "paw", "child": "hand"}
SS = 4  # supersampling for the drawn hands
TILE_H = (60, 115)  # rows shown above and below the wrist in a tile
PROMPT = (
    "Redraw this cartoon character's {noun} so that it is {pose}. Keep the same {noun} size, "
    "colours, outline and flat storybook art style, and keep the arm and the clothes as they are. "
    "The {noun} stays at the end of the arm, pointing down. Plain light background, nothing else."
)
POSE_WORDS = {
    "fist": "a closed fist",
    "point": "pointing with one finger, the other fingers curled",
    "open": "an open flat hand with the fingers together",
    "wave": "an open hand with the fingers spread, waving",
}


# ---------------------------------------------------------------- shared: part, wrist, tiles
class Char:
    def __init__(self, cid: str):
        self.id = cid
        d = FILM / "characters" / cid
        cands = json.loads((d / "design" / "candidates.json").read_text())
        self.cand = cands["chosen"]
        self.description = next(
            c["description"] for c in cands["candidates"] if c["id"] == self.cand
        )
        self.sheet = Image.open(d / "design" / self.cand / "sheet.png").convert("RGB")
        self.part = Image.open(d / "parts" / "front" / "forearm_l.png").convert("RGBA")
        rig = json.loads((d / "rig.json").read_text())
        self.line = rig["views"]["front"]["face"]["colors"]["line"]
        self.wy = WRIST[cid]
        a = np.asarray(self.part)[:, :, 3] > 128
        self.wx = float(np.nonzero(a[self.wy - 3 : self.wy + 4])[1].mean())
        self.stub = self.part.copy()
        self.stub.paste((0, 0, 0, 0), (0, self.wy, self.part.width, self.part.height))
        self.hand = self.part.crop((0, self.wy, self.part.width, self.part.height))
        self.hand = self.hand.crop(self.hand.getbbox())
        px = np.asarray(self.hand).reshape(-1, 4)
        px = px[px[:, 3] > 200][:, :3].astype("float32")
        luma = px @ np.array([0.299, 0.587, 0.114], dtype="float32")
        self.fill = tuple(int(v) for v in np.median(px[luma > np.percentile(luma, 20)], axis=0))
        self.cx0, self.cy0 = self.locate()  # where the part sits on the sheet

    def locate(self) -> tuple[int, int]:
        """Offset of the forearm part on the sheet: masked sum of squared differences by FFT."""
        s = np.asarray(self.sheet).astype("float64")
        t = np.asarray(self.part).astype("float64")
        m = (t[:, :, 3] > 250).astype("float64")
        h, w = m.shape
        H, W = s.shape[:2]
        fm = np.fft.rfft2(m, (H, W))
        ssd = np.zeros((H, W))
        for c in range(3):
            fi = np.fft.rfft2(s[:, :, c])
            ssd -= 2 * np.fft.irfft2(fi * np.conj(np.fft.rfft2(m * t[:, :, c], (H, W))), (H, W))
            ssd += np.fft.irfft2(np.fft.rfft2(s[:, :, c] ** 2) * np.conj(fm), (H, W))
        ssd = ssd[: H - h, : W // 2 - w]  # the front figure is the left half
        y, x = np.unravel_index(int(np.argmin(ssd)), ssd.shape)
        self.match = float(np.sqrt(max(ssd[y, x], 0.0) / (m.sum() * 3)))  # rms colour error
        return int(x), int(y)


def attach(ch: Char, hand: Image.Image, top_cx: float | None = None) -> Image.Image:
    """The tile: the hand under the forearm stub, its top-centre at the wrist, on light grey."""
    w, h = ch.part.size
    canvas = Image.new("RGBA", (w + 80, h + 120), (0, 0, 0, 0))
    ox, oy = 40, 0
    a = np.asarray(hand)[:, :, 3] > 128
    rows = np.nonzero(a.any(axis=1))[0]
    top = int(rows[0])
    cx = float(np.nonzero(a[top : top + 6])[1].mean()) if top_cx is None else top_cx
    canvas.alpha_composite(hand, (round(ox + ch.wx - cx), round(oy + ch.wy - top - 1)))
    canvas.alpha_composite(ch.stub, (ox, oy))
    y0 = ch.wy - TILE_H[0]
    tile = canvas.crop((0, y0, canvas.width, ch.wy + TILE_H[1]))
    bg = Image.new("RGBA", tile.size, (232, 232, 232, 255))
    bg.alpha_composite(tile)
    return bg.convert("RGB")


# ---------------------------------------------------------------- A: procedural variants
def procedural(ch: Char, pose: str) -> Image.Image:
    """The cut hand, squashed / stretched / rotated. No new pixels are made, only moved."""
    w, h = ch.hand.size
    if pose == "fist":  # squashed: shorter and a little wider, the paw curls up
        out = ch.hand.resize((round(w * 1.0), round(h * 0.72)), Image.Resampling.LANCZOS)
    elif pose == "point":  # narrower and longer: reads as a finger when the arm is raised
        out = ch.hand.resize((round(w * 0.72), round(h * 1.3)), Image.Resampling.LANCZOS)
    elif pose == "open":  # wider and flatter: an open palm
        out = ch.hand.resize((round(w * 1.3), round(h * 0.95)), Image.Resampling.LANCZOS)
    else:  # wave: open and splayed by a small angle
        out = ch.hand.resize((round(w * 1.3), round(h * 0.95)), Image.Resampling.LANCZOS)
        out = out.rotate(14, resample=Image.Resampling.BICUBIC, expand=True)
    return out


# ---------------------------------------------------------------- C: drawn in code
def _capsule(d: ImageDraw.ImageDraw, p0, p1, width, fill):
    d.line([p0, p1], fill=fill, width=round(width))
    r = width / 2
    for x, y in (p0, p1):
        d.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def drawn(ch: Char, pose: str) -> Image.Image:
    """A hand as capsules: all outline passes first, then all fill passes, so the shapes merge
    and only the outside keeps the line. `w` is the wrist width; fill and line are the
    character's (fill: the cut hand's median colour; line: rig face line colour)."""
    w = HAND_W[ch.id] * SS
    t = max(3.0, w * 0.055)  # outline thickness
    W, H = int(w * 2.0), int(w * 2.2)
    cx = W / 2
    fill, line = ch.fill, ch.line
    # (p0, p1, width) capsules; angles in degrees from straight down
    shapes: list[tuple[tuple[float, float], tuple[float, float], float]] = []
    details: list[tuple[tuple[float, float], tuple[float, float]]] = []

    def finger(base_x, base_y, length, width, deg):
        a = np.radians(deg)
        return (
            (cx + base_x, base_y),
            (cx + base_x + np.sin(a) * length, base_y + np.cos(a) * length),
            width,
        )

    if pose == "mitten":
        shapes = [
            ((cx, 0.0), (cx, 0.55 * w), w * 0.95),
            ((cx - 0.5 * w, 0.2 * w), (cx - 0.62 * w, 0.62 * w), 0.3 * w),
        ]
    elif pose == "fist":
        shapes = [
            ((cx, 0.0), (cx, 0.5 * w), w),
            ((cx - 0.55 * w, 0.28 * w), (cx - 0.5 * w, 0.62 * w), 0.3 * w),
        ]
        details = [((cx + dx * w, 0.5 * w), (cx + dx * w, 0.8 * w)) for dx in (-0.18, 0.1, 0.36)]
    elif pose == "point":
        shapes = [
            ((cx, 0.0), (cx, 0.4 * w), w * 0.95),
            ((cx - 0.5 * w, 0.2 * w), (cx - 0.5 * w, 0.5 * w), 0.28 * w),
        ]
        shapes.append(finger(0.22 * w, 0.4 * w, 0.8 * w, 0.26 * w, 0))
    elif pose == "open":
        shapes = [((cx, 0.0), (cx, 0.4 * w), w * 0.95)]
        for i, dx in enumerate((-0.33, -0.11, 0.11, 0.33)):
            shapes.append(finger(dx * w, 0.35 * w, (0.7, 0.85, 0.85, 0.7)[i] * w, 0.2 * w, dx * 20))
        shapes.append(((cx - 0.5 * w, 0.15 * w), (cx - 0.85 * w, 0.5 * w), 0.26 * w))
    else:  # wave: open, fingers splayed wider, the whole hand tilted
        shapes = [((cx, 0.0), (cx, 0.4 * w), w * 0.95)]
        for i, dx in enumerate((-0.33, -0.11, 0.11, 0.33)):
            shapes.append(finger(dx * w, 0.35 * w, (0.7, 0.85, 0.85, 0.7)[i] * w, 0.2 * w, dx * 75))
        shapes.append(((cx - 0.5 * w, 0.15 * w), (cx - 0.95 * w, 0.45 * w), 0.26 * w))
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for p0, p1, wd in shapes:
        _capsule(d, p0, p1, wd + 2 * t, line)
    for p0, p1, wd in shapes:
        _capsule(d, p0, p1, wd, fill)
    for p0, p1 in details:
        d.line([p0, p1], fill=line, width=round(t))
    if pose == "wave":
        img = img.rotate(12, resample=Image.Resampling.BICUBIC, center=(cx, 0))
    img = img.crop(img.getbbox())
    return img.resize((round(img.width / SS), round(img.height / SS)), Image.Resampling.LANCZOS)


# ---------------------------------------------------------------- B: AI redraw (klein, GPU)
CROP = 200  # sheet pixels around the hand, upscaled to SIZE for klein
SIZE = 768


def crop_box(ch: Char) -> tuple[int, int, int, int]:
    x = round(ch.cx0 + ch.wx - CROP / 2)
    y = round(ch.cy0 + ch.wy - 70)
    x = max(0, min(x, ch.sheet.width // 2 - CROP))
    return x, y, x + CROP, y + CROP


def redraw(ch: Char, pose: str, seed: int) -> dict:
    from studio_core.comfy_graphs import flux2_edit
    from studio_core.comfy_runs import run_graph
    from studio_core.config import load_config
    from studio_core.models import load_manifest

    out = WORK / ch.id / f"b_{pose}_s{seed}"
    box = crop_box(ch)
    ref = WORK / ch.id / "crop.png"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ch.sheet.crop(box).resize((SIZE, SIZE), Image.Resampling.LANCZOS).save(ref)
    if (out / "edit.png").is_file():
        return json.loads((out / "run.json").read_text())
    prompt = PROMPT.format(noun=NOUN[ch.id], pose=POSE_WORDS[pose])
    graph = flux2_edit(
        load_manifest(), prompt, references=["@crop"], width=SIZE, height=SIZE, seed=seed
    )
    rec = run_graph(
        FILM,
        "hand",
        graph,
        out_dir=out,
        params={"prompt": prompt},
        seed=seed,
        names=["edit.png"],
        uploads={"@crop": ref},
        cfg=load_config(),
    )
    return {"seconds": rec.seconds}


def cut_redraw(ch: Char, pose: str, seed: int) -> Image.Image | None:
    """The new hand from the klein edit: colour key on its background, the piece under the wrist
    row that touches the wrist column, scaled back to sheet pixels."""
    from studio_core.puppet import build
    from studio_core.puppet.checks import components
    from studio_core.puppet.turn import figure_mask

    f = WORK / ch.id / f"b_{pose}_s{seed}" / "edit.png"
    img = np.asarray(Image.open(f).convert("RGB")).astype("float32")
    mask, bg = figure_mask(img)
    k = SIZE / CROP
    box = crop_box(ch)
    wy = round((ch.cy0 + ch.wy - box[1]) * k)  # wrist row in the edit
    wx = round((ch.cx0 + ch.wx - box[0]) * k)
    below = mask.copy()
    below[:wy] = False
    blobs = components(below)
    if not blobs:
        return None
    pick = next((b for b in blobs if b[wy : wy + 8, wx - 40 : wx + 40].any()), blobs[0])
    alpha = build._alpha(img, pick, bg)
    colour = build._unmix(img, alpha, bg)
    rgba = np.dstack([colour, alpha * 255]).round().astype("uint8")
    im = Image.fromarray(rgba, "RGBA")
    im = im.crop(im.getbbox())
    return im.resize(
        (max(1, round(im.width / k)), max(1, round(im.height / k))), Image.Resampling.LANCZOS
    )


# ---------------------------------------------------------------- sheets
def label(img: Image.Image, text: str) -> Image.Image:
    out = Image.new("RGB", (img.width, img.height + 14), (255, 255, 255))
    out.paste(img, (0, 14))
    ImageDraw.Draw(out).text((3, 1), text, fill=(0, 0, 0))
    return out


def grid(rows: list[list[Image.Image]], path: Path, scale: float = 1.0) -> None:
    cw = max(t.width for r in rows for t in r)
    ch = max(t.height for r in rows for t in r)
    sheet = Image.new("RGB", (cw * max(map(len, rows)), ch * len(rows)), (255, 255, 255))
    for y, r in enumerate(rows):
        for x, t in enumerate(r):
            sheet.paste(t, (x * cw, y * ch))
    if scale != 1:
        sheet = sheet.resize(
            (round(sheet.width * scale), round(sheet.height * scale)), Image.Resampling.LANCZOS
        )
    sheet.save(path)


def main(args: list[str]) -> None:
    todo = set(args) or {"a", "c", "sheets"}
    OUT.mkdir(parents=True, exist_ok=True)
    resfile = OUT / "results.json"
    results = json.loads(resfile.read_text()) if resfile.is_file() else {}
    chars = [Char(c) for c in CHARS]
    for ch in chars:
        r = results.setdefault(ch.id, {})
        r.update(
            wrist_px=[round(ch.wx, 1), ch.wy],
            fill="#{:02x}{:02x}{:02x}".format(*ch.fill),
            line=ch.line,
            part_match_rms=round(ch.match, 1),
            part_at_sheet=[ch.cx0, ch.cy0],
        )
        wd = WORK / ch.id
        wd.mkdir(parents=True, exist_ok=True)
        if "a" in todo:
            t0 = time.perf_counter()
            for p in POSES:
                procedural(ch, p)
            r["a_seconds_all_poses"] = round(time.perf_counter() - t0, 4)
        if "c" in todo:
            t0 = time.perf_counter()
            for p in (*POSES, "mitten"):
                drawn(ch, p)
            r["c_seconds_all_poses"] = round(time.perf_counter() - t0, 4)
        if "b" in todo:
            secs = []
            for p in POSES:
                for s in SEEDS:
                    secs.append(redraw(ch, p, s)["seconds"])
            r["b_seconds_per_hand"] = [
                round(float(np.mean(secs)), 1),
                round(min(secs), 1),
                round(max(secs), 1),
            ]
        resfile.write_text(json.dumps(results, indent=1))
    if "sheets" in todo:
        rows = []
        for ch in chars:
            row = [label(attach(ch, ch.hand), f"{ch.id} cut")]
            row += [label(attach(ch, procedural(ch, p)), f"A {p}") for p in POSES]
            row += [label(attach(ch, drawn(ch, p)), f"C {p}") for p in ("mitten", *POSES)]
            rows.append(row)
        grid(rows, OUT / "sheet-ac.png")
        if any((WORK / c.id / f"b_fist_s{SEEDS[0]}" / "edit.png").is_file() for c in chars):
            rows = []
            for ch in chars:
                for s in SEEDS:
                    row = [label(attach(ch, ch.hand), f"{ch.id} cut")]
                    for p in POSES:
                        try:
                            new = cut_redraw(ch, p, s)
                        except FileNotFoundError:
                            new = None
                        row.append(
                            label(
                                attach(ch, new) if new else Image.new("RGB", (10, 10)),
                                f"B {p} s{s}",
                            )
                        )
                    rows.append(row)
            grid(rows, OUT / "sheet-b.png")
        print("sheets in", OUT)
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
