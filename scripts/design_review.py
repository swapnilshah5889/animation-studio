"""Character design candidates and their review page (Step 4 checkpoint 2, task 4.3).

    uv run scripts/design_review.py                       # the demo: Kit the fox, 4 candidates
    uv run scripts/design_review.py --film my-film --character kit \\
        --description "a cheerful young fox with a green scarf" --n 4 --seed 101 [--fast]
    uv run scripts/design_review.py --page-only           # rebuild the page from what exists
    uv run scripts/design_review.py --recheck             # re-run the checks, then the page

Makes the film (films/<film>/film.json, storybook style) if it doesn't exist, generates the
missing candidates through `design_character` (each seed is made once: re-running with the
same arguments skips what exists, so it is safe to re-run), frees ComfyUI's memory, and writes
characters/<id>/design/review.html: every sheet with its seed, timings and automatic checks,
and the skeleton that steered it as a toggleable overlay. The page is self-contained (sheets
embedded as JPEG), so it opens anywhere. films/ is git-ignored.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import sys
from pathlib import Path

from PIL import Image

from studio_core.comfy_runs import free_comfy
from studio_core.config import REPO_ROOT
from studio_core.film import Film
from studio_core.models import load_manifest
from studio_core.puppet.design import (
    Candidate,
    design_character,
    design_dir,
    load_candidates,
    recheck,
)

DEMO = {
    "film": "step4-demo",
    "character": "kit",
    "description": "a cheerful young fox with a green scarf",
    "n": 4,
    "seed": 101,
}

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Design candidates</title>
<style>
:root {{ --bg: #faf8f4; --fg: #222; --muted: #6b6b6b; --card: #fff; --ok: #1d7a3a;
        --bad: #b3361d; --line: #e4e0d8; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #17171a; --fg: #eee; --muted: #a0a0a0; --card: #222226; --ok: #5fcf83;
          --bad: #ff8a70; --line: #34343a; }}
}}
body {{ margin: 0; padding: 24px 16px 48px; background: var(--bg); color: var(--fg);
       font: 15px/1.5 -apple-system, system-ui, sans-serif; }}
main {{ max-width: 1400px; margin: 0 auto; }}
h1 {{ font-size: 22px; margin: 0 0 4px; }}
.sub {{ color: var(--muted); margin: 0 0 16px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 620px), 1fr));
        gap: 20px; }}
.card {{ background: var(--card); border: 1px solid var(--line); border-radius: 10px;
        overflow: hidden; }}
.sheet {{ position: relative; background: #fff; }}
.sheet img {{ display: block; width: 100%; height: auto; }}
.sheet img.pose {{ position: absolute; inset: 0; mix-blend-mode: multiply; opacity: 0;
                  filter: invert(1); transition: opacity .2s; }}
body.show-pose .sheet img.pose {{ opacity: .55; }}
.meta {{ padding: 10px 14px 14px; }}
.meta b {{ font-size: 16px; }}
.ok {{ color: var(--ok); }} .bad {{ color: var(--bad); }}
.meta ul {{ margin: 6px 0 0; padding-left: 18px; }}
.nums {{ color: var(--muted); font-size: 13px; }}
label {{ display: inline-flex; gap: 8px; align-items: center; margin-bottom: 16px;
        cursor: pointer; }}
</style></head>
<body><main>
<h1>{character}: design candidates</h1>
<p class="sub">{description_line} · style <b>{style}</b> · {count} candidates</p>
<p class="sub">Look for: the right look for the film, a head we can paint a face onto, and arms
and legs clear of the body (they become separate puppet parts).</p>
<label><input type="checkbox" onchange="document.body.classList.toggle('show-pose', this.checked)">
Show the skeleton that steered each sheet</label>
<div class="grid">
{cards}
</div>
</main></body></html>
"""

CARD = """<div class="card">
<div class="sheet"><img src="{sheet}" alt="candidate {id}">
<img class="pose" src="{pose}" alt=""></div>
<div class="meta"><b>{id}</b> <span class="{cls}">{verdict}</span>
<div class="nums">seed {seed} · {mode} · {seconds:.0f}s · {figures}</div>
{problems}</div></div>"""


def data_uri(path: Path, fmt: str = "JPEG") -> str:
    buf = io.BytesIO()
    Image.open(path).convert("RGB").save(buf, fmt, **({"quality": 88} if fmt == "JPEG" else {}))
    mime = "image/jpeg" if fmt == "JPEG" else "image/png"
    return f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode()}"


def figure_line(folder: Path, cid: str) -> str:
    checks = json.loads((folder / cid / "checks.json").read_text())
    parts = []
    for f in checks["figures"]:
        if not f["found"]:
            parts.append(f"{f['view']}: missing")
            continue
        parts.append(
            f"{f['view'].replace('_', ' ')}: height {f['height_ratio']:.2f}, "
            f"joints {f['joints_inside']:.0%}"
        )
    return " · ".join(parts)


def write_page(film_root: Path, character: str) -> Path:
    data = load_candidates(film_root, character)
    if not data:
        raise SystemExit(f"no candidates for {character!r} in {film_root}")
    folder = design_dir(film_root, character)
    pose = data_uri(folder / "pose.png", "PNG")
    cards = []
    for c in data["candidates"]:
        problems = "".join(f"<li>{html.escape(p)}</li>" for p in c["problems"])
        cards.append(
            CARD.format(
                sheet=data_uri(folder / c["sheet"]),
                pose=pose,
                id=c["id"],
                cls="ok" if c["ok"] else "bad",
                verdict="checks pass" if c["ok"] else "checks found problems",
                seed=c["seed"],
                mode="fast (8 steps)" if c["fast"] else "normal (25 steps)",
                seconds=c.get("seconds", 0),
                figures=html.escape(figure_line(folder, c["id"])),
                problems=f"<ul>{problems}</ul>" if problems else "",
            )
        )
    descriptions = sorted({c["description"] for c in data["candidates"]})
    page = PAGE.format(
        character=html.escape(character),
        description_line=" / ".join(f"“{html.escape(d)}”" for d in descriptions),
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
    ap.add_argument("--character", default=DEMO["character"])
    ap.add_argument("--description", default=DEMO["description"])
    ap.add_argument("--n", type=int, default=DEMO["n"])
    ap.add_argument("--seed", type=int, default=DEMO["seed"])
    ap.add_argument("--fast", action="store_true", help="Lightning, 8 steps (negatives ignored)")
    ap.add_argument("--style", default="storybook", help="only used when creating the film")
    ap.add_argument("--page-only", action="store_true")
    ap.add_argument("--recheck", action="store_true", help="re-run the checks, no generation")
    args = ap.parse_args()

    root = REPO_ROOT / "films" / args.film
    if args.recheck:
        recheck(root, args.character)
    elif not args.page_only:
        if not (root / "film.json").exists():
            Film.create(root, args.style, load_manifest())
        existing = {
            (c["description"], c["seed"], c["fast"])
            for c in (load_candidates(root, args.character) or {}).get("candidates", [])
        }
        todo = [
            s
            for s in range(args.seed, args.seed + args.n)
            if (args.description.strip(), s, args.fast) not in existing
        ]
        print(f"{len(todo)} to make, {args.n - len(todo)} already there", flush=True)

        def report(c: Candidate) -> None:
            verdict = "ok" if c.ok else "; ".join(c.problems)
            print(f"  {c.id} seed {c.seed}: {c.seconds:.0f}s, {verdict}", flush=True)

        try:
            for s in todo:
                design_character(
                    root, args.character, args.description, n=1, seed=s, fast=args.fast,
                    on_candidate=report,
                )  # fmt: skip
        finally:
            free_comfy()
    page = write_page(root, args.character)
    print(page.relative_to(REPO_ROOT))


if __name__ == "__main__":
    sys.exit(main())
