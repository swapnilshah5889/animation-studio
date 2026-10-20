"""Model manifest (config/models.toml): weight files and the style presets of the switcher.

A *file* is one downloadable weight (URL, sha256, size, destination, license).
A *style* is what a user picks in the switcher: a checkpoint plus VAE, style LoRAs, prompt
fragments, a negative prompt and sampler settings for a normal and a fast (few-step) variant.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from studio_core.config import CONFIG_DIR, StudioConfig

MANIFEST = CONFIG_DIR / "models.toml"


@dataclass(frozen=True)
class ModelFile:
    id: str
    url: str
    sha256: str
    size: int
    dest: str
    license: str
    commercial: str  # "yes" | "no" | "unclear"

    def path(self, models_dir: Path) -> Path:
        return models_dir / self.dest

    @property
    def comfy_name(self) -> str:
        """The name ComfyUI uses: the path inside its model folder (checkpoints/, loras/...)."""
        return self.dest.split("/", 1)[1]

    def is_present(self, models_dir: Path) -> bool:
        """Present = exists with the expected size (sha256 is checked at download time)."""
        p = self.path(models_dir)
        return p.is_file() and p.stat().st_size == self.size


@dataclass(frozen=True)
class Style:
    id: str
    data: dict[str, Any]

    @property
    def label(self) -> str:
        return self.data["label"]

    def settings(self, fast: bool) -> dict[str, Any]:
        """Sampler settings (steps, cfg, sampler, scheduler, optional speed `lora`)."""
        return self.data["fast" if fast else "normal"]

    def file_ids(self, fast: bool = True) -> list[str]:
        """Every file this style needs (the fast variant's speed LoRA included by default)."""
        ids = [self.data["checkpoint"]]
        if vae := self.data.get("vae"):
            ids.append(vae)
        ids += [lora["file"] for lora in self.data.get("loras", [])]
        if fast and (speed := self.data.get("fast", {}).get("lora")):
            ids.append(speed)
        return ids


@dataclass(frozen=True)
class Manifest:
    files: dict[str, ModelFile]
    styles: dict[str, Style]

    def style_files(self, style_id: str, fast: bool = True) -> list[ModelFile]:
        return [self.files[f] for f in self.styles[style_id].file_ids(fast)]

    def style_commercial(self, style_id: str) -> str:
        """'yes' only if every file is commercial-OK; otherwise the weakest status."""
        statuses = {f.commercial for f in self.style_files(style_id)}
        for status in ("no", "unclear"):
            if status in statuses:
                return status
        return "yes"

    def expand(self, ids: list[str]) -> list[ModelFile]:
        """Resolve a mix of style ids and file ids to unique files, in order."""
        out: dict[str, ModelFile] = {}
        for item in ids:
            if item in self.styles:
                out.update({f.id: f for f in self.style_files(item)})
            elif item in self.files:
                out[item] = self.files[item]
            else:
                raise KeyError(f"unknown style or model file: {item}")
        return list(out.values())


def load_manifest(path: Path = MANIFEST) -> Manifest:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    files = {k: ModelFile(id=k, **v) for k, v in data.get("files", {}).items()}
    styles = {k: Style(id=k, data=v) for k, v in data.get("styles", {}).items()}
    manifest = Manifest(files, styles)
    for style in styles.values():  # fail fast on typos in the manifest
        missing = [f for f in style.file_ids() if f not in files]
        if missing:
            raise ValueError(f"style {style.id} references unknown files: {missing}")
    return manifest


def comfy_models_dir(cfg: StudioConfig) -> Path:
    return cfg.path("comfyui", "models_dir")
