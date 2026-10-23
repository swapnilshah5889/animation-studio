"""Owner checkpoint 4 (Step 4, task 4.7): a generated place, split into layers, during a slow pan.

    uv run scripts/preview_background.py                         # the meadow, a 6 s pan right
    uv run scripts/preview_background.py --character kit        # with Kit standing on the ground
    uv run scripts/preview_background.py --background lake --move slow_pan_left --seconds 8
    uv run scripts/preview_background.py --move pull_out --zoom 0.8   # zooming out shows the edges

A command line over studio_core.preview.background (the test shot and the two-part hole check
are explained there). On top of the library it creates the film if it is missing. Exit status
0 = no hole and no layer edge with art on it entering the frame; 1 = a hole, an edge, or a
refusal.

Outputs (renders/ is git-ignored; every run overwrites them; `--out` picks another folder):
    renders/background-preview/<film>-<background>/background_preview.mp4
    renders/background-preview/<film>-<background>/contact_sheet.png
The shot stays in the film (shots/s00_sh02/: shot.json, scene.sif to open in Synfig Studio,
shot.mp4). Its frames are deleted.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from studio_core.config import REPO_ROOT, load_config
from studio_core.preview import PreviewError, ensure_film
from studio_core.preview.background import PIXEL_TOL, preview_background
from studio_core.preview.common import probe
from studio_core.rig import RigError
from studio_core.scene import CAMERA_MOVES, SceneError
from studio_core.shot_spec import SpecError


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--film", default="step4-demo")
    ap.add_argument("--background", default="meadow", help="a background of the film")
    ap.add_argument("--character", help="a character of the film, standing on the ground")
    ap.add_argument("--scale", type=float, help="the character's scale (default: Pip's height)")
    ap.add_argument("--move", choices=CAMERA_MOVES, default="slow_pan_right")
    ap.add_argument("--zoom", type=float, help="the camera's starting zoom (0.5-3, default 1)")
    ap.add_argument("--seconds", type=float, default=6.0, help="shot (= camera move) length")
    ap.add_argument("--every", type=int, default=4, help="hole-check every Nth frame")
    ap.add_argument("--tolerance", type=int, default=PIXEL_TOL, help="sentinel match, per channel")
    ap.add_argument("--size", help="render size WxH (default: 1920x1080)")
    ap.add_argument("--out", type=Path, help="output folder (default: renders/background-preview/)")
    args = ap.parse_args()
    size = tuple(int(v) for v in args.size.split("x")) if args.size else None
    out = args.out or (
        REPO_ROOT / "renders" / "background-preview" / f"{args.film}-{args.background}"
    )
    cfg = load_config()

    try:
        film = ensure_film(cfg.path("paths", "films"), args.film, log=print)
        result = preview_background(
            film,
            args.background,
            character=args.character,
            scale=args.scale,
            move=args.move,
            zoom=args.zoom,
            seconds=args.seconds,
            every=args.every,
            tolerance=args.tolerance,
            size=size,  # type: ignore[arg-type]
            out=out,
            cfg=cfg,
            log=print,
        )
    except PreviewError as e:
        sys.exit(str(e))
    except (SpecError, SceneError, RigError) as e:
        sys.exit(f"refused: {e}")
    print(*result.layer_table, sep="\n")
    print(*result.verdicts, sep="\n")
    print(f"rendered and checked in {result.seconds:.0f} s: {probe(result.video, cfg)}")
    print(f"video: {result.video}")
    print(f"contact sheet: {result.contact_sheet}")
    print(f"shot: {result.shot_dir}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
