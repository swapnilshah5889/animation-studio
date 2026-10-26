"""The puppet cut on a varied cast, before Step 4 closes: Kit, Bo, a child, a bird, a robot.

    uv run scripts/cast_review.py               # make what's missing, rebuild all, the sheets
    uv run scripts/cast_review.py --make        # only make the missing characters
    uv run scripts/cast_review.py --rebuild     # rebuild every puppet, then the sheets
    uv run scripts/cast_review.py --sheets      # only the sheets, from the builds there are
    uv run scripts/cast_review.py --only bird   # one character (with any of the above)

The cast lives in films/step4-cast/. Kit and Bo are copied in the first time (design, the
three-quarter redraw, the last build) from step4-demo and step4-proof, so the rigs there stay
as they are. The others are designed from their descriptions: 3 sheets a round, up to 2
rounds; the first sheet whose checks pass is built, and if the built views don't match, the
next one (as the director would, scripts/run_step4_shot.py). A rebuild reuses each
character's three-quarter redraw, so it takes under a minute; making one takes about 20.

Each character gets renders/cast-review/<id>.png: the chosen sheet, then the build's test
poses for both views (build/<view>/poses.png: rest, a wave, a turned head with bent knees),
captioned with what the build measured (limbs, face, consistency). renders/ is git-ignored.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from studio_core.comfy_runs import free_comfy
from studio_core.config import REPO_ROOT
from studio_core.film import Film
from studio_core.models import load_manifest
from studio_core.puppet.build import build_puppet
from studio_core.puppet.design import choose_design, design_character, load_candidates

FILM = REPO_ROOT / "films" / "step4-cast"
OUT = REPO_ROOT / "renders" / "cast-review"
CAST: list[dict[str, str]] = [
    {"id": "kit", "name": "Kit", "copy_from": "step4-demo"},
    {"id": "bo", "name": "Bo", "copy_from": "step4-proof"},
    {
        "id": "child",
        "name": "Mia",
        "description": "a cheerful little girl with curly brown hair in a yellow raincoat and "
        "red boots",
    },
    {
        "id": "bird",
        "name": "Pim",
        "description": "a round little blue bird with a yellow beak, small wings and orange feet",
    },
    {
        "id": "robot",
        "name": "Bolt",
        "description": "a friendly little robot with a boxy silver body, a round head and blue "
        "lights",
    },
]
SHEETS, ROUNDS, BUILDS = 3, 2, 2
WIDTH = 1800  # px, every row of a review sheet


def ensure_film() -> None:
    if not (FILM / "film.json").is_file():
        Film.create(FILM, "storybook", load_manifest())
        print(f"created {FILM.relative_to(REPO_ROOT)}")


def copy_in(member: dict[str, str]) -> bool:
    """Copy a character made elsewhere, once. False if its source film doesn't have it."""
    dst = FILM / "characters" / member["id"]
    if dst.is_dir():
        return True
    src = REPO_ROOT / "films" / member["copy_from"] / "characters" / member["id"]
    if not (src / "design" / "candidates.json").is_file():
        print(f"{member['id']}: not in films/{member['copy_from']}; skipped")
        return False
    shutil.copytree(src, dst)
    print(f"{member['id']}: copied from films/{member['copy_from']}")
    return True


def make(member: dict[str, str]) -> None:
    """Design rounds and builds until a sheet passes its checks and builds consistent views."""
    cid = member["id"]
    data = load_candidates(FILM, cid)
    if data and data.get("chosen") and (FILM / "characters" / cid / "rig.json").is_file():
        return  # made before
    candidates = list(data["candidates"]) if data else []
    tried: set[str] = set()
    for round_no in range(ROUNDS + 1):
        for c in [c for c in candidates if c["ok"] and c["id"] not in tried]:
            if len(tried) == BUILDS:
                print(f"{cid}: no build gave consistent views in {BUILDS} tries; kept the last")
                return
            tried.add(c["id"])
            choose_design(FILM, cid, c["id"])
            t0 = time.monotonic()
            built = build_puppet(FILM, cid, name=member["name"])
            consistency = built.report["consistency"]
            verdict = "match" if consistency["ok"] else f"differ: {consistency['problems']}"
            print(f"{cid}: built from {c['id']} in {time.monotonic() - t0:.0f} s; views {verdict}")
            if consistency["ok"]:
                return
        if len(tried) >= BUILDS:
            print(f"{cid}: no build gave consistent views in {BUILDS} tries; kept the last")
            return
        if round_no == ROUNDS:
            break
        t0 = time.monotonic()
        made = design_character(FILM, cid, member["description"], n=SHEETS)
        print(f"{cid}: round {round_no + 1}, {len(made)} sheets in {time.monotonic() - t0:.0f} s: "
              + ", ".join(f"{m.id} {'ok' if m.ok else 'failed'}" for m in made))  # fmt: skip
        candidates += [{"id": m.id, "ok": m.ok} for m in made]
    print(f"{cid}: no sheet passed its checks in {ROUNDS} rounds")


def rebuild(member: dict[str, str]) -> None:
    cid = member["id"]
    if not (FILM / "characters" / cid / "rig.json").is_file():
        print(f"{cid}: not built yet; run --make")
        return
    t0 = time.monotonic()
    built = build_puppet(FILM, cid, name=member["name"])
    print(f"{cid}: rebuilt in {time.monotonic() - t0:.0f} s")
    for line in notes(built.report):
        print(f"  {line}")


def notes(report: dict[str, Any]) -> list[str]:
    """What the build measured, one line per view and one for the views together."""
    lines = []
    for view, r in report["views"].items():
        loose = [name for name, limb in r.get("limbs", {}).items() if not limb.get("ok", True)]
        face = r.get("face", {})
        lines.append(
            f"{view}: limbs {'ok' if r.get('limbs_ok') else 'loose: ' + ', '.join(loose)}; "
            f"nose {'found' if face.get('nose_found') else 'not found'}, "
            f"eyes {face.get('eyes_found')}, {face.get('marks_painted_over')} marks painted; "
            f"hidden {sorted(r.get('hidden_limbs', {})) or 'none'}"
        )
    c = report.get("consistency", {})
    lines.append(
        f"views {'match' if c.get('ok') else 'differ: ' + '; '.join(c.get('problems', []))}"
    )
    return lines


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("/System/Library/Fonts/Helvetica.ttc", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def sheet(member: dict[str, str]) -> Path | None:
    """renders/cast-review/<id>.png: the chosen design, both views' poses, the build's notes."""
    cid = member["id"]
    folder = FILM / "characters" / cid
    report_file = folder / "build" / "report.json"
    if not report_file.is_file():
        return None
    report = json.loads(report_file.read_text())
    data = load_candidates(FILM, cid) or {}
    chosen = data.get("chosen")
    rows: list[tuple[str, Image.Image]] = []
    design = folder / "design" / f"{chosen}" / "sheet.png"
    if design.is_file():
        rows.append((f"design {chosen} (front | three-quarter as drawn)", Image.open(design)))
    turned = folder / "design" / f"{chosen}" / "three_quarter" / "sheet.png"
    if turned.is_file():
        rows.append(("the sheet after the three-quarter redraw (what is cut)", Image.open(turned)))
    for view in ("front", "three_quarter"):
        poses = folder / "build" / view / "poses.png"
        if poses.is_file():
            label = f"{view} poses: rest, a wave, a turned head with bent knees"
            rows.append((label, Image.open(poses)))
    font, small = _font(26), _font(20)
    text = [
        f"{member['name']} ({cid}): {member.get('description') or 'from ' + member['copy_from']}"
    ]
    text += notes(report)
    head_h = 16 + 34 + 28 * (len(text) - 1) + 12
    scaled = []
    for label, img in rows:
        img = img.convert("RGB")
        img = img.resize((WIDTH, round(img.height * WIDTH / img.width)), Image.Resampling.LANCZOS)
        scaled.append((label, img))
    height = head_h + sum(30 + img.height + 10 for _, img in scaled)
    out = Image.new("RGB", (WIDTH, height), (250, 248, 244))
    draw = ImageDraw.Draw(out)
    y = 16
    draw.text((16, y), text[0], fill=(20, 20, 20), font=font)
    y += 34
    for line in text[1:]:
        draw.text((16, y), line, fill=(90, 90, 90), font=small)
        y += 28
    y = head_h
    for label, img in scaled:
        draw.text((16, y + 4), label, fill=(60, 60, 60), font=small)
        y += 30
        out.paste(img, (0, y))
        y += img.height + 10
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{cid}.png"
    out.save(path)
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--make", action="store_true", help="only make the missing characters")
    ap.add_argument("--rebuild", action="store_true", help="rebuild every puppet, then sheets")
    ap.add_argument("--sheets", action="store_true", help="only the review sheets")
    ap.add_argument("--only", help="one character id")
    args = ap.parse_args()
    cast = [m for m in CAST if not args.only or m["id"] == args.only]
    if not cast:
        sys.exit(f"no character {args.only!r}; cast: {', '.join(m['id'] for m in CAST)}")
    everything = not (args.make or args.rebuild or args.sheets)
    ensure_film()
    present = [m for m in cast if "copy_from" not in m or copy_in(m)]
    if args.make or everything:
        for m in present:
            if "description" in m:
                make(m)
    if args.rebuild or everything:
        for m in present:
            rebuild(m)
    free_comfy()
    for m in present:
        path = sheet(m)
        if path:
            print(f"sheet: {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
