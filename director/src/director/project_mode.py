"""Films of a project (D-094): where the director keeps its files, and the library it may use.

A project film's working folder is derived data: the servers rebuild it from the store on every
call and it is safe to delete (D-091). The director's own files are not derived: its state, the
story, the recorded-line list and the shot plans are its memory. They live in
`projects/<project>/director/<film>/` (outside the store's own folders) and the working folder
holds two symlinks to them, `story/` and `director/`. Every stage, check and review then reads
`<working folder>/story/story.json` exactly as it does for an old film folder, and a deleted
working folder loses renders (a cache) but not progress.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from director.plans import ID, Roster
from studio_core.project import Project

HOME_DIRS = ("story", "director")
_ID_RE = re.compile(ID["pattern"])


def home_of(projects_root: Path, project: str, film: str) -> Path:
    return projects_root / project / "director" / film


def link_home(work: Path, home: Path) -> None:
    """Point `story/` and `director/` of the working folder at the director's home (idempotent).
    A real folder found there (from before the link) is moved into the home first."""
    work.mkdir(parents=True, exist_ok=True)
    for name in HOME_DIRS:
        target, link = home / name, work / name
        target.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            if link.resolve() == target.resolve():
                continue
            link.unlink()
        elif link.exists():
            shutil.copytree(link, target, dirs_exist_ok=True)
            shutil.rmtree(link)
        link.symlink_to(target, target_is_directory=True)


def library_roster(
    project: Project,
    *,
    pin_cast: list[str],
    pin_places: list[str],
    acts: int | None,
) -> Roster:
    """The project's characters and places the story can name (a slug that is not a valid plan id,
    such as one with a '-', cannot be used in a shot spec and is left out), and the pins."""
    usable = lambda slugs: [s for s in slugs if _ID_RE.match(s)]  # noqa: E731
    return Roster(
        cast=usable(c["slug"] for c in project.list_characters()),
        places=usable(b["slug"] for b in project.list_backgrounds()),
        pin_cast=pin_cast,
        pin_places=pin_places,
        acts=acts,
    )


def check_pins(project: Project, pin_cast: list[str], pin_places: list[str]) -> list[str]:
    """What the owner pinned that the library does not have (a pin is a promise to reuse it)."""
    have_c = {c["slug"] for c in project.list_characters()}
    have_p = {b["slug"] for b in project.list_backgrounds()}
    return [f"character {c!r}" for c in pin_cast if c not in have_c] + [
        f"place {p!r}" for p in pin_places if p not in have_p
    ]


def add_library_items(project: Project, film: str, cast: list[str], places: list[str]) -> list[str]:
    """Put the story's library characters and places into the film (latest version, pinned now).
    Returns what was added. Items the library lacks are skipped: the art stages make them."""
    added: list[str] = []
    film_doc = project.get_film(film)
    in_cast = {r["id"] for r in film_doc["cast"]}
    in_places = {r["id"] for r in film_doc["places"]}
    have_c = {c["slug"]: c["id"] for c in project.list_characters()}
    have_p = {b["slug"]: b["id"] for b in project.list_backgrounds()}
    for slug in cast:
        if slug in have_c and have_c[slug] not in in_cast:
            project.add_film_reference(film, "character", slug)
            added.append(slug)
    for slug in places:
        if slug in have_p and have_p[slug] not in in_places:
            project.add_film_reference(film, "background", slug)
            added.append(slug)
    return added
