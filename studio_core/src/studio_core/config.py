"""Per-machine configuration (config/studio.toml).

Every path to a binary, port or model name comes from here, so the same code runs on the Mac and,
later, on the Windows render node with a different config file. Nothing else should hard-code paths.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "config"


def expand_path(raw: str, base: Path = REPO_ROOT) -> Path:
    """Expand a leading ~ and resolve relative paths against `base` (the repo root)."""
    path = Path(os.path.expanduser(raw))
    return path if path.is_absolute() else base / path


@dataclass(frozen=True)
class StudioConfig:
    data: dict[str, Any]
    source: Path

    def get(self, section: str, key: str, default: Any = None) -> Any:
        return self.data.get(section, {}).get(key, default)

    def path(self, section: str, key: str) -> Path:
        """A path-valued setting, expanded. Raises KeyError if it is not configured."""
        raw = self.data[section][key]
        if not isinstance(raw, str) or not raw:
            raise KeyError(f"[{section}] {key} is not set in {self.source}")
        return expand_path(raw)


def load_config(path: Path | None = None) -> StudioConfig:
    """Load config/studio.toml, falling back to the committed example if it does not exist."""
    if path is None:
        path = CONFIG_DIR / "studio.toml"
        if not path.exists():
            path = CONFIG_DIR / "studio.example.toml"
    with path.open("rb") as fh:
        return StudioConfig(tomllib.load(fh), path)
