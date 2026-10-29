"""Reuse already-built art: copy characters and places from another film into a new one.

The existing cast (Kit, Bo, Pim, Mia, Bolt) lives in films/step4-cast and the places in other films;
the art stages skip anything that is already built, so importing is how a new film reuses them.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path


def import_assets(films_root: Path, dst_slug: str, spec: str, kind: str) -> list[str]:
    """spec: 'srcfilm:id,id'. kind: 'characters' or 'backgrounds'. Returns the ids copied."""
    src_slug, _, ids = spec.partition(":")
    copied = []
    for item in filter(None, ids.split(",")):
        src = films_root / src_slug / kind / item
        dst = films_root / dst_slug / kind / item
        if not src.is_dir():
            raise FileNotFoundError(f"{src} does not exist")
        if not dst.exists():
            shutil.copytree(src, dst)
        copied.append(item)
        if kind == "characters":
            fj = films_root / dst_slug / "film.json"
            data = json.loads(fj.read_text())
            if item not in data["characters"]:
                data["characters"].append(item)
                fj.write_text(json.dumps(data, indent=2) + "\n")
    return copied


def style_of(films_root: Path, slug: str) -> str | None:
    f = films_root / slug / "film.json"
    return json.loads(f.read_text()).get("style") if f.is_file() else None
