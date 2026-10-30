"""Fakes for the project-film director tests: a real project on disk (FileSystemStore), the fake
MCP world of director_world.py writing into the film's working folder, and the act tools
(add_act, render_act, export_movie) kept honest by the real act cache key."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from director_world import SHOTPLAN, STORY, FakeHub, PipelineChat, info, says

from director.project_mode import link_home
from studio_core.project import Project
from studio_core.project.link import ProjectLink
from studio_core.store import FileSystemStore
from studio_core.workspace import Workspace

ENGINE = "fake:preview"
FACE = {"face": {}}
RIG = json.dumps({"views": {"front": FACE, "three_quarter": FACE}}).encode()
LAYERS = json.dumps({"layers": [{}, {}, {}]}).encode()

# The same two-scene story as the old-folder tests, with the act titles a project film needs.
PROJECT_STORY = {
    **STORY,
    "scenes": [
        {**sc, "title": title}
        for sc, title in zip(STORY["scenes"], ("Finding it", "Letting go"), strict=False)
    ],
}


class ProjectWorld:
    """A project with a library, one empty film, and the director's home and working folder."""

    def __init__(self, tmp_path: Path, *, library=("kit", "bo"), film: str = "balloon") -> None:
        self.ws = Workspace(
            films_root=tmp_path / "films",
            projects_root=tmp_path / "projects",
            work_root=tmp_path / "work",
        )
        self.project = Project.create(
            FileSystemStore(self.ws.projects_root), name="Test cast", project_id="proj"
        )
        for slug in library:
            self.project.publish_character(slug, {"rig.json": RIG})
        self.project.publish_background("orchard", {"layers.json": LAYERS})
        self.slug = film
        self.project.create_film("Balloon", slug=film, cast=[], places=[])
        self.home = self.ws.projects_root / "proj" / "director" / film
        self.film = self.refresh()  # the working folder
        self.root = self.film.parent  # what run_film calls films_root

    def refresh(self) -> Path:
        root = self.ws.open_film(self.slug, "proj").root
        link_home(root, self.home)
        return root


class ProjectHub(FakeHub):
    """FakeHub plus the project tools. Shots are saved through the project link, as the real
    synfig tools do, so the store holds them; renders record the real act cache key."""

    def __init__(self, world: ProjectWorld, **kw: Any) -> None:
        super().__init__(world.film, **kw)
        self.world, self.project = world, world.project
        self.tools |= {n: info(n) for n in ("add_act", "edit_act", "remove_shot", "render_act")}
        self.tools["export_movie"] = info("export_movie")
        for tool in self.tools.values():  # the real tools take these two as well
            tool.input_schema["properties"].update(project={}, act={})
        self.rendered_acts: list[str] = []

    # --- shots are filed under the act
    def save(self, a) -> None:
        super().save(a)
        ProjectLink(self.project, self.film_id, self.film, act=a.get("act")).shot_saved(
            self.spec(a)
        )

    @property
    def film_id(self) -> str:
        return self.project.get_film("balloon")["id"]

    # --- art: a new character is drawn, built and published to the library
    def do_describe_art(self, a):
        return {"characters": [], "backgrounds": []}

    def do_design_character(self, a):
        return {"candidates": [{"candidate_id": "c1", "ok": True}]}

    def do_choose_design(self, a):
        return {"ok": True}

    def do_build_puppet(self, a):
        folder = self.film / "characters" / a["character_id"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "rig.json").write_bytes(RIG)
        ProjectLink(self.project, self.film_id, self.film).publish_character(a["character_id"])
        return {"views_consistent": True}

    # --- acts
    def do_add_act(self, a):
        act = self.project.add_act(
            self.film_id, a["title"], background=a["background"], cast=a["cast"], beats=a["beats"]
        )
        return {"act_id": act["id"], "title": act["title"]}

    def do_edit_act(self, a):
        self.project.update_act(a["act"], beats=a["beats"])
        return {"ok": True}

    def do_remove_shot(self, a):
        doc = next(
            d
            for d in self.project.list_shots(self.film_id, a["act"])
            if d["spec"]["id"] == a["shot_id"]
        )
        self.project.remove_shot(a["act"], doc["id"])
        return {"ok": True}

    def render_if_stale(self, act_id: str) -> bool:
        if not self.project.is_act_stale(self.film_id, act_id, ENGINE):
            return False
        key = self.project.act_key(self.film_id, act_id, ENGINE)
        self.project.record_render(self.film_id, act_id, ENGINE, cache_key=key)
        (self.film / "acts").mkdir(exist_ok=True)
        (self.film / "acts" / f"{act_id}.mp4").write_bytes(b"mp4")
        self.rendered_acts.append(act_id)
        return True

    def do_render_act(self, a):
        did = self.render_if_stale(a["act"])
        return {"act_id": a["act"], "rendered": did, "video_path": f"acts/{a['act']}.mp4"}

    def do_export_movie(self, a):
        order = [x["id"] for x in self.project.list_acts(self.film_id)]
        done = [x for x in order if self.render_if_stale(x)]
        (self.film / "edit").mkdir(exist_ok=True)
        (self.film / "edit" / "final.mp4").write_bytes(b"mp4")
        return {
            "checks_passed": True,
            "rendered_acts": done,
            "reused_acts": [x for x in order if x not in done],
            "duration_s": 15.0,
        }


class ProjectChat(PipelineChat):
    """Plans the two-act story, then one act's shots at a time (the plan for the scene in the
    schema), and runs each shot. A plan asked for with an owner's note differs from the first."""

    def __init__(self, story: dict = PROJECT_STORY) -> None:
        super().__init__(story, SHOTPLAN)
        self.briefs: list[str] = []
        self.formats: list[dict] = []

    async def __call__(self, messages, *, tools=None, think=False, format=None):
        if format and "scenes" not in format["properties"]:
            scenes = format["properties"]["shots"]["items"]["properties"]["scene"]["enum"]
            self.briefs.append(messages[1]["content"])
            plan = {
                "shots": [
                    json.loads(json.dumps(s)) for s in SHOTPLAN["shots"] if s["scene"] in scenes
                ]
            }
            if "Owner's note" in messages[1]["content"]:
                for sh in plan["shots"]:
                    if sh["id"] == "s02_sh01":
                        sh["camera"] = "push_in"
            self.calls.append({"n": len(messages), "format": True, "tools": False})
            return says(json.dumps(plan))
        if format:
            self.formats.append(format)
            self.briefs.append(messages[1]["content"])
        return await super().__call__(messages, tools=tools, think=think, format=format)
