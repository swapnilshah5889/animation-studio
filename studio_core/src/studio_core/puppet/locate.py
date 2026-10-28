"""A vision model as the seed for the cut's pixel rules (D-070, docs/spikes/vision-locator.md).

The pixel rules that find a character's eyes, nose, mouth and joints (`build.clean_face`,
`fit.fit_limbs`) are exact when they find the part and fail on drawings they were not tuned for
(Bolt the robot: no nose, oval eyes, a boxy body). A local vision model (qwen3-vl via Ollama)
finds roughly the right place on any drawing, about 0.1 head heights off, and swaps left and
right. So its answers are **seeds**, never results: the rules run around them and the pixels
have the last word (`settle`). It is opt-in (`build_puppet(locator=True)`).

    seeds, payload = locate_sheet(sheet_png, cache)   # per view: skeleton joint name -> (x, y)
    save_cache(character_folder, payload)             # characters/<id>/build/locator.json

Points are in sheet pixels (the 1344x768 canvas), like the skeletons'. Left and right are the
character's own; screen-left is the character's right in both views, and a pair is swapped
until it is, whatever the model labelled (`swap_by_geometry`).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from studio_core.puppet.skeleton import turnaround

MODEL = "qwen3-vl:8b-instruct"
VIEWS = ("front", "three_quarter")
HALF = 672  # a view is one half of the 1344x768 sheet

KEEP_HEAD = 0.15  # a pixel result this close to its seed (in head heights) is kept: it is exact
FAIL_HEAD = 0.3  # two methods further apart than this fail the part for a human look
INSIDE_TOL = 12  # px: a seed this close to the figure counts as on it

JOINTS = ("shoulder", "elbow", "wrist", "hip", "knee", "ankle")
# (our key, skeleton joint name). Left/right are the character's own, so "left" is screen-right
# in the front view.
PARTS: dict[str, str] = {
    "left_eye": "l_eye",
    "right_eye": "r_eye",
    "nose_or_beak_tip": "nose",
    "mouth_centre": "mouth",
} | {f"{s}_{j}": f"{s[0]}_{j}" for j in JOINTS for s in ("left", "right")}
KEYS = tuple(PARTS)
FACE_KEYS = ("left_eye", "right_eye", "nose_or_beak_tip", "mouth_centre")

POINT = {
    "type": "object",
    "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
    "required": ["x", "y"],
}
SCHEMA = {
    "type": "object",
    "properties": {k: POINT for k in KEYS},
    "required": list(KEYS),
}
GRID = (
    "Coordinates are integers on a 0..1000 grid over the whole image: x=0 is the left edge, "
    "x=1000 the right edge, y=0 the top edge, y=1000 the bottom edge. "
    "'left' and 'right' are the character's OWN left and right (a character facing us has its "
    "left side on the right of the image)."
)
PLAIN = (
    "This image is a character design for a children's cartoon: one character standing. "
    "Locate these points on the character: the centre of each eye, the tip of the nose or beak, "
    "the centre of the mouth, and the centre of each joint: shoulders, elbows, wrists (where "
    "the hand starts), hips, knees and ankles. For a robot or a creature use the equivalent "
    "parts. If a part is hidden, give your best guess of where it would be. " + GRID
)
SOM = (
    "This image is a character design for a children's cartoon. Numbered dots mark where a "
    "template skeleton expects each part; the template does NOT match this drawing exactly, so "
    "many dots are off. For every part below, give where it REALLY is on the drawing (it may be "
    "far from its dot). Do not just copy the dot positions. Dots: {legend}. Parts: eyes (centre), "
    "nose or beak tip, mouth centre, and the centre of each joint (shoulders, elbows, wrists = "
    "where the hand starts, hips, knees, ankles). For a robot or creature use the equivalent "
    "parts. If a part is hidden, guess where it would be. " + GRID
)
# the dots: skeleton joint -> number, in KEYS order
SOM_JOINTS = {k: v for k, v in PARTS.items() if v != "mouth"}

Point = tuple[float, float]
# an `ask` takes a view's crop and the view name; returns the model's answer in crop pixels
Ask = Callable[[Image.Image, str], "dict[str, Point | None]"]


class LocatorError(RuntimeError):
    """The locator can't run (ComfyUI busy, Ollama down). The message says what to do."""


# ------------------------------------------------------------------------------- the model


def png_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def view_crop(sheet: Image.Image, view: str) -> Image.Image:
    x0 = 0 if view == "front" else HALF
    return sheet.crop((x0, 0, x0 + HALF, sheet.height))


def som_image(crop: Image.Image, view: str) -> tuple[Image.Image, str]:
    """The crop with the template skeleton's joints as numbered red dots, and the legend."""
    sk = turnaround((1344, 768))[VIEWS.index(view)]
    x0 = 0 if view == "front" else HALF
    img = crop.copy()
    d = ImageDraw.Draw(img)
    legend = []
    for n, (key, joint) in enumerate(SOM_JOINTS.items(), 1):
        x, y = sk.joints[joint]
        x -= x0
        d.ellipse([x - 11, y - 11, x + 11, y + 11], fill=(255, 40, 40), outline="white", width=2)
        d.text((x - (6 if n > 9 else 3), y - 6), str(n), fill="white")
        legend.append(f"{n}={key.replace('_', ' ')}")
    legend.append(f"{len(SOM_JOINTS) + 1}=mouth centre (no dot)")
    return img, "; ".join(legend)


def ask_json(client: Any, img: Image.Image, prompt: str) -> tuple[dict | None, float, str]:
    """One deterministic call (temperature 0, thinking off, answer forced into SCHEMA)."""
    import time

    t = time.perf_counter()
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt, "images": [png_b64(img)]}],
        "stream": False,
        "think": False,
        "format": SCHEMA,
        "options": {"temperature": 0, "num_predict": 900},
        "keep_alive": "10m",
    }
    # `format` is not in the thin client's chat(); send the request ourselves
    resp = client._request("/api/chat", payload)
    secs = time.perf_counter() - t
    text = resp.get("message", {}).get("content", "")
    try:
        return json.loads(text), secs, text
    except json.JSONDecodeError:
        return None, secs, text


def to_px(ans: dict | None, size: tuple[int, int]) -> dict[str, Point | None]:
    """The model's 0..1000 grid answer as pixels of an image of `size` (None for a gap)."""
    out: dict[str, Point | None] = {}
    for k in KEYS:
        p = (ans or {}).get(k)
        try:
            out[k] = (p["x"] / 1000 * size[0], p["y"] / 1000 * size[1])
        except (TypeError, KeyError):
            out[k] = None
    return out


@contextmanager
def ollama_asker() -> Iterator[Ask]:
    """The real `ask`. Frees ComfyUI first, refuses while it has work queued (one large model in
    memory at a time), and unloads the vision model afterwards.

    Per view: the plain prompt for the face parts (the dots pull eyes toward the template) and
    the Set-of-Mark prompt for the joints (they are better with the dots): two calls, ~30 s each
    on the M4."""
    from studio_core.comfy_runs import free_comfy
    from studio_core.config import load_config
    from studio_core.ollama import Ollama

    cfg = load_config()
    try:
        from studio_core.comfy import Comfy

        queue = json.loads(Comfy(cfg.get("services", "comfyui_url"))._get("/queue"))
        if queue.get("queue_running") or queue.get("queue_pending"):
            raise LocatorError("ComfyUI has a job running; wait for it, then run the locator")
    except OSError:
        pass  # ComfyUI isn't running: it holds no memory
    free_comfy(cfg)
    client = Ollama()
    try:
        for m in client.loaded():
            client.unload(m["name"])
    except OSError as exc:
        raise LocatorError(f"Ollama isn't reachable ({exc}); start it with `ollama serve`") from exc

    def ask(crop: Image.Image, view: str) -> dict[str, Point | None]:
        plain, _, _ = ask_json(client, crop, PLAIN)
        som_img, legend = som_image(crop, view)
        som, _, _ = ask_json(client, som_img, SOM.format(legend=legend))
        face, limbs = to_px(plain, crop.size), to_px(som, crop.size)
        return {k: (face[k] or limbs[k]) if k in FACE_KEYS else (limbs[k] or face[k]) for k in KEYS}

    try:
        yield ask
    finally:
        with suppress(OSError, TimeoutError):
            client.unload(MODEL)


# ------------------------------------------------------------------------------ geometry


def swap_by_geometry(points: dict[str, Point | None]) -> dict[str, Point | None]:
    """Every left/right pair ordered by where it is, never by what the model called it: the
    character's right is on screen-left (smaller x) in both views."""
    out = dict(points)
    for part in ("eye", *JOINTS):
        left, right = out.get(f"left_{part}"), out.get(f"right_{part}")
        if left and right and left[0] < right[0]:
            out[f"left_{part}"], out[f"right_{part}"] = right, left
    return out


def near_figure(mask: np.ndarray, p: Point, tol: int = INSIDE_TOL) -> bool:
    """Is `p` on the mask, or within `tol` px of it?"""
    x, y = round(p[0]), round(p[1])
    h, w = mask.shape
    if not (0 <= x < w and 0 <= y < h):
        return False
    return bool(mask[max(0, y - tol) : y + tol + 1, max(0, x - tol) : x + tol + 1].any())


def settle(
    seed: Point | None,
    pixel: Point | None,
    blobs: list[Point],
    mask: np.ndarray,
    head_h: float,
) -> tuple[Point | None, str]:
    """Decide one part from the model's seed and the pixel rule's result (None: it found
    nothing). Returns the point to use and a status:

    - `pixel`: no seed, or the pixel result is within KEEP_HEAD of it: kept, it is exact;
    - `pixel_near_seed`: the rule's result is elsewhere but a mark lies within KEEP_HEAD of the
      seed: that mark (exact) is used;
    - `seed`: nothing found near it (or the rule found nothing, or something 0.15..0.3 head
      heights away): the seed itself, flagged;
    - `outside`: the seed isn't on the figure: ignored, the pixel result stays; fails the part;
    - `disagree`: the rule found something more than FAIL_HEAD from the seed and no mark lies
      near the seed: pixel result stays; fails the part for a human look."""
    if seed is None:
        return pixel, "pixel"
    if not near_figure(mask, seed):
        return pixel, "outside"
    if pixel is not None and math.dist(pixel, seed) <= KEEP_HEAD * head_h:
        return pixel, "pixel"
    near = [b for b in blobs if math.dist(b, seed) <= KEEP_HEAD * head_h]
    if near:
        return min(near, key=lambda b: math.dist(b, seed)), "pixel_near_seed"
    if pixel is not None and math.dist(pixel, seed) > FAIL_HEAD * head_h:
        return pixel, "disagree"
    return seed, "seed"


FAILED = {"outside", "disagree"}


def seeds_for_view(points: dict[str, Point | None]) -> dict[str, Point]:
    """Skeleton joint name -> point, from the model's keys (already swapped)."""
    return {PARTS[k]: p for k, p in points.items() if p is not None}


# --------------------------------------------------------------------------------- cache


def sheet_hash(sheet: Path) -> str:
    return hashlib.sha256(sheet.read_bytes()).hexdigest()[:16]


def prompt_hash() -> str:
    return hashlib.sha256((MODEL + PLAIN + SOM + json.dumps(SCHEMA)).encode()).hexdigest()[:16]


def cache_path(character_folder: Path) -> Path:
    return character_folder / "build" / "locator.json"


def load_cache(character_folder: Path) -> dict[str, Any] | None:
    try:
        return json.loads(cache_path(character_folder).read_text())
    except (OSError, json.JSONDecodeError):
        return None


def save_cache(character_folder: Path, payload: dict[str, Any]) -> None:
    path = cache_path(character_folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n")


def locate_sheet(
    sheet: Path, cache: dict[str, Any] | None = None, ask: Ask | None = None
) -> tuple[dict[str, dict[str, Point]], dict[str, Any]]:
    """Seeds for both views of the sheet: ({view: {joint name: (x, y)}}, cache payload).
    A cache for the same sheet, model and prompts is reused without calling the model."""
    key = {"model": MODEL, "prompts": prompt_hash(), "sheet": sheet_hash(sheet)}
    if cache and all(cache.get(k) == v for k, v in key.items()) and "views" in cache:
        views = {v: {k: tuple(p) for k, p in pts.items()} for v, pts in cache["views"].items()}
        return views, cache
    img = Image.open(sheet).convert("RGB")

    def run(ask: Ask) -> dict[str, Any]:
        raw: dict[str, Any] = {}
        for view in VIEWS:
            x0 = 0 if view == "front" else HALF
            answer = ask(view_crop(img, view), view)
            raw[view] = {k: (p[0] + x0, p[1]) if p else None for k, p in answer.items()}
        return raw

    if ask is None:
        with ollama_asker() as real:
            raw = run(real)
    else:
        raw = run(ask)
    swapped = {v: swap_by_geometry(p) for v, p in raw.items()}
    payload = {
        **key,
        "views": {
            v: {k: [round(p[0], 1), round(p[1], 1)] for k, p in seeds_for_view(pts).items()}
            for v, pts in swapped.items()
        },
        "swapped_pairs": {
            v: [
                part
                for part in ("eye", *JOINTS)
                if raw[v].get(f"left_{part}") != swapped[v].get(f"left_{part}")
            ]
            for v in raw
        },
    }
    views = {v: seeds_for_view(pts) for v, pts in swapped.items()}
    return views, payload
