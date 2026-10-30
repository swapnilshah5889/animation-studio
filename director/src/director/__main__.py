"""The director's command line.

    uv run scripts/direct.py new "<story prompt>" --film moon-picnic --seconds 15 \\
        --import-cast step4-cast:kit,bo --import-places step4-proof:orchard
    uv run scripts/direct.py resume moon-picnic        # also continues after an approval
    uv run scripts/direct.py approve moon-picnic story
    uv run scripts/direct.py revise moon-picnic story "make the ending quieter"
    uv run scripts/direct.py retry moon-picnic [--stage shots]
    uv run scripts/direct.py status moon-picnic

A film of a project (D-094): the cast and places come from the project's library, the story is
planned in acts, and each act has its own approval stop (act_s01, act_s02, ...):

    uv run scripts/direct.py new "<story prompt>" --project test-cast --film moon-picnic \
        --pin-cast kit,bo --pin-places orchard --acts 2 --seconds 20
    uv run scripts/direct.py resume moon-picnic --project test-cast
    uv run scripts/direct.py approve moon-picnic act_s01 --project test-cast
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from director import runner
from director import state as st
from director.assets import import_assets, style_of
from director.chat import OllamaChat
from director.config import CHECKPOINTS, MODEL, STAGES
from director.context import Deps
from director.hub import McpHub
from director.log import EventLog
from director.memory import MemoryGuard, comfy_state_via_http
from director.project_mode import check_pins, home_of, link_home
from director.stubs import StubbedHub
from director.stubs import handlers as stub_handlers
from studio_core.config import REPO_ROOT
from studio_core.ollama import Ollama
from studio_core.workspace import Workspace

FILMS = REPO_ROOT / "films"
SERVERS = ["synfig_mcp", "audio_mcp", "comfy_mcp", "edit_mcp", "qa_mcp"]


def split(text: str | None) -> list[str]:
    return [x for x in (text or "").split(",") if x]


def refresh_project_film(ws: Workspace, project: str, slug: str) -> Path:
    """Bring the film's working folder up to date with the store and link the director's home
    into it (the folder is a cache; the home keeps the director's progress). Returns the folder."""
    root = ws.open_film(slug, project).root
    link_home(root, home_of(ws.projects_root, project, slug))
    return root


def film_folder(args: argparse.Namespace, slug: str) -> Path:
    """Where the film's director/ and story/ are read: films/<slug>, or a project film's
    working folder (made, with its links, if it is missing)."""
    if not getattr(args, "project", None):
        return FILMS / slug
    return refresh_project_film(Workspace.from_config(), args.project, slug)


def build_deps(slug: str, hub: McpHub, args: argparse.Namespace) -> Deps:
    ollama = Ollama()
    from studio_core.comfy import Comfy

    guard = MemoryGuard(
        MODEL,
        loaded=lambda: [m["name"] for m in ollama.loaded()],
        unload=ollama.unload,
        comfy_state=comfy_state_via_http,
        comfy_free=Comfy().free_memory,
        comfy_stop=lambda: subprocess.run(
            [str(REPO_ROOT / "scripts" / "comfy_server.sh"), "--stop"], check=False
        ),
    )
    log = EventLog(film_folder(args, slug) / "director" / "log.jsonl", echo=True)
    deps = Deps(OllamaChat(ollama), hub, guard, on_event=log, auto=args.auto, quality=args.quality)
    if args.project:
        ws = Workspace.from_config()
        deps.project = ws.open_project(args.project)
        deps.refresh = lambda: refresh_project_film(ws, args.project, slug)
    return deps


async def create_project_film(args: argparse.Namespace, hub: McpHub) -> str:
    """A film of a project: its cast and places are the pins (or none yet: the story chooses from
    the library and the director adds them), and the state remembers project, pins and acts."""
    slug, ws = args.film, Workspace.from_config()
    project = ws.open_project(args.project)
    pin_cast, pin_places = split(args.pin_cast), split(args.pin_places)
    if missing := check_pins(project, pin_cast, pin_places):
        sys.exit(f"the project {args.project} has no {', '.join(missing)}; see describe_project")
    if slug not in [f["slug"] for f in project.list_films()]:
        res = await hub.call(
            "create_film",
            {
                "film": slug,
                "title": args.title or slug,
                "project": args.project,
                "cast": pin_cast,
                "places": pin_places,
            },
        )
        if res.refused:
            sys.exit(f"create_film refused: {res.text}")
    film = refresh_project_film(ws, args.project, slug)
    if not st.state_file(film).exists():
        st.save(
            film,
            st.DirectorState(
                film=slug,
                prompt=args.prompt,
                target_seconds=args.seconds,
                project=args.project,
                pinned_cast=pin_cast,
                pinned_places=pin_places,
                target_acts=args.acts,
            ),
        )
    return slug


async def create(args: argparse.Namespace, hub: McpHub) -> str:
    if args.project:
        return await create_project_film(args, hub)
    slug = args.film
    if not (FILMS / slug).exists():
        style = style_of(FILMS, args.import_cast.split(":")[0]) if args.import_cast else None
        res = await hub.call(
            "create_film",
            {"film": slug, "title": args.title or slug, **({"style": style} if style else {})},
        )
        if res.refused:
            sys.exit(f"create_film refused: {res.text}")
    for spec, kind in ((args.import_cast, "characters"), (args.import_places, "backgrounds")):
        if spec:
            print(f"imported {kind}: {import_assets(FILMS, slug, spec, kind)}")
    if not st.state_file(FILMS / slug).exists():
        st.save(
            FILMS / slug,
            st.DirectorState(film=slug, prompt=args.prompt, target_seconds=args.seconds),
        )
    return slug


def show_status(film: Path, slug: str) -> None:
    state = st.load(film)
    c = state.counters
    print(f"film {slug}: stage {state.current_stage}; target {state.target_seconds} s")
    for name in STAGES:
        s = state.stage(name)
        print(f"  {name:12} {s.status:18} attempts {s.attempts}  {s.last_error or ''}")
    print("approvals: " + ", ".join(f"{k}={a.status}" for k, a in state.approvals.items()))
    if state.project:
        print(
            f"project {state.project}: acts "
            + (json.dumps(state.acts) if state.acts else "none yet")
        )
    print(
        f"cost: {c.model_calls} model calls, {c.tool_calls} tool calls, {c.refusals} refusals, "
        f"{c.prompt_tokens}+{c.output_tokens} tokens, {c.llm_seconds:.0f}s LLM, "
        f"{c.tool_seconds:.0f}s tools"
    )


async def run(args: argparse.Namespace) -> int:
    slug = args.film if args.cmd == "new" else args.slug
    if args.project and getattr(args, "dry_run", False):
        sys.exit("--dry-run (stubs) works on old film folders only")
    async with McpHub(REPO_ROOT, SERVERS) as hub:
        if hub.skipped:
            print(f"servers that did not start: {hub.skipped}")
        if args.cmd == "new":
            await create(args, hub)
        film = film_folder(args, slug)
        state = st.load(film)
        if args.cmd == "approve":
            runner.approve(state, film, args.name)
            print(f"approved {args.name}; run `resume {slug}` to continue")
            return 0
        if args.cmd == "revise":
            runner.revise(state, film, args.name, args.note)
            print(f"{args.name} will run again with your note; run `resume {slug}`")
            return 0
        if args.cmd == "retry":
            runner.retry(state, film, args.stage)
        deps = build_deps(slug, hub, args)
        if getattr(
            args, "dry_run", False
        ):  # real model and cheap tools; slow tools replaced by stand-ins (stubs.py)
            template = FILMS / "step4-proof" / "audio" / "music" / "m01"
            deps.hub = StubbedHub(hub, stub_handlers(FILMS, template))
        root = Workspace.from_config().work_root / args.project if args.project else FILMS
        outcome = await runner.run_film(slug, deps, root)
        print(f"\n=> {outcome}")
        show_status(film, slug)
        return 0 if outcome == "finished" or outcome.startswith("awaiting") else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="director", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    new = sub.add_parser("new", help="start a film from a story prompt")
    new.add_argument("prompt")
    new.add_argument("--film", required=True, help="film folder name (lowercase, digits, '-')")
    new.add_argument("--title")
    new.add_argument("--seconds", type=int, default=15)
    new.add_argument(
        "--import-cast", help="srcfilm:id,id  reuse built puppets, e.g. step4-cast:kit,bo"
    )
    new.add_argument(
        "--import-places", help="srcfilm:id  reuse painted places, e.g. step4-proof:orchard"
    )
    new.add_argument("--pin-cast", help="project films: the characters the story may use, a,b")
    new.add_argument("--pin-places", help="project films: the places the story may use, a,b")
    new.add_argument("--acts", type=int, help="project films: exactly this many acts (scenes)")
    for name in ("new", "resume", "retry"):
        sp = new if name == "new" else sub.add_parser(name)
        if name != "new":
            sp.add_argument("slug")
        sp.add_argument(
            "--auto", action="store_true", help="approve every checkpoint automatically"
        )
        sp.add_argument("--quality", choices=["preview", "final"], default="final")
        sp.add_argument("--dry-run", action="store_true", help="stub the slow tools (stubs.py)")
        if name != "new":
            sp.add_argument("--project", help="the film belongs to this project")
    sub.choices["retry"].add_argument("--stage", choices=STAGES)
    new.add_argument("--project", help="make a film of this project (its library, acts)")
    for name in ("approve", "revise"):
        sp = sub.add_parser(name)
        sp.add_argument("slug")
        sp.add_argument("name", help=f"{', '.join(CHECKPOINTS)}, or act_<scene> (project films)")
        sp.add_argument("--project", help="the film belongs to this project")
        if name == "revise":
            sp.add_argument("note")
    status = sub.add_parser("status")
    status.add_argument("slug")
    status.add_argument("--project", help="the film belongs to this project")
    args = p.parse_args(argv)
    if args.cmd == "status":
        show_status(film_folder(args, args.slug), args.slug)
        return 0
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
