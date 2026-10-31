# Animation Studio — agent instructions

You are working on **Animation Studio**: a fully local, AI-native 2D animation studio that turns a
story prompt into a finished children's animated film. Open-source animation apps do the animating;
a local LLM acts as the director and drives those apps through MCP servers.
The end goal is **production-grade films**: the bar is defined in `docs/ROADMAP.md`
("The production-grade bar"), and every step from 4B on works toward it.

Read these before doing anything, in this order:

1. `docs/ARCHITECTURE.md`: what we are building and how the pieces fit
2. `docs/ROADMAP.md`: the steps, each with a "done when" definition
3. `docs/DECISIONS.md`: decisions already made, and why. Don't relitigate them without a reason.
4. `docs/PROGRESS.md`: where the last session stopped
5. `docs/steps/STEP-<n>-*.md`: the detailed brief for the current step, if one exists

## About the owner

- Senior software engineer (Java/Spring Boot, Python, TypeScript, Svelte/React, Temporal, AWS/GCP).
- **This project is primarily for learning AI engineering hands-on**: MCP, agents, RAG/vector search,
  evals, LoRA, fine-tuning, GRPO, durable workflows. A working product is the vehicle.
- So: explain non-obvious choices in the docs, keep code readable, and when you introduce a concept for
  the first time, add a short note under `docs/learning/` (what it is, why we use it here, gotchas).
- **Ask before implementing the director's agent loop core (Step 5) or the eval harness.** The owner may
  want to write those by hand. Propose the design and a skeleton first.

## Non-negotiable constraints

- **Fully local at runtime.** No paid APIs and no API keys. After models are downloaded, the whole
  pipeline must run offline. (A free Hugging Face token for gated *downloads* is fine.)
- **2D only.** No 3D animation. Version 1 targets **children's cut-out (rigged puppet) animation**.
  Anime-style tiers come later (see ARCHITECTURE "Future tiers").
- **Open-source apps first.** Wrap them through their file formats, command-line tools and APIs
  (level 1). Add in-app plugins (level 2) only when needed, and modify app source (level 3) only as a
  last resort, recording why in DECISIONS.md.
- **No reverse engineering of proprietary software.**
- **Children's content:** everything generated must be age-appropriate. Never use names of real studios
  or living artists in style presets or prompts. Describe styles generically.

## Machine facts (owner's hardware)

- **Primary: MacBook Pro, Apple M4, 24 GB unified memory, ~717 GB free.** Homebrew, Node 22, ffmpeg,
  Ollama, Docker and Git are already installed. **System Python is 3.15, too new for PyTorch and most
  ML libraries. Use `uv` with Python 3.12 for every Python environment.**
- **Secondary (joins at Step 5): Windows laptop**, 4 GB RTX GPU, 8-core AMD CPU, 32 GB RAM, ~700 GB free
  SSD. Becomes the render and services node (Synfig rendering, Docker services, TTS, final encodes),
  using WSL2.
- **Mac rules:**
  - Only **one large model in memory at a time** (~16 GB usable by the GPU). Unload Ollama models
    (`keep_alive: 0`) before ComfyUI work, and free ComfyUI memory before LLM work.
  - **Run ML models natively on macOS, never in Docker.** Docker on Mac has no GPU access.
    Docker is only for services (Qdrant now, Temporal/MinIO later).
  - Large model files live **outside the repo** (see `docs/MODELS.md` for locations).

## How to work

- **One roadmap step at a time.** Don't start the next step until the current one meets its
  "done when". If a step is big, split it into tasks and list them in PROGRESS.md.
- **Prove it works.** Run the command, show the output, check the file. Never mark something done
  without verifying it. If something fails or you skip something, say so plainly in PROGRESS.md.
- **Update `docs/PROGRESS.md` at the end of every session**: what was done, what was verified, what is
  next, and any open questions for the owner.
- **Record decisions** in `docs/DECISIONS.md` (short ADR entries) whenever you choose a tool, a model, a
  format, or deviate from the plan.
- **Record every model** you download in `docs/MODELS.md`, with its license and whether commercial use
  is allowed. **Check the license before downloading.** Prefer Apache-2.0/MIT/permissive licenses.
  Flag non-commercial ones clearly.
- **Ask the owner before:** downloads larger than ~20 GB in one go, installing anything not listed in
  the current step brief, deleting files you did not create, or changing a recorded decision.

## Git

- Repository: `origin` = `git@github-5889:swapnilshah5889/animation-studio.git`. Branch: `main`.
  The `github-5889` host alias comes from the owner's `~/.ssh/config` (it selects the right SSH key).
  Don't change it to `github.com`, or authentication fails.
- **Owner's standing instruction: keep everything committed in this repo.** After each completed,
  verified task: commit with a small, focused message (`feat:`, `fix:`, `docs:`, `chore:`), then
  `git push origin main`.
- Before pushing, check `git status` for anything that shouldn't be there. Never force-push or rewrite
  pushed history.
- **Never commit** model weights, renders, generated media, virtual environments, caches or secrets.
  `.gitignore` covers the common cases. Extend it when you add new artifact types.

## Code conventions

- **Python 3.12 via `uv`** (one `pyproject.toml` per package), `ruff` for lint and format, `pytest`
  for tests, type hints throughout.
- **MCP servers in Python using the official MCP Python SDK** (FastMCP style). One server per wrapped
  app, under `mcp/` (see ARCHITECTURE "Repository layout").
- Every MCP tool gets a clear docstring (the LLM reads it), validated inputs, and a structured result.
  Tools that produce media return file paths inside the film project folder, not raw bytes.
- **Rules live in code, not in the LLM.** Timing math, frame counts and file layout are deterministic
  and unit-tested. The LLM decides *what* happens, and code decides *how* it is executed.
- Prefer small, composable tools over one giant "do everything" tool.
- **Keep the scene model engine-neutral (D-030).** No Synfig- or OpenToonz-specific fields in the
  schemas, `film.json`, or MCP tool names and arguments. Engine details belong in
  `studio_core/engines/<engine>/`. Synfig ships the first film, and OpenToonz is the strategic engine
  (D-031). Final rendering is designed for stateless server-side containers (D-032).
- Scripts go in `scripts/` and must be safe to re-run (idempotent).

## Owner's standing preferences (learned; keep these across sessions)

- **Reset (2026-10-31, D-101): one vertical slice first.** Read ROADMAP "Reset" before any work. Engine is Blender,
  cast is the Kenney Female person and Robot; do not reopen either. One working session at a time, each with an
  owner-approved "done when". A session never changes direction or builds unrequested candidates: it stops and asks.
  Bring the owner one decision at a time, with a recommendation, and record it. A short owner message ("fix X") gets a
  question about what "fixed" means before a large brief, not a guess.

- **The end product decides, not the method.** The owner judges the film by eye. A weak-looking film is a
  failure even if the pipeline is clean. Look at the picture, not only at numbers.
- **Test the foundation before building on it.** The first film was built on Synfig before any engine had been
  compared, and the owner called it very weak. Before a big build, run a small bake-off or spike on the risky
  piece (engine, model, format) and write the result down.
- **Engines: Blender and OpenToonz are preferred** (open-source, industry standard, source may be changed as a
  last resort, recorded in DECISIONS.md). The owner is not impressed with Synfig. The final pick is made by eye
  (D-087, D-090). Strict 2D unless the owner approves 2.5D.
- **Data model:** a project owns its cast, its shared backgrounds and many films. A film is acts, each act has
  shots (camera angles). Specs are the editable source, renders are a cache (D-082 to D-084, D-089). Storage sits
  behind the `ProjectStore` interface so an online database can be added later. Do not build the database now.
- **Desktop app wanted at the end** (Step 13): Apple Silicon Mac, GUI for projects, stories, the director and
  saved files (D-081, D-085).
- **Usage is limited.** Keep token use low (read narrowly, few images, keep verification). Run at most two
  sessions at once, give each a time box, and stop a session that keeps re-measuring or polishing. Finish one
  lever before starting the next. (The owner hit their usage limit on 2026-10-30 after three or more parallel
  sessions.)
- **Always show progress** of background work, and write results down in the repo (PROGRESS, DECISIONS, spike
  notes, `docs/learning/`). Chat is not storage: anything learned must be committed.

## Skills and rubrics are agent-agnostic

Reusable know-how lives in plain files in the repo, never only in one tool's folder: rubrics as craft notes in
`docs/craft/` (the director reads them with `read_craft`), procedures and helper scripts in `skills/<name>/`
(`README.md` plus scripts, no tool-specific syntax). Tool-specific files such as `.claude/skills/<name>/SKILL.md`
are thin adapters that point to the neutral copy. Current skill: `skills/animation-review/` (use it before showing
any render to the owner).

