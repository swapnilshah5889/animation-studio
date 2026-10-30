"""Stage 1, story: one schema-forced planning call (thinking on), checked by code, then safety."""

from __future__ import annotations

import contextlib
import json
import shutil
from pathlib import Path
from typing import Any

from director.config import act_checkpoint
from director.context import StageCtx, StageFailed, capabilities
from director.hub import ToolRefused
from director.plans import Roster, check_story, plan_json, story_schema
from director.project_mode import library_roster
from director.state import Approval
from studio_core import safety
from studio_core.store import NotFound

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def roster_of(ctx: StageCtx) -> Roster | None:
    """The project's library and the owner's pins, or None for an old film folder."""
    if ctx.deps.project is None:
        return None
    st = ctx.state
    return library_roster(
        ctx.deps.project, pin_cast=st.pinned_cast, pin_places=st.pinned_places, acts=st.target_acts
    )


def brief(ctx: StageCtx, film: dict[str, Any], roster: Roster | None = None) -> str:
    cast = [f"- {c['id']}: {c['name']}" for c in film.get("characters", [])]
    places = [f"- {b['id']}: {b.get('name', '')}" for b in film.get("backgrounds", [])]
    if roster is not None:
        cast = [f"- {c}" for c in roster.cast]
        places = [f"- {p}" for p in roster.places]
    parts = [
        f"Story request: {ctx.state.prompt}",
        f"Target length: {ctx.state.target_seconds} seconds.",
        "Existing cast (already built puppets):\n" + ("\n".join(cast) or "- none"),
        "Existing places (already painted):\n" + ("\n".join(places) or "- none"),
    ]
    if roster is not None:
        parts.append(
            "Each scene is an ACT of the film: one place, the characters in it, a title, and a "
            "few camera angles that are planned for it later. Reuse the existing cast and places "
            "by their exact ids; invent a new character or place only when the story cannot do "
            "without one." + (f" Write exactly {roster.acts} scenes." if roster.acts else "")
        )
        if roster.pin_cast or roster.pin_places:
            parts.append(
                "The owner allows ONLY these: characters "
                f"{roster.pin_cast or 'any'}, places {roster.pin_places or 'any'}. Invent nothing "
                "else."
            )
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


def reset_acts(ctx: StageCtx) -> None:
    """A new story replaces the acts an earlier one made (the director made them, so it removes
    them; the cast, places and recordings of the project are not touched)."""
    if ctx.deps.project is None or not ctx.state.acts:
        return
    for act_id in ctx.state.acts.values():
        with contextlib.suppress(NotFound):
            ctx.deps.project.remove_act(ctx.slug, act_id)
    ctx.state.acts.clear()
    ctx.state.act_notes.clear()
    for key in ctx.state.act_approvals():
        del ctx.state.approvals[key]
    shutil.rmtree(ctx.film / "story" / "plans", ignore_errors=True)
    (ctx.film / "story" / "shotplan.json").unlink(missing_ok=True)


async def run(ctx: StageCtx) -> None:
    caps, film = await capabilities(ctx)
    roster = roster_of(ctx)
    reset_acts(ctx)
    story = await plan_json(
        ctx.deps.chat,
        (PROMPTS / "story.md").read_text(),
        brief(ctx, film, roster),
        story_schema(caps, roster=roster),
        lambda s: check_story(s, ctx.state.target_seconds, safety.blocked_words, roster),
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
    if roster is not None:  # one approval stop per act, after the story and the cast
        for sc in story["scenes"]:
            ctx.state.approvals.setdefault(act_checkpoint(sc["id"]), Approval())
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
