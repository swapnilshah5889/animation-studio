"""The workspace: a project film as a derived working folder, and its sync with the store."""

from __future__ import annotations

import shutil

import pytest
from project_world import FIXTURES, make_film, make_project, make_workspace

from studio_core import shot_spec
from studio_core.shot_spec import SpecError
from studio_core.workspace import Workspace


@pytest.fixture
def world(tmp_path):
    ws = make_workspace(tmp_path)
    project = make_project(ws)
    film = make_film(ws, project)
    return ws, project, film


def test_legacy_film_opens_unchanged(tmp_path):
    (tmp_path / "films" / "old").mkdir(parents=True)
    ws = Workspace(films_root=tmp_path / "films")
    folder = ws.open_film("old")
    assert folder.root == tmp_path / "films" / "old" and folder.link is None
    with pytest.raises(SpecError, match="no film 'nope'"):
        ws.open_film("nope")


def test_project_film_folder_is_derived_from_the_store(world):
    ws, project, _ = world
    folder = ws.open_film("three-acts", project.id)
    assert folder.root == ws.work_root / project.id / "three-acts"
    assert folder.characters() == ["pip"] and folder.backgrounds() == ["hill", "meadow", "pond"]
    assert len(folder.shots()) == 9
    spec = shot_spec.load(folder, "s02_sh03")
    assert spec["background"] == "hill"
    # the folder is disposable: delete it and open again
    shutil.rmtree(ws.work_root)
    again = ws.open_film("three-acts", project.id)
    assert shot_spec.load(again, "s02_sh03") == spec


def test_saved_shots_land_in_the_right_act_and_edits_update_them(world):
    ws, project, film = world
    acts = project.list_acts(film["id"])
    assert [len(a["shot_ids"]) for a in acts] == [3, 3, 3]
    docs = project.list_shots(film["id"], acts[1]["id"])
    assert [d["spec"]["id"] for d in docs] == ["s02_sh01", "s02_sh02", "s02_sh03"]
    folder = ws.open_film("three-acts", project.id)
    shot_spec.set_camera(folder, "s02_sh02", "push_in", start_s=0, duration_s=1, zoom=1.5)
    changed = project.list_shots(film["id"], acts[1]["id"])[1]
    assert changed["spec"]["camera"]["move"] == "push_in" and changed["rev"] > docs[1]["rev"]


def test_new_shot_needs_an_act_when_there_are_several(world):
    ws, project, film = world
    folder = ws.open_film("three-acts", project.id)
    with pytest.raises(SpecError, match="several acts"):
        shot_spec.create_shot(folder, "s09_sh01", 1.0, "pond")
    assert not folder.shot_file("s09_sh01").exists()  # a refusal saves nothing
    act = project.list_acts(film["id"])[2]
    folder = ws.open_film("three-acts", project.id, act="Act 3")
    shot_spec.create_shot(folder, "s09_sh01", 1.0, "pond")
    assert (
        project.get_act(film["id"], act["id"])["shot_ids"][-1]
        == project.list_shots(film["id"], act["id"])[-1]["id"]
    )


def test_unknown_project_and_film_name_what_exists(world):
    ws, project, _ = world
    with pytest.raises(SpecError, match="pip-world"):
        ws.open_film("three-acts", "nope")
    with pytest.raises(SpecError, match="three-acts"):
        ws.open_film("nope", project.id)


def _record_line(folder, line_id="l001", wav=b"RIFF-one"):
    audio = folder.root / "audio"
    (audio / "dialogue").mkdir(parents=True, exist_ok=True)
    (audio / "lipsync").mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "audio" / "pip_line_01.wav", audio / "dialogue" / f"{line_id}.wav")
    shutil.copy(FIXTURES / "audio" / "pip_line_01.txt", audio / "dialogue" / f"{line_id}.txt")
    shutil.copy(
        FIXTURES / "audio" / "pip_line_01.rhubarb.json", audio / "lipsync" / f"{line_id}.json"
    )


def test_a_changed_line_makes_only_its_act_stale(world):
    ws, project, film = world
    fid = film["id"]
    acts = project.list_acts(fid)
    for a in acts:
        project.record_render(fid, a["id"], "eng")
    assert project.stale_acts(fid, "eng") == []
    folder = ws.open_film("three-acts", project.id)
    _record_line(folder)
    assert folder.link.sync_audio() == 4  # wav, txt, cues, pip's voice
    shot_spec.add_dialogue(folder, "s01_sh01", "pip", "l001", 0.0, "Hello there")
    assert [a["title"] for a in project.stale_acts(fid, "eng")] == ["Act 1"]
    for a in acts:
        project.record_render(fid, a["id"], "eng")
    # same text, different recording: the shot spec is unchanged but the act is stale again
    (folder.root / "audio" / "dialogue" / "l001.wav").write_bytes(b"RIFFdifferent")
    folder.link.sync_audio()
    assert [a["title"] for a in project.stale_acts(fid, "eng")] == ["Act 1"]
    # the recording survives deleting the working folder
    shutil.rmtree(ws.work_root)
    again = ws.open_film("three-acts", project.id)
    assert (again.root / "audio" / "dialogue" / "l001.wav").read_bytes() == b"RIFFdifferent"


def test_publishing_a_built_character_adds_a_version_only_when_it_changed(world):
    ws, project, film = world
    folder = ws.open_film("three-acts", project.id)
    link = folder.link
    assert link.publish_character("pip")["new"] is False  # untouched since pulled
    extra = folder.root / "characters" / "pip" / "notes.txt"
    extra.write_text("new look")
    ref = link.publish_character("pip")
    assert ref["new"] is True and ref["version"] == 2
    assert link.publish_character("pip")["new"] is False
    assert project.get_film(film["id"])["cast"][0]["version"] == 2
    assert all(a["cast"][0]["version"] == 2 for a in project.list_acts(film["id"]))
    # a character built for this film is added to it and to the library
    shutil.copytree(folder.root / "characters" / "pip", folder.root / "characters" / "pop")
    (folder.root / "characters" / "pop" / ".pinned").unlink()
    new = link.publish_character("pop")
    assert new["version"] == 1 and {c["slug"] for c in project.list_characters()} == {"pip", "pop"}
    assert len(project.get_film(film["id"])["cast"]) == 2
