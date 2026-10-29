"""The edit spec and its timeline math. Pure and deterministic: the LLM says which shots in which
order and how they join, code decides every frame count and overlap.

All lengths are whole frames (`frames`), so a crossfade of 0.5 s at 24 fps is 12 frames and the
film is exactly `total_frames(spec)` long. A crossfade overlaps the end of one clip with the start
of the next, so it shortens the film by its length.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from studio_core.schema import validate

SHOT_ID = re.compile(r"^s[0-9]{2}_sh[0-9]{2}$")
TRANSITIONS = ("cut", "crossfade")
DEFAULT_CROSSFADE_S = 0.5
FPS = 24
FINAL_SIZE = (1920, 1080)


class EditError(ValueError):
    """An edit that cannot be built; the message says what to change."""


def frames(seconds: float, fps: int = FPS) -> int:
    return round(seconds * fps)


def edit_dir(film_root: Path) -> Path:
    return film_root / "edit"


def spec_file(film_root: Path) -> Path:
    return edit_dir(film_root) / "edit.json"


def shot_video(film_root: Path, shot_id: str) -> Path:
    if not SHOT_ID.match(shot_id):
        raise EditError(f"{shot_id!r} is not a shot id (like 's01_sh02')")
    return film_root / "shots" / shot_id / "shot.mp4"


def overlap_frames(clip: dict[str, Any], fps: int) -> int:
    """Frames this clip overlaps the previous one (0 for a cut)."""
    t = clip.get("transition_in") or {"type": "cut"}
    if t["type"] != "crossfade":
        return 0
    return frames(t.get("duration_s", DEFAULT_CROSSFADE_S), fps)


@dataclass(frozen=True)
class Placed:
    index: int
    start: int  # first frame on the film's timeline
    length: int
    overlap_in: int  # frames shared with the previous clip


def layout(spec: dict[str, Any]) -> list[Placed]:
    """Where every clip starts on the timeline. Refuses crossfades that do not fit."""
    fps = spec["fps"]
    placed: list[Placed] = []
    start = 0
    for i, clip in enumerate(spec["clips"]):
        length = frames(clip["duration_s"], fps)
        if length < 1:
            raise EditError(f"clip {i + 1} is shorter than one frame")
        overlap = overlap_frames(clip, fps) if i else 0
        if i:
            prev = placed[-1]
            if overlap > min(prev.length, length) // 2:
                raise EditError(
                    f"the crossfade into clip {i + 1} ({overlap} frames) is longer than half of "
                    f"the shorter clip around it; use a shorter crossfade or a cut"
                )
            start = prev.start + prev.length - overlap
        placed.append(Placed(i, start, length, overlap))
    return placed


def total_frames(spec: dict[str, Any]) -> int:
    last = layout(spec)[-1]
    return last.start + last.length


def total_seconds(spec: dict[str, Any]) -> float:
    return total_frames(spec) / spec["fps"]


def build_spec(
    clips: list[dict[str, Any]], *, fps: int = FPS, size: tuple[int, int] = FINAL_SIZE
) -> dict[str, Any]:
    spec = {"schema_version": 1, "fps": fps, "width": size[0], "height": size[1], "clips": clips}
    check(spec)
    return spec


def check(spec: dict[str, Any]) -> None:
    issues = validate("edit", spec)
    if issues:
        raise EditError("invalid edit: " + "; ".join(map(str, issues)))
    layout(spec)


def load(film_root: Path) -> dict[str, Any] | None:
    f = spec_file(film_root)
    return json.loads(f.read_text()) if f.is_file() else None


def save(film_root: Path, spec: dict[str, Any]) -> Path:
    check(spec)
    f = spec_file(film_root)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(spec, indent=2) + "\n")
    return f
