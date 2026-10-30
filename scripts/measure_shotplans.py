"""Measure the director's shot-planning taste: plan 5 fixed stories with the real model, count
taste-rule violations (director/taste.py) in the first answer and in the final plan.

    uv run scripts/measure_shotplans.py [--only balloon,pond] [--out results.json]

Uses the real qwen3:14b through Ollama (a minute or two per story) and no other tool, so no film
is needed. It unloads the model when done (keep_alive 0). Not a test: tests use a fake model.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))

from director_stories import STORIES  # noqa: E402

from director.chat import OllamaChat  # noqa: E402
from director.plans import Capabilities, PlanError  # noqa: E402
from director.stages.shots import plan_shots  # noqa: E402
from director.state import Counters  # noqa: E402
from director.taste import check_taste  # noqa: E402
from studio_core.face import EXPRESSIONS  # noqa: E402
from studio_core.ollama import Ollama  # noqa: E402
from studio_core.scene import CAMERA_MOVES  # noqa: E402
from synfig_mcp.server import _motion_help  # noqa: E402


def line_durations(story: dict) -> list[dict]:
    """Stand-ins for recorded lines: about 0.4 s a word."""
    return [
        {
            "scene": s["id"],
            "text": ln["text"],
            "duration_s": round(0.4 * len(ln["text"].split()), 2),
        }
        for s in story["scenes"]
        for ln in s["lines"]
    ]


async def one(name: str, story: dict, chat: OllamaChat, caps: Capabilities) -> dict:
    attempts: list[dict] = []

    def on_event(e: dict) -> None:
        if e.get("kind") == "model" and "plan_attempt" in e:
            attempts.append(json.loads(e["content"]))

    counters = Counters()
    t0 = time.monotonic()
    final, error = None, None
    try:
        final = await plan_shots(
            chat,
            story,
            caps,
            15,
            line_durations(story),
            notes=[],
            on_event=on_event,
            counters=counters,
        )
    except PlanError as err:
        error = str(err)
        final = attempts[-1] if attempts else None
    rules = lambda plan: [v.rule for v in check_taste(plan, story)] if plan else []  # noqa: E731
    return {
        "story": name,
        "seconds": round(time.monotonic() - t0, 1),
        "model_calls": counters.model_calls,
        "first": rules(attempts[0] if attempts else None),
        "final": rules(final),
        "error": error,
        "plan": final,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    caps = Capabilities(
        motions=list(_motion_help()),
        expressions=list(EXPRESSIONS),
        camera_moves=list(CAMERA_MOVES),
        moods=[],
    )
    ollama = Ollama(timeout=1800)  # a busy Mac (renders) can make one call very slow
    chat = OllamaChat(ollama)
    names = args.only.split(",") if args.only else list(STORIES)
    results = []
    try:
        for n in names:
            r = await one(n, STORIES[n], chat, caps)
            results.append(r)
            print(
                f"{n}: {r['seconds']} s, {r['model_calls']} calls, first={len(r['first'])} "
                f"final={len(r['final'])} {Counter(r['final']).most_common()} "
                f"{'ERROR ' + r['error'] if r['error'] else ''}",
                flush=True,
            )
    finally:
        ollama.unload("qwen3:14b")
    for k in ("first", "final"):
        c = Counter(x for r in results for x in r[k])
        print(f"TOTAL {k}: {sum(c.values())}  {dict(c)}")
    print(f"TOTAL seconds: {round(sum(r['seconds'] for r in results))}")
    if args.out:
        args.out.write_text(json.dumps(results, indent=1))


asyncio.run(main())
