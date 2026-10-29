"""The director's command line.

    uv run scripts/direct.py new "<story prompt>" --film moon-picnic --seconds 15 \\
        --import-cast step4-cast:kit,bo --import-places step4-proof:orchard
    uv run scripts/direct.py resume moon-picnic        # also continues after an approval
    uv run scripts/direct.py approve moon-picnic story
    uv run scripts/direct.py revise moon-picnic story "make the ending quieter"
    uv run scripts/direct.py retry moon-picnic [--stage shots]
    uv run scripts/direct.py status moon-picnic
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from director import runner
from director import state as st
from director.assets import import_assets, style_of
from director.chat import OllamaChat
from director.config import CHECKPOINTS, MODEL, STAGES
from director.context import Deps
from director.hub import McpHub
from director.log import EventLog
from director.memory import MemoryGuard, comfy_state_via_http
from studio_core.config import REPO_ROOT
from studio_core.ollama import Ollama

FILMS = REPO_ROOT / "films"
SERVERS = ["synfig_mcp", "audio_mcp", "comfy_mcp", "edit_mcp", "qa_mcp"]


def build_deps(slug: str, hub: McpHub, args: argparse.Namespace) -> Deps:
    ollama = Ollama()
    from studio_core.comfy import Comfy

    guard = MemoryGuard(
        MODEL,
        loaded=lambda: [m["name"] for m in ollama.loaded()],
        unload=ollama.unload,
        comfy_state=comfy_state_via_http,
        comfy_free=Comfy().free_memory,
    )
    log = EventLog(FILMS / slug / "director" / "log.jsonl", echo=True)
    return Deps(OllamaChat(ollama), hub, guard, on_event=log, auto=args.auto, quality=args.quality)


async def create(args: argparse.Namespace, hub: McpHub) -> str:
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


def show_status(slug: str) -> None:
    state = st.load(FILMS / slug)
    c = state.counters
    print(f"film {slug}: stage {state.current_stage}; target {state.target_seconds} s")
    for name in STAGES:
        s = state.stage(name)
        print(f"  {name:12} {s.status:18} attempts {s.attempts}  {s.last_error or ''}")
    print("approvals: " + ", ".join(f"{k}={a.status}" for k, a in state.approvals.items()))
    print(
        f"cost: {c.model_calls} model calls, {c.tool_calls} tool calls, {c.refusals} refusals, "
        f"{c.prompt_tokens}+{c.output_tokens} tokens, {c.llm_seconds:.0f}s LLM, "
        f"{c.tool_seconds:.0f}s tools"
    )


async def run(args: argparse.Namespace) -> int:
    slug = args.film if args.cmd == "new" else args.slug
    async with McpHub(REPO_ROOT, SERVERS) as hub:
        if hub.skipped:
            print(f"servers that did not start: {hub.skipped}")
        if args.cmd == "new":
            await create(args, hub)
        film = FILMS / slug
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
        outcome = await runner.run_film(slug, deps, FILMS)
        print(f"\n=> {outcome}")
        show_status(slug)
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
    for name in ("new", "resume", "retry"):
        sp = new if name == "new" else sub.add_parser(name)
        if name != "new":
            sp.add_argument("slug")
        sp.add_argument(
            "--auto", action="store_true", help="approve every checkpoint automatically"
        )
        sp.add_argument("--quality", choices=["preview", "final"], default="final")
    sub.choices["retry"].add_argument("--stage", choices=STAGES)
    for name in ("approve", "revise"):
        sp = sub.add_parser(name)
        sp.add_argument("slug")
        sp.add_argument("name", choices=list(CHECKPOINTS))
        if name == "revise":
            sp.add_argument("note")
    sub.add_parser("status").add_argument("slug")
    args = p.parse_args(argv)
    if args.cmd == "status":
        show_status(args.slug)
        return 0
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
