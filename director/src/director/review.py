"""Approval stops: what the owner is shown, and how an approval is recorded.

At each checkpoint the director writes director/review/<name>.md, prints its path and stops. The
owner approves with `director approve`, asks for changes with `director revise`, or runs with
`--auto` (every checkpoint approves itself).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from director import state as st
from director.checks import act_plan_of, read_json, shotplan_of, story_of
from director.config import ACT_CHECKPOINT


def review_path(film: Path, name: str) -> Path:
    return st.state_dir(film) / "review" / f"{name}.md"


def write_review(name: str, film: Path, state: st.DirectorState) -> Path:
    if name.startswith(ACT_CHECKPOINT):
        body = _act(name[len(ACT_CHECKPOINT) :], film, state)
    else:
        body = {
            "story": _story,
            "characters": _characters,
            "first_shot": _first_shot,
            "final": _final,
        }[name](film, state)
    path = review_path(film, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Review: {name} ({state.film})\n\n{body}\n\n"
        f"Approve: `director approve {state.film} {name}`  \n"
        f'Change: `director revise {state.film} {name} "what to change"`\n'
    )
    return path


def _story(film: Path, state: st.DirectorState) -> str:
    story = story_of(film) or {}
    out = [f"**{story.get('title', '?')}**: {story.get('logline', '')}", "", "## Characters"]
    out += [
        f"- `{c['id']}` {c['name']}: {c['description']} ({c['role']})"
        for c in story.get("characters", [])
    ]
    out += ["", "## Places"] + [
        f"- `{p['id']}` ({p['time_of_day']}): {p['description']}" for p in story.get("places", [])
    ]
    for s in story.get("scenes", []):
        out += [
            "",
            f"## {'Act' if state.project else 'Scene'} {s['id']}"
            + (f" '{s['title']}'" if s.get("title") else "")
            + f" at `{s['place']}`, {s['seconds']} s, mood {s['mood']}",
            s["summary"],
        ]
        out += [f'- {ln["who"]}: "{ln["text"]}"' for ln in s["lines"]]
    safety = read_json(film / "story" / "safety.json") or {}
    out += ["", f"Safety check: {safety}"]
    return "\n".join(out)


def _characters(film: Path, state: st.DirectorState) -> str:
    out = []
    for c in (story_of(film) or {}).get("characters", []):
        cdir = film / "characters" / c["id"]
        flag = state.stage("characters").per_item.get(c["id"], "?")
        out.append(
            f"- `{c['id']}` {c['name']}: {flag}. "
            f"Sheet: `{_first(cdir / 'design', '*/sheet.png')}`, "
            f"preview: `{_first(cdir, '**/preview*.mp4')}`"
        )
    return "\n".join(out)


def _act(scene_id: str, film: Path, state: st.DirectorState) -> str:
    story = story_of(film) or {}
    scene = next((s for s in story.get("scenes", []) if s["id"] == scene_id), {})
    plan = act_plan_of(film, scene_id) or {"shots": []}
    video = state.stage("shots").per_item.get(ACT_CHECKPOINT + scene_id, "(not rendered)")
    out = [
        f"Act `{scene_id}` '{scene.get('title', '')}' at `{scene.get('place', '?')}`: "
        f"{scene.get('summary', '')}",
        "",
        f"Act video: `{video}`",
        "",
    ]
    for sh in plan["shots"]:
        qa = read_json(film / "shots" / sh["id"] / "qa.json")
        out.append(
            f"- `{sh['id']}` {sh['seconds']} s, {sh['framing']}, {sh['camera']}: {sh['beat']}"
        )
        if qa:
            out.append(f"  QA: {qa}")
    out += ["", "Only this act renders again after a change; the other acts are reused."]
    return "\n".join(out)


def _first(base: Path, pattern: str) -> str:
    return next((str(p) for p in sorted(base.glob(pattern))), "(none)")


def _first_shot(film: Path, state: st.DirectorState) -> str:
    plan = shotplan_of(film) or {"shots": []}
    first = plan["shots"][0]["id"] if plan["shots"] else "?"
    folder = film / "shots" / first
    qa = read_json(folder / "qa.json")
    return (
        f"First shot `{first}`: `{folder / 'shot.mp4'}`\n\n"
        f"Beat: {plan['shots'][0]['beat'] if plan['shots'] else ''}\n\n"
        f"QA notes: {qa if qa else 'none recorded'}\n\n"
        "The other shots render after you approve this look."
    )


def _final(film: Path, state: st.DirectorState) -> str:
    report: dict[str, Any] = read_json(film / "qa" / "film_report.json") or {}
    c = state.counters
    return (
        f"Film: `{film / 'edit' / 'final.mp4'}`\n\n"
        f"Open QA issues: {report.get('open_issues', 'unknown')}\n\n"
        f"Cost: {c.model_calls} model calls, {c.tool_calls} tool calls, {c.refusals} refusals, "
        f"{c.prompt_tokens} prompt and {c.output_tokens} output tokens, "
        f"{c.llm_seconds / 60:.1f} min LLM, {c.tool_seconds / 60:.1f} min in tools."
    )
