"""Where the servers find a film: one place, so no server builds a film path by hand (D-082, D-084).

Two kinds of film, one door:

    ws = Workspace.from_config()
    ws.open_film("step4-demo")                              # legacy: films/step4-demo, as always
    ws.open_film("the-lost-kite", project="pip-and-friends")  # a film of a project

Both return a `shot_spec.FilmFolder`, so every tool that works on a film folder keeps working.
A legacy film *is* the folder. A project film's folder is derived data under the work directory
(`<studio_root>/work/<project>/<film>/`), rebuilt from the store on every open (`ProjectLink.pull`)
and safe to delete; the store holds the specs, the library versions and the audio (the source).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from studio_core.config import REPO_ROOT, StudioConfig, expand_path, load_config
from studio_core.project import Project
from studio_core.project.link import ProjectLink
from studio_core.shot_spec import FILM_SLUG, FilmFolder, SpecError
from studio_core.store import FileSystemStore, NotFound


@dataclass(frozen=True)
class Workspace:
    films_root: Path  # legacy film folders: films/<slug>
    projects_root: Path | None = None  # projects/<id>/ (FileSystemStore)
    work_root: Path | None = None  # derived working folders of project films
    sfx_root: Path | None = None  # the sound library; None = config [paths] sfx_library

    @classmethod
    def from_config(
        cls, cfg: StudioConfig | None = None, *, films_root: Path | None = None
    ) -> Workspace:
        cfg = cfg or load_config()
        studio_root = expand_path(cfg.get("paths", "studio_root", "~/ai-studio"))
        return cls(
            films_root=films_root or cfg.path("paths", "films"),
            projects_root=expand_path(cfg.get("paths", "projects", "projects")),
            work_root=expand_path(cfg.get("paths", "work", str(studio_root / "work"))),
        )

    # ------------------------------------------------------------------ projects

    def store(self) -> FileSystemStore:
        if self.projects_root is None:
            raise SpecError("projects are not set up (no projects folder configured)")
        return FileSystemStore(self.projects_root)

    def project_ids(self) -> list[str]:
        if self.projects_root is None or not self.projects_root.is_dir():
            return []
        return self.store().list_projects()

    def open_project(self, project: str) -> Project:
        known = self.project_ids()
        if project not in known:
            raise SpecError(f"no project {project!r}; projects: {known or 'none yet'}")
        return Project.open(self.store(), project)

    # --------------------------------------------------------------------- films

    def open_film(
        self,
        film: str,
        project: str | None = None,
        *,
        act: str | None = None,
        sfx_root: Path | None = None,
        pull: bool = True,
    ) -> FilmFolder:
        """The film's folder. `project` None = a legacy film folder. With a project, `film` is the
        film's slug or id and `act` (an act id or title) says where a *new* shot goes."""
        sfx = sfx_root or self.sfx_root
        if project is None:
            return FilmFolder.open(self.films_root, film, sfx_root=sfx)
        proj = self.open_project(project)
        try:
            doc = proj.get_film(film)
        except NotFound:
            known = [f["slug"] for f in proj.list_films()]
            raise SpecError(
                f"no film {film!r} in project {project}; films: {known or 'none'}"
            ) from None
        if not FILM_SLUG.match(doc["slug"].replace("_", "-")):
            raise SpecError(f"film slug {doc['slug']!r} cannot be a folder name")
        work = self.work_root or REPO_ROOT / "cache" / "work"
        link = ProjectLink(proj, doc["id"], work / proj.id / doc["slug"], act=act)
        link.root.mkdir(parents=True, exist_ok=True)
        if pull:
            link.pull()
        return FilmFolder(link.root, sfx, link=link)
