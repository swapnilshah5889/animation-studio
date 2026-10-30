"""In-memory ProjectStore for tests: same contract as the filesystem store, no disk."""

from __future__ import annotations

import copy
import io
import threading
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


class MemoryStore:
    def __init__(self, clock: Clock = utc_now) -> None:
        self._clock = clock
        self._docs: dict[tuple[str, str, str], dict] = {}
        self._assets: dict[tuple[str, str], bytes] = {}
        self._lock = threading.RLock()

    def list_projects(self) -> list[str]:
        with self._lock:
            return sorted(p for (p, kind, _), _d in self._docs.items() if kind == "project")

    def get_document(self, project_id: str, kind: str, doc_id: str) -> dict:
        check_ids(project_id, kind, doc_id)
        with self._lock:
            try:
                return copy.deepcopy(self._docs[(project_id, kind, doc_id)])
            except KeyError:
                raise NotFound(f"{kind} {doc_id} not in project {project_id}") from None

    def put_document(self, doc: dict, *, expected_rev: int | None = None) -> dict:
        check_envelope(doc)
        key = (doc["project_id"], doc["kind"], doc["id"])
        with self._lock:
            existing = self._docs.get(key)
            check_rev(existing, expected_rev, key)
            if existing is not None and existing.get("parent_id") != doc.get("parent_id"):
                raise InvalidDocument(f"{doc['kind']} {doc['id']} cannot move to another parent")
            stored = stamp(doc, existing, self._clock())
            self._docs[key] = stored
            return copy.deepcopy(stored)

    def list_documents(
        self, project_id: str, kind: str, *, parent_id: str | None = None
    ) -> list[dict]:
        check_ids(project_id, kind, parent_id)
        with self._lock:
            found = [
                d
                for (p, k, _), d in self._docs.items()
                if p == project_id
                and k == kind
                and (parent_id is None or d.get("parent_id") == parent_id)
            ]
            return [copy.deepcopy(d) for d in sorted(found, key=lambda d: d["id"])]

    def delete_document(
        self, project_id: str, kind: str, doc_id: str, *, expected_rev: int | None = None
    ) -> None:
        check_ids(project_id, kind, doc_id)
        key = (project_id, kind, doc_id)
        with self._lock:
            existing = self._docs.get(key)
            if existing is None:
                raise NotFound(f"{kind} {doc_id} not in project {project_id}")
            if expected_rev is not None and existing["rev"] != expected_rev:
                raise RevConflict(
                    f"{kind} {doc_id} is at rev {existing['rev']}, not {expected_rev}"
                )
            del self._docs[key]

    def put_asset(self, project_id: str, data: bytes | BinaryIO, mime: str) -> AssetRecord:
        check_ids(project_id)
        payload = data if isinstance(data, bytes) else data.read()
        digest = sha256_hex(payload)
        with self._lock:
            self._assets[(project_id, digest)] = payload
        return asset_record(digest, len(payload), mime)

    def open_asset(self, project_id: str, asset_id: str) -> BinaryIO:
        check_ids(project_id, None, asset_id)
        with self._lock:
            try:
                return io.BytesIO(self._assets[(project_id, asset_id)])
            except KeyError:
                raise NotFound(f"asset {asset_id} not in project {project_id}") from None

    def asset_exists(self, project_id: str, asset_id: str) -> bool:
        check_ids(project_id, None, asset_id)
        with self._lock:
            return (project_id, asset_id) in self._assets
