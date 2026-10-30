"""A small project built from the committed fixtures: one character (Pip), three places and a
film of three acts, each in its own place. Shared by the workspace, acts and server tests."""

from __future__ import annotations

from pathlib import Path

from studio_core import shot_spec
from studio_core.project import Project
from studio_core.store import FileSystemStore
from studio_core.workspace import Workspace

FIXTURES = Path(__file__).parent / "fixtures"
PLACES = ("meadow", "hill", "pond")


def folder_files(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def make_workspace(tmp_path: Path) -> Workspace:
    return Workspace(
        films_root=tmp_path / "films",
        projects_root=tmp_path / "projects",
        work_root=tmp_path / "work",
    )


def make_project(ws: Workspace, project_id: str = "pip-world") -> Project:
    project = Project.create(
        FileSystemStore(ws.projects_root), name="Pip world", project_id=project_id
    )
    project.publish_character("pip", folder_files(FIXTURES / "characters" / "pip") | {})
    for place in PLACES:  # same art, three places: what matters is the ids
        project.publish_background(place, folder_files(FIXTURES / "backgrounds" / "meadow"))
    return project


def make_film(ws: Workspace, project: Project, slug: str = "three-acts", shots_per_act: int = 3):
    """Three acts (one place each) with `shots_per_act` shots; every shot is saved through the
    working folder, as the synfig tools do."""
    film = project.create_film(
        slug.replace("-", " ").title(), slug=slug, cast=["pip"], places=PLACES
    )
    for n, place in enumerate(PLACES, start=1):
        act = project.add_act(film["id"], f"Act {n}", background=place, beats=[f"beat {n}"])
        folder = ws.open_film(slug, project.id, act=act["id"])
        for k in range(1, shots_per_act + 1):
            sid = f"s{n:02d}_sh{k:02d}"
            shot_spec.create_shot(folder, sid, 1.0 + k / 10, place)
            shot_spec.place_character(folder, sid, "pip", [0.5, 0.9])
    return project.get_film(film["id"])
