# Progress

Update this at the end of every working session. Newest entry at the top.

**Current step:** Step 2 (`synfig_mcp`): task 2.1 (schemas) done, **waiting for the owner's schema
review** (checkpoint 2). Steps 0 and 1 are done.

---

## 2026-10-21: Step 2 started: task 2.1 schemas done, waiting for owner review

The owner approved the Step 2 brief as written (D-028).

**Step 2 task list**

| Task | Status |
|---|---|
| 2.1 Schemas | **Done, waiting for owner review (checkpoint 2)**: `schemas/rig`, `shot`, `shotlist`, `film`; `studio_core/schema.py` (schema + semantic checks with fixable messages); `scripts/validate.py`; valid examples in `tests/fixtures/schemas/`; 27 tests of specific mistakes; `film.json` now validated on save. Learning note: `docs/learning/json-schema.md`. |
| 2.2 Rig model + validator | Next, after the schema review |
| 2.3 Vector shapes in the builder | To do |
| 2.4 Procedural face | To do |
| 2.5 Motion library (owner checkpoint 3) | To do |
| 2.6 Parallax + camera | To do |
| 2.7 `synfig_mcp` server | To do |
| 2.8 Prove it from the Inspector and Claude Code | To do |
| 2.9 Docs, Step 3 brief | To do |

**Verified:** 75 tests pass (`uv run pytest`). The four example files validate; each mistake
case is reported at the right path.

**Open questions for the owner (checkpoint 2: schema review)**
- Are the motion list (9), expressions (6), camera presets (5), the 4-characters-per-shot and
  60 s-per-shot limits, and fps options {12, 24, 25, 30} right for v1?
- Rig convention: rest pose = the art as drawn, `direction_deg` per bone, joints attached at a
  pixel of the parent's part, and draw order separate from the hierarchy. OK?

---

## 2026-10-21: Step 1 done; Step 2 brief drafted

**Done**
- **Rig technique decided by the owner (D-027):** bones for characters, nested groups for
  scene layout (placement, camera, parallax, props).
- **Step 1 done-when is all ticked** (`docs/steps/STEP-1-synfig.md`). The hand-built scenes
  were replaced per D-026 (GUI-saved official example rigs, plus the scene generated both ways).
- **Step 2 brief drafted:** `docs/steps/STEP-2-synfig-mcp.md`. It covers schemas, the rig model
  with a validator, vector shapes for the procedural face, the motion library, parallax and
  camera, the `synfig_mcp` server (12 tools over stdio), and tests from the MCP Inspector and
  from Claude Code as a client.

**Verified**
- 48 tests pass (`uv run pytest`), including real Synfig renders. `uv run scripts/sif_demo.py`
  renders the waving, lip-syncing puppet with both rig techniques; the frames match.

**Next**
- Owner: review and approve (or edit) the Step 2 brief. It proposes a few decisions to confirm:
  - The shot spec JSON is the source of truth; `scene.sif` is regenerated from it.
  - Motion composition: overrides per bone, plus additive idle motions.
  - A vector face.
  - Installs: `mcp` 2.x, `jsonschema`, and the MCP Inspector via npx.
- Agent, after approval: Step 2 task 2.1 (schemas), then owner checkpoint 2.

**Open questions for the owner**
- Approve the Step 2 brief, including its installs and proposed decisions.

---

## 2026-10-20: Step 1 started (Synfig by hand + .sif generator)

The owner approved the Step 1 brief ("yes begin").

**Step 1 task list**

| Task | Who | Status |
|---|---|---|
| 1.0 Install Synfig Studio GUI | Owner | **Done**: installed 2026-10-20, opens (doctor OK) |
| 1.1 Hand-made scene, rigged with groups and with bones | Owner | **Replaced (D-026)**: the owner asked the agent to do it; GUI-saved official example rigs were surveyed and the scene was generated in both rig variants |
| 1.2 `docs/learning/synfig-format.md` | Agent | **Done**: canvas, units, layers, measured group transform and interpolation curves, switch layers, bones and Skeleton Deformation (verified by render tests), what the GUI writes vs what the CLI needs, gotchas. |
| 1.3 `studio_core/sif/` builder | Agent | **Done**: units, typed values and waypoints, import/group/switch/rectangle/circle layers, **bones, bone links and skeleton layer**, deterministic XML, render and encode helpers, Rhubarb cues → mouth waypoints. |
| 1.4 Tests | Agent | **Done**: 48 tests, including real Synfig renders that check the pivot rotation, switch timing, and bone rigs (hand-written and builder-made) against forward kinematics in pixels (`-m render`). |
| 1.5 Demo → MP4 | Agent | **Done and verified**: `uv run scripts/sif_demo.py` builds a waving, nodding, lip-syncing bunny over a panning background, **rigged with groups and with bones**; both render 168 frames at 1080p with the voice line, and match (worst PSNR 97 dB). About 22 s for both. |
| 1.6 Docs: rig decision, Step 2 brief | Agent | After the owner's scenes (checkpoint 2) |

**Verified facts worth knowing** (details in `docs/learning/synfig-format.md`)
- Group transform: `parent = offset + R(angle) · scale · (local − origin)`, angles CCW in degrees,
  y up. Measured by rendering.
- Interpolation names in files: `halt` = ease, `linear`, `clamped` (default), `constant`, `auto` =
  TCB. Measured curves: `halt` stops at every waypoint; `clamped` carries speed through.
- Switch `layer_name` changes are frame-exact; `end-time` is inclusive; times written as frames.

**Next**
- Owner: confirm the rig technique (checkpoint 2, below).
- Agent: record it in DECISIONS.md, then draft the Step 2 brief (`synfig_mcp`) for review.

**Open questions for the owner**
- **Checkpoint 2 (rig technique):** the agent's evidence-based recommendation is **bones for
  characters, nested groups for scene-level transforms**. Bones give draw order independent of the
  hierarchy (far arm behind the body) and image bending; render speed and output are the same
  (the demo renders both). Cost: ~1.4–1.9x the XML and GUID bookkeeping, all in tested code.
  See "Rig technique" in `docs/learning/synfig-format.md`.

---

## 2026-10-19 (evening): Step 0 complete: environment set up, verified and benchmarked

**Done and verified** (`uv run scripts/doctor.py` → `ALL GREEN`, exit 0: 38 OK + 1 DEFER with ComfyUI running; with it stopped, ComfyUI shows as an on-demand DEFER)
- **Tools:** uv 0.13.1, Python 3.12.15 (uv-managed), Synfig 1.5.5 CLI (Homebrew formula, native
  arm64, D-014), MLT `melt` 7.42.0, Rhubarb 1.14.0 (x86_64 under Rosetta, D-022), Kdenlive 26.08 and
  Krita 5.3.4 (notarized, Gatekeeper accepts them), ffmpeg 9.0.2. vtracer vectorized a test frame.
- **Services:** Qdrant v1.19.2 via `infra/docker-compose.yml` (round-trip verified). **Ollama now
  runs as a Homebrew service** (`sh.brew.ollama`, D-023). ComfyUI v0.42.1 starts with
  `scripts/comfy_server.sh`.
- **Models** (all in `docs/MODELS.md` with licenses; everything in the default pipeline is
  commercial-OK): qwen3:14b, gpt-oss:20b, qwen3-vl:8b-instruct (+ the thinking tag), SDXL Base 1.0
  + StoryBook LoRA + SDXL-Lightning 8-step + fp16-fix VAE, SAM 2.1 small, Depth Anything V2 Small,
  Kokoro-82M, ACE-Step 1.5.
- **Smoke tests:** Synfig renders a hand-written cut-out scene to MP4; melt renders a color clip +
  voice to MP4; Kokoro voices a line; Rhubarb produces mouth cues for it (fixtures in
  `tests/fixtures/audio/`); ACE-Step produces 30 s of music; ComfyUI runs SDXL (normal and
  Lightning), SAM 2 and depth through its HTTP API (a flat kids'-book rabbit, its mask, its depth).
- **Tool calling:** qwen3:14b 5/5; gpt-oss:20b 3/5 first try, 4/5 after a validation-error retry.
  Provisional director pick: qwen3:14b with thinking off for tool calls (D-024).
- **Benchmarks:** every stage in `docs/benchmarks.md`, with a summary table and a rough 30–40 min
  estimate for a 60 s film on the Mac alone.
- **Style switcher** (owner request, D-019 → D-025): all three candidates downloaded and
  license-checked. Styles in `config/models.toml`:
  - `storybook` (A, **default**, commercial yes)
  - `dreamshaper-lightning` (B, commercial **unclear**)
  - `animagine` (C, commercial yes, `safe` tag always)
  - `cutecartoon` (bonus)
  `studio_core.comfy_graphs.txt2img(style, ...)` builds the ComfyUI workflow from a style.
  `studio_core.film` locks a film's style once it has characters (`StyleLockedError`); tested.
  Side-by-side samples (character fast/normal + background per style) with timings are in
  benchmarks.md; the image grid is at `~/ai-studio/scratch/style-compare/grid.png` (not
  committed: generated media). Animagine breaks with the Lightning LoRA, so its fast variant
  uses 16 of its own steps.
- **Docs:** DECISIONS D-014..D-024; learning notes on Apple Silicon inference, model licenses and
  tool calling; Step 1 brief drafted.
- **Commits:** small commits on `main`, pushed to `origin/main` by the parent session through
  `d693aee` (open question 1).

**Problems found (documented, not hidden)**
- **ACE-Step 1.5 overuses memory:** ~30 GB process footprint (float32 on MPS, plus a second MLX copy
  of the DiT), free memory down to 0–1% and up to 13 GB of swap for one 30 s cue. Step 3 must fix
  this before music runs inside a pipeline (D-020 lists options).
- **ACE-Step's language model** (3.8 GB) was meant to be skipped but the library refuses to start
  without it; it is installed and unused (D-020).
- **GPU benchmarks were contaminated** by the owner's Montage app, which kept `qwen2.5:7b` loaded in
  Ollama and calling it every 10–20 s. SDXL timings are upper bounds. Re-run on a quiet machine:
  `uv run scripts/benchmark.py sdxl` (and `llm`, `music`).
- **gpt-oss:20b invents enum values** in tool calls; the director must validate every call.
- **The network was slow** (~3 MB/s) for the first ~2 hours, then fast (~30 MB/s). A network blip
  made Ollama restart one 9 GB download and Homebrew fail Krita once (retried fine).
- **Not done by the agent on purpose:** launching Kdenlive and Krita for the first time (macOS shows
  its "downloaded from the internet" confirmation, which is the owner's to click) and installing
  the Synfig Studio GUI (unsigned, Gatekeeper; owner installs at Step 1).

**Next**
- Owner: review and approve (or edit) `docs/steps/STEP-1-synfig.md`.
- Owner: open Kdenlive and Krita once and accept the first-launch prompt; install Synfig Studio
  from `~/ai-studio/downloads/synfig-1.5.5/SynfigStudio-1.5.5.dmg` (Privacy & Security → Open
  Anyway), then remove the `[doctor] deferred` entry in `config/studio.toml`.
- Agent, after approval: Step 1 tasks 1.2–1.6.

**Open questions for the owner**
1. **Push (resolved):** on your instruction "keep everything committed in this repo", the parent
   session pushed all Step 0 and style commits to `origin/main` (through `d693aee`). CLAUDE.md now
   says to commit and push after each verified task (`github-5889` alias, never force-push). If you
   want this session to push its own commits too, just confirm once here.
2. **Default style:** `storybook` stays the default. Pick another for a film with
   `Film.create(..., style)`; it locks once characters exist. `dreamshaper-lightning` is
   commercial-unclear and should not be used for published films.
3. **Step 1 rig technique** (nested groups vs Synfig bones) is decided after you build the scene;
   the brief asks you to rig it both ways.
4. **Disk:** the thinking variant `qwen3-vl:8b` (6.2 GB) is kept for comparison; delete it with
   `ollama rm qwen3-vl:8b` if you prefer.
5. **Montage app:** it uses Ollama continuously. Fine for normal work, but stop it during
   benchmarks and long pipeline runs (24 GB holds one big model at a time).

**How to re-check this machine**
```
uv run scripts/doctor.py                     # everything green?
docker compose -f infra/docker-compose.yml up -d
scripts/comfy_server.sh && uv run scripts/comfy_smoke.py
uv run scripts/smoke_engines.py all --wav tests/fixtures/audio/pip_line_01.wav
```

---

## 2026-10-19: Project planned and handed off

**Done**
- Project folder and planning docs created: CLAUDE.md, README, ARCHITECTURE, ROADMAP, DECISIONS,
  MODELS, Step 0 brief, `.gitignore`.

**Known machine state (Mac)**
- Installed: Homebrew, Node 22.13, ffmpeg, Ollama 0.40.6, Docker 28.3, Git 2.50.
- Missing: uv, Synfig, Krita, Kdenlive, MLT `melt`, ComfyUI, Rhubarb.
- System Python is 3.15. Use uv + Python 3.12 for everything (D-009).
- ~717 GB free disk.

- Git repository initialized on `main`, pushed to `git@github-5889:swapnilshah5889/animation-studio.git`.

**Next**
- Agent: start Step 0, task 0.1 (doctor script). Commit and push after each verified task.

**Open questions for the owner**
- None yet. Image checkpoint choice comes up during Step 0, task 0.5.
