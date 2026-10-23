"""Background drafts and their review page (Step 4, task 4.6); `--choose` finishes one.

    uv run scripts/background_review.py                   # the demo: a meadow, 4 drafts
    uv run scripts/background_review.py --film my-film --background meadow \\
        --description "a sunny meadow at the edge of a forest" --n 4 --seed 11
    uv run scripts/background_review.py --choose c2       # finish c2 into the 2880x1080 plate
    uv run scripts/background_review.py --page-only

Makes the film (films/<film>/film.json, storybook style) if it doesn't exist, generates the
missing drafts through `generate_background` (each seed once: re-running with the same
arguments skips what exists, so it is safe to re-run), frees ComfyUI's memory, and writes
backgrounds/<id>/design/review.html: every draft with its seed, timing and ground-band checks,
and the finished plate once one is chosen. Self-contained (images embedded). films/ is
git-ignored.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import sys
from pathlib import Path

from PIL import Image

from studio_core.comfy_runs import free_comfy
from studio_core.config import REPO_ROOT
from studio_core.film import Film
from studio_core.models import load_manifest
from studio_core.place.design import (
    Draft,
    choose_background,
    design_dir,
    generate_background,
    load_plates,
)

DEMO = {
    "film": "step4-demo",
    "background": "meadow",
    "description": "a sunny meadow at the edge of a forest with a small stream",
    "n": 4,
    "seed": 11,
}
PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1"><title>Background drafts</title>
<style>
:root {{ --bg: #faf8f4; --fg: #222; --muted: #666; --card: #fff; --line: #e4e0d8;
        --ok: #1d7a3a; --bad: #b3361d; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #17171a; --fg: #eee; --muted: #aaa; --card: #222226; --line: #34343a;
          --ok: #5fcf83; --bad: #ff8a70; }}
}}
body {{ margin: 0; padding: 24px 16px 48px; background: var(--bg); color: var(--fg);
       font: 15px/1.5 -apple-system, system-ui, sans-serif; }}
main {{ max-width: 1500px; margin: 0 auto; }}
h1 {{ font-size: 22px; margin: 0 0 4px; }} .sub {{ color: var(--muted); margin: 0 0 16px; }}
.card {{ background: var(--card); border: 1px solid var(--line); border-radius: 10px;
        overflow: hidden; margin-bottom: 18px; }}
.card img {{ display: block; width: 100%; height: auto; }}
.meta {{ padding: 10px 14px 14px; }} .ok {{ color: var(--ok); }} .bad {{ color: var(--bad); }}
.nums {{ color: var(--muted); font-size: 13px; }} ul {{ margin: 6px 0 0; padding-left: 18px; }}
.chosen {{ outline: 3px solid var(--ok); }}
</style></head><body><main>
<h1>{background}: background drafts</h1>
<p class=sub>{descriptions} · style <b>{style}</b> · {count} drafts. Look for: a place that
suits the story, and open ground along the bottom where characters will stand. The chosen
draft is finished into the 2880&times;1080 plate (shown first once it exists).</p>
{cards}
</main></body></html>"""


def uri(path: Path, width: int = 1500) -> str:
    im = Image.open(path).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def write_page(film_root: Path, background: str) -> Path:
    data = load_plates(film_root, background)
    if not data:
        raise SystemExit(f"no drafts for {background!r} in {film_root}")
    folder = design_dir(film_root, background)
    cards = []
    for c in sorted(data["candidates"], key=lambda c: "plate" not in c):  # the plate first
        image = folder / c.get("plate", c["draft"])
        problems = "".join(f"<li>{html.escape(p)}</li>" for p in c["problems"])
        verdict = "checks pass" if c["ok"] else "checks found problems"
        what = "finished plate (2880&times;1080)" if "plate" in c else "draft (1536&times;576)"
        chosen = " chosen" if data.get("chosen") == c["id"] else ""
        cards.append(
            f'<div class="card{chosen}"><img src="{uri(image)}" alt="{c["id"]}">'
            f"<div class=meta><b>{c['id']}</b> {what} · <span class={'ok' if c['ok'] else 'bad'}>"
            f"{verdict}</span><div class=nums>seed {c['seed']} · {c.get('seconds', 0):.0f}s · "
            f"{html.escape(c['description'])}</div>"
            f"{f'<ul>{problems}</ul>' if problems else ''}</div></div>"
        )
    descriptions = sorted({c["description"] for c in data["candidates"]})
    page = PAGE.format(
        background=html.escape(background),
        descriptions=" / ".join(f"“{html.escape(d)}”" for d in descriptions),
        style=html.escape(data["style"]),
        count=len(data["candidates"]),
        cards="\n".join(cards),
    )
    out = folder / "review.html"
    out.write_text(page)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--film", default=DEMO["film"])
    ap.add_argument("--background", default=DEMO["background"])
    ap.add_argument("--description", default=DEMO["description"])
    ap.add_argument("--n", type=int, default=DEMO["n"])
    ap.add_argument("--seed", type=int, default=DEMO["seed"])
    ap.add_argument("--choose", help="finish this draft into the plate (e.g. c2)")
    ap.add_argument("--page-only", action="store_true")
    args = ap.parse_args()

    root = REPO_ROOT / "films" / args.film
    try:
        if args.choose:
            plate = choose_background(root, args.background, args.choose)
            print(f"plate: {plate.relative_to(REPO_ROOT)}")
        elif not args.page_only:
            if not (root / "film.json").exists():
                Film.create(root, "storybook", load_manifest())
            done = {
                (c["description"], c["seed"])
                for c in (load_plates(root, args.background) or {}).get("candidates", [])
            }
            todo = [
                s
                for s in range(args.seed, args.seed + args.n)
                if (args.description.strip(), s) not in done
            ]
            print(f"{len(todo)} to make, {args.n - len(todo)} already there", flush=True)

            def report(d: Draft) -> None:
                verdict = "ok" if d.ok else "; ".join(d.problems)
                print(f"  {d.id} seed {d.seed}: {d.seconds:.0f}s, {verdict}", flush=True)

            for s in todo:
                generate_background(
                    root, args.background, args.description, n=1, seed=s, on_draft=report
                )
    finally:
        if not args.page_only:
            free_comfy()
    print(write_page(root, args.background).relative_to(REPO_ROOT))


if __name__ == "__main__":
    sys.exit(main())
