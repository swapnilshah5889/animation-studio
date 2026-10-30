"""Acts as the unit of rendering, and "export all acts as a movie" (Step 5C, D-083).

The specs in the project store are the editable source. Rendering an act turns its shot documents
into a video (an asset), and records the cache key the act was rendered from. Export renders only
the acts whose key changed (`Project.stale_acts`), then joins the act videos in the acts' order
into one movie. Delete every render and export again, and the same film comes back from the specs.

    folder = Workspace.from_config().open_film("the-lost-kite", project="pip-and-friends")
    export_movie(folder, Target("synfig", "final"), synfig_renderer(cfg), cfg)

The engine is a name (`Target.engine`) mapped to a renderer function; the key includes it, so a
new engine renders every act again. Nothing here is specific to one engine (D-030).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from studio_core import safety, shot_spec
from studio_core.config import StudioConfig, load_config
from studio_core.edit import spec as edit_spec
from studio_core.edit.mlt import build_mlt
from studio_core.edit.render import QUALITIES, probe, run_melt, verify
from studio_core.edit.titles import render_title
from studio_core.store import FileSystemStore

DEFAULT_ENGINE = "synfig"
TITLE_S = 3.0

# (film working folder, shot id, size) -> the rendered shot video
Renderer = Callable[[Path, str, tuple[int, int]], Path]


class ActError(ValueError):
    """An act cannot be rendered or exported; the message says what to fix."""


@dataclass(frozen=True)
class Target:
    """What an act is rendered with: an engine and a quality. Both are part of the cache key,
    so a preview render never satisfies a final export."""

    engine: str = DEFAULT_ENGINE
    quality: str = "final"

    def __post_init__(self) -> None:
        if self.quality not in QUALITIES:
            raise ActError(f"quality must be one of {sorted(QUALITIES)}, not {self.quality!r}")

    @property
    def id(self) -> str:
        return f"{self.engine}:{self.quality}"

    @property
    def size(self) -> tuple[int, int]:
        return QUALITIES[self.quality]["size"]


def synfig_renderer(cfg: StudioConfig | None = None) -> Renderer:
    from studio_core.shot import render_shot

    def render(root: Path, shot_id: str, size: tuple[int, int]) -> Path:
        return render_shot(root, shot_id, size=size, cfg=cfg).mp4

    return render


def renderer_for(engine: str, cfg: StudioConfig | None = None) -> Renderer:
    if engine == "synfig":
        return synfig_renderer(cfg)
    raise ActError(f"no renderer for engine {engine!r}; engines: ['synfig']")


# ----------------------------------------------------------------------------- looking


def _link(folder: shot_spec.FilmFolder):
    if folder.link is None:
        raise ActError("acts belong to projects: open the film with a project id")
    return folder.link


def find_act(folder: shot_spec.FilmFolder, act: str) -> dict:
    """An act by id, title or number ('2')."""
    link = _link(folder)
    acts = link.project.list_acts(link.film_id)
    for a in acts:
        if act in (a["id"], a["title"]) or act == str(a["order"]):
            return a
    raise ActError(
        f"no act {act!r}; acts: {[f'{a["order"]}. {a["title"]}' for a in acts] or 'none'}"
    )


def has_video(link, act_id: str) -> bool:
    last = link.project.last_render(act_id)
    return bool(
        last
        and last.get("video")
        and link.project.store.asset_exists(link.project.id, last["video"]["id"])
    )


def needs_render(link, act_id: str, target: Target) -> bool:
    return link.project.is_act_stale(link.film_id, act_id, target.id) or not has_video(link, act_id)


def act_problems(link, act: dict) -> list[str]:
    """Mistakes in an act's specs that rendering would trip over."""
    project = link.project
    place = project.resolve_ref("background", act["background"]).slug
    problems = []
    if not act["shot_ids"]:
        problems.append("the act has no shots (add_shot)")
    for shot in project.list_shots(link.film_id, act["id"]):
        spec = shot["spec"]
        if spec.get("background") != place:
            problems.append(
                f"{spec['id']} is set in {spec.get('background')!r}, the act in {place!r}"
            )
    return problems


def act_table(folder: shot_spec.FilmFolder, target: Target) -> list[dict[str, Any]]:
    """Every act of the film in order: its shots, whether a render is needed, what is wrong."""
    link = _link(folder)
    project = link.project
    rows = []
    for act in project.list_acts(link.film_id):
        shots = project.list_shots(link.film_id, act["id"])
        rows.append(
            {
                "act_id": act["id"],
                "order": act["order"],
                "title": act["title"],
                "background": project.resolve_ref("background", act["background"]).slug,
                "cast": [project.resolve_ref("character", c).slug for c in act["cast"]],
                "beats": act["beats"],
                "shots": [
                    {"shot_id": s["spec"]["id"], "duration_s": s["spec"]["duration_s"]}
                    for s in shots
                ],
                "stale": needs_render(link, act["id"], target),
                "rendered": has_video(link, act["id"]),
                "problems": act_problems(link, act),
            }
        )
    return rows


# --------------------------------------------------------------------------- rendering


def _clip(root: Path, path: Path, cfg: StudioConfig, **ident: str) -> dict[str, Any]:
    frames = edit_spec.frames(probe(path, cfg).duration_s, edit_spec.FPS)
    return {
        "file": str(path.relative_to(root)),
        "duration_s": round(frames / edit_spec.FPS, 4),
        **ident,
    }


def _join(
    root: Path,
    clips: list[dict[str, Any]],
    where: Path,
    out: Path,
    target: Target,
    cfg: StudioConfig,
    progress: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    spec = edit_spec.build_spec(clips, size=target.size)
    where.mkdir(parents=True, exist_ok=True)
    (where / "edit.json").write_text(json.dumps(spec, indent=2) + "\n")
    (where / "film.mlt").write_text(build_mlt(spec, root))
    out.parent.mkdir(parents=True, exist_ok=True)
    run_melt(where / "film.mlt", out, target.quality, spec["fps"], progress, cfg)
    return spec


def _keep(link, path: Path) -> dict:
    store = link.project.store
    if isinstance(store, FileSystemStore):
        return store.import_file(link.project.id, path, "video/mp4", mode="clone")
    return store.put_asset(link.project.id, path.read_bytes(), "video/mp4")


def _fetch(link, record: dict, dest: Path) -> Path:
    """The recorded act video as a file in the working folder (a clone, not a copy, where the
    disk allows)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    store = link.project.store
    dest.unlink(missing_ok=True)
    local = getattr(store, "asset_path", None)
    if local is not None:
        from studio_core.store.filesystem import place_file

        place_file(local(link.project.id, record["id"]), dest, "clone")
    else:
        with store.open_asset(link.project.id, record["id"]) as handle:
            dest.write_bytes(handle.read())
    return dest


def render_act(
    folder: shot_spec.FilmFolder,
    act: str,
    target: Target,
    renderer: Renderer,
    cfg: StudioConfig | None = None,
    *,
    force: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Render one act's shots, join them into the act's video and record the render with the key
    the specs had when it started (so an edit made meanwhile still shows the act as stale).
    Nothing happens when the act is up to date, unless `force`."""
    cfg = cfg or load_config()
    say = progress or (lambda _: None)
    link = _link(folder)
    link.pull()
    project = link.project
    doc = find_act(folder, act)
    if not force and not needs_render(link, doc["id"], target):
        return {"act_id": doc["id"], "title": doc["title"], "rendered": False, "shots": []}
    problems = act_problems(link, doc)
    if problems:
        raise ActError(f"fix act {doc['title']!r} first: " + "; ".join(problems))
    key = project.act_key(link.film_id, doc["id"], target.id)  # before rendering
    specs = [s["spec"] for s in project.list_shots(link.film_id, doc["id"])]
    for spec in specs:
        errors, _ = shot_spec.check(folder, spec)
        if errors:
            raise ActError(f"shot {spec['id']} is invalid: " + "; ".join(errors))
    clips = []
    for n, spec in enumerate(specs, start=1):
        say(f"act {doc['title']!r}: shot {spec['id']} ({n}/{len(specs)})")
        video = renderer(link.root, spec["id"], target.size)
        clips.append(_clip(link.root, video, cfg, kind="shot", shot=spec["id"]))
    out = link.root / "acts" / doc["id"] / "act.mp4"
    _join(link.root, clips, link.root / "acts" / doc["id"], out, target, cfg)
    record = _keep(link, out)
    project.record_render(link.film_id, doc["id"], target.id, cache_key=key, video=record)
    return {
        "act_id": doc["id"],
        "title": doc["title"],
        "rendered": True,
        "shots": [s["id"] for s in specs],
        "video_path": str(out),
        "cache_key": key,
    }


def export_movie(
    folder: shot_spec.FilmFolder,
    target: Target,
    renderer: Renderer,
    cfg: StudioConfig | None = None,
    *,
    transition: str = "cut",
    start_title: str | None = None,
    end_title: str | None = None,
    force: bool = False,
    progress: Callable[[str], None] | None = None,
    progress_pct: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    """Export all acts: render every act that needs it, join the act videos in order, check the
    result (size, streams, length, loudness). Returns what was rendered and what was reused."""
    cfg = cfg or load_config()
    link = _link(folder)
    link.pull()
    project = link.project
    acts = project.list_acts(link.film_id)
    if not acts:
        raise ActError("the film has no acts yet (add_act)")
    for text in (start_title, end_title):
        bad = safety.blocked_words(text or "")
        if bad:
            raise ActError(f"title text is not suitable for children ({bad})")
    rendered, reused = [], []
    for act in acts:
        result = render_act(
            folder, act["id"], target, renderer, cfg, force=force, progress=progress
        )
        (rendered if result["rendered"] else reused).append(act["title"])
    root = link.root
    clips: list[dict[str, Any]] = []

    def card(text: str, n: int) -> None:
        path = render_title(
            root / "edit" / "titles" / f"t{n:02d}.mp4",
            text,
            None,
            TITLE_S,
            target.size,
            edit_spec.FPS,
            cfg,
        )
        clips.append(_clip(root, path, cfg, kind="title", text=text))

    if start_title:
        card(start_title, 1)
    for act in acts:
        record = project.last_render(act["id"])["video"]  # type: ignore[index]
        video = _fetch(link, record, root / "acts" / act["id"] / "act.mp4")
        clips.append(_clip(root, video, cfg, kind="act", act=act["id"]))
    if end_title:
        card(end_title, 2)
    for clip in clips[1:]:
        clip["transition_in"] = (
            {"type": "crossfade", "duration_s": edit_spec.DEFAULT_CROSSFADE_S}
            if transition == "crossfade"
            else {"type": "cut"}
        )
    out = edit_spec.edit_dir(root) / "final.mp4"
    spec = _join(root, clips, edit_spec.edit_dir(root), out, target, cfg, progress_pct)
    report = verify(out, spec, target.quality, cfg)
    return {
        "path": str(out),
        "quality": target.quality,
        "width": report.width,
        "height": report.height,
        "duration_s": report.duration_s,
        "expected_duration_s": report.expected_duration_s,
        "integrated_lufs": report.integrated_lufs,
        "checks_passed": report.ok,
        "problems": report.problems,
        "rendered_acts": rendered,
        "reused_acts": reused,
        "act_order": [a["title"] for a in acts],
    }


def clear_renders(folder: shot_spec.FilmFolder) -> int:
    """Throw away every render of the film (the records, the act videos, the working folder's
    videos and frames). The specs are untouched; export makes it all again. Returns how many act
    records were removed. Video assets stay in the store until it is cleaned up."""
    link = _link(folder)
    removed = 0
    for act in link.project.list_acts(link.film_id):
        if link.project.last_render(act["id"]):
            link.project.store.delete_document(link.project.id, "act_render", act["id"])
            removed += 1
    for name in ("acts", "edit"):
        shutil.rmtree(link.root / name, ignore_errors=True)
    shots = link.root / "shots"
    if shots.is_dir():
        for d in shots.iterdir():
            for leftover in ("shot.mp4", "scene.sif", "mix.wav", "preview.png"):
                (d / leftover).unlink(missing_ok=True)
            shutil.rmtree(d / "frames", ignore_errors=True)
    return removed


__all__ = [
    "ActError",
    "Renderer",
    "Target",
    "act_table",
    "clear_renders",
    "export_movie",
    "find_act",
    "render_act",
    "renderer_for",
    "synfig_renderer",
]
