"""Stages 2 and 3, characters and backgrounds: code-driven (owner's answer 4).

The art tools take minutes each and the 24 GB Mac holds one big model at a time, so the order of
calls is fixed here and only the *choice between candidates* is a rule (the first that passes its
own checks; another round if none does), as scripts/run_step4_shot.py did. A text-only model has no
signal beyond those flags, and a swap to it between art jobs costs a model load each time. What the
LLM contributed was the brief: the descriptions in the story plan. Things already built are skipped,
which is how an existing cast is reused.
"""

from __future__ import annotations

from typing import Any

from director.checks import read_json, story_of
from director.context import StageCtx, StageFailed
from director.hub import ToolRefused

SHEETS, DRAFTS, ROUNDS, BUILDS = 3, 2, 2, 2  # candidates per round, rounds, builds before giving up


def first_ok(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((c for c in candidates if c["ok"]), None)


def built(ctx: StageCtx, cid: str) -> bool:
    rig = read_json(ctx.film / "characters" / cid / "rig.json") or {}
    return bool(rig.get("views"))


async def make_puppet(ctx: StageCtx, c: dict[str, Any], known: dict[str, Any] | None) -> None:
    """Design rounds until a sheet passes, then build from passing sheets in order until one gives
    two consistent views (what the owner checks by eye)."""
    tried: set[str] = set()
    candidates = list(known["candidates"]) if known else []
    for round_no in range(ROUNDS + 1):
        for sheet in [x for x in candidates if x["ok"] and x["candidate_id"] not in tried]:
            if len(tried) == BUILDS:
                raise StageFailed(f"no build of {c['id']} gave consistent views in {BUILDS} tries")
            tried.add(sheet["candidate_id"])
            await ctx.tool(
                "choose_design", character_id=c["id"], candidate_id=sheet["candidate_id"]
            )
            result = await ctx.tool("build_puppet", character_id=c["id"], name=c["name"])
            if result.get("views_consistent"):
                return
            ctx.note(
                f"{c['id']} {sheet['candidate_id']}: views differ: "
                f"{result.get('consistency_problems')}"
            )
        if round_no == ROUNDS:
            break
        made = await ctx.tool(
            "design_character", character_id=c["id"], description=c["description"], n=SHEETS
        )
        candidates += made["candidates"]
    raise StageFailed(f"no sheet of {c['id']} passed its checks and built consistently")


async def run_characters(ctx: StageCtx) -> None:
    story = story_of(ctx.film)
    assert story is not None
    art = await ctx.tool("describe_art")
    known = {x["id"]: x for x in art["characters"]}
    for c in story["characters"]:
        if built(ctx, c["id"]):
            ctx.me.per_item[c["id"]] = "built (existing)"
            continue
        ctx.me.per_item[c["id"]] = "building"
        ctx.save()
        try:
            await make_puppet(ctx, c, known.get(c["id"]))
        except ToolRefused as err:
            ctx.me.per_item[c["id"]] = f"failed: {err.message[:120]}"
            raise StageFailed(f"{c['id']}: {err}") from err
        except StageFailed as err:
            ctx.me.per_item[c["id"]] = f"failed: {err}"
            raise
        ctx.me.per_item[c["id"]] = "built"
        ctx.save()


async def run_backgrounds(ctx: StageCtx) -> None:
    story = story_of(ctx.film)
    assert story is not None
    for p in story["places"]:
        layers = (read_json(ctx.film / "backgrounds" / p["id"] / "layers.json") or {}).get(
            "layers", []
        )
        if len(layers) >= 3:
            ctx.me.per_item[p["id"]] = "layered (existing)"
            continue
        chosen = None
        for round_no in range(1, ROUNDS + 1):
            made = await ctx.tool(
                "generate_background", background_id=p["id"], description=p["description"], n=DRAFTS
            )
            chosen = first_ok(made["drafts"])
            if chosen:
                break
            ctx.note(f"{p['id']} round {round_no}: no draft passed its checks")
        if chosen is None:
            ctx.me.per_item[p["id"]] = "failed: no draft passed"
            raise StageFailed(f"no draft of {p['id']} passed its checks in {ROUNDS} rounds")
        await ctx.tool(
            "choose_background", background_id=p["id"], candidate_id=chosen["candidate_id"]
        )
        await ctx.tool("split_depth_layers", background_id=p["id"])
        pan = await ctx.tool(
            "preview_background", background_id=p["id"], move="slow_pan_right", duration_s=6
        )
        ctx.me.per_item[p["id"]] = (
            "layered" if pan.get("ok") else f"layered, pan check failed: {pan.get('verdicts')}"
        )
        ctx.save()
