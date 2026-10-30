"""A project film as a working folder: how the servers use the Project API without building paths.

The shot, audio, art and render code works on a film *folder* (characters/<slug>/rig.json,
backgrounds/<slug>/layers.json, shots/<id>/shot.json, audio/...). In a project the source of truth
is the store (D-084), so the folder is **derived data**, rebuilt from the store and safe to delete:

    pull()         store -> folder   cast and places at the versions the film pins, every shot
                                     document as shots/<id>/shot.json, the film's recorded audio
    shot_saved()   folder -> store   a saved shot spec becomes (or updates) a shot document
    sync_audio()   folder -> store   new recordings become assets, shots get their audio snapshot
    publish_*()    folder -> store   a character or background built in the folder becomes a new
                                     version in the project library (only when its files changed)

`shot_spec.FilmFolder` carries a link, so every existing tool keeps working on the folder and the
store sees each change. Nothing here knows an engine (D-030).
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
from pathlib import Path
from typing import Any

from studio_core.project.project import Project, ResolvedVersion
from studio_core.store import AssetRecord, FileSystemStore, NotFound

AUDIO_DIRS = ("dialogue", "lipsync", "music")
PINNED = ".pinned"  # marker in a pulled character/background folder: "<id>:<version>"
_SKIP = {".DS_Store", PINNED}
KINDS = {"character": ("cast", "characters"), "background": ("places", "backgrounds")}


class LinkError(ValueError):
    """The folder and the project disagree in a way the caller can fix; the message says how."""


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _files_under(folder: Path, *, skip: frozenset[str] | set[str] = frozenset()) -> dict[str, Path]:
    return {
        p.relative_to(folder).as_posix(): p
        for p in sorted(folder.rglob("*"))
        if p.is_file()
        and p.name not in _SKIP
        and not p.name.startswith(".tmp-")
        and p.relative_to(folder).as_posix() not in skip
    }


class ProjectLink:
    def __init__(self, project: Project, film_id: str, root: Path, *, act: str | None = None):
        self.project, self.film_id, self.root, self.act = project, film_id, root, act

    # ------------------------------------------------------------------ reading

    @property
    def film(self) -> dict:
        return self.project.get_film(self.film_id)

    @property
    def slug(self) -> str:
        return self.film["slug"]

    def _audio_doc(self) -> dict | None:
        found = self.project.store.list_documents(self.project.id, "audio", parent_id=self.film_id)
        return found[0] if found else None

    def audio_files(self) -> dict[str, AssetRecord]:
        doc = self._audio_doc()
        return doc["files"] if doc else {}

    def shot_docs(self) -> list[dict]:
        return self.project.store.list_documents(self.project.id, "shot", parent_id=self.film_id)

    # --------------------------------------------------------------------- pull

    def pull(self) -> None:
        """Bring the folder up to date with the store. Cheap when nothing changed."""
        film = self.film
        for kind, (field, folder) in KINDS.items():
            for ref in film[field]:
                self._pull_version(kind, self.project.resolve_ref(kind, ref), folder)
        self._pull_shots()
        self._pull_audio()
        self._write_film_json(film)

    def _pull_version(self, kind: str, resolved: ResolvedVersion, folder: str) -> None:
        target = self.root / folder / resolved.slug
        marker = target / PINNED
        want = f"{resolved.id}:{resolved.version}"
        if marker.is_file() and marker.read_text() == want:
            return
        if target.exists():
            shutil.rmtree(target)
        self.project.materialize(resolved, target, mode="clone")
        marker.write_text(want)

    def _write_film_json(self, film: dict) -> None:
        """film.json in the folder, derived from the film document (code reads the style there)."""
        data: dict[str, Any] = {
            "schema_version": 1,
            "slug": film["slug"],
            "title": film["title"],
            "characters": [self.project.resolve_ref("character", r).slug for r in film["cast"]],
        }
        if film.get("style"):
            data["style"] = film["style"]
        _write_if_changed(self.root / "film.json", json.dumps(data, indent=2) + "\n")

    def _pull_shots(self) -> None:
        docs = {d["spec"]["id"]: d["spec"] for d in self.shot_docs()}
        shots = self.root / "shots"
        if shots.is_dir():
            for stale in shots.iterdir():
                if stale.is_dir() and stale.name not in docs:
                    shutil.rmtree(stale)  # the shot was removed from its act
        for shot_id, spec in docs.items():
            _write_if_changed(shots / shot_id / "shot.json", json.dumps(spec, indent=2) + "\n")

    def _pull_audio(self) -> None:
        for rel, record in self.audio_files().items():
            target = self._audio_target(rel)
            if (
                target.is_file()
                and target.stat().st_size == record["bytes"]
                and _sha(target) == record["sha256"]
            ):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with self.project.store.open_asset(self.project.id, record["id"]) as handle:
                target.write_bytes(handle.read())

    def _audio_target(self, rel: str) -> Path:
        sub, name = rel.split("/", 1)
        if sub == "voices":  # voices/<slug>.json is characters/<slug>/voice.json in the folder
            return self.root / "characters" / name.removesuffix(".json") / "voice.json"
        return self.root / "audio" / rel

    # ------------------------------------------------------------- shots -> store

    def act_for_new_shot(self) -> str:
        acts = self.project.list_acts(self.film_id)
        if self.act:
            for a in acts:
                if self.act in (a["id"], a["title"], str(a["order"])):
                    return a["id"]
            raise LinkError(f"no act {self.act!r}; acts: {[a['title'] for a in acts] or 'none'}")
        if len(acts) == 1:
            return acts[0]["id"]
        if not acts:
            raise LinkError("the film has no acts yet; add one first (edit_mcp add_act)")
        raise LinkError(
            "the film has several acts: say which one the new shot belongs to (act argument). "
            f"Acts: {[a['title'] for a in acts]}"
        )

    def shot_saved(self, spec: dict[str, Any]) -> None:
        """Called by shot_spec.save before the file is written: record the spec as a shot
        document (a new camera angle in an act, or an edit of an existing one)."""
        audio = self.audio_snapshot(spec)
        for doc in self.shot_docs():
            if doc["spec"]["id"] == spec["id"]:
                if doc["spec"] != spec or doc.get("audio", {}) != audio:
                    self.project.update_shot(doc["id"], spec, audio=audio)
                return
        self.project.add_shot(self.film_id, self.act_for_new_shot(), spec, audio=audio)

    def audio_snapshot(self, spec: dict[str, Any], files: dict | None = None) -> dict:
        """Content ids of the recordings a shot spec names, so the shot document (and so the act's
        cache key) changes when a line is re-recorded, not only when its text is edited."""
        files = self.audio_files() if files is None else files
        lines: dict[str, dict[str, str]] = {}
        for line in spec.get("dialogue", []):
            lid = line["line_id"]
            found = {
                rel: rec["id"]
                for rel, rec in files.items()
                if rel.split("/", 1)[0] in ("dialogue", "lipsync")
                and rel.split("/", 1)[1].rsplit(".", 1)[0] == lid
            }
            if found:
                lines[lid] = found
        out: dict[str, Any] = {}
        if lines:
            out["lines"] = lines
        cue = spec.get("music_cue")
        if cue and f"music/{cue}.wav" in files:
            out["music"] = {cue: files[f"music/{cue}.wav"]["id"]}
        return out

    # ------------------------------------------------------------- audio -> store

    def sync_audio(self) -> int:
        """Record new or changed recordings (lines, mouth cues, music, voices) in the project and
        refresh the audio snapshot of every shot. Returns how many files were new or changed."""
        local: dict[str, Path] = {}
        for sub in AUDIO_DIRS:
            folder = self.root / "audio" / sub
            if folder.is_dir():
                local.update({f"{sub}/{p.name}": p for p in _files_under(folder).values()})
        for voice in sorted((self.root / "characters").glob("*/voice.json")):
            local[f"voices/{voice.parent.name}.json"] = voice
        doc = self.project.film_document(self.film_id, "audio")
        known = doc.get("files", {})
        changed: dict[str, AssetRecord] = {}
        for rel, path in local.items():
            if rel in known and known[rel]["sha256"] == _sha(path):
                continue
            changed[rel] = self._import(path)
        if changed:
            self.project.edit_document(
                "audio", doc["id"], lambda d: d.setdefault("files", {}).update(changed)
            )
        files = {**known, **changed}
        for shot in self.shot_docs():
            snapshot = self.audio_snapshot(shot["spec"], files)
            if snapshot != shot.get("audio", {}):
                self.project.update_shot(shot["id"], shot["spec"], audio=snapshot)
        return len(changed)

    def _import(self, path: Path) -> AssetRecord:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        store = self.project.store
        if isinstance(store, FileSystemStore):
            return store.import_file(self.project.id, path, mime, mode="clone")
        return store.put_asset(self.project.id, path.read_bytes(), mime)

    # --------------------------------------------------------- art -> library

    def publish_character(self, slug: str, *, name: str | None = None, note: str = "") -> dict:
        """Publish characters/<slug>/ of the folder as a new version of that character, add it to
        the film (or move the film to it) and return {id, version, new}. No change = no new
        version. A voice stays with the film's audio, not with the character version."""
        return self._publish("character", slug, name, note, skip={"voice.json"})

    def publish_background(self, slug: str, *, name: str | None = None, note: str = "") -> dict:
        return self._publish("background", slug, name, note, skip=set())

    def _publish(self, kind: str, slug: str, name: str | None, note: str, skip: set[str]) -> dict:
        _, folder = KINDS[kind]
        source = self.root / folder / slug
        if not source.is_dir():
            raise LinkError(f"nothing to publish: {folder}/{slug} does not exist in the film")
        local = _files_under(source, skip=skip)
        shas = {rel: _sha(p) for rel, p in local.items()}
        try:
            versions = self.project.entry(kind, slug)["versions"]
        except NotFound:
            versions = []
        same = [
            v
            for v in versions
            if {r: f["sha256"] for r, f in v["files"].items() if r not in skip} == shas
        ]
        if same:  # nothing changed since a published version: no new version
            ref, new = (
                {"id": self.project.entry(kind, slug)["id"], "version": same[-1]["version"]},
                False,
            )
        else:
            files = {rel: self._import(p) for rel, p in local.items()}
            publish = (
                self.project.publish_character
                if kind == "character"
                else self.project.publish_background
            )
            ref = publish(slug, files, name=name or slug, note=note)
            new = True
        self.project.add_film_reference(self.film_id, kind, ref["id"], ref["version"])
        (source / PINNED).write_text(f"{ref['id']}:{ref['version']}")  # the folder is this version
        return {**ref, "new": new}


def _write_if_changed(path: Path, text: str) -> None:
    if path.is_file() and path.read_text() == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
