"""Background drafts from a description, and the chosen one finished into a plate (task 4.6,
D-054).

    made = generate_background(film_root, "meadow", "a sunny meadow at the edge of a forest")
    plate = choose_background(film_root, "meadow", "c2")   # backgrounds/meadow/plate.png

A background is drawn once as a **plate**: 2880x1080, the 1920x1080 frame plus room for the
camera to pan. Making one is slow on this machine (SDXL at ~3 MP), so the work is split:

1. **Drafts** at 1536x576 (an SDXL 8:3 bucket, so the composition is native), in the film's
   style, from a fixed prompt template around the director's description: a wide empty scene,
   open ground along the bottom, scenery further away toward the top. Seeds are recorded;
   every draft gets the cheap checks (place/checks.py). Rounds add drafts (c1..c4, c5..).
2. **Finish** (only the chosen draft): Real-ESRGAN x4 (anime_6B, BSD-3) to the plate size,
   then a low-denoise SDXL pass in the same style, which adds real detail without moving
   anything (comfy_graphs.finish_plate).

    backgrounds/<id>/design/
        plates.json        every draft's description, seed and checks (schemas/plates)
        c1/draft.png       the 1536x576 draft, with run.json and checks.json
        c1/plate.png       once chosen: the finished 2880x1080 plate (and plate_run.json)
    backgrounds/<id>/plate.png   the chosen plate, where split_depth_layers (4.7) reads it
"""

from __future__ import annotations

import json
import random
import re
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from studio_core.comfy_graphs import finish_plate, txt2img
from studio_core.comfy_runs import film_style, run_graph
from studio_core.config import StudioConfig, load_config
from studio_core.models import Manifest, load_manifest
from studio_core.place.checks import check_plate
from studio_core.safety import blocked_words
from studio_core.schema import validate

DRAFT_SIZE = (1536, 576)  # an SDXL 8:3 bucket
PLATE_SIZE = (2880, 1080)
MAX_DRAFTS = 8
BACKGROUND_ID = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
# The description's things (a stream, flowers, a house) are pushed into the middle and far
# distance; the front stays a plain lawn, like a stage floor, where characters stand (the
# first drafts put big flowers and the stream right along the bottom).
PROMPT = (
    "wide landscape background for a children's picture book, {description}, seen from a "
    "little way off, everything in the middle and far distance, an empty scene with no people "
    "and no animals, the bottom of the picture is a plain flat open lawn of short grass like a "
    "stage floor, soft daylight, simple flat colors, clean shapes"
)
NEGATIVE = (
    "people, person, character, child, animal, bird, creature, text, signature, watermark, "
    "frame, border, flowers in the foreground, tall grass in the foreground, water in the "
    "foreground, rocks in the foreground, objects in the foreground, cluttered ground, dark, "
    "night"
)


class PlaceError(ValueError):
    """A background request was refused. The message says what to fix."""


@dataclass
class Draft:
    id: str  # "c1"
    description: str
    seed: int
    draft: str  # relative to the design folder
    ok: bool
    problems: list[str]
    seconds: float
    created: str


def background_dir(film_root: Path, background_id: str) -> Path:
    return film_root / "backgrounds" / background_id


def design_dir(film_root: Path, background_id: str) -> Path:
    return background_dir(film_root, background_id) / "design"


def check_request(background_id: str, description: str, n: int) -> list[str]:
    """Why a background request can't run ([] = fine)."""
    problems = []
    if not BACKGROUND_ID.match(background_id):
        problems.append(
            f"background id {background_id!r} must be lowercase letters, digits or _ "
            "(starting with a letter, at most 40)"
        )
    if not 3 <= len(description.strip()) <= 300:
        problems.append("the description must be 3 to 300 characters")
    if blocked := blocked_words(description):
        problems.append(f"the description uses {blocked}, not for a children's film")
    if not 1 <= n <= MAX_DRAFTS:
        problems.append(f"n must be 1 to {MAX_DRAFTS}")
    return problems


def load_plates(film_root: Path, background_id: str) -> dict[str, Any] | None:
    path = design_dir(film_root, background_id) / "plates.json"
    return json.loads(path.read_text()) if path.is_file() else None


def _save(folder: Path, data: dict[str, Any]) -> None:
    issues = validate("plates", data)
    if issues:
        raise ValueError("invalid plates.json: " + "; ".join(map(str, issues)))
    (folder / "plates.json").write_text(json.dumps(data, indent=1) + "\n")


def _check(image_path: Path) -> Any:
    report = check_plate(Image.open(image_path))
    (image_path.parent / f"{image_path.stem}_checks.json").write_text(
        json.dumps({**asdict(report), "ok": report.ok}, indent=1) + "\n"
    )
    return report


def generate_background(
    film_root: Path,
    background_id: str,
    description: str,
    *,
    n: int = 4,
    seed: int | None = None,
    cfg: StudioConfig | None = None,
    manifest: Manifest | None = None,
    on_draft: Callable[[Draft], None] | None = None,
) -> list[Draft]:
    """`n` drafts of a described place at 1536x576 in the film's style, each checked and
    recorded in plates.json (saved as each one finishes)."""
    if problems := check_request(background_id, description, n):
        raise PlaceError("; ".join(problems))
    cfg = cfg or load_config()
    manifest = manifest or load_manifest()
    style = film_style(film_root, cfg)
    if style not in manifest.styles:
        raise PlaceError(f"the film's style {style!r} isn't in config/models.toml")
    description = description.strip()
    folder = design_dir(film_root, background_id)
    folder.mkdir(parents=True, exist_ok=True)
    data = load_plates(film_root, background_id) or {
        "schema_version": 1,
        "background": background_id,
        "style": style,
        "candidates": [],
    }
    if data["style"] != style:
        raise PlaceError(
            f"{background_id!r} was drafted in style {data['style']!r}, but the film is now "
            f"{style!r}; start a new background id"
        )
    base = seed if seed is not None else random.randrange(2**31)
    first = 1 + max((int(c["id"][1:]) for c in data["candidates"]), default=0)
    prompt = PROMPT.format(description=description)
    made = []
    for i in range(n):
        cid, cseed = f"c{first + i}", base + i
        graph = txt2img(
            manifest,
            style,
            prompt,
            negative=NEGATIVE,
            seed=cseed,
            width=DRAFT_SIZE[0],
            height=DRAFT_SIZE[1],
            filename_prefix=f"background_{background_id}_{cid}",
        )
        out = folder / cid
        record = run_graph(
            film_root,
            "background",
            graph,
            out_dir=out,
            params={"background": background_id, "description": description},
            seed=cseed,
            style=style,
            names=["draft.png"],
            cfg=cfg,
        )
        report = _check(out / "draft.png")
        draft = Draft(
            id=cid,
            description=description,
            seed=cseed,
            draft=f"{cid}/draft.png",
            ok=report.ok,
            problems=report.problems,
            seconds=record.seconds,
            created=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        data["candidates"].append(asdict(draft))
        _save(folder, data)
        made.append(draft)
        if on_draft:
            on_draft(draft)
    return made


def choose_background(
    film_root: Path,
    background_id: str,
    candidate_id: str,
    *,
    finish: bool = True,
    denoise: float = 0.3,
    cfg: StudioConfig | None = None,
    manifest: Manifest | None = None,
) -> Path:
    """Record the chosen draft and finish it into the 2880x1080 plate (upscale + low-denoise
    refine), saved as backgrounds/<id>/plate.png. Returns the plate (or, with
    finish=False, the draft)."""
    data = load_plates(film_root, background_id)
    if data is None:
        raise PlaceError(f"{background_id!r} has no drafts; run generate_background")
    by_id = {c["id"]: c for c in data["candidates"]}
    if candidate_id not in by_id:
        raise PlaceError(f"no draft {candidate_id!r} for {background_id!r}; known: {list(by_id)}")
    folder = design_dir(film_root, background_id)
    data["chosen"] = candidate_id
    _save(folder, data)
    draft = folder / by_id[candidate_id]["draft"]
    if not finish:
        return draft
    cfg = cfg or load_config()
    manifest = manifest or load_manifest()
    candidate = by_id[candidate_id]
    graph = finish_plate(
        manifest,
        data["style"],
        PROMPT.format(description=candidate["description"]),
        image="@draft",
        seed=candidate["seed"],
        width=PLATE_SIZE[0],
        height=PLATE_SIZE[1],
        denoise=denoise,
        negative=NEGATIVE,
        filename_prefix=f"plate_{background_id}_{candidate_id}",
    )
    work = folder / candidate_id / "finish"
    run_graph(
        film_root,
        "plate",
        graph,
        out_dir=work,
        params={"background": background_id, "candidate": candidate_id, "denoise": denoise},
        seed=candidate["seed"],
        style=data["style"],
        names=["plate.png"],
        uploads={"@draft": draft},
        cfg=cfg,
    )
    plate = folder / candidate_id / "plate.png"
    shutil.move(str(work / "plate.png"), plate)
    shutil.move(str(work / "run.json"), folder / candidate_id / "plate_run.json")
    shutil.rmtree(work)
    report = _check(plate)
    candidate["plate"] = f"{candidate_id}/plate.png"
    candidate["ok"], candidate["problems"] = report.ok, report.problems
    _save(folder, data)
    final = background_dir(film_root, background_id) / "plate.png"
    shutil.copy(plate, final)
    return final
