# ruff: noqa: E501
"""Rebuild cast characters into a scratch film (outside the repo) and print part hashes + a pointer
for the Blender harness. Never touches films/step4-cast.

    uv run --project studio_core python scripts/spikes/overlap_rebuild.py kit [bo pim child robot]
        [--out DIR]   # default ~/ai-studio/scratch/overlap/cast
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import time
from pathlib import Path

from studio_core.config import REPO_ROOT
from studio_core.puppet.build import build_puppet

CAST = REPO_ROOT / "films" / "step4-cast"


def hashes(char_dir: Path) -> dict[str, str]:
    return {
        p.relative_to(char_dir).as_posix(): hashlib.sha1(p.read_bytes()).hexdigest()[:8]
        for p in sorted((char_dir / "parts").rglob("*.png"))
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--old", action="store_true", help="overlap off (the baseline)")
    ap.add_argument("--out", type=Path, default=Path.home() / "ai-studio/scratch/overlap/cast")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    if not (a.out / "film.json").exists():
        shutil.copy(CAST / "film.json", a.out / "film.json")
    for cid in a.ids:
        dest = a.out / "characters" / cid
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(CAST / "characters" / cid, dest, symlinks=True)
        t0 = time.monotonic()
        build_puppet(a.out, cid, overlap=not a.old)
        old, new = hashes(CAST / "characters" / cid), hashes(dest)
        diff = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
        print(
            f"{cid}: rebuilt in {time.monotonic() - t0:.0f} s, {len(diff)} part images differ: {diff}"
        )
