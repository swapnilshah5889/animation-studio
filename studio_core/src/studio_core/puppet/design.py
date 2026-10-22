"""Character designs from a description (task 4.3, D-049).

    made = design_character(film_root, "kit", "a cheerful young fox with a green scarf", n=4)
    [(c.id, c.seed, c.ok, c.problems) for c in made]

Each candidate is a **turnaround sheet**: the character in front view (left half) and
three-quarter view (right half) on one 1344x768 canvas, in the film's style. Both views come
from one image, so they share one design (colours, clothes, proportions).

How the picture is steered:

- **Pose:** the skeleton (puppet/skeleton.py) conditions SDXL twice through the union
  ControlNet: as an OpenPose stick figure at full strength (the joints end up where the rig
  will put them, task 4.4), and as a mannequin "depth" image, weakly and only for the first
  steps (the arms stay off the torso; stronger, it turns every character into a wooden doll).
- **Prompt:** the description is wrapped in a fixed template (turnaround, full body, plain
  background, arms away from the body, faceless). The template is code; the director only
  writes the description.
- **Seeds:** candidate i of a round uses `seed + i`, recorded per candidate, so any sheet can
  be made again.
- **Fast mode** (Lightning, 8 steps) runs at CFG 1, where the negative prompt has no effect:
  quicker, but faces and shadows are suppressed less.

Every sheet gets the cheap pixel checks (puppet/checks.py). Problems are reported, never
silently fixed: the director or the owner chooses. Rounds add candidates (c1..c4, then
c5..c8), so earlier ones stay for comparison.

    characters/<id>/design/
        pose.png          the conditioning skeleton (OpenPose)
        mannequin.png     the conditioning body shape (depth)
        candidates.json   every candidate's description, seed and checks (schemas/design)
        c1/sheet.png      the generated sheet
        c1/run.json       the exact graph, seed and timings (comfy_runs)
        c1/checks.json    the full check report
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from studio_core.comfy_graphs import Control, txt2img
from studio_core.comfy_runs import film_style, run_graph
from studio_core.config import StudioConfig, load_config
from studio_core.models import Manifest, load_manifest
from studio_core.puppet.checks import SheetCheck, check_sheet
from studio_core.puppet.skeleton import mannequin_image, pose_image, turnaround
from studio_core.safety import blocked_words
from studio_core.schema import validate

CANVAS = (1344, 768)
MAX_CANDIDATES = 8
CHARACTER_ID = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
# Faces: SDXL draws them whatever the prompt says (weighting "(eyes:1.5)" only cost the arms),
# so the prompt asks gently and the build step paints the face area over (D-047, D-049).
PROMPT = (
    "character turnaround sheet of {description}, the same character twice, front view and "
    "three-quarter view, full body, standing, arms held out from the sides, hands visible, "
    "faceless, blank face without eyes or mouth, plain white background, "
    "simple flat colors, clean outlines"
)
NEGATIVE = (
    "eyes, mouth, nose, facial features, different characters, extra people, props, text, "
    "signature, leaves, ground shadow, grass, busy background, cropped, cut off feet"
)
CONTROLNET = "controlnet-union-sdxl-promax"
POSE = Control(CONTROLNET, "@pose", "openpose", strength=1.0, end=1.0)
MANNEQUIN = Control(CONTROLNET, "@mannequin", "depth", strength=0.4, end=0.5)


class DesignError(ValueError):
    """A design request was refused. The message says what to fix."""


@dataclass
class Candidate:
    id: str  # "c1"
    description: str
    seed: int
    fast: bool
    sheet: str  # relative to the design folder
    ok: bool
    problems: list[str]
    seconds: float
    created: str


def design_dir(film_root: Path, character_id: str) -> Path:
    return film_root / "characters" / character_id / "design"


def check_request(character_id: str, description: str, n: int) -> list[str]:
    """Why a design request can't run ([] = fine)."""
    problems = []
    if not CHARACTER_ID.match(character_id):
        problems.append(
            f"character id {character_id!r} must be lowercase letters, digits or _ "
            "(starting with a letter, at most 40)"
        )
    if not 3 <= len(description.strip()) <= 300:
        problems.append("the description must be 3 to 300 characters")
    if blocked := blocked_words(description):
        problems.append(f"the description uses {blocked}, not for a children's film")
    if not 1 <= n <= MAX_CANDIDATES:
        problems.append(f"n must be 1 to {MAX_CANDIDATES}")
    return problems


def load_candidates(film_root: Path, character_id: str) -> dict[str, Any] | None:
    path = design_dir(film_root, character_id) / "candidates.json"
    return json.loads(path.read_text()) if path.is_file() else None


def _save(folder: Path, data: dict[str, Any]) -> None:
    issues = validate("design", data)
    if issues:
        raise ValueError("invalid candidates.json: " + "; ".join(map(str, issues)))
    (folder / "candidates.json").write_text(json.dumps(data, indent=1) + "\n")


def _check(candidate_dir: Path) -> SheetCheck:
    """Run the sheet checks and write checks.json next to the sheet."""
    report = check_sheet(Image.open(candidate_dir / "sheet.png"), list(turnaround(CANVAS)))
    (candidate_dir / "checks.json").write_text(
        json.dumps({**asdict(report), "ok": report.ok}, indent=1) + "\n"
    )
    return report


def recheck(film_root: Path, character_id: str) -> dict[str, Any]:
    """Run the current checks again on every existing sheet (after the checks improve) and
    update checks.json and candidates.json. No images are generated."""
    data = load_candidates(film_root, character_id)
    if data is None:
        raise DesignError(f"{character_id!r} has no design candidates")
    folder = design_dir(film_root, character_id)
    for c in data["candidates"]:
        report = _check(folder / c["id"])
        c["ok"], c["problems"] = report.ok, report.problems
    _save(folder, data)
    return data


def design_character(
    film_root: Path,
    character_id: str,
    description: str,
    *,
    n: int = 4,
    seed: int | None = None,
    fast: bool = False,
    cfg: StudioConfig | None = None,
    manifest: Manifest | None = None,
    on_candidate: Callable[[Candidate], None] | None = None,
) -> list[Candidate]:
    """Generate `n` turnaround sheets for one described character, check each, and record
    them in candidates.json. Returns this round's candidates (each is saved as it finishes,
    so an interrupted round keeps what it made)."""
    if problems := check_request(character_id, description, n):
        raise DesignError("; ".join(problems))
    cfg = cfg or load_config()
    manifest = manifest or load_manifest()
    style = film_style(film_root, cfg)
    if style not in manifest.styles:
        raise DesignError(f"the film's style {style!r} isn't in config/models.toml")
    description = description.strip()
    folder = design_dir(film_root, character_id)
    folder.mkdir(parents=True, exist_ok=True)
    data = load_candidates(film_root, character_id) or {
        "schema_version": 1,
        "character": character_id,
        "style": style,
        "candidates": [],
    }
    if data["style"] != style:
        raise DesignError(
            f"{character_id!r} was designed in style {data['style']!r}, but the film is now "
            f"{style!r}; start a new character id"
        )

    skeletons = turnaround(CANVAS)
    uploads = {"@pose": folder / "pose.png", "@mannequin": folder / "mannequin.png"}
    pose_image(list(skeletons), CANVAS).save(uploads["@pose"])
    mannequin_image(list(skeletons), CANVAS).save(uploads["@mannequin"])
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
            width=CANVAS[0],
            height=CANVAS[1],
            fast=fast,
            controls=[POSE, MANNEQUIN],
            filename_prefix=f"design_{character_id}_{cid}",
        )
        out = folder / cid
        record = run_graph(
            film_root,
            "design",
            graph,
            out_dir=out,
            params={"character": character_id, "description": description, "fast": fast},
            seed=cseed,
            style=style,
            names=["sheet.png"],
            uploads=uploads,
            cfg=cfg,
        )
        report = _check(out)
        candidate = Candidate(
            id=cid,
            description=description,
            seed=cseed,
            fast=fast,
            sheet=f"{cid}/sheet.png",
            ok=report.ok,
            problems=report.problems,
            seconds=record.seconds,
            created=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        data["candidates"].append(asdict(candidate))
        _save(folder, data)
        made.append(candidate)
        if on_candidate:
            on_candidate(candidate)
    return made
