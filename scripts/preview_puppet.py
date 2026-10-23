"""Owner checkpoint 3 (Step 4, task 4.4): a built puppet waving, blinking and talking next to Pip.

    uv run scripts/preview_puppet.py                          # Kit in films/step4-demo
    uv run scripts/preview_puppet.py --film my-film --character fox --size 960x540
    uv run scripts/preview_puppet.py --view three_quarter     # the same shot in the 3/4 view

A command line over studio_core.preview.puppet (the timeline, the views and the outputs are
explained there). On top of the library it creates the film if it is missing (storybook style)
and casts the placeholder voice (c13) for a character that has none.

Outputs (renders/ is git-ignored, and every run overwrites them; the front view keeps its
folder name, other views add theirs, e.g. <film>-<character>-three_quarter):
    renders/puppet-preview/<film>-<character>/puppet_preview.mp4
    renders/puppet-preview/<film>-<character>/contact_sheet.png
The shot stays in the film (shots/s00_sh01/: shot.json, scene.sif to open in Synfig Studio,
shot.mp4). Its frames are deleted.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from studio_core.audio.voices import VoiceError
from studio_core.config import REPO_ROOT, load_config
from studio_core.preview import PreviewError, ensure_film
from studio_core.preview.common import probe
from studio_core.preview.puppet import LINE, VIEWS, output_name, preview_puppet
from studio_core.rig import RigError
from studio_core.shot_spec import SpecError


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--film", default="step4-demo")
    ap.add_argument("--character", default="kit")
    ap.add_argument(
        "--view",
        choices=VIEWS,
        default="front",
        help="the rig view to place; three_quarter faces Pip (default: front)",
    )
    ap.add_argument("--out", type=Path, help="output folder (default: renders/puppet-preview/)")
    ap.add_argument("--background", default="meadow", help="a background of the film")
    ap.add_argument("--line", default=LINE, help="what the puppet says")
    ap.add_argument("--scale", type=float, help="the puppet's scale (default: Pip's height)")
    ap.add_argument("--size", help="render size WxH (default: 1920x1080)")
    args = ap.parse_args()
    size = tuple(int(v) for v in args.size.split("x")) if args.size else None
    folder = output_name(args.film, args.character, args.view)
    out = args.out or REPO_ROOT / "renders" / "puppet-preview" / folder
    cfg = load_config()

    try:
        film = ensure_film(cfg.path("paths", "films"), args.film, log=print)
        result = preview_puppet(
            film,
            args.character,
            view=args.view,
            background=args.background,
            line=args.line,
            scale=args.scale,
            size=size,  # type: ignore[arg-type]
            out=out,
            cast_placeholder=True,
            cfg=cfg,
            log=print,
        )
    except PreviewError as e:
        sys.exit(str(e))
    except (SpecError, VoiceError, RigError) as e:
        sys.exit(f"refused: {e}")
    print(f"rendered in {result.seconds:.0f} s: {probe(result.video, cfg)}")
    print(f"key frames: {', '.join(f'{label} {f}' for label, f in result.key_frames)}")
    print(f"video: {result.video}")
    print(f"contact sheet: {result.contact_sheet}")
    print(f"shot: {result.shot_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
