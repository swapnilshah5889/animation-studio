# Step 2: `synfig_mcp`: scene, rig, motion and render tools

> **Status: done (2026-10-22); done-when closed 2026-10-26.** The done-when is proven by a
> scripted MCP client, not a logged-in Claude Code CLI (D-058). Approved 2026-10-21 as written
> (D-028); tool changes during the build are recorded in D-034.

**Goal:** an MCP server that lets an LLM build and render a cut-out shot: a bone-rigged character
with a procedural face, moving with named, parameterized motions, lip-synced from Rhubarb cues,
in front of a parallax background, with a simple camera. This is the first MCP server and the
core of the pipeline.

**Out of scope:**
- AI-generated art (Step 4): placeholder parts are drawn in code.
- Generating audio (Step 3): use the Step 0 fixture line and its Rhubarb cues.
- The director agent (Step 5): a coding agent and the MCP Inspector are the clients here.
- Real three-quarter view art: the schema supports views, but only the front view gets art.
- IK and Skeleton Deformation (bendy limbs).

## What Step 1 established (build on it, don't relitigate)

- **`studio_core/sif/`** builds `.sif` deterministically: canvas, units, typed values,
  waypoints, import/group/switch layers, **bones + `bone_link` + skeleton layer**, render
  (Synfig CLI → PNG) and encode (ffmpeg → MP4), and Rhubarb cues → mouth waypoints. 48 tests.
- **D-027:** **bones for characters**, **nested groups for scene layout** (placement, camera,
  parallax, props). Art lies in bone-local space; the skeleton layer is written but not rendered.
- **Format facts** (`docs/learning/synfig-format.md`):
  - Group transform: `parent = offset + R(angle) · scale · (local − origin)`.
  - Interpolation: `clamped` for continuous motion, `halt` for holds; strings step.
  - Switch changes are frame-exact. `end-time` is inclusive. Write times as frames.
  - The CLI aborts on bones-after-layers and renders blank parts on missing PNGs. **Validate
    before every render.**
- **Pipeline rule (Step 0):** Synfig → PNG frames → ffmpeg per shot; melt only assembles MP4s.

## Owner checkpoints

1. **Approve this brief.**
2. **Schemas** (`rig.schema.json`, `shotlist.schema.json`) after task 2.1, before tools are built
   on them. They are the contract the director LLM will write against.
3. **Motion feel:** a preview video of every motion in the library (task 2.5). Timing and energy
   are taste; the owner decides what "a wave" looks like.

## Design decisions proposed here (owner may overrule)

| Topic | Proposal | Why |
|---|---|---|
| Source of truth for a shot | A **shot spec JSON** (`shots/<id>/shot.json`, validated by the schema); `scene.sif` is a **build artifact** regenerated from it on every change | Tools stay small and idempotent; the LLM edits intent, not XML; hand edits in Synfig can be re-imported later if needed (D-008 still holds for the film folder) |
| Server layout | `mcp/synfig_mcp/` as a uv workspace member (`synfig-mcp`), importing `studio_core` | Matches ARCHITECTURE; one venv for our code |
| SDK | Official **MCP Python SDK 2.x** (`mcp` on PyPI, MIT; `from mcp.server import MCPServer`, the v2 name of the FastMCP decorator style) | AGENTS.md: official SDK, FastMCP style |
| Transport | **stdio** now (a coding agent, the Inspector); streamable HTTP added in Step 5 for the Windows node | Simplest locally |
| Motion composition | Per-bone channels; a shot lists motions with start times; a later motion overrides a bone channel for its duration; idle motions (breathe, blink) are **additive** layers | Predictable, testable, enough for v1 |
| Face | **Vector, procedural** (D-007): eyes (blink via eyelid switch or scale), brows (angle and offset per expression), mouth set **A–H, X** as vector shapes in a switch on the head bone | Exact lip-sync and expressions with zero AI cost |

## Installs this step needs (approve with the brief)

- `mcp` 2.x (MIT) and `jsonschema` 4.x (MIT) into the workspace.
- The MCP Inspector, run on demand with `npx @modelcontextprotocol/inspector` (Node 22 is
  installed; npm fetches it on first use).

## Tasks

### 2.1 Schemas (owner checkpoint 2)
- `schemas/rig.schema.json`:
  - `parts`: file, size, pivot.
  - `bones`: name, parent, joint position (in the parent part's image pixels), rest angle, length.
  - Which part each bone carries, and `draw_order` (independent of the hierarchy).
  - `views` (front, three_quarter).
  - `face`: anchor points on the head for eyes, brows and mouth; sizes; colors.
- `schemas/shotlist.schema.json`: the illustrative shot spec in ARCHITECTURE, formalized:
  id, duration, background, camera, characters (position, view, actions with motion name + start +
  params, expressions), dialogue (line id + start), sfx and music placeholders.
- `schemas/film.schema.json`: the fields `studio_core.film` already owns (style and its lock),
  plus stage status.
- Validation in `studio_core/schema.py`; example fixtures that pass and fail; unit tests.

### 2.2 Rig model: `studio_core/rig.py`
- Load `rig.json` → bones (relative angles, origins converted into parent-bone space, exactly
  as the Step 1 demo computes them) + linked part groups in draw order + skeleton layer.
- Placeholder rig: update `scripts/make_placeholder_parts.py` so the head has **no painted
  eyes or mouth** (the face becomes procedural), add a second arm and two legs, and write the
  matching `rig.json`.
- **Validator** (`studio_core/sif/validate.py`): bones before layers, required links, GUIDs
  resolve, images exist, no duplicate GUIDs across characters. It runs inside `render_*`.

### 2.3 Builder additions for vector art
- `region` and `outline` layers (spline points with tangents) and `polygon`, enough for eyes,
  lids, brows and the 9 mouth shapes. Golden tests and a render test.

### 2.4 Procedural face: `studio_core/face.py`
- Eyes (whites, pupils, lids) with **blink** (lid switch or scale, 2–4 frames).
- Brows per expression: neutral, happy, sad, surprised, angry-but-kid-safe "grumpy", worried.
- Mouth set **A–H, X** following Rhubarb's shape guide, as vector shapes in a switch on the head
  bone. `apply_lipsync` drives it with `studio_core.sif.lipsync.mouth_track` (no shape map
  needed any more).
- A face preview sheet (every expression × every mouth) for the owner.

### 2.5 Motion library v1: `studio_core/motions/` (owner checkpoint 3)
- Motions: `idle_breathe`, `blink`, `wave`, `nod`, `head_tilt`, `walk_cycle` (in place),
  `jump`, `point`, `talk_gesture`.
- Each motion is a pure function `(rig, start_frame, fps, params) → keyframes per bone`, with
  parameters such as `duration_s`, `energy` 0–1 and `side` left/right.
- Uses `clamped` for continuous motion and `halt` for holds.
- **Unit-tested timing:** start and end frames, keyframe counts, angle ranges per energy, and
  composition (overrides vs additive idle).
- `scripts/preview_motions.py` renders a short labelled clip of each motion for the owner.

### 2.6 Scene: placement, parallax and camera: `studio_core/scene.py`
- Characters placed by normalized position (0–1, as in the shot spec) inside scene groups.
- **Parallax:** background layers (far → near) in groups whose pan speed scales with a parallax
  factor. Placeholder: 3 procedurally drawn layers (sky, hills, foreground grass/flowers).
- **Camera:** a root group for pan, zoom and push-in. Moves are named presets (`static`,
  `slow_pan_left/right`, `push_in`, `pull_out`) with an ease.

### 2.7 `synfig_mcp` server: `mcp/synfig_mcp/`
Tools (each with a docstring written for the LLM, validated input, and a structured result
containing paths inside the film folder):

| Tool | Does |
|---|---|
| `create_scene(film, shot_id, duration_s, background, camera)` | creates `shots/<id>/shot.json` |
| `build_rig(film, character_id, rig_json?)` | validates and registers a character rig (placeholder rig if none) |
| `add_character(film, shot_id, character_id, position, view)` | places a character in the shot |
| `apply_motion(film, shot_id, character_id, motion, start_s, params)` | adds a motion |
| `pose_at(film, shot_id, character_id, time_s, bone_angles)` | a manual key pose |
| `set_expression(film, shot_id, character_id, expr, start_s)` | brows/eyes expression |
| `apply_lipsync(film, shot_id, character_id, cues_path, start_s)` | Rhubarb cues → mouth |
| `add_parallax_background(film, shot_id, background_id, layers)` | parallax set |
| `camera_move(film, shot_id, move, start_s, duration_s)` | camera preset |
| `render_preview_frame(film, shot_id, time_s, scale=0.5)` | one PNG (fast feedback for the LLM and, in Step 5, the vision QA) |
| `render_shot(film, shot_id, audio?)` | validate → `scene.sif` → frames → `shot.mp4` |
| `describe_shot(film, shot_id)` | the current spec + warnings (cheap state read for the LLM) |

Errors are returned as structured, fixable messages ("unknown motion 'wavee'; known: wave,
nod, …"), because the LLM reads them.

### 2.8 Prove it from a client
- Unit and render tests for every tool, calling the Python functions directly.
- **MCP Inspector:** list the tools, call each one, check schemas and errors.
- **A scripted MCP client** (a project `.mcp.json` entry): build and render the done-when
  shot with only tool calls, and save the transcript as `docs/learning/mcp-first-shot.md`.

### 2.9 Docs
- `docs/learning/mcp.md`: what MCP is (tools, resources, prompts, transports), how a tool
  schema reaches the model, why small tools, what the Inspector shows.
- `docs/learning/motion-library.md`: keyframes vs curves, overlap and follow-through, why
  energy is a parameter.
- DECISIONS: shot spec as source of truth, motion composition, face design, anything changed.
- PROGRESS, and the Step 3 brief (`audio_mcp`).

## Done when

- [x] Schemas approved by the owner; valid and invalid fixtures tested
- [x] `rig.json` → bone rig with draw order and validator; the placeholder rig has a procedural face
- [x] Motion library v1 with timing unit tests; the owner approved the motion preview
- [x] Parallax background and camera presets render correctly (render tests)
- [x] `synfig_mcp` exposes the tools above over stdio; all are tested; the Inspector lists and
      calls them (`scripts/inspector_check.py`)
- [x] **From an MCP client, the shot is built and rendered: a 10-second shot of a rigged
      character waving and blinking in front of a parallax background, with a mouth cue track
      driving the mouth** (ROADMAP Step 2). `scripts/run_first_shot.py` is a scripted MCP client
      that does it (10 tool calls, verified 2026-10-26; D-058).
- [x] Learning notes, DECISIONS, PROGRESS updated; Step 3 brief drafted; work committed and pushed
