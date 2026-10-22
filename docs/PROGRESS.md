# Progress

Update this at the end of every working session. Newest entry at the top.

**Current step:** Step 3 (`audio_mcp`): tasks 3.1–3.4 done. **Waiting for the owner's music review**
(checkpoint 3, `renders/music-samples/index.html`). Step 2 has one done-when item open (D-035).

---

## 2026-10-22: Step 3 started: tasks 3.1–3.4 (schemas, voices, lip-sync, music) done

The owner approved the Step 3 brief as written (D-036).

**Step 3 task list**

| Task | Status |
|---|---|
| 3.1 Audio schemas and file layout | **Done**: `schemas/voice`, `line`, `lipsync`, `music`, `sfx_library`; shot schema gains `sfx[].sound` and `music_volume`; semantic checks (cue order and coverage, unique voices, sounds and audio, line/voice consistency); asset checks in `shot_spec` (line metadata, stale mouth cues, chosen sounds in the library, music cues exist); `studio_core/audio/library.py` (manifest loader); files named by id recognized by folder in `validate_file` (D-037). |
| 3.2 Voices: `speak` (owner checkpoint 2: casting) | **Done; cast by the owner** (Pip c12, Bunny c03, D-039): `studio_core/audio/voices.py` (text checks, content-hash cache, one Kokoro batch per call, trim + pitch step + linear-gain loudness, line metadata, stale cues removed), `studio_core/audio/ffmpeg.py`, `scripts/audio/kokoro_batch.py`, 4 casting voices fetched; casting page `scripts/audio/voice_casting.py` (14 candidates × 2 lines) (D-038). Note: `docs/learning/voices-and-loudness.md`. |
| 3.3 Lip-sync: `lipsync` | **Done**: `studio_core/audio/lipsync.py` (Rhubarb on the final audio with the text, recognizer by language, cache by validity and length, relative `soundFile`, parallel lines); `speak` lip-syncs by default (D-040). Note: `docs/learning/lip-sync.md`. |
| 3.4 Music: `compose` (owner checkpoint 3) | **Done, waiting for the owner's review**: memory fixed in place (bf16 + PyTorch DiT and VAE only): **21.0 → 9.6 GB** peak for a 10 s cue, no swap, flat to 60 s; `studio_core/audio/music.py` (9 moods, instrument list, caption in code, seeded, cached by hash, Ollama unloaded and ComfyUI refused first, peak footprint measured per cue, trimmed + faded + −20 LUFS); samples page `scripts/audio/music_samples.py` (D-041). |
| 3.5 Sound-effect library and search: `find_sfx` | To do |
| 3.6 The mix | To do |
| 3.7 `audio_mcp` server, and shot tools for sound | To do |
| 3.8 Prove it (owner checkpoint 4) | To do |
| 3.9 Docs, Step 4 brief | To do |

**Verified**
- 186 tests pass (`uv run pytest`); ruff is clean.
- Every schema has a valid example. The lip-sync example is the real Rhubarb output from Step 0.
- 24 new mistake cases are each reported at the right path, e.g. a non-CC0 license
  (`sounds[0].license: 'CC0-1.0' was expected`) and a gap between mouth cues.
- Asset checks are tested on a film folder:
  - a line recorded in another character's voice
  - mouth cues made for a shorter take ("run lipsync on it again")
  - an unchosen sound (a warning)
  - an unknown sound id, a broken manifest and a missing music cue (errors)

**Task 3.2 (same day)**
- `speak` works end to end in a scratch film:
  - two lines at −20.0 and −19.9 LUFS (target −20), with true peaks −3.7 and −5.0 dBTP
  - a repeat request is a cache hit in 0 s, even with different spacing
  - `regenerate` makes take 2 and removes stale cues
- 9 voice tests:
  - text checks, the hash, line ids, load errors and refusals (nothing is synthesized when a
    request is refused)
  - synthetic tones: a +2 semitone step lands within 2% of 493.9 Hz and keeps the length within
    30 ms; the trim keeps 80/120 ms of air; the linear gain reaches −23 LUFS within 0.3 LU
  - one real Kokoro run (`-m models`)
- Casting page: 28 takes in 25 s, 1.6 MB self-contained HTML. All 28 embedded clips decode.
- The owner cast Pip as c12 and Bunny as c03 (D-039). Their `voice.json` files are in the
  fixtures, and the demo film now has Bunny.

**Task 3.3 (same day)**
- Rhubarb on the Step 0 fixture line reproduces the fixture's 34 cues exactly. It took 6.3 s,
  and the repeat call is a cache hit.
- End to end: `speak` in Pip's cast voice → cues → `add_dialogue` → the shot passes every check,
  with no errors and no warnings.
- 200 tests pass; ruff is clean. The suite now takes ~60 s, because the `models` tests run
  Kokoro and Rhubarb. Skip them with `-m "not models"`.

**Task 3.4 (same day)**
- Memory hunt (measured, `docs/benchmarks.md`), 10 s cue:
  - fp32 (ACE-Step's MPS default): 21.0 GB, 5.7 GB swapped
  - bf16: 18.6 GB
  - bf16 + PyTorch VAE: **9.6 GB, no swap**
- PyTorch's own numbers (6.9 GB allocated) showed that ~10 GB lived elsewhere: a second,
  float32 MLX copy of the VAE that ACE-Step builds on Macs. Option (b), ComfyUI with a 6.3 GB
  download, wasn't needed. Note: `local-inference-on-apple-silicon.md` (worked example).
- The fix holds at 30 s (9.6 GB) and 60 s (9.7 GB). Generation takes 6 / 14 / 25 s.
- `compose` test (`-m models`): a 10 s cue within the budget, normalized, with valid metadata.
  The repeat call is a cache hit.
- Music samples: 3 moods × 2 takes, 15 s each, 130 s in all. Every take peaked at 9.6 GB and
  measured −20 LUFS, true peak ≤ −1.5 dBTP. All 6 embedded clips decode.
- 206 tests pass (~90 s with the `models` tests); ruff is clean.
- Next: the owner reviews the samples (checkpoint 3), then 3.5 (the sound-effect library and
  `find_sfx`).

## 2026-10-22: Step 2 closed (task 2.9); Step 3 brief drafted

**Done**
- `docs/learning/mcp.md`:
  - what the Inspector showed (docstring indentation reaching the model, validation before our
    code runs, error and result shapes)
  - how a tool schema reaches the model
- `docs/learning/motion-library.md`: keyframes and curves (pose-to-pose, interpolation types),
  overlap and follow-through as the code does them, and why `energy` is a parameter (with the
  wave's numbers).
- `docs/steps/STEP-2-synfig-mcp.md`: status and done-when checklist updated. Every item is met
  except the Claude Code run (D-035).
- DECISIONS: nothing new. The brief's list (shot spec as source of truth, motion composition,
  face design, changes) is covered by D-028, D-029 and D-033–D-035.
- **Step 3 brief drafted:** `docs/steps/STEP-3-audio-mcp.md` (voices, lip-sync, music, sound
  effects with CLAP + Qdrant, the mix). Not started.

**Next**
- Owner: review the Step 3 brief, its proposed decisions and its installs.
- Agent, after approval: task 3.1 (audio schemas).

## 2026-10-21/22: Step 2 task 2.8 done: the Inspector and Claude Code as clients

**Done**
- `.mcp.json` (repo root) registers `synfig_mcp` for Claude Code and the Inspector.
- `scripts/inspector_check.py` drives the MCP Inspector CLI (pinned 2.9.0) through every tool,
  plus 3 calls that must be refused, on a scratch film `films/inspector-check/`.
- Tool descriptions are now cleaned of docstring indentation; the Inspector showed the raw
  indentation reaching the model. A test guards it.
- `scripts/run_first_shot.py`: the done-when run. It runs Claude Code headless with only our 14
  tools on a fresh film `films/first-shot/`, saves the transcript to
  `docs/learning/mcp-first-shot.md`, and checks the result against the done-when.
- `docs/learning/mcp.md`: sections on the Inspector and Claude Code as the client (D-035).

**Verified**
- Inspector: `tools/list` shows the 14 tools, and all 18 calls did what was expected (19/19 with
  the list). Edits, `build_rig`, a preview frame and a 640x360 render worked. The refusals
  (unknown motion, unknown bone, unknown character) came back as `isError` with fixable
  messages. The preview PNG was checked by eye: Pip at x=0.4, mid-wave and talking.
- `claude mcp list` sees the server ("Pending approval": project servers need the owner's OK in
  an interactive session).
- Headless `claude -p` with `--mcp-config .mcp.json --strict-mcp-config --tools ""`: the server
  is `connected` with 14 tools and no built-in tools.
- The done-when checks pass on the hand-written demo shot and fail on an empty film.
- 150 tests pass; ruff is clean.

**Skipped by the owner (2026-10-22): the Claude Code done-when run**
- The run needs the standalone `claude` CLI logged in, and the owner couldn't log it in. Every
  shell the app reaches (the agent's, sandboxed or not, and the Terminal panel) reports
  `loggedIn: false`.
- From inside a Claude Code session, the child `claude` also inherits the session's auth proxy
  and fails with "OAuth session expired". The script now drops those variables and checks the
  login first, so it fails with a clear message.
- **Open done-when item:** "From Claude Code as an MCP client, the LLM builds and renders a
  10-second shot". To close it later, run `uv run scripts/run_first_shot.py` in any terminal where
  `claude auth status` says `loggedIn: true`. It writes `docs/learning/mcp-first-shot.md` and the
  checks. Otherwise, Step 5's director (a local LLM driving these same tools) proves it.

**Notes**
- Inspector 2.9 asks for Node ≥ 22.19 (installed: 22.13.1). It works with warnings. Upgrading
  Node is not in the brief, so it was left alone.

## 2026-10-21: Step 2 task 2.7 done: the `synfig_mcp` server

**Done**
- `studio_core/shot_spec.py` (engine-neutral): the director's verbs as functions that edit
  `shots/<id>/shot.json`. Every edit re-checks the whole spec (schema, semantic rules, the film's
  assets, a dry run of the motion library) and saves nothing if it fails.
- `mcp/synfig_mcp/` (uv workspace member `synfig-mcp`, `mcp` 2.3.0, stdio). 14 tools:
  - read: `describe_film`, `describe_shot`
  - edit: `create_scene`, `add_character`, `apply_motion`, `pose_at`, `set_expression`,
    `apply_lipsync`, `add_parallax_background`, `camera_move`, `remove_from_shot`
  - characters: `build_rig`
  - render: `render_preview_frame`, `render_shot`
- Differences from the brief's tool table, and why: D-034.
- `studio_core/shot.py` gained `render_preview` (one frame → `shots/<id>/preview.png`) and an
  `audio` switch.
- The demo film now has the line's transcript (`audio/dialogue/l001.txt`).
- Note: `docs/learning/mcp.md` (a first version; 2.9 extends it).

**Verified**
- 150 tests pass (`uv run pytest`); ruff is clean. The new MCP tests use the SDK's real client:
  - all 14 tools are listed with descriptions and enums, and no tool schema names an engine
  - a 10-second shot is built step by step (motions, expression, lip-sync, a pose, a camera move),
    and `describe_shot` returns the expected spec with no errors or warnings
  - refusals come back as `is_error` with fixable messages (unknown film, background, motion,
    bone; a character not in the shot; an index out of range; a hand-broken spec refused before
    rendering)
  - `render_preview_frame` (192x108 PNG) and `render_shot` (24 frames at 640x360) work
  - the server starts over stdio and lists its tools
- 12 unit tests for the spec editor.

**Next**
- 2.8: list and call the tools from the MCP Inspector, then build and render the done-when shot
  from Claude Code as the client (`.mcp.json`), and save the transcript.

## 2026-10-21: Step 2 task 2.6 done: placement, parallax, camera and shot assembly

**Done**
- `studio_core/scene.py`: background layers as parallax planes, a characters plane (factor 1),
  in-front layers, a camera group with eased presets (`static`, `slow_pan_left/right`, `push_in`,
  `pull_out`) and a solid backdrop. Built at the 1920x1080 design size and rendered at any size.
- `schemas/background.schema.json` (`layers.json`) and a placeholder meadow with 4 layers
  (`scripts/make_placeholder_background.py` → `tests/fixtures/backgrounds/meadow/`).
- A character's `position` now means the point between its feet (`rig.ground_offset_px`, D-033).
- `studio_core/shot.py`: `shot.json` → `scene.sif` → frames → `shot.mp4`, with expression and
  lip-sync tracks per character and the dialogue mixed in at each line's start. `animate` takes
  manual key `poses`.
- `scripts/make_demo_film.py`: builds `films/step2-demo/` from the fixtures and renders shot
  `s01_sh01` (Pip waves, blinks and speaks line l001 in the meadow during a slow pan).
- Notes: `docs/learning/parallax-and-camera.md`; `motion-library.md` covers key poses.

**Verified**
- 132 tests pass (`uv run pytest`); ruff is clean. Render tests:
  - each layer slides by -pan x parallax, within 1 px
  - `push_in` widens a stripe x1.25
  - zoom 0.5 leaves no transparent pixel
  - a character lands within 1.5 px of its position: body centre on x, lowest pixel on y
  - `render_shot` end to end: 48 frames, plus a video and an audio stream
- The demo shot at 1080p: 240 frames in 55 s (~0.23 s/frame), 1.1 MB MP4. Checked on a contact
  sheet:
  - Pip's feet are on the path at y≈0.92.
  - Pip and the meadow move together during the pan; the hills and sky move slower.
  - The left arm waves, and the mouth changes while talking.
  - Speech is audible from 1.8 to 6.6 s (the line starts at 1.5 s; the WAV has a short lead-in).

**Not done**
- Sound effects and music are not mixed into `shot.mp4` yet (Step 3).
- Placement is fixed per shot. Walking across the frame needs a moving placement and side-view art.

**D-030 (landed during this task)**
- **Schema audit done:** none of the five schemas has an engine-specific field. Two descriptions
  named Synfig internals and were reworded (D-033).
- `scene.py`, `shot.py`, `sif/`, `rig.build_character` and the face layers are Synfig-specific, and
  the motion tracks use Synfig value types. ROADMAP Step 6 already schedules moving them under
  `studio_core/engines/synfig/` behind a backend interface, with no behavior change. So there's no
  extra Step 2 task. 2.7 keeps the MCP tools engine-neutral: they edit shot specs and call
  `render_shot(film, shot_id)`, never `.sif` details.

**Next**
- Agent: 2.7 (`synfig_mcp` server).
- Owner (optional): say so if you'd rather do the `engines/` move before 2.7 instead of in Step 6.

## 2026-10-21: Engine strategy decided (planning session)

**Done**
- OpenToonz spike finished: `docs/spikes/opentoonz.md` and three scripts in `scripts/spikes/`.
  Python-generated `.tnz` scenes render headless, and Plastic works from code. The Tahoma2D
  evaluation was stopped at the owner's request (notes are in the report's appendix). Spike
  leftovers were moved to the Trash. `~/Applications/OpenToonz.app` and
  `~/ai-studio/tools/opentoonz-stuff` were kept.
- The owner approved three decisions:
  - **D-030:** engine-neutral scene model, with engines as backends
  - **D-031:** OpenToonz is the strategic engine, and Synfig ships the first film
  - **D-032:** final rendering runs server-side in stateless containers
- ROADMAP: a new **Step 6, OpenToonz backend + render containers**. The old Step 6 (level up) is now
  Step 7, and its references were renumbered.
- ARCHITECTURE and the CLAUDE.md conventions were updated to match. D-001 (fully local) is unchanged.

**Impact on the current step**
- Step 2: audit the schemas for Synfig-specific fields and move any into the Synfig backend (D-030).
  Keep MCP tool names and arguments engine-neutral.

**Open question for the owner**
- Product delivery: hosted web app, desktop app, or both. This decides D-001's future and whether
  the web-preview backend is needed.

## 2026-10-21: Step 2 started: task 2.1 schemas done, waiting for owner review

The owner approved the Step 2 brief as written (D-028).

**Step 2 task list**

| Task | Status |
|---|---|
| 2.1 Schemas | **Done, approved by the owner (checkpoint 2, 2026-10-21)**: `schemas/rig`, `shot`, `shotlist`, `film`; `studio_core/schema.py` (schema + semantic checks with fixable messages); `scripts/validate.py`; valid examples in `tests/fixtures/schemas/`; 27 tests of specific mistakes; `film.json` now validated on save. Learning note: `docs/learning/json-schema.md`. |
| 2.2 Rig model + validator | **Done**: `studio_core/rig.py` (load + validate rig.json, bones from rest directions and joint pixels, flat bone-linked parts in draw order, skeleton layer, FK `world_pose`, `clamp_offset`); `studio_core/sif/validate.py` runs before every render (bones first, links complete, GUIDs resolve, no duplicates, images exist); placeholder **Pip** with a faceless head, both arms and two-segment legs (`tests/fixtures/characters/pip/`, `scripts/make_placeholder_character.py`). A render test lands parts within 1.5 px of FK. Note: `docs/learning/rigging.md`. |
| 2.3 Vector shapes in the builder | **Done**: `studio_core/sif/shapes.py` (splines with Hermite tangents, smooth/ellipse/arc helpers, region, outline, polygon); render tests measure ellipse and triangle areas within 1%. Found: `bgcolor` doesn't paint renders (transparent → black in MP4), so scenes need a background layer. |
| 2.4 Procedural face | **Done**: `studio_core/face.py` (eyes with open/half/closed and `blink_track`, brows for 6 expressions, Rhubarb mouths A–H + an expression-aware rest X), attached to the head bone via `build_character(attachments=...)`; render test: the face turns with the head (±1.5 px); preview sheet `scripts/preview_face.py`. |
| 2.5 Motion library (owner checkpoint 3) | **Done, approved by the owner (checkpoint 3, 2026-10-21)**: `studio_core/motions/` with 9 motions (idle_breathe, blink, wave, nod, head_tilt, walk_cycle, jump, point, talk_gesture), energy/side/cycles/duration/target params, per-bone override + additive composition, joint-limit clamping, root and joint shifts (`build_character(shifts=...)`); 22 tests (timing, composition, determinism, a rendered jump rising 160 px); preview video `scripts/preview_motions.py`. Bone `role` added to the rig schema (D-029). Note: `docs/learning/motion-library.md`. |
| 2.6 Parallax + camera | **Done**: `studio_core/scene.py` (parallax planes, camera presets, backdrop, feet placement), `schemas/background.schema.json` + placeholder meadow, `studio_core/shot.py` (spec → `scene.sif` → `shot.mp4` with dialogue), key poses, demo film `scripts/make_demo_film.py`; render tests for parallax rates, zoom, placement and the full shot (D-033). Note: `docs/learning/parallax-and-camera.md`. |
| 2.7 `synfig_mcp` server | **Done**: `mcp/synfig_mcp/` (workspace member, `mcp` 2.3.0, stdio, `uv run synfig-mcp`) with 14 tools over the engine-neutral editor `studio_core/shot_spec.py`; 18 tests, including a real client in-process and over stdio, fixable errors and renders (D-034). Note: `docs/learning/mcp.md`. |
| 2.8 Prove it from the Inspector and Claude Code | **Done, except the Claude Code run (skipped by the owner)**: Inspector check (`scripts/inspector_check.py`, 19/19 as expected); `.mcp.json`; headless Claude Code connects with only our 14 tools; the done-when run `scripts/run_first_shot.py` is ready but not run, because the CLI login isn't available (D-035). |
| 2.9 Docs, Step 3 brief | **Done**: `mcp.md` (the Inspector's findings, how a tool schema reaches the model), `motion-library.md` (keyframes and curves, follow-through, why energy is a parameter); Step 2 brief checklist ticked; Step 3 brief drafted for review. |

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
