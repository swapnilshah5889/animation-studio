"""Assemble a small demo film project from the test fixtures, and optionally render its shot.

    uv run scripts/make_demo_film.py                      # films/step2-demo/ (no render)
    uv run scripts/make_demo_film.py --render             # + shots/s01_sh01/shot.mp4, 1920x1080
    uv run scripts/make_demo_film.py --render --size 640x360   # quick preview

The folder follows the film project layout (docs/ARCHITECTURE.md): Pip's rig and parts, the
meadow background, dialogue line l001 (its WAV and Rhubarb cues) and the 10-second shot spec
s01_sh01 (tests/fixtures/schemas/shot_s01_sh01.json). films/ is git-ignored. Safe to re-run:
the inputs are copied fresh each time; renders are overwritten.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time

from studio_core.config import REPO_ROOT
from studio_core.shot import render_shot

FIXTURES = REPO_ROOT / "tests" / "fixtures"
FILM = REPO_ROOT / "films" / "step2-demo"
SHOT = "s01_sh01"
COPIES = {
    FIXTURES / "characters" / "pip": FILM / "characters" / "pip",
    FIXTURES / "backgrounds" / "meadow": FILM / "backgrounds" / "meadow",
    FIXTURES / "audio" / "pip_line_01.wav": FILM / "audio" / "dialogue" / "l001.wav",
    FIXTURES / "audio" / "pip_line_01.rhubarb.json": FILM / "audio" / "lipsync" / "l001.json",
    FIXTURES / "schemas" / "shot_s01_sh01.json": FILM / "shots" / SHOT / "shot.json",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--render", action="store_true", help="render the shot to shot.mp4")
    ap.add_argument("--size", default=None, help="render size WxH (default: 1920x1080)")
    args = ap.parse_args()

    for src, dst in COPIES.items():
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    print(f"film folder ready: {FILM.relative_to(REPO_ROOT)}")
    if not args.render:
        return 0

    size = tuple(int(v) for v in args.size.split("x")) if args.size else None
    t0 = time.monotonic()
    out = render_shot(FILM, SHOT, size=size)  # type: ignore[arg-type]
    print(f"rendered {len(out.frames)} frames in {time.monotonic() - t0:.0f} s")
    print(f"scene: {out.sif.relative_to(REPO_ROOT)}")
    print(f"video: {out.mp4.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
