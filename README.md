# Animation Studio

A fully local, AI-native studio for making 2D animated children's films.

You give it a story idea. A local LLM acts as the **director**: it writes the script, designs
characters, plans shots, and drives open-source animation apps (Synfig, ComfyUI, Kdenlive and others)
through **MCP servers** to produce a finished film. Everything runs on your own machines, with no paid
APIs and no API keys.

> Status: **Steps 0–1 done** (environment + benchmarks; Synfig format + `.sif` generator).
> **Step 2 brief (`synfig_mcp`) awaiting owner review.**
> See `docs/PROGRESS.md`. Check this machine with `uv run scripts/doctor.py`.

## Why it's built this way

- **AI makes assets once; real animation tools do the animating.** Characters are generated once,
  rigged as puppets, and animated by Synfig. That keeps them consistent in every shot, cheaply.
- **Open-source apps become AI-native** through MCP servers the LLM can call.
- **It's a learning project** covering MCP, agents, vector search, evals, LoRA, fine-tuning, GRPO and
  durable workflows, all hands-on.

## Docs

| Doc | What's in it |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Instructions for coding agents working on this repo |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Pipeline, MCP servers, film folder layout, machines, model picks |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Steps 0–6, each with a "done when" |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Decisions made so far, and why |
| [`docs/PROGRESS.md`](docs/PROGRESS.md) | Current status and next actions |
| [`docs/MODELS.md`](docs/MODELS.md) | Every model used, with license and location |
| [`docs/steps/`](docs/steps/) | Detailed brief for each step |

## Starting an agent session

Open a coding agent (e.g. Claude Code) in this folder and say:

> Read CLAUDE.md and the docs it lists, then start the current step in docs/PROGRESS.md.

The agent updates `docs/PROGRESS.md` at the end of every session, so the next one picks up where it
left off.

## Hardware

- **Mac (primary):** Apple M4, 24 GB. Runs the LLM director, image generation, vision QA and music.
- **Windows laptop (from Step 5):** 4 GB RTX, 8-core AMD, 32 GB RAM. Handles rendering, services, TTS
  and encoding.
