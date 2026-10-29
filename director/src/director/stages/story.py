"""Stage 1, story: one schema-forced planning call (thinking on), checked by code, then safety."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from director.context import StageCtx, StageFailed, capabilities
from director.hub import ToolRefused
from director.plans import check_story, plan_json, story_schema
from studio_core import safety

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def brief(ctx: StageCtx, film: dict[str, Any]) -> str:
    cast = [f"- {c['id']}: {c['name']}" for c in film.get("characters", [])]
    places = [f"- {b['id']}: {b.get('name', '')}" for b in film.get("backgrounds", [])]
    parts = [
        f"Story request: {ctx.state.prompt}",
        f"Target length: {ctx.state.target_seconds} seconds.",
        "Existing cast (already built puppets):\n" + ("\n".join(cast) or "- none"),
        "Existing places (already painted):\n" + ("\n".join(places) or "- none"),
    ]
    parts += [f"Owner's note: {n}" for n in ctx.me.revision_notes]
    return "\n\n".join(parts)


def story_text(story: dict[str, Any]) -> str:
    """The whole story as prose for the safety check (the tool takes 4000 characters)."""
    lines = [story["title"] + ". " + story["logline"]]
    for s in story["scenes"]:
        lines.append(
            s["summary"] + " " + " ".join(f"{x['who']} says: {x['text']}" for x in s["lines"])
        )
    return " ".join(lines)[:3900]


async def run(ctx: StageCtx) -> None:
    caps, film = await capabilities(ctx)
    story = await plan_json(
        ctx.deps.chat,
        (PROMPTS / "story.md").read_text(),
        brief(ctx, film),
        story_schema(caps),
        lambda s: check_story(s, ctx.state.target_seconds, safety.blocked_words),
        on_event=ctx.deps.on_event,
        counters=ctx.state.counters,
    )
    story_dir = ctx.film / "story"
    story_dir.mkdir(exist_ok=True)
    outline = {k: story[k] for k in ("title", "logline", "scenes")} | {
        "target_seconds": ctx.state.target_seconds
    }
    for name, data in (
        ("story", story),
        ("outline", outline),
        ("characters", {"characters": story["characters"]}),
        ("places", {"places": story["places"]}),
    ):
        (story_dir / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n")
    ctx.note(f"story planned: {story['title']!r}, {len(story['scenes'])} scenes")

    # The vision model does the judging, and two big models do not share the Mac's memory.
    if ctx.deps.guard:
        ctx.deps.guard.release_llm()
    try:
        verdict = await ctx.tool("check_safety", text=story_text(story))
    except ToolRefused as err:
        raise StageFailed(f"the safety check did not run: {err.message}") from err
    (story_dir / "safety.json").write_text(json.dumps(verdict, indent=2) + "\n")
    if not verdict.get("ok"):
        raise StageFailed(
            "the story did not pass the children's safety check"
            + (" (unsure: the owner should read it)" if verdict.get("needs_human") else "")
            + f": {verdict}"
        )
