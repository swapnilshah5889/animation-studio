"""One contract suite for every ProjectStore (D-084); a future database store must pass it as is.

Add an implementation by adding a fixture param; nothing below knows which store it is running on.
"""

from __future__ import annotations

import hashlib
import io
import threading

import pytest

from studio_core.store import (
    FileSystemStore,
    InvalidDocument,
    MemoryStore,
    NotFound,
    ProjectStore,
    RevConflict,
    new_id,
)


@pytest.fixture(params=["memory", "filesystem"])
def store(request, tmp_path) -> ProjectStore:
    return MemoryStore() if request.param == "memory" else FileSystemStore(tmp_path / "projects")


def doc(project="p1", kind="note", doc_id="a1", parent=None, **extra) -> dict:
    out = {
        "schema_version": 1,
        "kind": kind,
        "id": doc_id,
        "project_id": project,
        "owner_id": "local",
        **extra,
    }
    if parent:
        out["parent_id"] = parent
    return out


# ------------------------------------------------------------------ documents


def test_put_get_roundtrip_sets_rev_and_timestamps(store):
    stored = store.put_document(doc(text="hi"))
    assert stored["rev"] == 1
    assert stored["created_at"] == stored["updated_at"]
    assert store.get_document("p1", "note", "a1") == stored


def test_update_bumps_rev_and_keeps_created_at(store):
    first = store.put_document(doc(text="v1"))
    second = store.put_document({**first, "text": "v2"}, expected_rev=1)
    assert second["rev"] == 2
    assert second["created_at"] == first["created_at"]
    assert store.get_document("p1", "note", "a1")["text"] == "v2"


def test_stale_rev_is_rejected_and_nothing_changes(store):
    first = store.put_document(doc(text="v1"))
    store.put_document({**first, "text": "mine"}, expected_rev=1)
    with pytest.raises(RevConflict):
        store.put_document({**first, "text": "theirs"}, expected_rev=1)
    assert store.get_document("p1", "note", "a1")["text"] == "mine"


def test_create_refuses_to_overwrite_and_update_needs_existing(store):
    store.put_document(doc())
    with pytest.raises(RevConflict):
        store.put_document(doc())  # create over an existing one
    with pytest.raises(RevConflict):
        store.put_document(doc(doc_id="nope"), expected_rev=1)  # update of a missing one


def test_two_writers_one_rev_exactly_one_wins(store):
    store.put_document(doc(n=0))
    results: list[str] = []

    def writer(tag: str) -> None:
        try:
            store.put_document(doc(n=tag), expected_rev=1)
            results.append("ok")
        except RevConflict:
            results.append("conflict")

    threads = [threading.Thread(target=writer, args=(str(i),)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["conflict"] * 7 + ["ok"]
    assert store.get_document("p1", "note", "a1")["rev"] == 2


def test_get_missing_raises_not_found(store):
    with pytest.raises(NotFound):
        store.get_document("p1", "note", "missing")


def test_returned_documents_are_copies(store):
    store.put_document(doc(tags=["a"]))
    got = store.get_document("p1", "note", "a1")
    got["tags"].append("b")
    assert store.get_document("p1", "note", "a1")["tags"] == ["a"]


def test_project_scoping_same_id_in_two_projects(store):
    store.put_document(doc(project="p1", text="one"))
    store.put_document(doc(project="p2", text="two"))
    assert store.get_document("p1", "note", "a1")["text"] == "one"
    assert store.get_document("p2", "note", "a1")["text"] == "two"
    assert [d["text"] for d in store.list_documents("p1", "note")] == ["one"]
    with pytest.raises(NotFound):
        store.get_document("p3", "note", "a1")


def test_delete_in_one_project_leaves_the_other(store):
    store.put_document(doc(project="p1"))
    store.put_document(doc(project="p2"))
    store.delete_document("p1", "note", "a1")
    assert store.list_documents("p1", "note") == []
    assert len(store.list_documents("p2", "note")) == 1
    with pytest.raises(NotFound):
        store.delete_document("p1", "note", "a1")


def test_delete_respects_expected_rev(store):
    store.put_document(doc())
    with pytest.raises(RevConflict):
        store.delete_document("p1", "note", "a1", expected_rev=7)
    store.delete_document("p1", "note", "a1", expected_rev=1)


def test_list_by_kind_sorted_by_id_and_filtered_by_parent(store):
    for doc_id, parent in (("b", "f1"), ("a", "f1"), ("c", "f2")):
        store.put_document(doc(kind="act", doc_id=doc_id, parent=parent))
    store.put_document(doc(kind="note", doc_id="n"))
    assert [d["id"] for d in store.list_documents("p1", "act")] == ["a", "b", "c"]
    assert [d["id"] for d in store.list_documents("p1", "act", parent_id="f1")] == ["a", "b"]
    assert [d["id"] for d in store.list_documents("p1", "note")] == ["n"]
    assert store.list_documents("p1", "shot") == []


def test_get_finds_a_film_scoped_document_without_its_parent(store):
    store.put_document(doc(kind="act", doc_id="x", parent="f9"))
    assert store.get_document("p1", "act", "x")["parent_id"] == "f9"


def test_project_level_kinds_roundtrip_and_list_projects(store):
    for kind in ("project", "character", "background", "film"):
        store.put_document(doc(project="p1", kind=kind, doc_id="d1"))
    store.put_document(doc(project="p0", kind="project", doc_id="p0"))
    assert store.list_projects() == ["p0", "p1"]
    for kind in ("character", "background", "film"):
        assert [d["id"] for d in store.list_documents("p1", kind)] == ["d1"]


@pytest.mark.parametrize(
    "bad",
    [
        {"schema_version": 2},
        {"project_id": "../escape"},
        {"id": "a/b"},
        {"kind": "../x"},
        {"owner_id": ""},
        {"path": "/Users/me/film/x.png"},
        {"nested": {"list": ["ok", "C:\\films\\x.png"]}},
        {"home": "~/films"},
    ],
)
def test_envelope_and_no_paths_rules(store, bad):
    with pytest.raises(InvalidDocument):
        store.put_document({**doc(), **bad})


def test_missing_envelope_field_and_parent_on_project_level_kind(store):
    broken = doc()
    del broken["owner_id"]
    with pytest.raises(InvalidDocument):
        store.put_document(broken)
    with pytest.raises(InvalidDocument):
        store.put_document(doc(kind="film", parent="f1"))


def test_a_document_cannot_move_to_another_parent(store):
    first = store.put_document(doc(kind="act", doc_id="x", parent="f1"))
    with pytest.raises(InvalidDocument):
        store.put_document({**first, "parent_id": "f2"}, expected_rev=1)


# --------------------------------------------------------------------- assets


def test_asset_is_addressed_by_its_sha256(store):
    data = b"some png bytes"
    record = store.put_asset("p1", data, "image/png")
    digest = hashlib.sha256(data).hexdigest()
    assert record == {"id": digest, "sha256": digest, "mime": "image/png", "bytes": len(data)}
    assert store.asset_exists("p1", digest)
    assert store.open_asset("p1", digest).read() == data


def test_same_bytes_same_id_different_bytes_different_id(store):
    a = store.put_asset("p1", b"aaa", "text/plain")
    again = store.put_asset("p1", io.BytesIO(b"aaa"), "text/plain")  # a stream works too
    b = store.put_asset("p1", b"aab", "text/plain")
    assert a == again
    assert a["id"] != b["id"]


def test_assets_are_scoped_to_their_project(store):
    record = store.put_asset("p1", b"secret", "text/plain")
    assert not store.asset_exists("p2", record["id"])
    with pytest.raises(NotFound):
        store.open_asset("p2", record["id"])


def test_missing_asset(store):
    assert not store.asset_exists("p1", "0" * 64)
    with pytest.raises(NotFound):
        store.open_asset("p1", "0" * 64)


def test_empty_and_large_assets(store):
    assert store.put_asset("p1", b"", "text/plain")["bytes"] == 0
    big = b"x" * (3 * (1 << 20) + 5)
    record = store.put_asset("p1", io.BytesIO(big), "application/octet-stream")
    assert record["bytes"] == len(big)
    assert store.open_asset("p1", record["id"]).read() == big


def test_asset_ids_cannot_escape(store):
    with pytest.raises(InvalidDocument):
        store.asset_exists("p1", "../../project.json")


# ------------------------------------------------------------------------ ids


def test_new_ids_are_ulid_like_and_sort_by_creation():
    ids = [new_id() for _ in range(200)]
    assert all(len(i) == 26 for i in ids)
    assert ids == sorted(ids) and len(set(ids)) == 200
    assert new_id(now_ms=1) < new_id(now_ms=2**40)
