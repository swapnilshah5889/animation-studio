"""Stage 5 for a film of a project (D-094): the shots stage, one act at a time.

A scene of the story is an act. For each act, in order:

  1. plan its shots (one schema-forced call for this act alone; the taste rules see the acts
     before it, so the film's variety, peak and ending are judged on the film so far);
  2. make the act in the project (`add_act`, once), and drop shots it no longer plans;
  3. build every planned shot with the same scaffold and conversation as an old film folder, but
     the shots are saved as camera angles of the act;
  4. write the act's beats and render the act (`render_act`; a no-op when its cache key is fresh);
  5. stop for the owner's approval of the act (`act_<scene>`) unless the run is automatic.

Resuming is the same walk: every step is idempotent, so a finished act costs a few tool calls.
Planning the next act waits for the previous act's approval, so the owner's notes reach it.
"""

from __future__ import annotations

import json
from typing import Any

from director.checks import (
    act_plan_of,
    act_target,
    lines_of,
    merged_plan,
    one_scene_story,
    read_json,
    shot_missing,
    story_of,
)
from director.config import act_checkpoint
from director.context import StageCtx, StageFailed, capabilities
from director.stages.shots import build_shot, gate, plan_shots
from studio_core.store import NotFound


async def plan_act(
    ctx: StageCtx,
    story: dict[str, Any],
    scene: dict[str, Any],
    prior: list[dict[str, Any]],
    final: bool,
) -> dict[str, Any]:
    caps, _ = await capabilities(ctx)
    notes = [*ctx.me.revision_notes, *ctx.state.act_notes.get(scene["id"], [])]
    plan = await plan_shots(
        ctx.deps.chat,
        one_scene_story(story, scene["id"]),
        caps,
        act_target(ctx.film, scene),
        [x for x in lines_of(ctx.film) if x["scene"] == scene["id"]],
        notes=notes,
        on_event=ctx.deps.on_event,
        counters=ctx.state.counters,
        prior=prior,
        final=final,
        taste_story=story,
    )
    path = ctx.film / "story" / "plans" / f"{scene['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2) + "\n")
    (ctx.film / "story" / "shotplan.json").write_text(
        json.dumps(merged_plan(ctx.film, story), indent=2) + "\n"
    )
    ctx.note(
        f"act {scene['id']} planned: {len(plan['shots'])} shots, "
        f"{sum(s['seconds'] for s in plan['shots'])} s"
    )
    return plan


async def ensure_act(ctx: StageCtx, scene: dict[str, Any]) -> str:
    """The act of this scene in the project (made once, remembered in the director's state)."""
    project = ctx.deps.project
    assert project is not None
    act_id = ctx.state.acts.get(scene["id"])
    if act_id:
        try:
            project.get_act(ctx.slug, act_id)
            return act_id
        except NotFound:
            pass  # removed outside the director: make it again
    made = await ctx.tool(
        "add_act",
        title=scene["title"],
        background=scene["place"],
        cast=scene["characters"],
        beats=[scene["summary"][:200]],
    )
    ctx.state.acts[scene["id"]] = made["act_id"]
    ctx.save()
    return made["act_id"]


async def drop_unplanned_shots(ctx: StageCtx, act_id: str, plan: dict[str, Any]) -> None:
    """A re-planned act may have fewer or other shots: the old ones leave the act (and the cut)."""
    project = ctx.deps.project
    assert project is not None
    keep = {s["id"] for s in plan["shots"]}
    for doc in project.list_shots(ctx.slug, act_id):
        if doc["spec"]["id"] not in keep:
            await ctx.tool("remove_shot", act=act_id, shot_id=doc["spec"]["id"])


async def run(ctx: StageCtx) -> None:
    story = story_of(ctx.film)
    assert story is not None
    scene_place = {s["id"]: s["place"] for s in story["scenes"]}
    music = read_json(ctx.film / "director" / "music.json") or {}
    scenes = story["scenes"]
    prior: list[dict[str, Any]] = []
    first = True
    for i, scene in enumerate(scenes):
        sid = scene["id"]
        plan = act_plan_of(ctx.film, sid)
        if plan is None:
            plan = await plan_act(ctx, story, scene, prior, final=i == len(scenes) - 1)
        prior = [*prior, *plan["shots"]]
        act_id = await ensure_act(ctx, scene)
        await drop_unplanned_shots(ctx, act_id, plan)
        for planned in plan["shots"]:
            if shot_missing(ctx.film, planned) is not None:
                ctx.me.per_item[planned["id"]] = "building"
                ctx.save()
                await build_shot(ctx, planned, scene_place, music, act_id)
            ctx.me.per_item[planned["id"]] = "rendered"
            ctx.save()
            if first:
                first = False
                gate(ctx)  # the look-and-feel check before the other shots render
        await tool_edit_act(ctx, act_id, plan)
        rendered = await ctx.tool("render_act", act=act_id, quality=ctx.deps.quality)
        if rendered.get("rendered") is False:
            ctx.note(f"act {sid}: up to date, not rendered again")
        ctx.me.per_item[act_checkpoint(sid)] = rendered.get("video_path") or "rendered"
        ctx.save()
        gate(ctx, act_checkpoint(sid))
    if first:
        raise StageFailed("the story has no acts to build")


async def tool_edit_act(ctx: StageCtx, act_id: str, plan: dict[str, Any]) -> None:
    """The act's beats are the planned shots' beats (story, not picture: no re-render)."""
    await ctx.tool("edit_act", act=act_id, beats=[s["beat"][:200] for s in plan["shots"]][:20])
