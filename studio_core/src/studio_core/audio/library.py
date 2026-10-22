"""The sound-effect library: <sfx_library>/manifest.json (schemas/sfx_library.schema.json).

Only CC0 sounds are allowed (D-036), each with its source and the URL its license was checked
at. Shot specs store a chosen sound's id (sfx[].sound); this module resolves ids to files.
Search by meaning (CLAP + Qdrant) comes in task 3.5.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from studio_core.config import load_config
from studio_core.schema import validate


class LibraryError(ValueError):
    pass


@dataclass(frozen=True)
class SoundLibrary:
    root: Path
    sounds: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    def path(self, sound_id: str) -> Path:
        if sound_id not in self.sounds:
            raise LibraryError(f"no sound {sound_id!r} in the library ({len(self.sounds)} sounds)")
        return self.root / self.sounds[sound_id]["file"]


def load_library(root: Path | None = None) -> SoundLibrary:
    """The library at `root` (default: config [paths] sfx_library). No manifest yet = empty."""
    root = root or load_config().path("paths", "sfx_library")
    manifest = root / "manifest.json"
    if not manifest.is_file():
        return SoundLibrary(root)
    data = json.loads(manifest.read_text())
    issues = validate("sfx_library", data)
    if issues:
        raise LibraryError(f"{manifest}: " + "; ".join(map(str, issues)))
    return SoundLibrary(root, {s["id"]: s for s in data["sounds"]})
