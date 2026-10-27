"""Task 4B.1: render every motion of every character at its extreme poses and check the frames.

    uv run scripts/pose_sweep.py                          # all characters of films/step4-cast
    uv run scripts/pose_sweep.py --only kit --motion wave
    uv run scripts/pose_sweep.py --film films/step4-cast --only bo --view three_quarter

For each character, view and motion (studio_core.motions) it renders the frames where a bone
reaches its minimum or maximum, on a magenta probe backdrop (Synfig, CPU only), and fails on
holes, seams and detached parts (studio_core.preview.sweep has the definitions and thresholds).
Exit status 1 when any defect is found, so it can gate a change.

Outputs (renders/ is git-ignored; every run overwrites them):
    renders/pose-sweep/report.json              defects per character, view, motion and frame
    renders/pose-sweep/<character>.png          a labelled contact sheet per character
Nothing is written into the film: the characters are linked into a scratch film.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from studio_core.config import REPO_ROOT, load_config
from studio_core.preview.sweep import (
    VIEWS,
    contact_sheet,
    scratch_film,
    sweep_character,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--film", type=Path, default=REPO_ROOT / "films" / "step4-cast")
    ap.add_argument("--only", action="append", help="a character id (repeatable; default: all)")
    ap.add_argument("--view", action="append", choices=VIEWS, help="default: every view")
    ap.add_argument("--motion", action="append", help="a motion, e.g. wave or wave[left]")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "renders" / "pose-sweep")
    args = ap.parse_args()

    chars_dir = args.film / "characters"
    available = sorted(p.name for p in chars_dir.iterdir() if (p / "rig.json").is_file())
    chosen = args.only or available
    unknown = [c for c in chosen if c not in available]
    if unknown:
        sys.exit(f"no such character: {', '.join(unknown)} (characters: {', '.join(available)})")

    cfg = load_config()
    film = scratch_film(args.out / "work", {c: chars_dir / c for c in chosen})
    t0 = time.monotonic()
    reports = []
    for cid in chosen:
        report = sweep_character(
            film,
            cid,
            views=args.view or VIEWS,
            only_motions=args.motion,
            keep_images=True,
            cfg=cfg,
            log=print,
        )
        sheet = contact_sheet(report, args.out / f"{cid}.png")
        print(f"{cid}: {len(report.defects)} defects in {report.seconds:.0f} s; sheet {sheet}")
        reports.append(report)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(
        json.dumps({"film": str(args.film), "characters": [r.to_json() for r in reports]}, indent=1)
    )

    print("\ncharacter  view           motion           frames holes seams detached")
    failed = 0
    for r in reports:
        for key, c in r.counts().items():
            view, motion = key.split(" ", 1)
            print(
                f"{r.character:<10} {view:<14} {motion:<16} {c['frames']:>6} "
                f"{c['hole']:>5} {c['seam']:>5} {c['detached']:>8}"
            )
        for d in r.defects:
            failed += 1
            print("FAIL", d.message())
    print(f"\n{failed} defects; {time.monotonic() - t0:.0f} s; report {args.out / 'report.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
