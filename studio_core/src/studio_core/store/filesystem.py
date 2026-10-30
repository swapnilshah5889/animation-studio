"""FileSystemStore: the `projects/<project-id>/...` layout of ROADMAP Step 5B.

    projects/<project-id>/
      project.json
      characters/<id>/character.json        backgrounds/<id>/background.json
      films/<id>/film.json
      films/<film-id>/<kind>s/<id>.json     (acts, shots, ...: documents with a parent_id)
      documents/<kind>/<id>.json            (other documents without a parent)
      assets/<aa>/<sha256>                  (content-addressed media, shared by the whole project)

Writes are atomic (temp file + rename) and the read-check-write of a document is serialised by an
in-process lock plus an advisory `flock` on the project folder, so the director and the MCP servers
(separate processes) cannot both win the same rev. Only this module builds these paths.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from studio_core.store.base import (
    AssetRecord,
    Clock,
    asset_record,
    check_envelope,
    check_ids,
    check_rev,
    sha256_hex,
    stamp,
    utc_now,
)
from studio_core.store.errors import InvalidDocument, NotFound, RevConflict

try:
    import fcntl
except ImportError:  # native Windows: in-process lock only
    fcntl = None  # type: ignore[assignment]

_FOLDER_KINDS = {
    "project": ("", "project.json"),
    "character": ("characters", "character.json"),
    "background": ("backgrounds", "background.json"),
    "film": ("films", "film.json"),
}
_CHUNK = 1 << 20


class FileSystemStore:
    def __init__(self, root: Path, clock: Clock = utc_now) -> None:
        self.root = Path(root)
        self._clock = clock
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ paths

    def _project_dir(self, project_id: str) -> Path:
        check_ids(project_id)
        return self.root / project_id

    def _doc_path(self, project_id: str, kind: str, doc_id: str, parent_id: str | None) -> Path:
        base = self._project_dir(project_id)
        if kind in _FOLDER_KINDS:
            folder, name = _FOLDER_KINDS[kind]
            return base / name if kind == "project" else base / folder / doc_id / name
        if parent_id is not None:
            return base / "films" / parent_id / f"{kind}s" / f"{doc_id}.json"
        return base / "documents" / kind / f"{doc_id}.json"

    def _asset_path(self, project_id: str, asset_id: str) -> Path:
        check_ids(project_id, None, asset_id)
        return self._project_dir(project_id) / "assets" / asset_id[:2] / asset_id

    def asset_path(self, project_id: str, asset_id: str) -> Path:
        """Where an asset lives on disk. Local-only escape hatch (engines that need a real file);
        it is not part of the ProjectStore interface and a database store has no equivalent."""
        return self._asset_path(project_id, asset_id)

    @contextlib.contextmanager
    def _locked(self, project_id: str) -> Iterator[None]:
        with self._lock:
            if fcntl is None:
                yield
                return
            folder = self._project_dir(project_id)
            folder.mkdir(parents=True, exist_ok=True)
            with open(folder / ".lock", "a") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    # -------------------------------------------------------------- documents

    def list_projects(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if (p / "project.json").is_file())

    def _read(self, path: Path) -> dict | None:
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            return None

    def get_document(self, project_id: str, kind: str, doc_id: str) -> dict:
        check_ids(project_id, kind, doc_id)
        for path in self._candidates(project_id, kind, doc_id, None):
            doc = self._read(path)
            if doc is not None:
                return doc
        raise NotFound(f"{kind} {doc_id} not in project {project_id}")

    def _candidates(
        self, project_id: str, kind: str, doc_id: str, parent_id: str | None
    ) -> list[Path]:
        """Where a document may live. A film-scoped document is found without knowing its film."""
        if kind in _FOLDER_KINDS or parent_id is not None:
            return [self._doc_path(project_id, kind, doc_id, parent_id)]
        base = self._project_dir(project_id)
        found = sorted((base / "films").glob(f"*/{kind}s/{doc_id}.json"))
        return [*found, self._doc_path(project_id, kind, doc_id, None)]

    def put_document(self, doc: dict, *, expected_rev: int | None = None) -> dict:
        check_envelope(doc)
        pid, kind, doc_id, parent = doc["project_id"], doc["kind"], doc["id"], doc.get("parent_id")
        path = self._doc_path(pid, kind, doc_id, parent)
        with self._locked(pid):
            existing = None
            for candidate in self._candidates(pid, kind, doc_id, None):
                existing = self._read(candidate)
                if existing is not None:
                    break
            check_rev(existing, expected_rev, (pid, kind, doc_id))
            if existing is not None and existing.get("parent_id") != parent:
                raise InvalidDocument(f"{kind} {doc_id} cannot move to another parent")
            stored = stamp(doc, existing, self._clock())
            self._atomic_write(path, (json.dumps(stored, indent=2, sort_keys=True) + "\n").encode())
        return stored

    def list_documents(
        self, project_id: str, kind: str, *, parent_id: str | None = None
    ) -> list[dict]:
        check_ids(project_id, kind, parent_id)
        base = self._project_dir(project_id)
        if kind == "project":
            paths = [base / "project.json"]
        elif kind in _FOLDER_KINDS:
            folder, name = _FOLDER_KINDS[kind]
            paths = sorted((base / folder).glob(f"*/{name}"))
        elif parent_id is not None:
            paths = sorted((base / "films" / parent_id / f"{kind}s").glob("*.json"))
        else:
            paths = sorted((base / "films").glob(f"*/{kind}s/*.json"))
            paths += sorted((base / "documents" / kind).glob("*.json"))
        docs = [d for d in (self._read(p) for p in paths) if d is not None]
        return sorted(docs, key=lambda d: d["id"])

    def delete_document(
        self, project_id: str, kind: str, doc_id: str, *, expected_rev: int | None = None
    ) -> None:
        check_ids(project_id, kind, doc_id)
        with self._locked(project_id):
            for path in self._candidates(project_id, kind, doc_id, None):
                existing = self._read(path)
                if existing is None:
                    continue
                if expected_rev is not None and existing["rev"] != expected_rev:
                    raise RevConflict(
                        f"{kind} {doc_id} is at rev {existing['rev']}, not {expected_rev}"
                    )
                path.unlink()
                return
        raise NotFound(f"{kind} {doc_id} not in project {project_id}")

    # ----------------------------------------------------------------- assets

    def put_asset(self, project_id: str, data: bytes | BinaryIO, mime: str) -> AssetRecord:
        check_ids(project_id)
        if isinstance(data, bytes):
            digest, size = sha256_hex(data), len(data)
            self._store_asset(project_id, digest, lambda dest: dest.write_bytes(data))
            return asset_record(digest, size, mime)
        with tempfile.TemporaryFile() as spool:  # hash while streaming, then place
            hasher, size = hashlib.sha256(), 0
            while chunk := data.read(_CHUNK):
                hasher.update(chunk)
                spool.write(chunk)
                size += len(chunk)
            digest = hasher.hexdigest()

            def fill(dest: Path) -> None:
                spool.seek(0)
                with dest.open("wb") as out:
                    shutil.copyfileobj(spool, out, _CHUNK)

            self._store_asset(project_id, digest, fill)
        return asset_record(digest, size, mime)

    def import_file(
        self, project_id: str, path: Path, mime: str, *, mode: str = "auto"
    ) -> AssetRecord:
        """Add a file that already exists on disk without a second copy where the disk allows it.

        mode: "clone" (copy-on-write, APFS: no space, safe if the original is later rewritten),
        "link" (hard link: no space, but rewriting the original in place would change the asset),
        "copy", or "auto" (clone, else link, else copy). The asset is still addressed by its hash.
        """
        check_ids(project_id)
        hasher_digest = _file_sha256(path)
        size = path.stat().st_size

        def fill(dest: Path) -> None:
            place_file(path, dest, mode)

        self._store_asset(project_id, hasher_digest, fill)
        return asset_record(hasher_digest, size, mime)

    def _store_asset(self, project_id: str, digest: str, fill) -> None:
        dest = self._asset_path(project_id, digest)
        if dest.exists():
            return  # content-addressed: same bytes are already here
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=".tmp-")
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            tmp.unlink()  # `fill` creates it (a clone or hard link needs the name free)
            fill(tmp)
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)

    def open_asset(self, project_id: str, asset_id: str) -> BinaryIO:
        try:
            return self._asset_path(project_id, asset_id).open("rb")
        except FileNotFoundError:
            raise NotFound(f"asset {asset_id} not in project {project_id}") from None

    def asset_exists(self, project_id: str, asset_id: str) -> bool:
        return self._asset_path(project_id, asset_id).is_file()

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            hasher.update(chunk)
    return hasher.hexdigest()


def place_file(src: Path, dest: Path, mode: str) -> None:
    if mode not in ("auto", "clone", "link", "copy"):
        raise ValueError(f"unknown import mode {mode!r}")
    if mode in ("auto", "clone") and _clone(src, dest):
        return
    if mode in ("auto", "link"):
        try:
            os.link(src, dest)
            return
        except OSError:
            if mode == "link":
                raise
    shutil.copyfile(src, dest)


def _clone(src: Path, dest: Path) -> bool:
    """Copy-on-write clone (macOS `cp -c`). False when the platform or volume cannot."""
    if shutil.which("cp") is None or os.uname().sysname != "Darwin":
        return False
    return subprocess.run(["cp", "-c", str(src), str(dest)], capture_output=True).returncode == 0
