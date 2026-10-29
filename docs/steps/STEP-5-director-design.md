# Step 5 director: design and skeleton plan (fast path to a first film)

> **Status: proposal, docs only.** Companion to [`STEP-5-director.md`](STEP-5-director.md) (which
> stays the brief). Per AGENTS.md the **agent loop core is the owner's to write by hand**; this file
> says what it is, so you can write it, or hand it to a session. Nothing here is built.
> Where this file differs from the brief, it says so (see "Differences from the brief").

The fastest credible path: **one director process, a flat stage machine, per-stage tool subsets,
schema-forced plans, code-checked completeness, 4 approval stops, and a 15-second film before the 60-second one.**
Craft library, look-then-fix, and the Windows render node are layered on after the first film exists.

## 1. Stage state machine

Stages, in order: `story → characters → backgrounds → audio → shots → edit → qa`.
(The brief folds `qa` into `shots`; here the per-shot fix loop stays inside `shots`, and `qa` is the
whole-film check after `edit`.) Each stage is *complete* only when **code** says so by checking the
film folder (files exist and validate); the model's "I'm done" is never enough.

| Stage | Produces (in `films/<slug>/`) | Complete when | Main servers |
|---|---|---|---|
| story | `story/outline.json`, `story/characters.json`, `story/places.json` | schemas valid; kid-safety passed; durations sum to target ±10% | none (LLM plan) |
| characters | `characters/<id>/` puppets, `art_report` | every character in `characters.json` is built and `describe_art` says passed | art |
| backgrounds | `backgrounds/<id>/` layers | every place built, `preview_background` has no hole | art |
| audio | `audio/` voices cast, lines, music cues | every line in the outline has a `line_id`; one music cue per scene | sound |
| shots | `story/shotplan.json`, `shots/<id>/shot.json`, `shot.mp4` | every planned shot has a valid spec, preview frames, a render | animation, sound, (qa) |
| edit | `edit/film.kdenlive`, `film.mlt`, `final.mp4` | `describe_edit` lists all shots; `final.mp4` duration ≈ sum | edit |
| qa | `qa/film_report.json` | `check_frame` on key frames of the final, no open `error`-level issue (or the cap hit) | qa |

### State file: `films/<slug>/director/state.json`

(Not `director.json` as in the brief: one folder, `director/`, holds `state.json`, `review/`,
`log.jsonl`, `transcripts/`.) Pydantic model `DirectorState`; saved atomically (write temp, rename)
after every tool call batch and every stage change.

```json
{
  "schema_version": 1,
  "film": "moon-picnic",
  "prompt": "<the owner's story prompt>",
  "target_seconds": 60,
  "approvals": {"story": "required", "characters": "required", "first_shot": "required", "final": "required"},
  "current_stage": "characters",
  "stages": {
    "story": {"status": "approved", "attempts": 1, "started": "...", "finished": "...",
              "artifacts": ["story/outline.json", "story/characters.json", "story/places.json"],
              "approval": {"by": "owner", "at": "..."}, "last_error": null},
    "characters": {"status": "running", "attempts": 1, "artifacts": ["characters/kit/rig.json"],
                   "per_item": {"kit": "built", "bo": "awaiting_choice"}, "last_error": null}
  },
  "counters": {"model_calls": 41, "tool_calls": 63, "refusals": 5, "prompt_tokens": 182340,
               "output_tokens": 21110, "llm_seconds": 612.4, "tool_seconds": 3120.8,
               "per_stage": {"story": {"model_calls": 6, "...": 0}}}
}
```

Statuses: `pending → running → awaiting_approval → approved → complete`, plus `failed` (stopped with
`last_error`, needs the owner or a retry). `per_item` lets art stages resume per character/place.

**Resume rules**
1. `director resume <slug>` loads the state, then **re-verifies from the top**: for each stage marked
   complete, run its completeness check; the first one that fails is reset to `pending` (files were
   deleted or edited), and everything after it is marked stale.
2. A `running` stage (crash) restarts with a **fresh conversation** plus a state summary (what exists,
   what is missing). Tools are idempotent (same text = cached take, `--resume`-style art skip), so
   re-asking is safe. Never replay old messages.
3. `failed` stages need `director retry <slug> [--stage x]` (resets attempts) or an owner edit of the
   artifact; the director never silently retries a failed stage.
4. `awaiting_approval` stays until `director approve <slug> <name>` (or `--auto`).

**Approval checkpoints** (default; `approvals` in state turns each `required`/`auto`). At each stop
the director writes `films/<slug>/director/review/<name>.md` and prints its path; the owner approves with
the CLI or asks for a change (`director revise <slug> <name> "<note>"` re-runs the stage with the
note appended to the user message).

| Checkpoint | After | Owner sees |
|---|---|---|
| `story` | story stage | `review/story.md`: the outline per scene, characters, places, lines (text from the structured JSON, rendered) |
| `characters` | each `choose_design` and the build | `review/characters.md` linking each `design_sheet` PNG and `preview_puppet` MP4, with the pass/fail flags from `describe_art` |
| `first_shot` | first rendered shot | `review/first_shot.md` with `shot.mp4` and the QA notes; this is the look-and-feel gate before the other shots render |
| `final` | qa stage | `edit/final.mp4`, `edit/film.kdenlive`, and `review/final.md` (open QA issues, counters, time spent) |

## 2. The tool-calling loop on Ollama

**Model**: qwen3:14b (D-024). `think: false` for routine calls (tool execution stages), `think: true`
for the planning calls (`story`, shot plan, and one retry after a schema failure). Switching
`think` is per request, so a stage can plan with thinking on and then run tools with it off.

**Message layout** (one fresh conversation per stage, per item in art stages):

```
system  : stage prompt (director/prompts/<stage>.md) + craft index (names + one-liners, §6)
user    : film brief: the prompt, target length, style, the capability block (compact)
user    : state summary: what exists, what is missing, any owner revision note
assistant/tool pairs ...   (grows; tool results are short: ids, paths, counts, never dumps)
```

**Tool lists through a stdio MCP client.** One `McpHub` starts the five servers (the `.mcp.json`
entries, `mcp.Client` + `StdioServerParameters` exactly as `scripts/run_step4_shot.py`'s
`server_params` and `call_tool(..., progress_callback=...)` do), calls `list_tools()` once, and
keeps `{tool_name: (server, schema)}`. The model sees only the **stage's subset**, an allowlist in
`stages.py` (`ToolView`), converted to Ollama's `{"type":"function","function":{name, description, parameters}}`:

| Stage | Tools the model sees (about) |
|---|---|
| story / shot plan | none; planning is a `format`-constrained call (§3). Plus `read_craft` |
| characters | `describe_art`, `design_character`, `choose_design`, `build_puppet`, `preview_puppet`, `read_craft` (6) |
| backgrounds | `describe_art`, `generate_background`, `choose_background`, `split_depth_layers`, `preview_background` (5) |
| audio | `describe_audio`, `set_voice`, `speak`, `compose`, `find_sfx` (5) |
| shots | `describe_film`, `create_scene`, `add_character`, `apply_motion`, `set_expression`, `apply_lipsync`, `pose_at`, `camera_move`, `add_sound_effect`, `set_music`, `describe_shot`, `render_preview_frame`, `render_shot`, `check_frame`, `read_craft` (about 15; the top of the budget) |
| edit | `assemble`, `add_titles`, `export`, `describe_edit` |
| qa | `check_frame`, `kid_safety_check`, `describe_edit` |

The `shots` stage runs **one shot per conversation** (a loop in the stage runner), so 15 tools and a
single shot's history is all the model carries. Tool names are unique across servers (verify; else
prefix with server name in the `ToolView`).

**Validation before running** (`validate_call`, in code, in this order): name is in the stage subset
→ arguments are an object (parse if the model sent a string) → JSON Schema from the MCP tool →
cheap semantic rules (film slug equals the current film; ids exist in the cached `describe_*`). On
failure the call is **not sent**; the error text goes back as the `tool` message, in the form the
servers already use (D-034: "what to fix"). A server-side `is_error` is fed back the same way.

**Budgets** (all in `LoopLimits`, counted in state, enforced in code):
- 3 consecutive refusals of the same tool → stage `failed` with the last message; 12 refusals per stage.
- 25 model calls per shot/item, 120 per stage; a repeated identical call (same name+args) 3 times → stop.
- Per-stage wall-clock cap (art stages: 3 h; others: 30 min) excluding time inside a tool call.
- No tool call and not complete → **one** nudge naming what is missing; second time → `failed`.
- Schema-invalid plan: validation error back once with `think: true`, then fail.

**Context window.** `num_ctx = 16384` (check memory: 14B Q4 ≈ 9 GB plus KV cache for 16k is fine on
24 GB; 32k is a later bump after measuring). Budget: system prompt + craft index ≤ 1.5k tokens;
film brief + capability block ≤ 2.5k; per-turn tool results ≤ 600 tokens (truncate; paths and counts); history ≤ 8k; a
`prompt_tokens > 0.8 × num_ctx` check triggers **conversation compaction**: drop the oldest tool
results, keep a one-line summary per dropped pair ("add_character kit ok"). Since stages and shots
each start fresh, compaction should rarely fire; log when it does.

**Long calls.** `McpHub.call` passes a `progress_callback` that writes each note to the log and the
console; art tools take 4 to 25 minutes, so the client's read timeout is `None` for art tools
(per-tool `timeout_s` in the `ToolView`), and the stage clock is paused while inside a call. If the
process dies mid-call, resume re-asks and relies on idempotency.

## 3. Structured planning outputs

Planning calls use Ollama's `format` (a JSON Schema, constrained decoding) on `/api/chat` with no
tools. Constrained decoding guarantees *syntax*, not sense, so code then checks semantics
(durations, ids, safety) and feeds back a message once. Schemas live in `director/schemas/`.

- **`outline.schema.json`**: `title`, `logline`, `target_seconds`, `scenes[]` {`id`, `place`
  (id from places), `summary`, `seconds`, `characters[]`, `lines[]` {`who`, `text` ≤ 12 words}}. Max 4 scenes, 6 lines per scene (enforced in schema as `maxItems`).
- **`characters.schema.json`**: `characters[]` {`id` (slug), `name`, `description` (plain words: species/age, colours, one distinguishing item, no studio or artist names), `voice_hint`, `role`}; max 3 for the fast path. **`places[]`** {`id`, `description`, `time_of_day`}; max 2.
- **Shot plan (`shotplan.schema.json`)** is a **new** schema. `schemas/shotlist.schema.json`
  exists (`film`, `fps`, `resolution`, `shots[]` each `$ref shot.schema.json`) and describes the
  **built** result: low-level, engine-neutral shot specs (`id`, `duration_s`, `background`, `camera`,
  `characters` with their motions/positions, `dialogue` with line ids, `sfx`, `music_cue`,
  `notes`). A 14B model cannot fill that from nothing: it needs line ids, motion names and bone
  positions. So the model writes a **plan**, and the shot stage turns it into `shot.json` through
  tools, which write `shotlist.json` at the end:

  ```json
  {"shots":[{"id":"s01_sh01","scene":"s01","seconds":5,"place":"orchard",
    "beat":"Kit arrives and spots the apple tree",
    "characters":[{"id":"kit","where":"left","does":"walk_in_then_idle","expression":"curious"}],
    "line":{"who":"kit","text":"What a big tree!"},"camera":"slow_push_in","sfx":"footsteps on grass"}]}
  ```
  `does`, `expression`, `camera` are **enums built at run time from `describe_film`** (the
  capability block), injected into the schema before the call, so the model can only name motions
  that exist. Code checks: every `place`/`id` exists, `seconds` ∈ [2, 8], sum ≈ target, every
  line belongs to the outline, ≥ 1 `idle`/`blink` per character (rules in code).

Open conversion step: `shotplan → shot.json` is a **deterministic call sequence** where possible
(create_scene, add_character, blink + idle, the named motion, camera). The LLM only takes over when a
step is refused or the plan is ambiguous. That is the biggest saving of model calls (and risk).

## 4. Memory between stages

One large model in memory at a time (AGENTS.md). `MemoryGuard` (in `memory.py`) is a context manager
around each stage:

| Entering | Before | After |
|---|---|---|
| story, shots, edit, qa (LLM stages) | ComfyUI `/free` (and check Qdrant/others are tiny); load qwen3:14b with `keep_alive` 30 m | keep loaded across LLM stages |
| characters, backgrounds | unload qwen3:14b (`keep_alive: 0`), verify via `loaded()` | the art servers unload ComfyUI themselves after the job (existing 4.1 behaviour) |
| audio (`compose`) | unload qwen3:14b; `compose` refuses while ComfyUI is up | nothing |
| qa (qwen3-vl) | unload qwen3:14b, load qwen3-vl | unload qwen3-vl |

Order to avoid thrash: `story` (LLM) → `characters` + `backgrounds` (art; the director LLM only
reloads between items for the choose-or-retry decision, so make that decision **in code**, as
`run_step4_shot.py` does: first passing candidate, else another round) → `audio` → `shots` (LLM, with
`render` tools) → `edit` → `qa`. Art stages are therefore mostly **code-driven** with the LLM
used for `design_character` descriptions, which come from `characters.json` anyway. That is the
fastest path to a first film: the LLM *plans* once, then *operates* the shot tools, which is where
tool calling earns its keep. Note this in the roadmap as a deliberate narrowing (an owner call, §8).

## 5. Module layout (skeleton: names and responsibilities only)

```
director/
  pyproject.toml                  # package, uv, Python 3.12, deps: mcp, jsonschema, pydantic
  src/director/
    __main__.py                   # PLUMBING  CLI: new | resume | approve | revise | retry | status
    state.py                      # PLUMBING  DirectorState, StageState, Counters; load/save atomic
    config.py                     # PLUMBING  LoopLimits, model names, num_ctx, approval defaults
    hub.py                        # PLUMBING  McpHub: start 5 stdio servers, list_tools, call with progress
    toolview.py                   # PLUMBING  per-stage allowlists; MCP schema -> Ollama tool dict
    ollama_chat.py                # PLUMBING  thin wrapper on studio_core ollama: chat(), format=, think=
    schemas/*.json                # PLUMBING  outline, characters, shotplan (+ runtime enum injection)
    prompts/<stage>.md            # PLUMBING  one system prompt per stage, plain files
    capability.py                 # PLUMBING  capability block from describe_* results (compact text)
    memory.py                     # PLUMBING  MemoryGuard (unload/free)
    review.py                     # PLUMBING  render review/<name>.md, approval gate
    craft.py                      # PLUMBING  index + read_craft(topic) (local tool, not MCP)
    checks.py                     # PLUMBING  completeness check per stage (pure functions on the film folder)
    log.py                        # PLUMBING  log.jsonl writer (every model and tool call)
    loop.py                       # CORE      run_conversation(): model call -> validate -> dispatch -> feed back
    dispatch.py                   # CORE      validate_call(), run_tool_call(), error-to-message
    runner.py                     # CORE      run_stage(), run_film(): state machine, retries, approval stops
  tests/                          # fake-model scripted loop test; state/resume; checks on fixture film folders
```

**The agent loop core** = `loop.py` + `dispatch.py` + `runner.py` (≈ 300 lines together). They hold every
decision that makes this an agent: when to stop, what counts as an error, how failure becomes
feedback, what resumes. Everything else is plumbing a session can write and test without Ollama.
To let the owner start right away, the plumbing session should deliver the core as annotated stubs
plus the fake-model test (`FakeChat` returning scripted `tool_calls`), exactly as the brief's 5.7 says.

Key signatures (all without bodies):

```python
# loop.py
@dataclass
class Turn: messages: list[dict]; tool_calls: int; refusals: int; stop: Literal["done","limit","nudge","stuck"]

async def run_conversation(chat: ChatFn, hub: ToolDispatcher, messages: list[dict], tools: ToolView,
                           *, think: bool, limits: LoopLimits, complete: Callable[[], str | None],
                           on_event: Callable[[dict], None]) -> Turn:
    """Model -> tool_calls -> validate -> run -> tool message -> repeat. `complete()` returns None
    when done, else a sentence naming what is missing (used for the one nudge)."""

# dispatch.py
def validate_call(call: ToolCall, view: ToolView, ctx: FilmContext) -> str | None:
    """None if fine, else a fixable message that is sent to the model instead of running the tool."""

async def run_tool_call(hub: McpHub, call: ToolCall, view: ToolView) -> ToolResult:
    """Run via MCP with progress; refused (is_error) results are returned as data, never raised;
    long results are truncated to the per-result token budget."""

# runner.py
async def run_stage(stage: Stage, state: DirectorState, deps: Deps) -> StageStatus: ...
async def run_film(slug: str, deps: Deps, *, auto: bool = False) -> None:
    """Resume-aware: verify completed stages, run the next, stop at approvals."""

# checks.py
def stage_complete(stage: StageName, film: Path) -> str | None:   # None = complete, else what is missing

# hub.py / toolview.py / memory.py / craft.py
class McpHub:    async def start(names: list[str]); async def call(tool: str, args: dict, on_progress) -> ToolResult
class ToolView:  def for_stage(stage: StageName) -> "ToolView"; def ollama_tools(self) -> list[dict]
class MemoryGuard: async def __aenter__(self): ...   # per stage, unload/free as in §4
def read_craft(topic: str) -> str    # exposed to the model as a local tool next to the MCP ones
```

## 6. Minimal craft library (milestone 2, D-065 part 1)

`docs/craft/<topic>.md`, 200 to 400 words each, shape *When to use / How / What fails and why*.
Retrieval v1: the system prompt carries the **index** (topic name + one line, ~12 lines, ~300
tokens) and the model calls `read_craft(topic)` (a local tool returning the file, capped at 600
tokens). No embeddings, no Qdrant, no new model. Upgrade (later, measured): Qdrant + embedding
retrieval at stage start, as the brief's 5.9, only if the model fails to ask for the right topic.

| # | Topic file | One line | Already written in |
|---|---|---|---|
| 1 | `motion-choice` | which motion for which story beat; what each motion looks like | `learning/motion-library.md` |
| 2 | `timing-and-spacing` | anticipation, follow-through, holds; durations per action | `learning/motion-library.md`, D-046 |
| 3 | `blink-and-idle` | every character gets blink + idle_breathe; when a held pose is dead | `learning/rigging.md`, synfig server text |
| 4 | `expressions` | which expression for which emotion; pairing with lines | `learning/rigging.md` (faces), D-077/078 |
| 5 | `lip-sync` | speak first, then apply_lipsync; mouth shapes; timing of lines | `learning/lip-sync.md` |
| 6 | `dialogue-length` | short lines (≤ 12 words), seconds per word, pauses between speakers | `learning/voices-and-loudness.md` |
| 7 | `staging` | where characters stand (feet fractions), left/right, overlap, front-to-back | `learning/parallax-and-camera.md` |
| 8 | `camera-moves` | push-in, pan, hold; when and how far; no move during dialogue | `learning/parallax-and-camera.md` |
| 9 | `shot-length` | 3 to 6 s typical; establishing first, close-ups for lines, one idea per shot | (new; from the film's own first runs) |
| 10 | `parallax-backgrounds` | layers, pan range, holes, `preview_background` | `learning/monocular-depth-and-layering.md`, `parallax-and-camera.md` |
| 11 | `character-design-prompts` | what to put in a description (plain words, 1 distinguishing item), what fails (busy patterns, tiny props, three-quarter faces) | `learning/consistency-without-training.md`, `cutting-puppets.md`, D-066 |
| 12 | `music-and-sfx` | mood and energy choices, ducking under speech, SFX search phrasing | `learning/voices-and-loudness.md`, D-036 |
| 13 | `what-fails` | the failure catalogue: cropped, overlapping, hole visible, off-model, silent line | D-066, `learning/cutting-puppets.md` |
| 14 | `kids-checklist` | age-appropriateness, no scary peril, no real studios/artists, clear simple story | AGENTS.md constraints, safety list |
| 15 | `qa-fixes` | typed QA issue -> which tool fixes it (missing_character -> add_character, etc.) | brief table in STEP-5-director.md (`check_frame`) |

A session can write 1 to 8, 10, 11, 13, 14 largely by condensing the learning notes; 9 and 15 are
written after the first film run from real findings. Mark anything unmeasured as such.

## 7. Plan: milestone 2

Preconditions from other sessions: `create_film` (5.1), `edit_mcp` (5.5), `qa_mcp` (5.2/5.3) land in
parallel. The director can start before them if the tool views handle absent servers.

| # | Task | Order / parallel | Proves |
|---|---|---|---|
| M1 | Owner reviews this design; decides who writes the core (§8 Q1) | first | go / no-go |
| M2 | Plumbing: `state.py`, `config.py`, `checks.py`, `log.py`, CLI, `review.py`, tests on fixture film folders | parallel with M3, M5 | resume and stage-complete rules, no model |
| M3 | Plumbing: `hub.py`, `toolview.py`, `ollama_chat.py`; a script that lists each stage's tools and calls `describe_film` through the hub | parallel | MCP client wrapper works with 3 existing servers; tool count per stage |
| M4 | **Core**: `loop.py`, `dispatch.py`, with the `FakeChat` test (scripted tool_calls, refusal, loop-stop, nudge) | after M2+M3 (owner, or a session if told) | the loop, caps and feedback, in CI, no GPU |
| M5 | Craft files 1 to 8, 10, 11, 13, 14 + `craft.py` | parallel, anytime | topics exist, `read_craft` returns text |
| M6 | Planning: schemas, prompts, runtime-enum injection; run story+characters+places+shot plan **live** on the test story, `think` on | after M3 | does qwen3:14b plan within schemas; time and tokens |
| M7 | **Core**: `runner.py` + `memory.py`; one real tool round trip, then `shots` stage on **existing** assets (e.g. `step4-proof` cast) for a 10 s shot | after M4, M6 | the model operates the animation tools |
| M8 | Art and audio stages code-driven (first passing candidate), approvals on, 15-second film (1 character, 1 place) | after M7 and 5.1 | first end-to-end film, all four checkpoints |
| M9 | Edit + qa stages with `edit_mcp` / `qa_mcp`, one fix round | after M8 and the sibling servers | final.mp4 + film.kdenlive |
| M10 | The 60-second test film (below), then write craft 9 and 15 and record findings for Step 7 | last | the milestone |

### Test story (fixed, for the first full run)

> *Write a gentle 60-second children's film for ages 4 to 6. Kit, a small curious fox cub with a red
> scarf, and Bo, a cheerful little brown bear cub in blue dungarees, find a lost red balloon in the
> orchard (scene 1, about 25 seconds). They carry it up to the hill at sunset and let it float up to
> the sky (scene 2, about 30 seconds). Both characters talk (two or three short lines each). Warm,
> quiet, friendly mood; soft music; sounds of birds, footsteps and wind. Nobody is sad for long.*

(Kit and Bo already have built puppets and passes in D-066, so this run can reuse them first to
separate "planning and tool use" from "art quality"; the same prompt later runs with fresh art.)

**Done-when for the first run**: (1) `state.json` shows all 7 stages `complete`, 4 approvals recorded;
(2) schema-valid outline and shot plan; every plan shot has a `shot.mp4`; (3) `final.mp4` is 55 to 65 s,
has audio, plays; `film.kdenlive` opens; (4) no kid-safety failure; (5) kill the process in `shots`,
`resume` finishes without redoing finished shots or art; (6) `log.jsonl` has every call; counters
recorded (tokens, refusals, wall-clock) in PROGRESS as Step 7 input; (7) honest list of what the
director got wrong.

## 8. Risks and open questions

**Risks**
- **14B planning quality.** Weak plots, lines too long, invented motions. Mitigations: schema `maxItems`,
  runtime enums from `describe_film`, thinking on for plans, code checks with one feedback round,
  few-shot example outline in the prompt, owner approval after the story.
- **Tool-call drift in `shots`.** Wrong ids, forgotten blink/idle. Mitigations: deterministic call
  sequence from the plan, per-shot conversation, `validate_call`, the "every character gets blink and idle" rule enforced in `checks.py`.
- **Long jobs.** Art 4 to 25 min; a full run is hours. Mitigations: progress notes in the log,
  per-item resume, no read timeout on art tools, `director status` prints the current call and elapsed time.
- **Context overflow.** Fresh conversation per stage/shot, short results, compaction rule, `prompt_tokens` logged each call.
- **Memory.** Two Ollama models and ComfyUI cannot overlap: `MemoryGuard` checks `loaded()` before and after; a test with a fake "ComfyUI up" must refuse an LLM stage.
- **Bad art accepted.** The characters checkpoint shows the pass/fail flags; a failed character stops the stage rather than building on it (D-066 open item).
- **Loop cost.** Hard caps in code, counters in state; a stuck run ends `failed`, never spins.

**Open questions for the owner**
1. **Who writes the loop core** (`loop.py`, `dispatch.py`, `runner.py`)? You by hand, with a session
   supplying the plumbing and stubs plus the fake-model test first; or a session after you review this.
2. **Story length for the first films:** 15 s then 60 s as above, or go straight to 60 s? Scene count (2 here) and shots (about 8 to 12 of 3 to 6 s)?
3. **Approval granularity:** four stops as above, or fewer (story and final only) once Kit/Bo reuse is trusted?
4. **Code-driven art stages** (the LLM only plans and operates shot tools) as the fast path, versus the LLM
   choosing among candidates. This narrows the brief's "director drives all servers"; it can widen later.
5. **Differences from the brief to confirm:** `director/state.json` (folder) vs `director.json`; `qa` as a seventh stage;
   `read_craft` by name first, embeddings later; a separate `shotplan` schema.

## Differences from `STEP-5-director.md`

State path and folder; `qa` as its own stage after `edit`; craft retrieval by named topic before any
embedding model (removes the embedding install from milestone 2); a new `shotplan` schema distinct from
`shotlist.schema.json`; art stages decided in code, per `run_step4_shot.py`. Everything else (D-024 model,
fresh context per stage, caps, `--auto`, logging, memory rules) is the brief's design, restated concretely.
