"""Acts as the unit of rendering: per-act render, staleness, export-all-acts, stitch order, and
rebuilding the same movie from the specs after every render is deleted. The renderer is a stand-in
that makes a colored clip per shot (so these run in seconds); the stitching, the checks and the
store are real."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest
from project_world import make_film, make_project, make_workspace

from studio_core import acts, shot_spec
from studio_core.acts import ActError, Target
from studio_core.audio import ffmpeg
from studio_core.config import load_config
from studio_core.edit.render import probe

CFG = load_config()
PREVIEW = Target("fake", "preview")


class FakeRenderer:
    """One clip per shot: its color comes from the shot spec, its length from duration_s."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, root: Path, shot_id: str, size: tuple[int, int]) -> Path:
        self.calls.append(shot_id)
        spec = (root / "shots" / shot_id / "shot.json").read_text()
        color = hashlib.sha256(spec.encode()).hexdigest()[:6]
        seconds = shot_spec.load(shot_spec.FilmFolder(root), shot_id)["duration_s"]
        out = root / "shots" / shot_id / "shot.mp4"
        ffmpeg.run(
            [
                *("-f", "lavfi", "-i", f"color=c=0x{color}:size={size[0]}x{size[1]}:rate=24"),
                *("-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000"),
                *("-t", f"{seconds}", "-ac", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p"),
                *("-c:a", "aac", str(out)),
            ],
            CFG,
        )
        return out


@pytest.fixture
def world(tmp_path):
    ws = make_workspace(tmp_path)
    project = make_project(ws)
    film = make_film(ws, project)
    return ws, project, film, FakeRenderer()


def folder_of(ws, project):
    return ws.open_film("three-acts", project.id)


def frame_hashes(video: Path) -> list[str]:
    out = subprocess.run(
        [
            str(CFG.path("tools", "ffmpeg")),
            "-v",
            "error",
            "-i",
            str(video),
            "-an",
            "-f",
            "framemd5",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line.split(",")[-1].strip() for line in out.splitlines() if line and line[0] != "#"]


def test_acts_start_stale_and_render_one_act_at_a_time(world):
    ws, project, _film, fake = world
    folder = folder_of(ws, project)
    assert [r["stale"] for r in acts.act_table(folder, PREVIEW)] == [True, True, True]
    result = acts.render_act(folder, "Act 2", PREVIEW, fake, CFG)
    assert result["rendered"] and result["shots"] == ["s02_sh01", "s02_sh02", "s02_sh03"]
    assert fake.calls == ["s02_sh01", "s02_sh02", "s02_sh03"]
    assert [r["stale"] for r in acts.act_table(folder, PREVIEW)] == [True, False, True]
    p = probe(Path(result["video_path"]), CFG)
    assert abs(p.duration_s - (1.1 + 1.2 + 1.3)) < 0.15
    again = acts.render_act(folder, "Act 2", PREVIEW, fake, CFG)  # up to date: nothing to do
    assert again["rendered"] is False and len(fake.calls) == 3


def test_a_preview_render_does_not_satisfy_a_final_export(world):
    ws, project, _film, fake = world
    folder = folder_of(ws, project)
    acts.render_act(folder, "Act 1", PREVIEW, fake, CFG)
    assert acts.act_table(folder, PREVIEW)[0]["stale"] is False
    assert acts.act_table(folder, Target("fake", "final"))[0]["stale"] is True


def test_editing_one_shot_rerenders_only_its_act(world):
    ws, project, _film, fake = world
    folder = folder_of(ws, project)
    acts.export_movie(folder, PREVIEW, fake, CFG)
    assert len(fake.calls) == 9
    fake.calls.clear()
    shot_spec.set_camera(folder, "s03_sh02", "push_in", start_s=0, duration_s=1, zoom=1.4)
    assert [r["stale"] for r in acts.act_table(folder, PREVIEW)] == [False, False, True]
    result = acts.export_movie(folder, PREVIEW, fake, CFG)
    assert fake.calls == ["s03_sh01", "s03_sh02", "s03_sh03"]
    assert result["rendered_acts"] == ["Act 3"] and result["reused_acts"] == ["Act 1", "Act 2"]
    fake.calls.clear()
    assert acts.export_movie(folder, PREVIEW, fake, CFG)["rendered_acts"] == []  # nothing changed
    assert fake.calls == []


def test_export_joins_the_acts_in_order_and_follows_a_reorder(world):
    ws, project, film, fake = world
    folder = folder_of(ws, project)
    result = acts.export_movie(folder, PREVIEW, fake, CFG)
    assert result["checks_passed"], result["problems"]
    assert result["act_order"] == ["Act 1", "Act 2", "Act 3"]
    edit = shot_spec.json.loads((folder.root / "edit" / "edit.json").read_text())
    by_id = {a["id"]: a["title"] for a in project.list_acts(film["id"])}
    assert [by_id[c["act"]] for c in edit["clips"]] == ["Act 1", "Act 2", "Act 3"]
    # each act is 3 shots of 1.1, 1.2, 1.3 s = 3.6 s; the movie is the three of them
    assert abs(result["duration_s"] - 3 * 3.6) < 0.3
    a1, a2, a3 = (a["id"] for a in project.list_acts(film["id"]))
    project.reorder_acts(film["id"], [a3, a1, a2])
    fake.calls.clear()
    result = acts.export_movie(folder, PREVIEW, fake, CFG)
    assert result["act_order"] == ["Act 3", "Act 1", "Act 2"] and fake.calls == []
    edit = shot_spec.json.loads((folder.root / "edit" / "edit.json").read_text())
    assert [by_id[c["act"]] for c in edit["clips"]] == ["Act 3", "Act 1", "Act 2"]


def test_titles_and_crossfades_are_optional(world):
    ws, project, _film, fake = world
    folder = folder_of(ws, project)
    result = acts.export_movie(
        folder,
        PREVIEW,
        fake,
        CFG,
        transition="crossfade",
        start_title="Pip's Day",
        end_title="The End",
    )
    assert result["checks_passed"], result["problems"]
    # 3 acts of 3.6 s + two 3 s cards, minus 4 half-second overlaps
    assert abs(result["duration_s"] - (3 * 3.6 + 6 - 4 * 0.5)) < 0.4
    with pytest.raises(ActError, match="not suitable"):
        acts.export_movie(folder, PREVIEW, fake, CFG, start_title="a bloody mess")


def test_deleting_every_render_and_exporting_again_gives_the_same_film(world):
    ws, project, _film, fake = world
    folder = folder_of(ws, project)
    first = acts.export_movie(folder, PREVIEW, fake, CFG)
    before = frame_hashes(Path(first["path"]))
    assert acts.clear_renders(folder) == 3
    shutil.rmtree(ws.work_root)  # the working folder is disposable too
    assert all(r["stale"] for r in acts.act_table(ws.open_film("three-acts", project.id), PREVIEW))
    fake.calls.clear()
    again = acts.export_movie(ws.open_film("three-acts", project.id), PREVIEW, fake, CFG)
    assert len(fake.calls) == 9 and again["rendered_acts"] == ["Act 1", "Act 2", "Act 3"]
    after = frame_hashes(Path(again["path"]))
    assert after == before and len(before) > 200


def test_problems_are_refused_with_the_fix(world):
    ws, project, film, fake = world
    folder = folder_of(ws, project)
    a1 = project.list_acts(film["id"])[0]
    shot_spec.set_background(folder, "s01_sh01", "hill")  # the act is in the meadow
    row = acts.act_table(folder, PREVIEW)[0]
    assert "s01_sh01 is set in 'hill'" in row["problems"][0]
    with pytest.raises(ActError, match="fix act 'Act 1'"):
        acts.render_act(folder, a1["id"], PREVIEW, fake, CFG)
    with pytest.raises(ActError, match="no act 'Act 9'"):
        acts.render_act(folder, "Act 9", PREVIEW, fake, CFG)
    legacy = shot_spec.FilmFolder(folder.root)
    with pytest.raises(ActError, match="belong to projects"):
        acts.act_table(legacy, PREVIEW)


def test_a_new_character_version_makes_exactly_the_acts_that_use_it_stale(world):
    ws, project, _film, fake = world
    folder = folder_of(ws, project)
    acts.export_movie(folder, PREVIEW, fake, CFG)
    (folder.root / "characters" / "pip" / "notes.txt").write_text("rounder ears")
    folder.link.publish_character("pip")  # version 2, film and acts follow
    assert all(r["stale"] for r in acts.act_table(folder, PREVIEW))
