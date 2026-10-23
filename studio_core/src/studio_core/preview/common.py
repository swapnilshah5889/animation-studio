"""What both previews share: the film, the reference puppet's height, fonts and ffprobe."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import ImageFont

from studio_core.config import StudioConfig
from studio_core.film import Film
from studio_core.models import load_manifest
from studio_core.rig import world_pose
from studio_core.shot_spec import FILM_SLUG, FilmFolder

Log = Callable[[str], None]  # receives the progress lines; the command lines pass print
REFERENCE = "pip"  # the hand-drawn placeholder puppet every generated puppet is compared with
STYLE = "storybook"  # only used when ensure_film creates the film

Box = tuple[float, float, float, float]


def quiet(_line: str) -> None:
    """The log when the caller doesn't want progress lines."""


def ensure_film(films_root: Path, slug: str, log: Log | None = None) -> FilmFolder:
    """Open the film, creating it (film.json, storybook style) only if the folder is missing.

    A command-line convenience: the preview functions take a film that already exists."""
    root = films_root / slug
    if FILM_SLUG.match(slug) and not root.exists():  # a bad name is refused by FilmFolder.open
        Film.create(root, STYLE, load_manifest())
        (log or quiet)(f"created film {slug} ({STYLE})")
    return FilmFolder.open(films_root, slug)


# --------------------------------------------------------------------------- the puppet's size


def rest_box(view: dict[str, Any], part: str | None = None) -> Box:
    """(left, bottom, right, top) of the rest pose's art, or of one part of it, in art px with
    y up and the root joint at (0, 0). Parts are drawn unrotated at rest."""
    rest = world_pose(view)
    boxes = []
    for name, spec in view["parts"].items():
        if part is not None and name != part:
            continue
        joint = rest[spec["bone"]][0]
        (w, h), (px, py) = spec["size_px"], spec["pivot_px"]
        boxes.append((joint.x - px, joint.y - (h - py), joint.x - px + w, joint.y + py))
    if not boxes:
        raise ValueError(f"no part {part!r}; parts: {sorted(view['parts'])}")
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def matched_scale(view: dict[str, Any], reference: dict[str, Any], ref_scale: float = 1.0) -> float:
    """The scale that makes `view` stand as tall as `reference` at `ref_scale` (within the shot
    schema's 0.2-3)."""
    height = rest_box(view)[3] - rest_box(view)[1]
    ref_height = rest_box(reference)[3] - rest_box(reference)[1]
    return round(min(3.0, max(0.2, ref_scale * ref_height / height)), 3)


# --------------------------------------------------------------------------- outputs


def font(size: int, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Arial (or Menlo for tables) from macOS, else Pillow's built-in font."""
    path = (
        "/System/Library/Fonts/Menlo.ttc"
        if mono
        else "/System/Library/Fonts/Supplemental/Arial.ttf"
    )
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size)


def probe(mp4: Path, cfg: StudioConfig) -> str:
    """One line about a video: size, frame count, length and whether it has sound."""
    result = subprocess.run(
        [str(cfg.path("tools", "ffprobe")), "-v", "error", "-show_entries",
         "stream=codec_type,width,height,nb_frames:format=duration", "-of", "json", str(mp4)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    data = json.loads(result.stdout)
    streams = {s["codec_type"]: s for s in data["streams"]}
    v = streams["video"]
    seconds = float(data["format"]["duration"])
    audio = "with audio" if "audio" in streams else "no audio"
    return f"{v['width']}x{v['height']}, {v['nb_frames']} frames, {seconds:.2f} s, {audio}"
