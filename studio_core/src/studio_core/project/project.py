"""The Project API: one project's characters, backgrounds and films, on top of any ProjectStore.

    project = Project.create(store, name="Pip and friends")
    kit = project.publish_character("kit", {"rig.json": rig_bytes, "parts/head.png": head_bytes})
    orchard = project.publish_background("orchard", {"plate.png": plate_bytes})
    film = project.create_film("The Lost Kite", cast=["kit"], places=["orchard"])
    act = project.add_act(film["id"], "Morning", background="orchard", cast=["kit"], beats=["..."])

Films and acts hold `{id, version}` references, never copies and never paths. A published character
or background version is immutable; improving one publishes the next version, and a film moves to it
only when you ask (`upgrade_reference`), so finished films keep rendering the same (D-082).
All reads and writes go through the store, so this works unchanged on a database store later.
"""

from __future__ import annotations

import mimetypes
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from studio_core.project.staleness import act_cache_key, is_stale
from studio_core.project.validation import validate_document
from studio_core.store import (
    LOCAL_OWNER,
    SCHEMA_VERSION,
    AssetRecord,
    InvalidDocument,
    NotFound,
    ProjectStore,
    RevConflict,
    new_id,
)
from studio_core.store.base import iso, utc_now
from studio_core.store.filesystem import place_file

Ref = dict[str, Any]  # {"id": ..., "version": n}
FileInput = bytes | AssetRecord
_RETRIES = 4
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,59}$")


class ImmutableVersionError(InvalidDocument):
    """A published character or background version may not change; publish a new version."""


@dataclass(frozen=True)
class ResolvedVersion:
    """One version of a character or background, ready to read."""

    kind: str  # "character" | "background"
    id: str
    slug: str
    name: str
    version: int
    files: Mapping[str, AssetRecord]

    @property
    def ref(self) -> Ref:
        return {"id": self.id, "version": self.version}


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].strip("-")
    return slug or "untitled"


def check_versions_append_only(old: Sequence[Mapping], new: Sequence[Mapping]) -> None:
    if len(new) < len(old) or any(a != b for a, b in zip(old, new, strict=False)):
        raise ImmutableVersionError("published versions are immutable; publish a new version")


class Project:
    def __init__(self, store: ProjectStore, project_id: str, *, owner_id: str = LOCAL_OWNER):
        self.store, self.id, self.owner_id = store, project_id, owner_id
        self.doc = store.get_document(project_id, "project", project_id)

    # ----------------------------------------------------------------- lifecycle

    @classmethod
    def create(
        cls,
        store: ProjectStore,
        *,
        name: str,
        premise: str = "",
        style: str | None = None,
        project_id: str | None = None,
        owner_id: str = LOCAL_OWNER,
    ) -> Project:
        pid = project_id or new_id()
        doc: dict[str, Any] = {
            **_envelope("project", pid, pid, owner_id),
            "name": name,
            "premise": premise,
            "status": "active",
        }
        if style:
            doc["style"] = style
        validate_document(doc)
        store.put_document(doc)
        return cls(store, pid, owner_id=owner_id)

    @classmethod
    def open(cls, store: ProjectStore, project_id: str, **kwargs: Any) -> Project:
        return cls(store, project_id, **kwargs)

    # ------------------------------------------------------------------ plumbing

    def _new(self, kind: str, parent_id: str | None = None, doc_id: str | None = None) -> dict:
        doc = _envelope(kind, doc_id or new_id(), self.id, self.owner_id)
        if parent_id:
            doc["parent_id"] = parent_id
        return doc

    def _put(self, doc: dict, *, expected_rev: int | None = None) -> dict:
        validate_document(doc)
        if doc["kind"] in ("character", "background") and expected_rev is not None:
            old = self.store.get_document(self.id, doc["kind"], doc["id"])
            check_versions_append_only(old["versions"], doc["versions"])
        return self.store.put_document(doc, expected_rev=expected_rev)

    def _update(self, kind: str, doc_id: str, change: Callable[[dict], None]) -> dict:
        """Read, change, write; try again when someone else wrote in between."""
        for attempt in range(_RETRIES):
            doc = self.store.get_document(self.id, kind, doc_id)
            change(doc)
            try:
                return self._put(doc, expected_rev=doc["rev"])
            except RevConflict:
                if attempt == _RETRIES - 1:
                    raise
        raise AssertionError("unreachable")

    def _find(self, kind: str, id_or_slug: str, *, parent_id: str | None = None) -> dict:
        try:
            return self.store.get_document(self.id, kind, id_or_slug)
        except (NotFound, InvalidDocument):
            pass
        for doc in self.store.list_documents(self.id, kind, parent_id=parent_id):
            if doc.get("slug") == id_or_slug:
                return doc
        raise NotFound(f"no {kind} {id_or_slug!r} in project {self.id}")

    def _free_slug(self, kind: str, wanted: str) -> str:
        if not _SLUG_RE.match(wanted):
            raise InvalidDocument(f"slug {wanted!r} must be lowercase letters, digits, - or _")
        if any(d["slug"] == wanted for d in self.store.list_documents(self.id, kind)):
            raise InvalidDocument(f"a {kind} with slug {wanted!r} already exists")
        return wanted

    # ------------------------------------------- characters and backgrounds (library)

    def list_characters(self) -> list[dict]:
        return self.store.list_documents(self.id, "character")

    def list_backgrounds(self) -> list[dict]:
        return self.store.list_documents(self.id, "background")

    def list_films(self) -> list[dict]:
        return self.store.list_documents(self.id, "film")

    def entry(self, kind: str, id_or_slug: str) -> dict:
        """A character or background entry document (all its versions), by id or slug."""
        return self._find(kind, id_or_slug)

    def publish_character(self, slug: str, files: Mapping[str, FileInput], **kw: Any) -> Ref:
        return self._publish("character", slug, files, **kw)

    def publish_background(self, slug: str, files: Mapping[str, FileInput], **kw: Any) -> Ref:
        return self._publish("background", slug, files, **kw)

    def _publish(
        self,
        kind: str,
        slug: str,
        files: Mapping[str, FileInput],
        *,
        name: str | None = None,
        description: str = "",
        note: str = "",
    ) -> Ref:
        """Add a version: the first publish of a slug creates the entry (version 1), later ones
        append the next version. Earlier versions are never touched."""
        if not files:
            raise InvalidDocument("a version needs at least one file")
        records = {rel: self._asset(rel, data) for rel, data in files.items()}
        version = {"created_at": iso(utc_now()), "files": records}
        if note:
            version["note"] = note
        try:
            entry = self._find(kind, slug)
        except NotFound:
            entry = None
        if entry is None:
            doc = self._new(kind)
            doc.update(slug=self._free_slug(kind, slug), name=name or slug, versions=[])
            if description:
                doc["description"] = description
            self._append_version(doc, version)
            stored = self._put(doc)
        else:
            stored = self._update(kind, entry["id"], lambda d: self._append_version(d, version))
        return {"id": stored["id"], "version": stored["versions"][-1]["version"]}

    @staticmethod
    def _append_version(doc: dict, version: dict) -> None:
        doc["versions"] = [*doc["versions"], {"version": len(doc["versions"]) + 1, **version}]

    def _asset(self, rel: str, data: FileInput) -> AssetRecord:
        if isinstance(data, Mapping):
            if not self.store.asset_exists(self.id, data["id"]):
                raise InvalidDocument(f"{rel}: asset {data['id']} is not in this project")
            return dict(data)  # type: ignore[return-value]
        mime = mimetypes.guess_type(rel)[0] or "application/octet-stream"
        return self.store.put_asset(self.id, data, mime)

    def resolve_character(self, id_or_slug: str, version: int | None = None) -> ResolvedVersion:
        return self._resolve("character", id_or_slug, version)

    def resolve_background(self, id_or_slug: str, version: int | None = None) -> ResolvedVersion:
        return self._resolve("background", id_or_slug, version)

    def resolve_ref(self, kind: str, ref: Mapping[str, Any]) -> ResolvedVersion:
        return self._resolve(kind, ref["id"], ref["version"])

    def _resolve(self, kind: str, id_or_slug: str, version: int | None) -> ResolvedVersion:
        entry = self._find(kind, id_or_slug)
        wanted = version if version is not None else len(entry["versions"])
        if not 1 <= wanted <= len(entry["versions"]):
            raise NotFound(f"{kind} {entry['slug']} has no version {wanted}")
        found = entry["versions"][wanted - 1]
        return ResolvedVersion(
            kind, entry["id"], entry["slug"], entry["name"], found["version"], found["files"]
        )

    def read_file(self, resolved: ResolvedVersion, rel: str) -> bytes:
        with self.store.open_asset(self.id, resolved.files[rel]["id"]) as handle:
            return handle.read()

    def materialize(self, resolved: ResolvedVersion, dest: Path, *, mode: str = "auto") -> Path:
        """Lay a version out as a normal folder (rig.json, parts/...) for tools that need files.

        On a filesystem store the files are cloned or linked, not copied (mode as in
        FileSystemStore.import_file). The folder is derived data: delete it any time."""
        local = getattr(self.store, "asset_path", None)
        for rel, record in resolved.files.items():
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target.unlink()
            if local is not None:
                place_file(local(self.id, record["id"]), target, mode)
            else:
                target.write_bytes(self.read_file(resolved, rel))
        return dest

    # --------------------------------------------------------------------- films

    def create_film(
        self,
        title: str,
        *,
        slug: str | None = None,
        cast: Iterable[str | Mapping[str, Any]] = (),
        places: Iterable[str | Mapping[str, Any]] = (),
        premise: str = "",
        style: str | None = None,
        source: Mapping[str, Any] | None = None,
    ) -> dict:
        """Start a film that references project characters and backgrounds (by id, slug or
        {id, version}; a plain id or slug pins the latest version now)."""
        doc = self._new("film")
        doc.update(
            slug=self._free_slug("film", slug or slugify(title)),
            title=title,
            cast=self._refs("character", cast),
            places=self._refs("background", places),
        )
        if premise:
            doc["premise"] = premise
        style = style or self.doc.get("style")
        if style:
            doc["style"] = style
        if source:
            doc["source"] = dict(source)
        return self._put(doc)

    def _refs(self, kind: str, items: Iterable[str | Mapping[str, Any]]) -> list[Ref]:
        out: list[Ref] = []
        for item in items:
            if isinstance(item, str):
                ref = self._resolve(kind, item, None).ref
            else:
                ref = self._resolve(kind, item["id"], item.get("version")).ref
            if any(r["id"] == ref["id"] for r in out):
                raise InvalidDocument(f"{kind} {ref['id']} listed twice")
            out.append(ref)
        return out

    def get_film(self, id_or_slug: str) -> dict:
        return self._find("film", id_or_slug)

    def upgrade_reference(self, film: str, kind: str, id_or_slug: str, version: int | None = None):
        """Move a film (and its acts) to another version of one character or background; the
        latest by default. Acts that use it get a new cache key, so they render again."""
        film_doc = self.get_film(film)
        target = self._resolve(kind, id_or_slug, version)
        field = "cast" if kind == "character" else "places"

        def bump(refs: list[Ref]) -> None:
            for ref in refs:
                if ref["id"] == target.id:
                    ref["version"] = target.version

        def change_film(doc: dict) -> None:
            if not any(r["id"] == target.id for r in doc[field]):
                raise InvalidDocument(f"{target.slug} is not in film {doc['slug']}'s {field}")
            bump(doc[field])

        updated = self._update("film", film_doc["id"], change_film)
        for act in self.list_acts(film_doc["id"]):
            self._update("act", act["id"], lambda d: (bump(d["cast"]), bump([d["background"]])))
        return updated

    # --------------------------------------------------------------- acts, shots

    def list_acts(self, film: str) -> list[dict]:
        film_id = self.get_film(film)["id"]
        acts = self.store.list_documents(self.id, "act", parent_id=film_id)
        return sorted(acts, key=lambda a: a["order"])

    def get_act(self, film: str, act_id: str) -> dict:
        return self.store.get_document(self.id, "act", act_id)

    def add_act(
        self,
        film: str,
        title: str,
        *,
        background: str | Mapping[str, Any],
        cast: Iterable[str | Mapping[str, Any]] | None = None,
        beats: Iterable[str] = (),
    ) -> dict:
        """Append an act. Its background and cast must belong to the film; by default the cast is
        the whole film cast, and versions are the film's."""
        film_doc = self.get_film(film)
        place = self._within(film_doc["places"], "background", background)
        if cast is None:
            members = [dict(r) for r in film_doc["cast"]]
        else:
            members = [self._within(film_doc["cast"], "character", c) for c in cast]
        doc = self._new("act", film_doc["id"])
        doc.update(
            order=len(self.list_acts(film_doc["id"])) + 1,
            title=title,
            background=place,
            cast=members,
            beats=list(beats),
            shot_ids=[],
        )
        return self._put(doc)

    def _within(self, film_refs: list[Ref], kind: str, item: str | Mapping[str, Any]) -> Ref:
        wanted = self._resolve(kind, item if isinstance(item, str) else item["id"], None)
        for ref in film_refs:
            if ref["id"] == wanted.id:
                return dict(ref)  # the film's pinned version
        raise InvalidDocument(f"{kind} {wanted.slug} is not in the film; add it to the film first")

    def reorder_acts(self, film: str, act_ids: Sequence[str]) -> list[dict]:
        current = {a["id"] for a in self.list_acts(film)}
        if set(act_ids) != current or len(act_ids) != len(current):
            raise InvalidDocument("reorder_acts needs every act id of the film exactly once")
        for order, act_id in enumerate(act_ids, start=1):
            self._update("act", act_id, lambda d, o=order: d.update(order=o))
        return self.list_acts(film)

    def update_act(self, act_id: str, **fields: Any) -> dict:
        """Edit an act's title, beats or cast (the editable source). Background and shots have
        their own calls."""
        unknown = set(fields) - {"title", "beats", "cast"}
        if unknown:
            raise InvalidDocument(f"cannot edit {sorted(unknown)} here")
        return self._update("act", act_id, lambda d: d.update(fields))

    def add_shot(self, film: str, act_id: str, spec: dict, *, shot_id: str | None = None) -> dict:
        """Add a camera angle to an act: the engine-neutral shot spec as a document."""
        film_id = self.get_film(film)["id"]
        doc = self._new("shot", film_id, shot_id)
        doc.update(act_id=act_id, spec=spec)
        stored = self._put(doc)
        self._update("act", act_id, lambda d: d["shot_ids"].append(stored["id"]))
        return stored

    def update_shot(self, shot_id: str, spec: dict) -> dict:
        return self._update("shot", shot_id, lambda d: d.update(spec=spec))

    def list_shots(self, film: str, act_id: str) -> list[dict]:
        """The act's shots in the act's own order."""
        act = self.store.get_document(self.id, "act", act_id)
        return [self.store.get_document(self.id, "shot", s) for s in act["shot_ids"]]

    # ---------------------------------------------------------------- staleness

    def act_key(self, film: str, act_id: str, engine_id: str) -> str:
        film_doc = self.get_film(film)
        act = self.store.get_document(self.id, "act", act_id)
        extra = {"style": film_doc.get("style")}
        return act_cache_key(act, self.list_shots(film, act_id), engine_id, extra=extra)

    def last_render(self, act_id: str) -> dict | None:
        try:
            return self.store.get_document(self.id, "act_render", act_id)
        except NotFound:
            return None

    def is_act_stale(self, film: str, act_id: str, engine_id: str) -> bool:
        return is_stale(self.act_key(film, act_id, engine_id), self.last_render(act_id))

    def stale_acts(self, film: str, engine_id: str) -> list[dict]:
        return [a for a in self.list_acts(film) if self.is_act_stale(film, a["id"], engine_id)]

    def record_render(
        self,
        film: str,
        act_id: str,
        engine_id: str,
        *,
        cache_key: str | None = None,
        video: AssetRecord | None = None,
    ) -> dict:
        """Store the key an act was rendered from, beside its video. Pass the key computed
        *before* rendering so an edit made during the render still shows as stale."""
        film_id = self.get_film(film)["id"]
        key = cache_key or self.act_key(film, act_id, engine_id)
        existing = self.last_render(act_id)
        doc = existing or self._new("act_render", film_id, act_id)
        doc.update(act_id=act_id, cache_key=key, engine=engine_id)
        if video:
            doc["video"] = dict(video)
        else:
            doc.pop("video", None)
        return self._put(doc, expected_rev=existing["rev"] if existing else None)


def _envelope(kind: str, doc_id: str, project_id: str, owner_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "id": doc_id,
        "project_id": project_id,
        "owner_id": owner_id,
    }
