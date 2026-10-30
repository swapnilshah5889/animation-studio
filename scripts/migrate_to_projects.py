"""Build a project from the old flat film folders (Step 5B, D-082). Dry-run unless --apply.

    uv run scripts/migrate_to_projects.py                       # show the plan, write nothing
    uv run scripts/migrate_to_projects.py --apply               # build projects/test-cast/
    uv run scripts/migrate_to_projects.py --apply --only real-15s,step4-cast

Each `films/<name>/characters/<slug>/` and `backgrounds/<slug>/` folder becomes a *version* of a
character or background in the project; identical folders in different films become one version, a
changed one becomes the next version. Each old film becomes a film document that references them.
Files are not copied twice: they enter the content-addressed store by copy-on-write clone (APFS),
else hard link, else copy (`--mode`). The old folders are only read, never changed or deleted, and
the old tools keep reading them. Re-running is safe: it finds what is already there and adds only
what is new. Shots, audio and edits stay in the old folders for now (adoption is a later task).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import sys
from dataclasses import dataclass, field
from pathlib import Path

from studio_core.config import REPO_ROOT
from studio_core.project import Project
from studio_core.store import FileSystemStore, NotFound, ProjectStore

IGNORED = {".DS_Store"}


@dataclass
class Unit:
    """One character or background folder as it is in one old film."""

    kind: str  # "character" | "background"
    slug: str
    film: str
    root: Path
    files: dict[str, str]  # relative path -> sha256

    @property
    def signature(self) -> dict[str, str]:
        return self.files


@dataclass
class FilmPlan:
    slug: str
    title: str
    style: str | None
    units: list[Unit] = field(default_factory=list)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def scan_unit(kind: str, root: Path, film: str) -> Unit:
    files = {
        p.relative_to(root).as_posix(): _sha(p)
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name not in IGNORED and not p.name.startswith(".tmp-")
    }
    return Unit(kind, root.name, film, root, files)


def scan_films(films_dir: Path, only: set[str] | None = None) -> list[FilmPlan]:
    plans = []
    for folder in sorted(p for p in films_dir.iterdir() if (p / "film.json").is_file()):
        if only and folder.name not in only:
            continue
        meta = json.loads((folder / "film.json").read_text())
        plan = FilmPlan(folder.name, meta.get("title") or folder.name, meta.get("style"))
        for kind, sub in (("character", "characters"), ("background", "backgrounds")):
            base = folder / sub
            for unit_dir in (
                sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
            ):
                unit = scan_unit(kind, unit_dir, folder.name)
                if unit.files:
                    plan.units.append(unit)
        plans.append(plan)
    return plans


def _existing_versions(project: Project | None, kind: str, slug: str) -> list[dict]:
    if project is None:
        return []
    try:
        return project.entry(kind, slug)["versions"]
    except NotFound:
        return []


def plan_versions(
    plans: list[FilmPlan], project: Project | None
) -> dict[tuple[str, str], list[dict]]:
    """For every (kind, slug): its distinct folder contents in order, each with whether the project
    already has it. Existing project versions come first so a re-run never renumbers anything."""
    out: dict[tuple[str, str], list[dict]] = {}
    for plan in plans:
        for unit in plan.units:
            key = (unit.kind, unit.slug)
            if key not in out:
                out[key] = [
                    {
                        "files": {r: f["sha256"] for r, f in v["files"].items()},
                        "unit": None,
                        "have": True,
                    }
                    for v in _existing_versions(project, *key)
                ]
            versions = out[key]
            if not any(v["files"] == unit.signature for v in versions):
                versions.append({"files": unit.signature, "unit": unit, "have": False})
    return out


def apply_plan(
    plans: list[FilmPlan], project: Project, store: ProjectStore, mode: str
) -> dict[str, int]:
    done = {"versions": 0, "films": 0}
    for (kind, slug), versions in plan_versions(plans, project).items():
        for v in versions:
            if v["have"]:
                continue
            unit: Unit = v["unit"]
            files = {}
            for rel in unit.files:
                path = unit.root / rel
                mime = mimetypes.guess_type(rel)[0] or "application/octet-stream"
                files[rel] = _import(store, project.id, path, mime, mode)
            note = f"imported from films/{unit.film}"
            publish = (
                project.publish_character if kind == "character" else project.publish_background
            )
            publish(slug, files, note=note)
            done["versions"] += 1
    done["films"] = _create_films(plans, project)
    return done


def _import(store: ProjectStore, project_id: str, path: Path, mime: str, mode: str):
    if isinstance(store, FileSystemStore):
        return store.import_file(project_id, path, mime, mode=mode)
    with path.open("rb") as handle:
        return store.put_asset(project_id, handle, mime)


def _version_of(project: Project, kind: str, unit: Unit) -> int:
    for entry_version in project.entry(kind, unit.slug)["versions"]:
        if {r: f["sha256"] for r, f in entry_version["files"].items()} == unit.signature:
            return entry_version["version"]
    raise RuntimeError(f"{kind} {unit.slug} from {unit.film} is not in the project")


def _create_films(plans: list[FilmPlan], project: Project) -> int:
    existing = {f["slug"] for f in project.list_films()}
    created = 0
    for plan in plans:
        if plan.slug in existing:
            continue
        refs = {"character": [], "background": []}
        for unit in plan.units:
            entry = project.entry(unit.kind, unit.slug)
            refs[unit.kind].append(
                {"id": entry["id"], "version": _version_of(project, unit.kind, unit)}
            )
        project.create_film(
            plan.title,
            slug=plan.slug,
            cast=refs["character"],
            places=refs["background"],
            style=plan.style,
            source={"type": "legacy-film-folder", "folder": f"films/{plan.slug}"},
        )
        created += 1
    return created


def report(plans: list[FilmPlan], versions: dict, project: Project | None) -> str:
    lines = []
    for (kind, slug), vs in sorted(versions.items()):
        for number, v in enumerate(vs, start=1):
            if v["have"]:
                lines.append(f"  {kind:<10} {slug:<14} v{number}  already in the project")
            else:
                unit = v["unit"]
                size = sum((unit.root / r).stat().st_size for r in unit.files) / 1e6
                lines.append(
                    f"  {kind:<10} {slug:<14} v{number}  NEW from films/{unit.film} "
                    f"({len(unit.files)} files, {size:.1f} MB; content already stored is shared)"
                )
    have = {f["slug"] for f in project.list_films()} if project else set()
    for plan in plans:
        state = "already in the project" if plan.slug in have else "NEW"
        lines.append(f"  film       {plan.slug:<14} {state} ({len(plan.units)} characters/places)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--films-dir", type=Path, default=REPO_ROOT / "films")
    parser.add_argument("--projects-dir", type=Path, default=REPO_ROOT / "projects")
    parser.add_argument("--project", default="test-cast", help="project id (default: test-cast)")
    parser.add_argument("--only", help="comma-separated film folder names")
    parser.add_argument("--mode", choices=["auto", "clone", "link", "copy"], default="auto")
    parser.add_argument("--apply", action="store_true", help="write the project (default: dry-run)")
    args = parser.parse_args(argv)

    store = FileSystemStore(args.projects_dir)
    only = set(args.only.split(",")) if args.only else None
    plans = scan_films(args.films_dir, only)
    project = Project.open(store, args.project) if args.project in store.list_projects() else None
    versions = plan_versions(plans, project)
    print(
        f"{'APPLY' if args.apply else 'DRY RUN'}: {len(plans)} old films -> project {args.project}"
    )
    print(report(plans, versions, project))
    if not args.apply:
        print("\nNothing written. Re-run with --apply.")
        return 0
    if project is None:
        project = Project.create(
            store,
            name="Test cast",
            premise="The test characters and places, imported from the old film folders.",
            project_id=args.project,
            style=next((p.style for p in plans if p.style), None),
        )
    done = apply_plan(plans, project, store, args.mode)
    print(f"\nAdded {done['versions']} versions and {done['films']} films. Old folders untouched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
