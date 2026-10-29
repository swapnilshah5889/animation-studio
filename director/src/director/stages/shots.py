"""Stage 5, shots: plan the shots once, then build and render them one by one.

Per shot, rules in code come first and the model second:
  1. scaffold (code): create_scene, add_character, blink + idle_breathe, expression, the planned
     motion, the line, a sound, the music. A fixed call list; a refusal is recorded, not hidden.
  2. conversation (the agent loop): the model looks at the shot (describe_shot, a preview frame,
     check_frame), fixes what is wrong and renders it. Done = shot.mp4 exists and the spec is valid
     (checks.shot_missing), never "the model said so".
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from director import craft
from director.checks import lines_of, read_json, shot_missing, shotplan_of, story_of
from director.config import LINE_LEAD_S, LINE_TAIL_S, SHOT_SECONDS
from director.context import PauseForApproval, StageCtx, StageFailed, capabilities
from director.dispatch import CallContext
from director.hub import ProgressFn, ToolDispatcher, ToolResult
from director.loop import run_conversation
from director.plans import (
    check_shotplan,
    drop_empty_lines,
    norm,
    plan_json,
    shotplan_schema,
)
from director.review import write_review
from director.state import now
from director.toolview import ToolView

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
GROUND_Y = 0.92
X_BY_WHERE = {"left": 0.3, "center": 0.5, "right": 0.7}


# ---- planning ---------------------------------------------------------------------------------


def fit_lines(plan: dict[str, Any], lines: list[dict[str, Any]], scene_of: dict[str, str]) -> None:
    """A shot with a line must outlast the recording (lead + line + tail). The model estimates
    seconds; the recorded duration is a fact, so code extends the shot to fit (up to the cap)."""
    by_text = {(x["scene"], norm(x["text"])): x["duration_s"] for x in lines}
    for sh in plan["shots"]:
        if ln := sh.get("line"):
            dur = by_text.get((sh["scene"], norm(ln["text"])))
            if dur:
                need = LINE_LEAD_S + dur + LINE_TAIL_S
                sh["seconds"] = min(
                    SHOT_SECONDS[1], max(sh["seconds"], round(need * 2 + 0.499) / 2)
                )


async def make_plan(ctx: StageCtx) -> dict[str, Any]:
    story = story_of(ctx.film)
    assert story is not None
    caps, _ = await capabilities(ctx)
    lines = lines_of(ctx.film)
    scene_of = {s["id"]: s["place"] for s in story["scenes"]}

    def check(plan: dict[str, Any]) -> list[str]:
        if isinstance(plan.get("shots"), list):
            drop_empty_lines(plan)
            fit_lines(plan, lines, scene_of)
        return check_shotplan(plan, story, ctx.state.target_seconds)

    brief = [
        f"Target length: {ctx.state.target_seconds} seconds.",
        "Story:",
        json.dumps({k: story[k] for k in ("title", "scenes")}),
        "Characters: "
        + "; ".join(f"{c['id']} ({c['name']}): {c['description']}" for c in story["characters"]),
    ]
    brief += [f"Owner's note: {n}" for n in ctx.me.revision_notes]
    plan = await plan_json(
        ctx.deps.chat,
        (PROMPTS / "shotplan.md").read_text(),
        "\n".join(brief),
        shotplan_schema(story, caps),
        check,
        on_event=ctx.deps.on_event,
        counters=ctx.state.counters,
    )
    (ctx.film / "story" / "shotplan.json").write_text(json.dumps(plan, indent=2) + "\n")
    return plan


# ---- scaffolding: the plan as a fixed list of tool calls ---------------------------------------


def positions(members: list[dict[str, Any]]) -> dict[str, float]:
    xs = [X_BY_WHERE[m["where"]] for m in members]
    if len(set(xs)) < len(xs):  # two on the same spot: spread them evenly instead
        n = len(members)
        xs = [0.5] if n == 1 else [round(0.3 + 0.4 * i / (n - 1), 3) for i in range(n)]
    return {m["id"]: x for m, x in zip(members, xs, strict=True)}


def scaffold_steps(
    planned: dict[str, Any], line_ids: dict[str, str], music_cue: str | None
) -> list[tuple[str, dict[str, Any]]]:
    """The deterministic tool calls that turn a planned shot into a shot spec (film and shot_id
    are added when they run). Everything here is a rule, not a choice."""
    secs = float(planned["seconds"])
    members = planned["characters"]
    xs = positions(members)
    steps: list[tuple[str, dict[str, Any]]] = [
        (
            "create_scene",
            {
                "duration_s": secs,
                "background": planned["place"],
                "camera_move": planned["camera"],
                "replace": True,
            },
        )
    ]
    line = planned.get("line")
    lead = LINE_LEAD_S if line else 0.5
    for i, m in enumerate(members):
        me, others = m["id"], [x for k, x in xs.items() if k != m["id"]]
        facing = "right" if not others or xs[me] <= min(others) else "left"
        steps.append(
            (
                "add_character",
                {"character_id": me, "position": [xs[me], GROUND_Y], "facing": facing},
            )
        )
        steps.append(
            (
                "apply_motion",
                {"character_id": me, "motion": "blink", "start_s": 0, "duration_s": secs},
            )
        )
        steps.append(("apply_motion", {"character_id": me, "motion": "idle_breathe", "start_s": 0}))
        steps.append(
            ("set_expression", {"character_id": me, "expr": m["expression"], "start_s": 0})
        )
        start = round(lead + 0.4 * i, 2)
        if m.get("moves_to") and X_BY_WHERE[m["moves_to"]] != xs[me]:
            span = round(max(1.0, secs - 0.8), 2)
            steps.append(
                (
                    "move_character",
                    {
                        "character_id": me,
                        "to": [X_BY_WHERE[m["moves_to"]], GROUND_Y],
                        "start_s": 0.4,
                        "duration_s": span,
                    },
                )
            )
            steps.append(
                (
                    "apply_motion",
                    {
                        "character_id": me,
                        "motion": "walk_cycle",
                        "start_s": 0.4,
                        "duration_s": span,
                    },
                )
            )
        elif m["does"] not in ("blink", "idle_breathe"):
            steps.append(
                ("apply_motion", {"character_id": me, "motion": m["does"], "start_s": start})
            )
    if line and (lid := line_ids.get(norm(line["text"]))):
        steps.append(
            ("apply_lipsync", {"character_id": line["who"], "line_id": lid, "start_s": LINE_LEAD_S})
        )
    if music_cue:
        steps.append(("set_music", {"cue_id": music_cue, "volume": 0.4}))
    return steps


async def run_scaffold(
    ctx: StageCtx, planned: dict[str, Any], steps: list[tuple[str, dict[str, Any]]]
) -> tuple[list[str], list[str]]:
    """Run the steps; returns (done, refused) as short lines for the model's brief."""
    done: list[str] = []
    refused: list[str] = []
    steps = list(steps)
    if sfx := planned.get("sfx"):
        try:
            found = await ctx.tool("find_sfx", queries=[sfx], k=3, avoid=["traffic"])
            sound = found["results"][0]["sounds"][0]["sound_id"]
            steps.append(
                (
                    "add_sound_effect",
                    {"sound_id": sound, "start_s": 0.0, "volume": 0.3, "query": sfx},
                )
            )
        except Exception as err:
            refused.append(f"find_sfx {sfx!r}: {err}")
    for tool, args in steps:
        res = await ctx.deps.hub.call(tool, {"film": ctx.slug, "shot_id": planned["id"], **args})
        ctx.state.counters.tool_calls += 1
        ctx.state.counters.tool_seconds += res.seconds
        short = f"{tool} {json.dumps(args, separators=(',', ':'))}"
        if res.refused:
            ctx.state.counters.refusals += 1
            refused.append(f"{short} -> REFUSED: {res.text[:200]}")
        else:
            done.append(short[:160])
    return done, refused


# ---- the conversation for one shot -------------------------------------------------------------


class ShotHub:
    """Wraps the hub for one shot's conversation: swaps models before the vision tool, and keeps
    the check_frame results (the gate before render_shot and the shot's qa.json)."""

    def __init__(self, hub: ToolDispatcher, before: dict[str, Callable[[], None]]) -> None:
        self.hub, self.before, self.tools = hub, before, hub.tools
        self.frames: list[dict[str, Any]] = []

    async def call(
        self, tool: str, args: dict[str, Any], on_progress: ProgressFn | None = None
    ) -> ToolResult:
        if hook := self.before.get(tool):
            hook()
        res = await self.hub.call(tool, args, on_progress)
        if tool == "check_frame" and not res.refused and res.data:
            self.frames.append(res.data)
        return res


def shot_brief(
    planned: dict[str, Any],
    line_ids: dict[str, str],
    lines: list[dict[str, Any]],
    done: list[str],
    refused: list[str],
    quality: str,
) -> str:
    parts = [
        f"Shot {planned['id']} ({planned['seconds']} s) in {planned['place']}. "
        f"Beat: {planned['beat']}",
        "Plan: " + json.dumps(planned, separators=(",", ":")),
        f"Render quality: {quality}",
    ]
    if planned.get("line"):
        rec = next(
            (x for x in lines if x["line_id"] == line_ids.get(norm(planned["line"]["text"]))), None
        )
        if rec:
            parts.append(
                f"The line is {rec['line_id']}, {rec['duration_s']} s long, at {LINE_LEAD_S} s."
            )
    parts.append("Built by code already:\n" + "\n".join(f"- {d}" for d in done))
    parts.append(
        "REFUSED when building (fix these first):\n" + "\n".join(f"- {r}" for r in refused)
        if refused
        else "Nothing was refused."
    )
    return "\n".join(parts)


async def build_shot(
    ctx: StageCtx, planned: dict[str, Any], scene_place: dict[str, str], music: dict[str, str]
) -> None:
    planned = {**planned, "place": scene_place[planned["scene"]]}
    lines = [x for x in lines_of(ctx.film) if x["scene"] == planned["scene"]]
    line_ids = {norm(x["text"]): x["line_id"] for x in lines}
    done, refused = await run_scaffold(
        ctx, planned, scaffold_steps(planned, line_ids, music.get(planned["scene"]))
    )
    ctx.note(f"{planned['id']}: scaffold {len(done)} ok, {len(refused)} refused")

    guard = ctx.deps.guard
    shot_hub = ShotHub(ctx.deps.hub, {"check_frame": guard.release_llm} if guard else {})
    view = ToolView.for_stage("shots", shot_hub.tools)
    call_ctx = CallContext(
        fixed_args={"film": ctx.slug, "shot_id": planned["id"]},
        allowed={"character_id": {m["id"] for m in planned["characters"]}},
        preconditions={
            "render_shot": lambda: (
                None
                if shot_hub.frames
                else "Look first: render_preview_frame, then check_frame at the same time_s."
            )
        },
    )
    messages = [
        {
            "role": "system",
            "content": (PROMPTS / "shots.md").read_text().replace("{craft_index}", craft.index()),
        },
        {
            "role": "user",
            "content": shot_brief(planned, line_ids, lines, done, refused, ctx.deps.quality),
        },
    ]
    turn = await run_conversation(
        ctx.deps.chat,
        shot_hub,
        messages,
        view,
        call_ctx,
        think=False,
        limits=ctx.deps.limits,
        complete=lambda: shot_missing(ctx.film, planned),
        on_event=ctx.deps.on_event,
        counters=ctx.state.counters,
    )
    (ctx.film / "director" / "transcripts").mkdir(parents=True, exist_ok=True)
    (ctx.film / "director" / "transcripts" / f"{planned['id']}.json").write_text(
        json.dumps(turn.messages, indent=1, default=str)
    )
    qa = {
        "frames": [
            {k: f.get(k) for k in ("time_s", "ok", "code_findings", "problems")}
            for f in shot_hub.frames
        ]
    }
    (ctx.film / "shots" / planned["id"] / "qa.json").write_text(json.dumps(qa, indent=2) + "\n")
    if turn.stop != "done":
        raise StageFailed(
            f"shot {planned['id']}: the conversation stopped ({turn.stop}): {turn.why}"
        )


# ---- the stage ---------------------------------------------------------------------------------


async def run(ctx: StageCtx) -> None:
    plan = shotplan_of(ctx.film)
    if plan is None:
        plan = await make_plan(ctx)
        ctx.note(
            f"shot plan: {len(plan['shots'])} shots, {sum(s['seconds'] for s in plan['shots'])} s"
        )
    story = story_of(ctx.film)
    assert story is not None
    scene_place = {s["id"]: s["place"] for s in story["scenes"]}
    music = read_json(ctx.film / "director" / "music.json") or {}
    for i, planned in enumerate(plan["shots"]):
        if shot_missing(ctx.film, planned) is not None:
            ctx.me.per_item[planned["id"]] = "building"
            ctx.save()
            await build_shot(ctx, planned, scene_place, music)
        ctx.me.per_item[planned["id"]] = "rendered"
        ctx.save()
        if i == 0:
            gate(ctx)  # the look-and-feel check before the other shots render


def gate(ctx: StageCtx) -> None:
    ap = ctx.state.approvals["first_shot"]
    if ap.status == "approved":
        return
    if ctx.deps.auto or ap.mode == "auto":
        ap.status, ap.at = "approved", now()
        return
    ap.status = "waiting"
    write_review("first_shot", ctx.film, ctx.state)
    raise PauseForApproval("first_shot")
