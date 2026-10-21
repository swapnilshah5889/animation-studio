"""Film project state in films/<slug>/film.json. For now: the film's style and its lock.

A film picks a style (config/models.toml [styles]) when it is created. Once the film has any
character, the style is **locked**: generating new art in another style would no longer match
the existing puppets (D-025). film.json follows schemas/film.schema.json and is validated on
every save.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from studio_core.models import Manifest
from studio_core.schema import validate

STAGES = ("story", "characters", "backgrounds", "audio", "shots", "edit")


class StyleLockedError(RuntimeError):
    """Raised when changing the style of a film that already has characters."""


@dataclass
class Film:
    root: Path  # films/<slug>/
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def file(self) -> Path:
        return self.root / "film.json"

    @classmethod
    def load(cls, root: Path) -> Film:
        return cls(root, json.loads((root / "film.json").read_text()))

    @classmethod
    def create(cls, root: Path, style_id: str, manifest: Manifest) -> Film:
        if (root / "film.json").exists():
            raise FileExistsError(root / "film.json")
        film = cls(
            root,
            {
                "schema_version": 1,
                "slug": root.name,
                "characters": [],
                "stages": dict.fromkeys(STAGES, "pending"),
            },
        )
        film.set_style(style_id, manifest)
        return film

    @property
    def style(self) -> str | None:
        return self.data.get("style")

    @property
    def style_locked(self) -> bool:
        """Locked once any character exists, in film.json or as a characters/<id>/ folder."""
        chars_dir = self.root / "characters"
        has_folder = chars_dir.is_dir() and any(p.is_dir() for p in chars_dir.iterdir())
        return bool(self.data.get("characters")) or has_folder

    def set_style(self, style_id: str, manifest: Manifest) -> None:
        if style_id not in manifest.styles:
            raise KeyError(f"unknown style {style_id!r}; known: {sorted(manifest.styles)}")
        if self.style_locked and style_id != self.style:
            raise StyleLockedError(
                f"film {self.root.name!r} already has characters in style {self.style!r}; "
                f"switching to {style_id!r} would break consistency. Start a new film instead."
            )
        self.data["style"] = style_id
        # Recorded so a publishing check can refuse films made with non-commercial models.
        self.data["style_commercial"] = manifest.style_commercial(style_id)
        self.save()

    def add_character(self, character_id: str) -> None:
        if not self.style:
            raise ValueError("pick a style before creating characters")
        if character_id not in self.data.setdefault("characters", []):
            self.data["characters"].append(character_id)
        self.save()

    def save(self) -> None:
        issues = validate("film", self.data)
        if issues:
            raise ValueError("invalid film.json: " + "; ".join(map(str, issues)))
        self.root.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(self.data, indent=2) + "\n")
