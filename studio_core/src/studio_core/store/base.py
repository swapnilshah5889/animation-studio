"""The ProjectStore interface (D-084) and the rules every implementation shares.

Nothing outside a store builds file paths by hand. A store keeps two kinds of things, both scoped
to one project (the tenancy boundary):

* documents: JSON specs with an envelope (schema_version, kind, id, project_id, owner_id,
  created_at, updated_at, rev). `rev` is optimistic concurrency: a write names the rev it read.
* assets: media bytes, content-addressed: the id is the sha256 of the bytes.
"""

from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import BinaryIO, Protocol, TypedDict, runtime_checkable

from studio_core.store.errors import InvalidDocument, RevConflict
from studio_core.store.ids import is_valid_id

SCHEMA_VERSION = 1
LOCAL_OWNER = "local"
# These kinds sit directly under the project; any other kind belongs to a film (parent_id).
PROJECT_LEVEL_KINDS = ("project", "character", "background", "film")

Clock = Callable[[], datetime]
_KIND_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_PATHLIKE_RE = re.compile(r"^(/|~|[A-Za-z]:[\\/]|file:|\\\\)")
_REQUIRED = ("schema_version", "kind", "id", "project_id", "owner_id")


class AssetRecord(TypedDict):
    id: str  # the sha256 hex digest (content address)
    sha256: str
    mime: str
    bytes: int


@runtime_checkable
class ProjectStore(Protocol):
    def list_projects(self) -> list[str]:
        """Ids of the projects that have a project document."""
        ...

    def get_document(self, project_id: str, kind: str, doc_id: str) -> dict:
        """The stored document. Raises NotFound."""
        ...

    def put_document(self, doc: dict, *, expected_rev: int | None = None) -> dict:
        """Create or replace a document and return it as stored (rev, created_at, updated_at set).

        `expected_rev=None` means create: it raises RevConflict if the document exists.
        Otherwise it must equal the stored rev, or RevConflict is raised and nothing changes.
        """
        ...

    def list_documents(
        self, project_id: str, kind: str, *, parent_id: str | None = None
    ) -> list[dict]:
        """Documents of one kind in one project (optionally under one film), sorted by id."""
        ...

    def delete_document(
        self, project_id: str, kind: str, doc_id: str, *, expected_rev: int | None = None
    ) -> None:
        """Remove a document. Raises NotFound; RevConflict if expected_rev is given and stale."""
        ...

    def put_asset(self, project_id: str, data: bytes | BinaryIO, mime: str) -> AssetRecord:
        """Store bytes under their sha256 (idempotent) and return the record."""
        ...

    def open_asset(self, project_id: str, asset_id: str) -> BinaryIO:
        """A readable binary stream of the asset. Raises NotFound."""
        ...

    def asset_exists(self, project_id: str, asset_id: str) -> bool: ...


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_ids(project_id: str, kind: str | None = None, doc_id: str | None = None) -> None:
    """Reject anything that could escape a folder or is not a plain id (applies to every store)."""
    if not is_valid_id(project_id):
        raise InvalidDocument(f"project_id {project_id!r} is not a valid id")
    if kind is not None and not _KIND_RE.match(kind):
        raise InvalidDocument(f"kind {kind!r} must be lower_snake_case")
    if doc_id is not None and not is_valid_id(doc_id):
        raise InvalidDocument(f"id {doc_id!r} is not a valid id")


def _path_strings(value: object, at: str = "") -> list[str]:
    if isinstance(value, str):
        return [at] if _PATHLIKE_RE.match(value) else []
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in _path_strings(v, f"{at}.{k}" if at else k)]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in _path_strings(v, f"{at}[{i}]")]
    return []


def check_envelope(doc: dict) -> None:
    """The rules every document obeys, whatever its kind. Raises InvalidDocument."""
    missing = [k for k in _REQUIRED if k not in doc]
    if missing:
        raise InvalidDocument(f"missing envelope fields: {', '.join(missing)}")
    if doc["schema_version"] != SCHEMA_VERSION:
        raise InvalidDocument(f"schema_version must be {SCHEMA_VERSION}")
    check_ids(doc["project_id"], doc["kind"], doc["id"])
    if not isinstance(doc["owner_id"], str) or not doc["owner_id"]:
        raise InvalidDocument("owner_id must be a non-empty string")
    parent = doc.get("parent_id")
    if parent is not None:
        check_ids(doc["project_id"], None, parent)
        if doc["kind"] in PROJECT_LEVEL_KINDS:
            raise InvalidDocument(f"a {doc['kind']} document cannot have a parent_id")
    bad = _path_strings(doc)
    if bad:
        raise InvalidDocument(f"no paths in specs (D-084); path-like values at: {', '.join(bad)}")


def stamp(doc: dict, existing: dict | None, now: datetime) -> dict:
    """The document as it will be stored: a deep copy with rev and timestamps set by the store."""
    out = copy.deepcopy(doc)
    stamp_time = iso(now)
    out["rev"] = 1 if existing is None else existing["rev"] + 1
    out["created_at"] = stamp_time if existing is None else existing["created_at"]
    out["updated_at"] = stamp_time
    return out


def asset_record(data_sha256: str, size: int, mime: str) -> AssetRecord:
    return {"id": data_sha256, "sha256": data_sha256, "mime": mime, "bytes": size}


def check_rev(existing: dict | None, expected_rev: int | None, key: tuple[str, str, str]) -> None:
    label = f"{key[1]} {key[2]}"
    if expected_rev is None:
        if existing is not None:
            raise RevConflict(f"{label} already exists (rev {existing['rev']}); pass expected_rev")
    elif existing is None:
        raise RevConflict(f"{label} does not exist; cannot update from rev {expected_rev}")
    elif existing["rev"] != expected_rev:
        raise RevConflict(f"{label} is at rev {existing['rev']}, not {expected_rev}")
