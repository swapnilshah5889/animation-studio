"""scripts/migrate_to_projects.py: dry-run writes nothing, apply is idempotent, old folders stay."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import migrate_to_projects as migrate

from studio_core.project import Project
from studio_core.store import FileSystemStore


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def make_film(films: Path, slug: str, cast: dict[str, bytes], places: dict[str, bytes]) -> None:
    root = films / slug
    write(
        root / "film.json",
        json.dumps({"slug": slug, "title": slug.title(), "style": "storybook"}).encode(),
    )
    for name, rig in cast.items():
        write(root / "characters" / name / "rig.json", rig)
        write(root / "characters" / name / "parts" / "head.png", b"HEAD-" + name.encode())
    for name, plate in places.items():
        write(root / "backgrounds" / name / "plate.png", plate)


def snapshot(root: Path) -> dict[str, tuple[str, float]]:
    return {
        str(p.relative_to(root)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def old_films(tmp_path: Path) -> Path:
    films = tmp_path / "films"
    make_film(films, "a", {"kit": b"kit-1", "bo": b"bo-1"}, {"orchard": b"orchard"})
    make_film(films, "b", {"kit": b"kit-1"}, {"orchard": b"orchard"})  # same cast and place
    make_film(films, "c", {"kit": b"kit-2"}, {})  # kit changed since: a second version
    (films / "no-film-json" / "characters" / "x").mkdir(parents=True)  # ignored: no film.json
    return films


def run(tmp_path: Path, *extra: str) -> int:
    return migrate.main(
        [
            "--films-dir",
            str(tmp_path / "films"),
            "--projects-dir",
            str(tmp_path / "projects"),
            *extra,
        ]
    )


def test_dry_run_writes_nothing(tmp_path, capsys):
    old_films(tmp_path)
    assert run(tmp_path) == 0
    assert not (tmp_path / "projects").exists()
    assert "DRY RUN" in capsys.readouterr().out


def test_apply_builds_a_project_with_references_and_versions(tmp_path):
    old_films(tmp_path)
    assert run(tmp_path, "--apply") == 0
    project = Project.open(FileSystemStore(tmp_path / "projects"), "test-cast")
    assert {c["slug"] for c in project.list_characters()} == {"kit", "bo"}
    assert [b["slug"] for b in project.list_backgrounds()] == ["orchard"]
    assert len(project.entry("character", "kit")["versions"]) == 2  # kit-1 and kit-2
    assert len(project.entry("character", "bo")["versions"]) == 1
    films = {f["slug"]: f for f in project.list_films()}
    assert set(films) == {"a", "b", "c"}
    kit, bo = project.resolve_character("kit", 1), project.resolve_character("bo")
    assert sorted(r["id"] for r in films["a"]["cast"]) == sorted([kit.id, bo.id])
    assert films["b"]["cast"] == [kit.ref]  # the same reference, not a copy
    assert films["a"]["places"] == films["b"]["places"]  # one shared background, not two copies
    assert [r["version"] for r in films["c"]["cast"]] == [2]
    kit_v1 = project.resolve_character("kit", 1)
    assert project.read_file(kit_v1, "rig.json") == b"kit-1"


def test_apply_twice_changes_nothing_and_old_folders_are_untouched(tmp_path, capsys):
    films = old_films(tmp_path)
    before = snapshot(films)
    run(tmp_path, "--apply")
    first = snapshot(tmp_path / "projects")
    capsys.readouterr()
    run(tmp_path, "--apply")
    assert "Added 0 versions and 0 films" in capsys.readouterr().out
    assert snapshot(tmp_path / "projects") == first
    assert snapshot(films) == before


def test_new_old_film_is_added_on_a_later_run(tmp_path):
    films = old_films(tmp_path)
    run(tmp_path, "--apply")
    make_film(films, "d", {"kit": b"kit-2", "bird": b"bird-1"}, {"orchard": b"orchard"})
    run(tmp_path, "--apply")
    project = Project.open(FileSystemStore(tmp_path / "projects"), "test-cast")
    assert {f["slug"] for f in project.list_films()} == {"a", "b", "c", "d"}
    assert len(project.entry("character", "kit")["versions"]) == 2  # kit-2 already known
    assert project.resolve_character("bird").version == 1


def test_link_mode_shares_the_file_instead_of_copying(tmp_path):
    films = old_films(tmp_path)
    run(tmp_path, "--apply", "--mode", "link")
    assert os.stat(films / "a" / "characters" / "bo" / "rig.json").st_nlink >= 2


def test_copy_mode_makes_independent_files(tmp_path):
    films = old_films(tmp_path)
    run(tmp_path, "--apply", "--mode", "copy")
    assert os.stat(films / "a" / "characters" / "bo" / "rig.json").st_nlink == 1
