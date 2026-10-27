# Step 5: the director, `qa_mcp` and `edit_mcp`: one prompt to a 60-second film

> **Status: draft, for the owner's review.** Nothing here is approved or started. The installs and
> the design decisions below are proposals. **The director's agent-loop core is the owner's to
> write by hand (AGENTS.md); this brief proposes its design and a skeleton, and the owner decides
> who writes it (open question 1).** The eval harness is out of scope (Step 7).

**Goal:** a story prompt goes in, and a finished children's film comes out that the owner can open
and polish in Kdenlive. Three new pieces and one upgrade:
- **`qa_mcp`**: a vision model checks a rendered frame against the shot spec, and a kid-safety
  check replaces the word list in `config/safety_blocklist.txt`.
- **`edit_mcp`**: assembles the rendered shots, titles and audio into an MLT project (openable in
  Kdenlive) and encodes the final film.
- **The director** (`director/`): a hand-written agent loop on Ollama that drives the four MCP
  servers (animation, sound, art, edit) plus `qa_mcp` through a stage state machine over the film
  folder, with approval checkpoints and resume. It acts like a veteran animator (D-065): a craft
  library it looks things up in, a look-then-fix loop, rules in code, and a capability list.
- **The Windows laptop as a render node**, and **faster, more autonomous asset creation** (D-064).

**Out of scope:**
- The eval harness and any measurement of the director's *quality* (Step 7). Here we only log what
  happened so Step 7 has data.
- Training the director (Step 9) and OpenToonz (Step 6). The director must not change when the
  engine does (D-030).
- Temporal, MinIO and task queues (Step 8). The render node here is plain HTTP MCP plus a shared
  folder.
- AI-generated video, key-scene generation and image interpolation (D-064, Step 12).
- Anime-style tiers, a second film style, multi-episode memory (Step 10).
- Vision-QA *accuracy* work beyond "good enough to drive the fix loop". Step 7 scores it.

## What Steps 0–4 established (build on it, don't relitigate)

- **Three MCP servers over stdio**, one `.mcp.json`, checked by the Inspector script (D-035):
  - `synfig_mcp` (shots, `describe_film`, `describe_shot`, `render_preview_frame`, `render_shot`)
  - `audio_mcp` (voices, `speak`, `compose`, `find_sfx`, `preview_mix`)
  - `comfy_mcp` (`describe_art`, `design_character`, `choose_design`, `build_puppet`,
    `generate_background`, `choose_background`, `split_depth_layers`, previews)
- **Conventions (D-034, D-046, D-056):** two layers (`studio_core` functions, thin MCP layer);
  every edit re-checks the whole spec and is refused with a fixable message (`ToolError` →
  `is_error`); results are pydantic models; media results are paths inside the film folder; film
  and ids are pattern-checked. **The director's error feedback reuses this:** a refused call's
  message goes back to the model as the tool result.
- **Engine-neutral schemas (D-030):** `film.json`, `rig.json`, `layers.json`, `shot.json`. The
  director's vocabulary names no engine.
- **The film folder is the state** (ARCHITECTURE "Repository layout"): `characters/`,
  `backgrounds/`, `audio/`, `shots/<id>/` (`shot.json`, `preview.png`, `qa.json`, `shot.mp4`),
  `edit/`. The director's resume logic reads it.
- **Director model (D-024, provisional):** qwen3:14b through Ollama, thinking **off** for routine
  tool calls (valid call 5/5, about 7.5 s a trial on the benchmark), thinking **on** for story and
  shot-list planning. gpt-oss:20b is the comparison candidate.
- **`studio_core/ollama.py` is a thin stdlib client**, written so the agent loop can sit on it
  (`chat`, `generate`, `load`, `unload`, `loaded`).
- **Vision model:** qwen3-vl 8B Instruct via Ollama (D-018), already planned for automatic checks,
  *sequenced* (never alongside SDXL).
- **Machine rules:** one large model in memory at a time on the Mac. Unload Ollama before ComfyUI
  and `/free` ComfyUI before LLM work. `compose` refuses while ComfyUI is up; the comfy tools do
  the unloading themselves (4.1).
- **Qdrant** runs in Docker and already holds the sound-effect index (CLAP vectors, D-036).
- **Open items from Step 4 that this step inherits** (D-066): 3 of 5 test casts pass the pass bar
  (4 needed); the pass bar and asset speed are Step 4B's, but the director needs the pass/fail
  flags that `describe_art` already reports, so it can stop and say "this character failed" rather
  than build on it.
- **A gap:** there is no MCP tool that creates a film. `Film.create(root, style_id, manifest)`
  exists in `studio_core`, but the Step 4 proof script (`scripts/run_step4_shot.py`) creates the
  empty film outside MCP. The director cannot start from nothing until it can (task 5.1).

## Owner checkpoints

1. **Approve this brief**, and decide **open question 1** (who writes the loop core).
2. **`qa_mcp` first look (task 5.3):** the vision model describing three of our real preview
   frames and flagging one deliberately wrong frame. Is the critique useful?
3. **Hand-assembled edit (task 5.5):** a 3-shot film assembled by script and opened in Kdenlive
   by the owner. Does it open, play, and look right?
4. **Loop skeleton (task 5.7):** the module layout, the state file and the tool-calling loop
   reviewed, before anything is filled in.
5. **First director run (task 5.11):** the story, the shot list and the character designs the
   director chose, at the approval checkpoints, on a 15-second film.
6. **The 60-second film (task 5.14).**

## Design decisions proposed here (owner may overrule)

| Topic | Proposal | Why |
|---|---|---|
| Film creation | A new `create_film` tool (name, style) on `synfig_mcp`, wrapping `Film.create`. It returns the film id and the locked style. Styles still lock on the first character (D-025) | The director starts from nothing, so it needs a verb for it; the proof script's workaround goes away |
| Where the director talks | Through **MCP clients** to the real servers (stdio on the Mac, HTTP to the Windows node), not by importing `studio_core` | The director then uses exactly what the Inspector and a coding agent use; a tool schema change is seen by the model. Importing would hide bugs the MCP layer has |
| `qa_mcp` model | **qwen3-vl 8B Instruct** (Ollama, already chosen D-018, Apache-2.0). Structured output via Ollama's `format` JSON schema | One vision model for both tools; schema output means the verdict is data, not prose to parse |
| `check_frame` | Inputs: the shot id and a time (or the frame path). The tool builds the question from `shot.json` (who is in it, where, what they do, the camera) and returns `{matches, issues[], confidence}`. Issues are typed (`missing_character`, `wrong_place`, `pose_wrong`, `cropped`, `overlap`, `hole_visible`, `other`) with a plain-words note | The director needs something it can act on, not a caption. Typed issues map to fixes (move, re-time, swap background) |
| `kid_safety_check` | A vision-and-text classifier call over *text* (story, lines, prompts) or *an image*, returning `{safe, reasons[]}`. **The word list stays as a free first gate** and is joined, not deleted: the model only runs when the list passes | A word list is cheap and deterministic; the model catches what words miss. Rules in code first (D-065 part 3) |
| Sequencing | A shared **memory lock** in `studio_core` (the one `comfy_runs` and `compose` already honour): `qa_mcp` takes it, unloads nothing it does not own, refuses with a message while ComfyUI or ACE-Step is up, and unloads qwen3-vl when done. The director also runs QA *between* art stages, never inside one | One large model at a time; the refusal text tells the director what to do (finish the art stage, then retry) |
| Two Ollama models | The director LLM (qwen3:14b) and qwen3-vl do not stay loaded together. Stage boundaries load the one the stage needs (`keep_alive` 0 on the other). Loading costs seconds, so QA calls are batched per stage (check all key frames in one go) | Memory rule; batching hides the swap |
| `edit_mcp` format | Generate **MLT XML** by code (producers, a playlist per track, `mix`/`luma` transitions only where the shot spec asks, title `kdenlivetitle` or plain `qtext`/`pango` producers). Write it as `edit/film.kdenlive` *and* a plain `film.mlt` | MLT is the format Kdenlive opens natively, so "open and polish in Kdenlive" is a file, not an import. A plain `.mlt` plays in `melt` on any node |
| Encoding | **`ffmpeg` encodes each shot to MP4** (`shot.mp4`, already the shot render's job), and `melt` only **assembles** them, with one final encode. Final = H.264 + AAC, 1920×1080, 24 fps | ffmpeg is our encoder (the animation server already writes shot MP4s); melt's own encoder is the less predictable part, and shots stay independently re-renderable |
| `edit_mcp` tools | `assemble(film, shot_order, transitions?)` → `edit/film.kdenlive` + `film.mlt`; `add_titles(film, title, credits?)`; `export(film, quality)` → `edit/final.mp4`; `describe_edit(film)`. Shot order and titles are validated against a small `edit.json` schema (ordered shots, gaps, title cards) | Small, composable tools (AGENTS.md); `edit.json` is the engine-neutral source, MLT is the output |
| Director model | **qwen3:14b** (D-024); thinking **on** only for `story` and `shotlist` stages; **off** elsewhere. gpt-oss:20b stays a comparison for Step 7 | Already decided; this brief just confirms the on/off split by stage |
| Loop core | The agent loop (messages in, tool calls out, results back) is **hand-written** over `studio_core/ollama.py`, **the owner's to write or not**. The brief supplies the design and a skeleton (below) | AGENTS.md: ask before implementing the loop; the learning goal is the point |
| Stage state machine | Stages `story → characters → backgrounds → audio → shots → edit`, each *complete* when named files exist and validate (rules in code, not LLM opinion). State in `films/<film>/director.json`: current stage, per-stage status, approvals, attempt counts, last error. Resume = read the file, re-verify the last completed stage's outputs, continue | Idempotent and crash-safe; the film folder is the truth, `director.json` only remembers progress and approvals |
| Shot lists | A `shotlist.json` with a JSON Schema (`schemas/shotlist.schema.json`): shots (id, purpose, duration, background, characters with actions, lines, music cue, camera). Ollama `format` forces schema-valid output; code then checks the semantic rules (total duration, every id exists in `describe_film`) | Schema-validated, as the roadmap requires. Planning gets structure; the director only *chooses* |
| Approval checkpoints | Configurable per film in `director.json`: default pauses after `story`, after each character `choose_design`, and after the **first** shot. The director writes what it wants approved to `review.md`, stops, and resumes when the owner marks it approved (CLI flag or editing the file) | The owner stays in control early; `--auto` for unattended runs once trusted |
| Error feedback | Same as D-034: a refused tool call returns its message as the tool result, the model retries. **Caps:** 3 consecutive refusals of the same tool → the stage records the failure and asks for help (or tries a different route). A schema-invalid reply gets the validation error back once, then a retry with thinking on | A loop that cannot stop is the classic agent failure; the caps are code |
| Craft library | `docs/craft/` short playbooks (see task 5.9), chunked by heading, embedded and kept in a Qdrant collection `craft`. The director has a read-only `lookup_craft(query)` tool plus stage-start retrieval (the stage name and the shot's actions as the query) | D-065 part 1. Same machinery as `find_sfx` (embed, store, search), reused |
| Embedding model | **Not CLAP**, which embeds audio and short sound captions. Proposed: **`qwen3-embedding:0.6b`** through Ollama (Apache-2.0; the same family as the text encoder already inside the ACE-Step download), or **`nomic-embed-text`** (Apache-2.0) as the fallback. **Licence to be confirmed against `docs/learning/model-licenses.md` terms and recorded in MODELS.md before download** (it is a new model, though small: a few hundred MB) | A text-to-text model is the right tool for chunks of prose. Both candidates are small, permissive and served by the Ollama already installed, so no new runtime |
| Look-then-fix | After a shot is assembled the director renders 2–4 preview frames (start, the line, the end, the motion peak), `qa_mcp.check_frame` each, and revises with the typed issues, up to **2 fix rounds** per shot; then it keeps the shot and records `qa.json` with the open issues. The final render only follows a pass (or the cap) | D-065 part 2; a bounded loop |
| Capability list | At every stage start the director calls the `describe_*` tools and builds a short capability block (motions, expressions, camera moves, bones, voices, installed styles, what `describe_art` says is built and its next step). It plans only from that block, and a request outside it is **declined with a reason** | D-065 part 4; it can never plan a thing the tools lack |
| Memory between stages | A stage runner unloads the director model before an art stage and `/free`s ComfyUI before an LLM stage | The M4 rule, enforced in code |
| Render node | The same MCP servers started with **streamable HTTP** on the Windows laptop (`render-win`), reached by the director through a second entry in `.mcp.json`. The node renders **Synfig shots in parallel**; the Mac stays on the LLM and image work. Files move over a **shared folder** (SMB or `rsync` of the film folder), not MinIO (Step 8) | Only what the step needs: Synfig renders on CPU and do not fight the Mac's memory; shots are independent. Temporal and queues come later |
| Parallel renders | The director enqueues one `render_shot` per shot, with a per-node limit (CPU cores ÷ threads per render), and waits for all. The shared-folder sync happens before (spec + assets) and after (the MP4) | Shots do not depend on each other, so this scales with cores |
| Logging | Every model call and tool call is appended to `films/<film>/director.log.jsonl` with timings and token counts | Step 7 evals and Step 9 training data come from here; cheap to add now, hard to recover later |

### The director's skeleton (proposal; the owner decides who writes the loop core)

Layout under `director/` (a `pyproject.toml` package, Python 3.12, `uv`, like `studio_core`):

```
director/
  pyproject.toml
  src/director/
    __main__.py        # CLI: director new "<prompt>" | resume <film> | approve <film>
    state.py           # director.json: stages, approvals, attempts, last error (pydantic)
    stages.py          # the stage list, each stage's "is it complete?" check on the film folder
    loop.py            # THE LOOP CORE: model call -> tool calls -> results -> repeat (owner's)
    tools.py           # MCP clients (stdio/HTTP) -> the tool list given to the model
    prompts/           # one system prompt per stage (plain .md files)
    craft.py           # lookup_craft(), indexing docs/craft/ into Qdrant
    capability.py      # builds the capability block from describe_* results
    memory.py          # the unload-before-art / free-before-LLM stage guard
    review.py          # writes review.md; checks approvals
  tests/               # state transitions, stage completeness, a fake-model loop test
```

The loop core, in plain words (this is what the owner may want to write):

1. Build `messages`: the stage's system prompt, the capability block, retrieved craft notes, the
   film's state summary.
2. Call Ollama `chat` with the MCP tool schemas as `tools`, `think` set by the stage.
3. If the reply has `tool_calls`: run each through the MCP client. **A successful result and a
   refused result both go back as `tool` messages** (refusals carry the fixable message, D-034).
   Repeat.
4. If the reply has no tool calls, the stage asks its **completeness check** (code). Complete →
   save state, go to the next stage (unload and load models as needed). Not complete → one nudge
   message naming what is missing, then the caps above apply.
5. Anywhere an approval is configured: write `review.md`, save state, stop.

A fake-model test (scripted replies, no Ollama) checks the loop, the refusal retry caps and resume
without any GPU, so the loop is testable in CI.

The skeleton is: all modules above with signatures, docstrings and the state schema, the CLI, the
stage list and completeness checks, and `loop.py` as an annotated stub with the test already
written. The owner fills `loop.py`, or asks for it.

## Installs this step needs (approve with the brief)

All local after download, no API keys, each far under the 20 GB ask-first limit.

| Install | License | Size | Purpose |
|---|---|---|---|
| **qwen3-vl 8B Instruct** (Ollama) | Apache-2.0 | ~6 GB (already planned in D-018; check if pulled) | `qa_mcp` |
| **A text-embedding model:** `qwen3-embedding:0.6b` (or `nomic-embed-text`) via Ollama | Apache-2.0, to be confirmed and recorded in MODELS.md first | a few hundred MB | Craft library retrieval |
| **MLT / `melt`** (Homebrew `mlt`) and **Kdenlive** (the owner's Mac app, to open projects) | LGPL / GPL (run as separate programs; we write files and call the CLI) | MLT ~100 MB; Kdenlive ~300 MB | `edit_mcp`, owner's polish |
| **MCP over HTTP** on the Windows laptop: Python 3.12 + `uv`, Synfig, the repo checked out in WSL2 | per tool | no model downloads | Render node |

`mlt` and Kdenlive are not in the Step 5 list today; approving this brief approves them.

## Tasks

Each task ends with its tests and an update to PROGRESS.md, then a commit.

### 5.1 `create_film` (the missing verb)
- A `create_film` tool on `synfig_mcp` over `Film.create`; it appears in `describe_film`'s next
  step list. Tests; the Step 4 proof script uses it instead of its workaround.

### 5.2 `qa_mcp` plumbing and memory lock
- New `mcp/qa_mcp/` and `studio_core/qa.py`. Ollama vision call with `format` schema output.
- The shared memory lock (refuse while ComfyUI or ACE-Step is up; unload qwen3-vl when done).
- Tests with a fake Ollama (recorded responses), plus a real call under the `gpu` marker.

### 5.3 `check_frame` (owner checkpoint 2)
- Builds the question from `shot.json`; returns typed issues. Try it on three real preview frames
  and one deliberately wrong frame (a character removed, the background swapped). Record what it
  catches and misses, honestly, in `docs/benchmarks.md`.

### 5.4 `kid_safety_check`
- Text and image variants. The word list runs first, the model second. The refusal text says
  *why*. Existing safety tests keep passing; new tests for what the list missed.

### 5.5 `edit.json`, `assemble`, `add_titles`, `export`, `describe_edit` (owner checkpoint 3)
- The `edit.json` schema and a generator for MLT XML (`studio_core/edit/`). Golden-file tests for
  the XML. `melt` renders the plain `.mlt`; the `.kdenlive` variant opens in Kdenlive.
- Hand-assembled 3-shot film from existing shot MP4s, opened by the owner.

### 5.6 Director design review
- This brief's skeleton, the state schema and the stage list. **Owner decides open question 1.**

### 5.7 Skeleton (owner checkpoint 4)
- The `director/` package as laid out above: state, stages, completeness checks, CLI, MCP
  clients, capability block, memory guard, craft lookup stub, the fake-model loop test, and
  `loop.py` stubbed. No LLM call yet.

### 5.8 The loop core
- **Owner-written, or written by the agent only on the owner's explicit say-so.** Done when the
  fake-model test passes and one real tool call round trip works against Ollama.

### 5.9 The craft library
- `docs/craft/`: short playbooks, one idea each, **200–400 words**, a fixed shape: *When to use* /
  *How* / *What fails and why*. First set, written from what the repo already knows:
  tool use (which motion for which beat, expressions with lip-sync), **timing and spacing**
  (anticipation, follow-through, holds), **staging and shot grammar** (where the character stands,
  camera moves, shot length), **parallax**, **what fails** (from D-066, `learning/cutting-puppets.md`,
  `lip-sync.md`, `motion-library.md`), and **a children's-film checklist**.
- Chunked **by second-level heading** (one chunk per "When / How / Fails" block, so a chunk is one
  usable rule, not a paragraph from the middle), each carrying `title`, `file` and `tags` as
  payload, embedded and stored in the `craft` collection. `scripts/index_craft.py` is idempotent
  (the same text keeps its point id).
- `lookup_craft(query, k=3)` and a stage-start retrieval. A retrieval test: 15 hand-written
  queries, each must return the intended playbook in the top 3 (a regression test, not a model
  score).
- The embedding model's licence confirmed and recorded in MODELS.md first.

### 5.10 Stages, shot lists and approvals
- Prompts for each stage; `shotlist.schema.json` and the semantic checks; stage completeness;
  `review.md` and the approval gate; `--auto`.

### 5.11 First director run (owner checkpoint 5)
- A 15-second, one-character, one-background film from one prompt, with approvals on. Everything
  logged; what the director got wrong is recorded in PROGRESS.md as input for Step 7.

### 5.12 Look-then-fix
- Preview frames → `check_frame` → typed issues → the director's revision (≤ 2 rounds per shot).
  The sequencing (QA between art stages) is checked in a test that a fake `qa_mcp` call while
  ComfyUI is "up" is refused.

### 5.13 Render node
- `--transport http` on each server; the Windows node's setup script (`scripts/windows_node.md`,
  idempotent steps); a second `.mcp.json` entry; the shared-folder sync; `render_shot` in
  parallel. **Check the node renders one shot, then eight in parallel, and record the times** in
  benchmarks.md.

### 5.14 Asset speed and autonomy (D-064)
Proposed, owner picks which to do; all are measured before and after in `benchmarks.md`. The
savings below are **what each option attacks, not measurements**: measure first.

| Option | Attacks | Rough expectation (to be measured) |
|---|---|---|
| **Pre-check on a cheap draft:** a low-step, low-resolution draft of a sheet is checked by the existing automatic checks; only a pass gets the full-quality render | Full sheets spent on rejects | Large if the reject rate is high, none if it is low. Measure the reject rate first |
| **Two sheets per round** instead of N, and another round only on failure | A round makes more sheets than are usually needed | Roughly proportional to the sheets saved |
| **Cache rejected seeds** per character and prompt | Re-drawing a seed that already failed | Small; helps on resume and re-runs |
| **Simpler layer fills** for backgrounds (fill behind with a cheaper method where the pan range is short) | The fill-behind pass per layer | Medium for backgrounds; none for characters |
| **A vision model to find faces** (qwen3-vl returning eye and mouth boxes) instead of the detector rules | The face-finder's misses that cost redraws (D-066's Bolt, Mia) | Only if face misses are a common reject reason; measure that first |
| **Lower Docker's memory reservation** (D-064 option already listed) | Memory headroom for ComfyUI | Frees memory, may not change time |

Done for this task when at least two options are measured and the keep/drop decision is recorded.

### 5.15 The 60-second film
- One prompt, two characters, two backgrounds, dialogue, music, sound effects, `final.mp4` and a
  `film.kdenlive` the owner opens and polishes.

### 5.16 Docs
- Learning notes: **agent loops and tool calling in practice**, **state machines for long-running
  agents**, **RAG for a craft library (chunking, retrieval tests)**, **vision models as critics**,
  **MLT and Kdenlive projects**.
- DECISIONS, PROGRESS, MODELS; the Step 6 brief refreshed; work committed and pushed.

## Done when

- [ ] The brief approved and open question 1 decided; installs done and recorded in MODELS.md
      with licenses (including the embedding model)
- [ ] `create_film`, `qa_mcp` (`check_frame`, `kid_safety_check`) and `edit_mcp` (`assemble`,
      `add_titles`, `export`, `describe_edit`) tested and in `.mcp.json` and the Inspector check
- [ ] `director/` runs the six stages from a prompt, with schema-validated shot lists, approval
      checkpoints and resume from the last completed stage; models unloaded between stages;
      logs written
- [ ] The craft library is indexed in Qdrant and retrieval tests pass; the capability list is built
      from `describe_*` tools, and an out-of-range request is declined with a reason
- [ ] The look-then-fix loop runs, bounded, on every shot of the film
- [ ] The Windows node renders shots in parallel through HTTP MCP, with timings in benchmarks.md
- [ ] **One prompt produces a 60-second children's film** (2 characters, 2 backgrounds, dialogue,
      music, sound effects) that opens and plays in Kdenlive
- [ ] Learning notes, DECISIONS, PROGRESS, MODELS updated; the Step 6 brief refreshed; work
      committed and pushed

## Risks

- **A 14B model drives a long job badly.** It can loop, drop a field or forget the plan. Mitigations:
  schema-forced output for plans, rules in code for completeness, bounded retries, state saved
  after every stage, and thinking on for planning. If it still fails, gpt-oss:20b is the
  comparison and Step 9 is where the real fix lives.
- **Context length.** The capability block, craft notes and a growing tool-result history can
  outgrow the window. Mitigations: per-stage conversations (a stage starts with a fresh context
  and a state summary), short tool results (paths and counts, not dumps), and tight craft chunks.
- **Model swapping time.** Switching between the director, the vision model and ComfyUI costs
  loading time on the M4. Mitigations: stage order, batching QA per stage, and measuring the swap
  cost once.
- **Vision QA is a weak judge** (false alarms, misses). The loop is bounded to 2 rounds and a
  failed check never blocks a film by itself; Step 7 measures it. Do not tune on a few frames.
- **Autonomy exposes art failures.** Step 4B's bar and D-066's 3-of-5 cast rate mean the director
  will sometimes receive a bad character. It must be able to stop and ask (approval checkpoint)
  rather than build a film on it.
- **Kdenlive project fidelity.** Kdenlive's own project format carries extra metadata beyond plain
  MLT, and the version on the owner's machine may be fussy. Mitigation: the plain `.mlt` always
  exists and plays; checkpoint 3 opens the project before the rest is built on it.
- **Render-node file sync.** A shared folder across Mac and WSL2 is slow or flaky for many small
  frame files. Mitigation: render to the node's local disk and copy only the finished MP4s back.
- **Craft library quality.** Retrieval only helps if the playbooks are good and right. Mitigation:
  write them from facts already verified in this repo and mark anything unmeasured as such.
- **Licences.** The embedding model is new and unverified until checked (task 5.9). MLT and
  Kdenlive are GPL/LGPL and run as separate programs, like the other apps.

## Open questions for the owner

1. **Who writes the loop core (`loop.py`, task 5.8)?** You by hand (the skeleton and fake-model
   test are ready for you), or the agent after you have reviewed the design?
2. **Approval defaults:** pause after the story, after each character choice and after the first
   shot, as proposed? Or more or fewer?
3. **Embedding model:** `qwen3-embedding:0.6b` first, `nomic-embed-text` as the fallback, both
   Apache-2.0 pending the check?
4. **Windows node file sharing:** an SMB share, or `rsync` over SSH? (Affects the setup script
   only.) Is the laptop reachable from the Mac on the LAN as it is today?
5. **Asset speed options (5.14):** which of the six to try first? The brief suggests measuring the
   reject rate first, since the first and fourth options depend on it.
6. **Shot length and count for the 60-second film:** about 10–14 shots of 3–6 seconds, one scene
   per background? Or fewer, longer shots?
7. **`kid_safety_check` strictness:** refuse on a model flag, or flag for review at an approval
   checkpoint and refuse only the word-list and clear cases?
8. **Kdenlive version:** which version is installed on your Mac? The `.kdenlive` writer targets a
   specific project-format version, and we will match yours.
