"""Stages 6 and 7, edit and qa. Code-driven: the model chooses nothing here (honest scope note).

edit: assemble the planned shots in order (a title card only on a long film), then render the film.
qa:   check_film (up to 3 key frames per shot, every line) and write qa/film_report.json. Open
      issues are *reported* at the final approval, not auto-fixed: the per-shot fix loop already ran
      inside the shots stage.
"""

from __future__ import annotations

import json
from typing import Any

from director.checks import shotplan_of, story_of
from director.context import StageCtx, StageFailed

TITLE_CARD_MIN_S = 40  # a 15 s film has no room for a 3 s title card


async def run_edit(ctx: StageCtx) -> None:
    plan, story = shotplan_of(ctx.film), story_of(ctx.film)
    assert plan is not None and story is not None
    args: dict[str, Any] = {"shots": [s["id"] for s in plan["shots"]], "default_transition": "cut"}
    if ctx.state.target_seconds >= TITLE_CARD_MIN_S:
        args["titles"] = [{"text": story["title"], "position": "start"}]
    await ctx.tool("assemble", **args)
    result = await ctx.tool("render_film", quality=ctx.deps.quality)
    if not result.get("checks_passed", True):
        raise StageFailed(f"render_film checks failed: {result.get('problems') or result}")


async def run_qa(ctx: StageCtx) -> None:
    if ctx.deps.guard:
        ctx.deps.guard.release_llm()
    result = await ctx.tool("check_film")
    frames = sum(len(s["frames"]) for s in result["shots"])
    open_issues = [
        {"shot": s["shot_id"], "problems": f["problems"], "code": f["code_findings"]}
        for s in result["shots"]
        for f in s["frames"]
        if not f["ok"]
    ]
    report = {
        "frames_checked": frames,
        "ok": result["ok"],
        "needs_human": result["needs_human"],
        "open_issues": open_issues,
        "summary": result["summary"],
    }
    (ctx.film / "qa").mkdir(exist_ok=True)
    (ctx.film / "qa" / "film_report.json").write_text(json.dumps(report, indent=2) + "\n")
