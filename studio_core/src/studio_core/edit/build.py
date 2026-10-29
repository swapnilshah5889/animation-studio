"""assemble: shot ids in order (plus title cards and joins) → edit/edit.json + edit/film.mlt."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from studio_core import safety
from studio_core.config import StudioConfig, load_config
from studio_core.edit import spec as edit_spec
from studio_core.edit.mlt import build_mlt
from studio_core.edit.render import probe
from studio_core.edit.titles import render_title

TITLE_S = 3.0


def rendered_shots(film_root: Path) -> list[str]:
    shots = film_root / "shots"
    if not shots.is_dir():
        return []
    return sorted(d.name for d in shots.iterdir() if (d / "shot.mp4").is_file())


def assemble(
    film_root: Path,
    shots: list[str],
    *,
    default_transition: str = "cut",
    crossfade_s: float = edit_spec.DEFAULT_CROSSFADE_S,
    transitions: list[dict[str, Any]] | None = None,
    titles: list[dict[str, Any]] | None = None,
    cfg: StudioConfig | None = None,
) -> dict[str, Any]:
    """Build and save the edit. `transitions` override the join into a shot
    ({"into": shot_id, "type", "duration_s"}); `titles` are cards ({"text", "subtitle",
    "duration_s", "position": "start" | "end" | a shot id to put it before})."""
    cfg = cfg or load_config()
    if not shots:
        raise edit_spec.EditError("give at least one shot id")
    if len(set(shots)) != len(shots):
        raise edit_spec.EditError("a shot appears twice in the list; each shot goes in once")
    have = rendered_shots(film_root)
    for s in shots:
        edit_spec.shot_video(film_root, s)  # validates the id
        if s not in have:
            raise edit_spec.EditError(
                f"shot {s!r} has no rendered shot.mp4 (render_shot first); rendered: {have}"
            )
    overrides = {t["into"]: t for t in transitions or []}
    for into in overrides:
        if into not in shots:
            raise edit_spec.EditError(f"transitions: {into!r} is not one of the shots to assemble")

    cards: dict[str, list[dict[str, Any]]] = {"start": [], "end": []}
    for t in titles or []:
        bad = safety.blocked_words(f"{t['text']} {t.get('subtitle') or ''}")
        if bad:
            raise edit_spec.EditError(f"title text is not suitable for children ({bad})")
        pos = t.get("position", "start")
        if pos not in ("start", "end") and pos not in shots:
            raise edit_spec.EditError(
                f"title position {pos!r} must be 'start', 'end' or one of the shots"
            )
        cards.setdefault(pos, []).append(t)

    fps = edit_spec.FPS
    size = edit_spec.FINAL_SIZE
    out_dir = edit_spec.edit_dir(film_root)
    title_dir = out_dir / "titles"
    clips: list[dict[str, Any]] = []

    def add_title(t: dict[str, Any]) -> None:
        n = sum(1 for c in clips if c["kind"] == "title") + 1
        dur = t.get("duration_s") or TITLE_S
        path = render_title(
            title_dir / f"t{n:02d}.mp4", t["text"], t.get("subtitle"), dur, size, fps, cfg
        )
        clip = {"kind": "title", "text": t["text"], "file": str(path.relative_to(film_root))}
        if t.get("subtitle"):
            clip["subtitle"] = t["subtitle"]
        clip["duration_s"] = round(frames_of(path) / fps, 4)
        clips.append(clip)

    def frames_of(path: Path) -> int:
        return edit_spec.frames(probe(path, cfg).duration_s, fps)

    for t in cards["start"]:
        add_title(t)
    for s in shots:
        for t in cards.get(s, []):
            add_title(t)
        path = edit_spec.shot_video(film_root, s)
        clip = {
            "kind": "shot",
            "shot": s,
            "file": str(path.relative_to(film_root)),
            "duration_s": round(frames_of(path) / fps, 4),
        }
        clips.append(clip)
    for t in cards["end"]:
        add_title(t)

    for clip in clips[1:]:
        o = overrides.get(clip.get("shot", ""))
        kind = o["type"] if o else default_transition
        secs = (o or {}).get("duration_s") or crossfade_s
        clip["transition_in"] = (
            {"type": "crossfade", "duration_s": secs} if kind == "crossfade" else {"type": "cut"}
        )

    spec = edit_spec.build_spec(clips, fps=fps, size=size)
    edit_spec.save(film_root, spec)
    (out_dir / "film.mlt").write_text(build_mlt(spec, film_root))
    return spec
