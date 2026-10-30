"""Is a stage complete? Pure functions on the film folder: code decides, never the model.

`stage_complete` returns None when the stage's files exist and validate, else one sentence naming
what is missing (also the nudge text). Resume re-runs these from the top (runner.reverify).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from director.plans import check_shotplan, check_story, norm
from studio_core import safety
from studio_core.schema import schema_issues

REQUIRED_MOTIONS = ("blink", "idle_breathe")  # every character, every shot (rules in code)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def story_of(film: Path) -> dict[str, Any] | None:
    return read_json(film / "story" / "story.json")


def shotplan_of(film: Path) -> dict[str, Any] | None:
    return read_json(film / "story" / "shotplan.json")


def one_scene_story(story: dict[str, Any], scene_id: str) -> dict[str, Any]:
    """The story cut down to one scene (one act of a project film) and the characters in it."""
    scene = next(s for s in story["scenes"] if s["id"] == scene_id)
    return {
        **story,
        "scenes": [scene],
        "characters": [c for c in story["characters"] if c["id"] in scene["characters"]],
    }


def act_plan_of(film: Path, scene_id: str) -> dict[str, Any] | None:
    return read_json(film / "story" / "plans" / f"{scene_id}.json")


def merged_plan(film: Path, story: dict[str, Any]) -> dict[str, Any]:
    """The shot plan of the acts planned so far, in story order (story/shotplan.json)."""
    shots: list[dict[str, Any]] = []
    for sc in story["scenes"]:
        shots += (act_plan_of(film, sc["id"]) or {"shots": []})["shots"]
    return {"shots": shots}


def stage_complete(
    stage: str, film: Path, target_seconds: int, project: bool = False
) -> str | None:
    """None when the stage is complete. `project`: a film of a project (acts instead of one
    shot plan, one exported movie instead of an assembled edit)."""
    checks = PROJECT_CHECKS if project else CHECKS
    return checks[stage](film, target_seconds)


def _story(film: Path, target: int) -> str | None:
    story = story_of(film)
    if story is None:
        return "story/story.json is missing or unreadable."
    for name in ("outline", "characters", "places"):
        if not (film / "story" / f"{name}.json").is_file():
            return f"story/{name}.json is missing."
    if problems := check_story(story, target, safety.blocked_words):
        return problems[0]
    if not (read_json(film / "story" / "safety.json") or {}).get("ok"):
        return "the story has not passed the safety check (story/safety.json)."
    return None


def _characters(film: Path, target: int) -> str | None:
    story = story_of(film)
    if story is None:
        return "no story yet."
    for c in story["characters"]:
        rig = read_json(film / "characters" / c["id"] / "rig.json")
        views = (rig or {}).get("views", {})
        if not views:
            return f"character {c['id']} has no rig.json (not built)."
        if not all("face" in v for v in views.values()):
            return f"character {c['id']} has a view without a face."
    return None


def _backgrounds(film: Path, target: int) -> str | None:
    story = story_of(film)
    if story is None:
        return "no story yet."
    for p in story["places"]:
        layers = (read_json(film / "backgrounds" / p["id"] / "layers.json") or {}).get("layers", [])
        if len(layers) < 3:
            return f"place {p['id']} has {len(layers)} parallax layers; it needs at least 3."
    return None


def lines_of(film: Path) -> list[dict[str, Any]]:
    return read_json(film / "director" / "lines.json") or []


def _audio(film: Path, target: int) -> str | None:
    story = story_of(film)
    if story is None:
        return "no story yet."
    recorded = {(x["scene"], x["who"], norm(x["text"])): x for x in lines_of(film)}
    for s in story["scenes"]:
        for ln in s["lines"]:
            rec = recorded.get((s["id"], ln["who"], norm(ln["text"])))
            if rec is None:
                return f"the line {ln['text']!r} ({ln['who']}) has not been recorded."
            if not (film / "audio" / "lipsync" / f"{rec['line_id']}.json").is_file():
                return f"line {rec['line_id']} has no mouth cues."
    music = read_json(film / "director" / "music.json") or {}
    for s in story["scenes"]:
        cue = music.get(s["id"])
        if not cue or not list((film / "audio" / "music").glob(f"{cue}.*")):
            return f"scene {s['id']} has no music cue."
    return None


def _shots(film: Path, target: int) -> str | None:
    story, plan = story_of(film), shotplan_of(film)
    if story is None or plan is None:
        return "story/shotplan.json is missing."
    if problems := check_shotplan(plan, story, target):
        return problems[0]
    return next(filter(None, (shot_missing(film, s) for s in plan["shots"])), None)


def shot_missing(film: Path, planned: dict[str, Any]) -> str | None:
    """What is missing from one planned shot, or None when it is built and rendered."""
    folder = film / "shots" / planned["id"]
    spec = read_json(folder / "shot.json")
    if spec is None:
        return f"shot {planned['id']} has no shot.json."
    if issues := schema_issues("shot", spec):
        return f"shot {planned['id']} is invalid: {issues[0]}"
    for ch in spec["characters"]:
        done = {a["motion"] for a in ch.get("actions", [])}
        if gap := [m for m in REQUIRED_MOTIONS if m not in done]:
            return f"shot {planned['id']}: {ch['id']} needs {' and '.join(gap)} for the whole shot."
    if (ln := planned.get("line")) and not spec.get("dialogue"):
        return f"shot {planned['id']} must have the line {ln['text']!r} (apply_lipsync)."
    if not (folder / "shot.mp4").is_file():
        return f"shot {planned['id']} is not rendered (render_shot)."
    return None


def _edit(film: Path, target: int) -> str | None:
    plan = shotplan_of(film)
    spec = read_json(film / "edit" / "edit.json")
    if plan is None or spec is None:
        return "the edit has not been assembled (edit/edit.json)."
    in_edit = [c["shot"] for c in spec["clips"] if c["kind"] == "shot"]
    want = [s["id"] for s in plan["shots"]]
    if in_edit != want:
        return f"the edit has shots {in_edit} but the plan has {want}."
    final = film / "edit" / "final.mp4"
    if not final.is_file() or final.stat().st_mtime < (film / "edit" / "edit.json").stat().st_mtime:
        return "edit/final.mp4 is missing or older than the edit (render_film)."
    return None


def _qa(film: Path, target: int) -> str | None:
    report = read_json(film / "qa" / "film_report.json")
    if report is None or "frames_checked" not in report:
        return "qa/film_report.json is missing."
    return None


def _shots_project(film: Path, target: int) -> str | None:
    story = story_of(film)
    if story is None:
        return "no story yet."
    for sc in story["scenes"]:
        plan = act_plan_of(film, sc["id"])
        if plan is None:
            return f"act {sc['id']} has no shot plan (story/plans/{sc['id']}.json)."
        if problems := check_shotplan(plan, one_scene_story(story, sc["id"]), sc["seconds"]):
            return f"act {sc['id']}: {problems[0]}"
        if gap := next(filter(None, (shot_missing(film, s) for s in plan["shots"])), None):
            return gap
    return None


def _edit_project(film: Path, target: int) -> str | None:
    story = story_of(film)
    done = read_json(film / "director" / "export.json")
    if story is None or done is None:
        return "the movie has not been exported (director/export.json)."
    if done.get("acts") != [s["id"] for s in story["scenes"]]:
        return f"the movie has acts {done.get('acts')} but the story has a different list."
    if not (film / "edit" / "final.mp4").is_file():
        return "edit/final.mp4 is missing (export_movie)."
    return None


CHECKS = {
    "story": _story,
    "characters": _characters,
    "backgrounds": _backgrounds,
    "audio": _audio,
    "shots": _shots,
    "edit": _edit,
    "qa": _qa,
}

# A film of a project: same stages, two different checks (D-094).
PROJECT_CHECKS = {**CHECKS, "shots": _shots_project, "edit": _edit_project}
