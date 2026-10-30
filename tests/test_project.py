"""The Project API on both stores: references, versions, acts, staleness (D-082, D-083)."""

from __future__ import annotations

import pytest

from studio_core.project import (
    ImmutableVersionError,
    Project,
    act_cache_key,
    document_issues,
    is_stale,
)
from studio_core.store import FileSystemStore, InvalidDocument, MemoryStore, NotFound

ENGINE = "synfig-1"


@pytest.fixture(params=["memory", "filesystem"])
def store(request, tmp_path):
    return MemoryStore() if request.param == "memory" else FileSystemStore(tmp_path / "projects")


@pytest.fixture
def project(store) -> Project:
    p = Project.create(store, name="Test cast", style="storybook", project_id="test-cast")
    p.publish_character("kit", {"rig.json": b'{"v":1}', "parts/head.png": b"HEAD1"}, name="Kit")
    p.publish_character("bo", {"rig.json": b'{"bo":1}'})
    p.publish_background("orchard", {"plate.png": b"ORCHARD"})
    p.publish_background("meadow", {"plate.png": b"MEADOW"})
    return p


def shot(camera: str) -> dict:
    return {"camera": camera, "duration": 3.0}


@pytest.fixture
def film(project) -> dict:
    f = project.create_film("Two Day Walk", cast=["kit", "bo"], places=["orchard", "meadow"])
    a1 = project.add_act(f["id"], "Morning", background="orchard", beats=["wake up"])
    a2 = project.add_act(f["id"], "Evening", background="meadow", cast=["kit"])
    for act, cams in ((a1, ("wide", "two-shot", "close")), (a2, ("wide", "close", "reaction"))):
        for cam in cams:
            project.add_shot(f["id"], act["id"], shot(cam))
    return f


# ------------------------------------------------------------ library and refs


def test_project_lists_its_library(project):
    assert {c["slug"] for c in project.list_characters()} == {"kit", "bo"}
    assert {b["slug"] for b in project.list_backgrounds()} == {"orchard", "meadow"}


def test_resolve_by_slug_or_id_latest_or_pinned(project):
    kit = project.resolve_character("kit")
    assert kit.version == 1 and set(kit.files) == {"rig.json", "parts/head.png"}
    assert project.resolve_character(kit.id).slug == "kit"
    assert project.read_file(kit, "rig.json") == b'{"v":1}'
    with pytest.raises(NotFound):
        project.resolve_character("kit", 2)
    with pytest.raises(NotFound):
        project.resolve_character("nobody")


def test_two_films_share_characters_and_places_without_copies(project, store):
    f1 = project.create_film("One", cast=["kit"], places=["orchard"])
    f2 = project.create_film("Two", cast=["kit", "bo"], places=["orchard"])
    assert f1["cast"][0] == f2["cast"][0]  # the same {id, version}, not a copy
    assert f1["places"] == f2["places"]
    assert len(project.list_characters()) == 2


def test_new_version_never_changes_old_ones_or_old_films(project):
    f1 = project.create_film("Old", cast=["kit"], places=["orchard"])
    before = project.resolve_character("kit", 1)
    ref = project.publish_character("kit", {"rig.json": b'{"v":2}'}, note="better ears")
    assert ref["version"] == 2
    again = project.resolve_character("kit", 1)
    assert dict(again.files) == dict(before.files)
    assert project.read_file(again, "rig.json") == b'{"v":1}'
    assert project.resolve_character("kit").version == 2
    assert project.get_film(f1["id"])["cast"][0]["version"] == 1  # finished film unchanged
    f2 = project.create_film("New", cast=["kit"])
    assert f2["cast"][0]["version"] == 2
    assert len(project.list_characters()) == 2  # kit, bo: still one entry per character


def test_published_versions_are_immutable(project):
    entry = project.list_characters()[0]
    entry["versions"][0]["files"]["rig.json"] = project.store.put_asset(
        project.id, b"tampered", "application/json"
    )
    with pytest.raises(ImmutableVersionError):
        project._put(entry, expected_rev=entry["rev"])


def test_film_can_pin_an_older_version_and_upgrade_later(project):
    project.publish_character("kit", {"rig.json": b'{"v":2}'})
    film = project.create_film(
        "Pinned", cast=[{"id": project.resolve_character("kit").id, "version": 1}]
    )
    assert film["cast"][0]["version"] == 1
    up = project.upgrade_reference(film["id"], "character", "kit")
    assert up["cast"][0]["version"] == 2
    with pytest.raises(InvalidDocument):
        project.upgrade_reference(film["id"], "character", "bo")  # not in this film


def test_unknown_or_duplicate_references_are_refused(project):
    with pytest.raises(NotFound):
        project.create_film("X", cast=["ghost"])
    with pytest.raises(InvalidDocument):
        project.create_film("Y", cast=["kit", "kit"])
    project.create_film("Same", slug="same")
    with pytest.raises(InvalidDocument):
        project.create_film("Same again", slug="same")


def test_documents_hold_no_paths_and_pass_their_schemas(project, film):
    for kind in ("project", "character", "background", "film", "act", "shot"):
        docs = (
            [project.doc] if kind == "project" else project.store.list_documents(project.id, kind)
        )
        assert docs, kind
        assert all(document_issues(d) == [] for d in docs), kind


def test_schema_rejects_bad_shapes(project):
    bad = project.list_films() or [project.create_film("F")]
    doc = {**bad[0], "cast": [{"id": "x"}]}  # a reference needs a version
    assert any("version" in i for i in document_issues(doc))


def test_materialize_lays_out_a_folder(project, tmp_path):
    kit = project.resolve_character("kit")
    out = project.materialize(kit, tmp_path / "kit")
    assert (out / "rig.json").read_bytes() == b'{"v":1}'
    assert (out / "parts" / "head.png").read_bytes() == b"HEAD1"
    project.materialize(kit, out)  # safe to run again


# ----------------------------------------------------------------------- acts


def test_acts_are_ordered_and_hold_background_cast_beats_shots(project, film):
    acts = project.list_acts(film["id"])
    assert [a["title"] for a in acts] == ["Morning", "Evening"]
    assert acts[0]["background"]["id"] == project.resolve_background("orchard").id
    assert len(acts[0]["cast"]) == 2 and len(acts[1]["cast"]) == 1
    assert [len(project.list_shots(film["id"], a["id"])) for a in acts] == [3, 3]
    assert [s["spec"]["camera"] for s in project.list_shots(film["id"], acts[0]["id"])] == [
        "wide",
        "two-shot",
        "close",
    ]
    again = project.reorder_acts(film["id"], [acts[1]["id"], acts[0]["id"]])
    assert [a["title"] for a in again] == ["Evening", "Morning"]


def test_act_must_use_the_films_own_cast_and_places(project, film):
    other = project.create_film("Other", cast=["kit"], places=["orchard"])
    with pytest.raises(InvalidDocument):
        project.add_act(other["id"], "Bad place", background="meadow")
    with pytest.raises(InvalidDocument):
        project.add_act(other["id"], "Bad cast", background="orchard", cast=["bo"])


# ------------------------------------------------------------------ staleness


def acts_of(project, film):
    return project.list_acts(film["id"])


def test_key_is_stable_and_ignores_bookkeeping(project, film):
    a1 = acts_of(project, film)[0]
    k1 = project.act_key(film["id"], a1["id"], ENGINE)
    assert k1 == project.act_key(film["id"], a1["id"], ENGINE)
    project.update_act(a1["id"], title="Morning")  # a write that changes nothing but rev/time
    assert k1 == project.act_key(film["id"], a1["id"], ENGINE)


def test_editing_one_shot_changes_only_its_act(project, film):
    a1, a2 = acts_of(project, film)
    keys = {a["id"]: project.act_key(film["id"], a["id"], ENGINE) for a in (a1, a2)}
    s = project.list_shots(film["id"], a1["id"])[1]
    project.update_shot(s["id"], shot("over-the-shoulder"))
    assert project.act_key(film["id"], a1["id"], ENGINE) != keys[a1["id"]]
    assert project.act_key(film["id"], a2["id"], ENGINE) == keys[a2["id"]]


def test_character_version_changes_only_acts_that_use_it(project, film):
    a1, a2 = acts_of(project, film)
    # a2 has only kit; publishing a new bo and upgrading must not touch a2
    before = {a["id"]: project.act_key(film["id"], a["id"], ENGINE) for a in (a1, a2)}
    project.publish_character("bo", {"rig.json": b'{"bo":2}'})
    project.upgrade_reference(film["id"], "character", "bo")
    after = {a["id"]: project.act_key(film["id"], a["id"], ENGINE) for a in (a1, a2)}
    assert after[a1["id"]] != before[a1["id"]]
    assert after[a2["id"]] == before[a2["id"]]


def test_engine_and_background_version_change_the_key(project, film):
    a1 = acts_of(project, film)[0]
    k = project.act_key(film["id"], a1["id"], ENGINE)
    assert project.act_key(film["id"], a1["id"], "opentoonz-1") != k
    project.publish_background("orchard", {"plate.png": b"ORCHARD-v2"})
    project.upgrade_reference(film["id"], "background", "orchard")
    assert project.act_key(film["id"], a1["id"], ENGINE) != k


def test_render_record_makes_an_act_fresh_until_it_is_edited(project, film):
    a1, a2 = acts_of(project, film)
    assert {a["id"] for a in project.stale_acts(film["id"], ENGINE)} == {a1["id"], a2["id"]}
    video = project.store.put_asset(project.id, b"MP4", "video/mp4")
    project.record_render(film["id"], a1["id"], ENGINE, video=video)
    project.record_render(film["id"], a2["id"], ENGINE)
    assert project.stale_acts(film["id"], ENGINE) == []
    project.update_shot(project.list_shots(film["id"], a2["id"])[0]["id"], shot("crane"))
    assert [a["id"] for a in project.stale_acts(film["id"], ENGINE)] == [a2["id"]]
    assert project.is_act_stale(film["id"], a1["id"], "other-engine")
    project.record_render(film["id"], a2["id"], ENGINE)  # re-render: rev moves on, fresh again
    assert project.stale_acts(film["id"], ENGINE) == []


def test_key_computed_before_a_render_keeps_a_mid_render_edit_visible(project, film):
    a1 = acts_of(project, film)[0]
    key = project.act_key(film["id"], a1["id"], ENGINE)
    project.update_shot(project.list_shots(film["id"], a1["id"])[0]["id"], shot("edited"))
    project.record_render(film["id"], a1["id"], ENGINE, cache_key=key)
    assert project.is_act_stale(film["id"], a1["id"], ENGINE)


# ------------------------------------------------------- pure staleness function


def test_pure_key_function_rules():
    act = {"id": "A", "background": {"id": "b", "version": 1}, "cast": [], "shot_ids": ["s1", "s2"]}
    s1, s2 = {"id": "s1", "spec": {"x": 1}}, {"id": "s2", "spec": {"x": 2, "y": 1}}
    key = act_cache_key(act, [s1, s2], "e")
    assert len(key) == 64
    # key order and bookkeeping fields do not matter
    s2_shuffled = {"spec": {"y": 1, "x": 2}, "id": "s2", "rev": 9, "updated_at": "later"}
    assert act_cache_key({**act, "rev": 3}, [s1, s2_shuffled], "e") == key
    assert act_cache_key(act, [s1, {**s2, "spec": {"x": 2, "y": 2}}], "e") != key
    assert act_cache_key(act, [s1, s2], "e", extra={"style": "x"}) != key
    with pytest.raises(ValueError):
        act_cache_key(act, [s2, s1], "e")  # shots must come in the act's order
    assert is_stale(key, None)
    assert is_stale(key, {"cache_key": "other"})
    assert not is_stale(key, {"cache_key": key})


# ------------------------------------------------------- editing acts and shots (Step 5C)


def test_shots_can_be_reordered_removed_and_change_only_their_act(project, film):
    a1, a2 = project.list_acts(film["id"])
    key2 = project.act_key(film["id"], a2["id"], ENGINE)
    key1 = project.act_key(film["id"], a1["id"], ENGINE)
    ids = list(a1["shot_ids"])
    project.reorder_shots(a1["id"], [ids[2], ids[0], ids[1]])
    assert project.act_key(film["id"], a1["id"], ENGINE) != key1  # a different cut
    assert project.act_key(film["id"], a2["id"], ENGINE) == key2
    with pytest.raises(InvalidDocument):
        project.reorder_shots(a1["id"], ids[:2])
    project.remove_shot(a1["id"], ids[0])
    assert len(project.get_act(film["id"], a1["id"])["shot_ids"]) == 2
    with pytest.raises(NotFound):
        project.store.get_document(project.id, "shot", ids[0])


def test_removing_an_act_renumbers_the_rest_and_background_can_change(project, film):
    a1, a2 = project.list_acts(film["id"])
    project.record_render(film["id"], a1["id"], ENGINE)
    left = project.remove_act(film["id"], a1["id"])
    assert [a["id"] for a in left] == [a2["id"]] and left[0]["order"] == 1
    assert project.last_render(a1["id"]) is None
    key = project.act_key(film["id"], a2["id"], ENGINE)
    project.set_act_background(film["id"], a2["id"], "orchard")
    assert project.act_key(film["id"], a2["id"], ENGINE) != key
    project.publish_background("cave", {"plate.png": b"CAVE"})  # in the library, not in the film
    with pytest.raises(InvalidDocument):
        project.set_act_background(film["id"], a2["id"], "cave")


def test_a_shot_document_carries_its_audio_snapshot(project, film):
    act = project.list_acts(film["id"])[0]
    shot_id = act["shot_ids"][0]
    spec = project.store.get_document(project.id, "shot", shot_id)["spec"]
    key = project.act_key(film["id"], act["id"], ENGINE)
    project.update_shot(shot_id, spec, audio={"lines": {"l001": {"dialogue/l001.wav": "a" * 64}}})
    assert project.act_key(film["id"], act["id"], ENGINE) != key
    with pytest.raises(InvalidDocument):
        project.update_shot(shot_id, spec, audio={"lines": 3})


def test_add_film_reference_adds_or_moves(project, film):
    project.publish_character("pim", {"rig.json": b"{}"})
    project.add_film_reference(film["id"], "character", "pim")
    assert {r["id"] for r in project.get_film(film["id"])["cast"]} >= {
        project.resolve_character("pim").id
    }
    project.publish_character("kit", {"rig.json": b"{2}"})
    project.add_film_reference(film["id"], "character", "kit")
    assert project.get_film(film["id"])["cast"][0]["version"] == 2


def test_reordering_or_retitling_acts_does_not_make_them_stale(project, film):
    a1, a2 = project.list_acts(film["id"])
    keys = [project.act_key(film["id"], a["id"], ENGINE) for a in (a1, a2)]
    project.reorder_acts(film["id"], [a2["id"], a1["id"]])
    project.update_act(a1["id"], title="Dawn", beats=["a new beat"])
    assert [project.act_key(film["id"], a["id"], ENGINE) for a in (a1, a2)] == keys
