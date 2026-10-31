# Progress

Update this at the end of every working session. Newest entry at the top.

**Current step:** choosing the animation engine and fixing the cut's quality. Done: director (D-080), engine bake-off (D-090),
project data layer, servers on projects, acts and export (D-091), joint overlap (opt-in, plateaued, D-092). Running: a one-session
spike on a single skinned mesh per character in Blender. Next: the engine pick by eye, the lifelike
pass (the director now works on projects and acts, D-094), then the desktop app (Step 13). The owner signed off on the 2026-10-30 plan and leans towards Blender plus OpenToonz over
Synfig. Owner preferences are in `AGENTS.md` ("Owner's standing preferences").
---

## 2026-10-30 (late): the director works on projects and acts (D-094)

**Done and verified (tests):** `director new --project test-cast --film <slug> [--pin-cast kit,bo] [--pin-places orchard]
[--acts 2]` makes a film of a project. The story stage sees the project's library and the owner's pins (an `enum` in the
schema plus a check); a scene is an act with a title. The characters/places stages put library items into the film and run
the art tools only for missing ones (which publish to the library). The shots stage (`stages/acts.py`) plans, builds and
renders one act at a time (`add_act`, `create_scene act=`, `edit_act`, `render_act`), the edit stage is `export_movie`, and
each act has an approval stop (`act_s01`, ...; `revise act_s01 "note"` redoes that act alone). The agent loop core is
untouched. The director's state, story and plans live in `projects/<project>/director/<film>/`, symlinked into the derived
working folder, so deleting the folder loses only renders. Docs: STEP-5B "Adoption by the director",
`docs/learning/director-on-projects.md`. `tests/test_director_projects.py`: 14 new tests (fake model, a real project on disk,
stand-in tools using the real act cache key): library reuse with no art tool, a missing character built and published,
pins, per-act approvals (act 2 is not planned before act 1 is approved), resume after a crash, revising one act re-renders
only that act, dropped shots, working-folder deletion. 93 director tests pass. A latent bug was fixed on the way:
`StageCtx.tool(name, **args)` could not call `build_puppet` (its `name` argument clashed), nothing had exercised it.

**Real run (qwen3:14b, ComfyUI not running), honest result: partial.** 2-act film `kite-smoke` on `test-cast`
(pinned kit, bo, orchard; preview quality). Worked for real: story plan (the safety check refused the first story because
the kids climbed a tree: correct, I revised it), library reuse (no art tool), voices and lines, act 1 planned (3 shots),
built and rendered by the model loop (`act.mp4`, 9.5 s, 640x360, with audio), act 2 planned, and a resume saw act 1 as up
to date (`render_act` skipped it). Failed: act 2's first shot, three tries (one after `revise act_s02`): the shot
conversation stopped as "stuck" (the vision `check_frame` kept flagging a face and the model repeated a call three times;
the loop's stop condition did its job). It is the 14B model's shot loop, not the project plumbing, but it means **no full
film and no `export_movie` run for real**, and the review skill was **not run** (nothing complete to review). Found by the
real run and fixed: a scene with 3 lines at 8 s cannot fit its lines (the story is planned before the lines are spoken), so
an act's target is now `max(scene seconds, what its recorded lines need)`. The film is left in
`projects/test-cast/films/` and `~/ai-studio/work/test-cast/kite-smoke/` (gitignored): `uv run scripts/direct.py retry
kite-smoke --stage shots --project test-cast` continues it.

**Full test suite:** 1047 passed, 6 failed. Four are real-model tests that refuse when `qwen3:14b` is loaded (my smoke film
was holding it), two more heavy model tests (`test_comfy_graph_depth[da3]`, `test_puppet_segment` SAM); not re-run after the
smoke film because they load ComfyUI models. None touch the director.

**Not done / open:** director files are not behind `ProjectStore` and there is no event-log document (D-084 wanted one);
`--dry-run` stubs work on old folders only; a shot renders twice (`render_shot` for the model's check, then `render_act`);
`retry` resets a stage, not one act. **Next:** make the shot conversation less brittle (do not stop on a repeated
`check_frame`; let the code accept the plan's face when the vision advice repeats), then a full 2-act film through the review
skill. **Question for the owner:** should the director keep stopping at every act in non-auto runs (story, cast, first shot, each
act, final is six stops for two acts), or should `first_shot` be dropped when acts exist?

---

## 2026-10-30 (night): head turn moves the whole head (D-097)

**Done and verified:** the owner's bug (on a turn only the face moved). `face_layout.head_warp` turns the whole head about its
vertical axis (skin, face, fringe, hair back, side locks; the far side narrows more; the hair trails by about 0.12 s); the face
features still slide more than the outline (parallax). Rules in code with 140 test cases over yaw -1..1: features stay inside the
skin, the head moves at least 40% of the face's shift, the head stays on the neck (at least 60% chin-over-neck at the collar), turned
parts are not clipped, the hair lags without overshoot. Blender harness swaps the hair images per frame. `turn_test.mp4` and
`turn_sheet.png` are in `~/ai-studio/scratch/rigged-character-test/`. **Independent review (separate agent, rubric item "on a turn
the head moves as a whole"): PASS**, minors only (far locks do not tuck more, square skin corners beside the fringe, the neck does
not follow, the swing through centre reads as a whip, tight headroom in the test). `docs/craft/visual-review.md` Faces has the new
line (file kept under 2400 chars). **Not done / honest:** a real three-quarter set for turns beyond about 0.6; the round-2 majors
(walk, hair shape, headroom in the clip) are untouched by instruction; frames between the sheet times, the body in the turn and
audio were not checked.

---

## 2026-10-30 (night): Mia round 2, review findings fixed (D-096)

**Done and verified:** the independent review's findings: the double-exposure dissolve is gone (one real camera push-in, rule
`transition_for`: cut when both scenes hold the character at scales more than 1.25x apart), the neck is a tapered torso part under
a collar band with a chin shade, the hair is one smooth unioned shape (no flat top, notch or slab), legs are 27.7% of the height
(11% before) with boots at 9% (14%), hands overlap the cuffs (the hand image was clipped), new `walk_step` motion (higher eased
lift, knee bend, bob, sway), pupils converge. 11 new tests (`tests/test_flat_round2.py`); `clip_v2.mp4`, `sheet_v2.png` and my
own `review_v2/review.md` are in `~/ai-studio/scratch/rigged-character-test/`; `motion.csv` has 0 spikes above 5x median.
**Independent review of clip_v2: NEEDS WORK** (my self-review said PASS and was wrong). Majors: (1) after the push-in the hair
top touches or is clipped by the frame top and the boots are cut off from 4.25 s (no head room); (2) walk: short thin legs under
a big head, a scissor cross at 1.25 s, almost no arm swing, a shuffle; (3) hair is a helmet with square scalloped lobes and the
face a near-rectangle. Minors: neck still a tan block in a bowl collar, dead hold 2.0 to 3.0 s with a rigid arm, sly or sleepy
lids at 3.25 and 5.25 s, body frozen while talking. Round-1 status: dissolve fixed, neck partly, hair and walk not. Full table in
`docs/spikes/rigged-character-test.md`. **Stopped after two fix passes by instruction; round 3 not started, the owner decides.**
Still unchecked: lip-sync and audio by ear, the defect counter on the new art.

---

## 2026-10-30 (late): the director works on projects and acts (D-094)

**Done and verified (tests):** `director new --project test-cast --film <slug> [--pin-cast kit,bo] [--pin-places orchard]
[--acts 2]` makes a film of a project. The story stage sees the project's library and the owner's pins (an `enum` in the
schema plus a check); a scene is an act with a title. The characters/places stages put library items into the film and run
the art tools only for missing ones (which publish to the library). The shots stage (`stages/acts.py`) plans, builds and
renders one act at a time (`add_act`, `create_scene act=`, `edit_act`, `render_act`), the edit stage is `export_movie`, and
each act has an approval stop (`act_s01`, ...; `revise act_s01 "note"` redoes that act alone). The agent loop core is
untouched. The director's state, story and plans live in `projects/<project>/director/<film>/`, symlinked into the derived
working folder, so deleting the folder loses only renders. Docs: STEP-5B "Adoption by the director",
`docs/learning/director-on-projects.md`. `tests/test_director_projects.py`: 14 new tests (fake model, a real project on disk,
stand-in tools using the real act cache key): library reuse with no art tool, a missing character built and published,
pins, per-act approvals (act 2 is not planned before act 1 is approved), resume after a crash, revising one act re-renders
only that act, dropped shots, working-folder deletion. 93 director tests pass. A latent bug was fixed on the way:
`StageCtx.tool(name, **args)` could not call `build_puppet` (its `name` argument clashed), nothing had exercised it.

**Real run (qwen3:14b, ComfyUI not running), honest result: partial.** 2-act film `kite-smoke` on `test-cast`
(pinned kit, bo, orchard; preview quality). Worked for real: story plan (the safety check refused the first story because
the kids climbed a tree: correct, I revised it), library reuse (no art tool), voices and lines, act 1 planned (3 shots),
built and rendered by the model loop (`act.mp4`, 9.5 s, 640x360, with audio), act 2 planned, and a resume saw act 1 as up
to date (`render_act` skipped it). Failed: act 2's first shot, three tries (one after `revise act_s02`): the shot
conversation stopped as "stuck" (the vision `check_frame` kept flagging a face and the model repeated a call three times;
the loop's stop condition did its job). It is the 14B model's shot loop, not the project plumbing, but it means **no full
film and no `export_movie` run for real**, and the review skill was **not run** (nothing complete to review). Found by the
real run and fixed: a scene with 3 lines at 8 s cannot fit its lines (the story is planned before the lines are spoken), so
an act's target is now `max(scene seconds, what its recorded lines need)`. The film is left in
`projects/test-cast/films/` and `~/ai-studio/work/test-cast/kite-smoke/` (gitignored): `uv run scripts/direct.py retry
kite-smoke --stage shots --project test-cast` continues it.

**Full test suite:** 1047 passed, 6 failed. Four are real-model tests that refuse when `qwen3:14b` is loaded (my smoke film
was holding it), two more heavy model tests (`test_comfy_graph_depth[da3]`, `test_puppet_segment` SAM); not re-run after the
smoke film because they load ComfyUI models. None touch the director.

**Not done / open:** director files are not behind `ProjectStore` and there is no event-log document (D-084 wanted one);
`--dry-run` stubs work on old folders only; a shot renders twice (`render_shot` for the model's check, then `render_act`);
`retry` resets a stage, not one act. **Next:** make the shot conversation less brittle (do not stop on a repeated
`check_frame`; let the code accept the plan's face when the vision advice repeats), then a full 2-act film through the review
skill. **Question for the owner:** should the director keep stopping at every act in non-auto runs (story, cast, first shot, each
act, final is six stops for two acts), or should `first_shot` be dropped when acts exist?

---

## 2026-10-30 (night): Mia round 2, review findings fixed (D-096)

**Done and verified:** the independent review's findings: the double-exposure dissolve is gone (one real camera push-in, rule
`transition_for`: cut when both scenes hold the character at scales more than 1.25x apart), the neck is a tapered torso part under
a collar band with a chin shade, the hair is one smooth unioned shape (no flat top, notch or slab), legs are 27.7% of the height
(11% before) with boots at 9% (14%), hands overlap the cuffs (the hand image was clipped), new `walk_step` motion (higher eased
lift, knee bend, bob, sway), pupils converge. 11 new tests (`tests/test_flat_round2.py`); `clip_v2.mp4`, `sheet_v2.png` and my
own `review_v2/review.md` are in `~/ai-studio/scratch/rigged-character-test/`; `motion.csv` has 0 spikes above 5x median.
**Not done / honest:** my own review (sheet once, two zooms) found no major but five minors (a small brown square under the hem,
collar reads as a bowl, hard step between hair tones, front-view shuffle walk, plate tree highlight); the review was by the author,
so an independent re-review is due; audio and lip-sync not re-checked; defect counter not rerun on the new art.

---

## 2026-10-30 (late): rig-first Mia, parametric face, smooth motion (D-095)

**Done and verified:** a one-session spike (`docs/spikes/rigged-character-test.md`). Old Mia's face measured: eyes 78% of the
skin width apart, mouth 49 px off centre. New `face_layout.py` computes the face from the head box with hard limits (13 tests,
incl. a 243-style x 7-yaw x 3-size sweep); `puppet/flat.py` draws Mia as complete parts in a flat palette; `motions/smooth.py` +
`Clip.max_speed_dps` smooth pops and blend blinks, mouth shapes and expressions (jerk 5.0 to 0.9, jumps 71 to 20; 11 tests); keyed
camera and transparent render added to the bake and Blender harness. 6 s 1080p clip with a 2.5D parallax plate, a matching cut with
an 8-frame cross-fade and mixed dialogue: `~/ai-studio/scratch/rigged-character-test/clip.mp4`, `sheet.png`. Defect frames on the
bake-off close-up 44 to 3 of 72 (a shot that bends little; the counter does not see looks). I looked at one contact sheet only.
FLUX.2 klein A-pose edits tried and rejected for limbs. The brief's "D-093" was taken, so this is D-095.
**Not done / honest:** Mia is not production ready: front view only (the walk is a sideways shuffle), simple art, big hair, no
side or three-quarter set; the clip was not reviewed frame by frame or the audio by ear; no other character or background
converted; no new models downloaded. **Open for the owner:** is the flat vector look the film's look? If yes, next: side and
three-quarter part sets, flat backgrounds, then a second character from a spec.

---

## 2026-10-30 (night): single skinned mesh spike, dropped (D-093)

**Done and verified:** built one skinned mesh per character in Blender (`engines/blender/skin.py`, spike branch in
`build_render.py`, `scripts/spikes/skinned_measure.py`) and measured it on the same shots as the cut. Defect frames: Kit
48 to 15 of 120, Mia 42 to 32 of 72; 0.023 s per frame (same as the cut). I looked at one sheet per character (plus three
extra Kit sheets while tuning): wave, jump and gesture frames show smeared, folded texture that the hole/seam counter cannot
see, so the lower numbers overstate it. Recommendation in `docs/spikes/skinned-mesh.md`: drop; test separate part meshes with
a fill of hidden areas, and a draw-order switch for crossing legs. **Not done:** a calibrated stretch measure (mine ranks the
worst frame low), the pose sweep over all motions, any production adapter. **Open for the owner:** the contact sheets are in
the side-session notes folder (`skinned-kit-sheet.png`, `skinned-mia-sheet.png`); say if you read them differently.

## 2026-10-30 (evening): servers use projects, acts export (D-091); joint overlap plateaus (D-092)

- **5B.2 servers adopt projects (`ecc8096`..`68d1a46`):** all five MCP servers take a project id; `Workspace.open_film(film, project)` is the
  one door (no project = the old `films/<slug>` folder); a project film is a derived working folder under `~/ai-studio/work/`
  rebuilt from the store. edit_mcp gained acts: `list_acts` (with `stale`), `add_act`, `edit_act`, `reorder_acts`, `remove_act`,
  `reorder_shots`, `remove_shot`, `render_act`, `export_movie`, `clear_renders`. Verified with the real Synfig engine
  (`tests/test_acts.py`): 3 acts, different places, 3 camera angles each, a recorded line; editing one shot re-renders only its
  act; export gives one movie passing size/streams/length/loudness checks; after deleting every render the re-export has
  identical frames. Full offline suite 995 passed (`-m "not models"`). Stale detection, stitch order and scoping mutation-checked.
  Not done: sound effects not in the audio snapshot; render is per act not per shot; old act videos are not cleaned up;
  `render_shot` on a project film records nothing; the director still builds flat film folders.
- **6.4 joint overlap (`5dc7d2b`, opt-in `build_puppet(overlap=True)`, session stopped at its usage limit):** growing a part under its
  front neighbour near joints cut Kit's full-sweep defects 124 to 78 and Kit's Blender shot 48 to 29 of 120 in a first version, but
  Mia got worse (68 to 74) and the safer final code gave only 44. Target (under 10 of 120) **not met**. Finding: most remaining
  defects are not hidden-pixel gaps (legs crossing in the jump, a hand beside a thigh, loose torso strips, tail over a leg), so
  more overlap will not reach the target. Left off by default. Not done: spike note, contact sheet, full suite run, decisions.
  Handover with numbers is in the shared notes folder (`joint-overlap-handover.md`).
- **Environment note:** `test_compose_within_the_memory_budget` fails whenever ComfyUI is running (seen again today); it should be
  marked `models` or skipped when ComfyUI is up.
- **Owner usage:** the owner hit their usage limit after three sessions ran in parallel. Run fewer sessions at once.

## 2026-10-30 (later): bake-off results, project data layer, director taste (D-088 to D-091)

- **Engine bake-off (6.3, `b6b7e5c`..`0499baf`, report `docs/spikes/engine-bakeoff.md`):** Blender 5.2.3 and OpenToonz both clear
  Gate 1 (code builds the scene from our data, applies the clips, renders headless on the Mac, same frames on re-run) with no
  plugins and no source changes (level 1). Blender: native arm64, every render engine works headless, Workbench 0.03 s/frame
  (EEVEE 0.14, Cycles CPU 0.23), about 360 lines of glue. OpenToonz: Intel build under Rosetta, single thread only, rigid 0.16
  s/frame, Plastic bends 0.5 to 0.8 s/frame, about 400 lines. Synfig reference: 0.15 s/frame. **Defects on Kit's 120-frame
  shot are about the same everywhere** (Synfig rigid 56, bendable 50; Blender rigid 53, bend 48; OpenToonz rigid 63, Plastic
  43), so the engine alone does not remove the holes and seams: they come from the cut (parts do not overlap at joints).
  Recommendation (session): Blender for puppets; OpenToonz later for hand-drawn hero shots (needs a frame-by-frame test and
  an arm64 build or the Windows node). **Not decided:** the owner picks by eye from `~/ai-studio/scratch/engine-bakeoff/compare.mp4`
  and `bend_sheet.png` (no look advantage was shown by numbers). Replacement of Synfig is only recorded after that.
- **Project data layer (5B.1, `1c8c46c`, `5bfc394`, `9fee84a`):** `ProjectStore` (filesystem and memory), nine new schemas,
  `Project` API (versioned cast and places by reference, acts, act staleness), migration into `projects/test-cast/` (6
  characters, 3 backgrounds, 4 films, about 17 MB for 130 MB of sources). 59 contract tests plus project and migration
  tests; 14 guards mutation-checked; full offline suite 929 passed, ruff clean. Not done: servers and director do not
  use it yet (task list in `docs/steps/STEP-5B-projects.md`); audio cues are not in shot documents yet; 6 smoke films
  without `film.json` skipped.
- **Director taste (6.2, `3fd74d0`, `1ef0a2f`):** 16 taste rules, required `emotion`, `framing`, `line.to`, `target` fields, one
  feedback round, a few-shot example, `emotions.json` as data. On 5 fixed stories with the real qwen3:14b rule violations
  fell from 52 to 8, all plans valid; plan time about doubled (feedback round, busy Mac). Not done: no film rendered, framing
  scales not checked on a frame, 8 violations remain (camera intent, motion mood, addressee, listener motion, expression,
  arc). One suite failure seen once (`test_compose_within_the_memory_budget`, caused by ComfyUI running in another session).
  Ideas: a gaze `look_at` motion, a calm face that does not read as angry, cap story lines to about target seconds / 4.

## 2026-10-30: plan reset, owner sign-off, real motion (D-081 to D-086)

- **Why:** the owner found the first director-made film weak and wants much more lifelike animation. Real mocap
  motion (CMU, retargeted) gave only a modest gain because limbs are rigid two-piece cuts, so the engine is the limit.
- **Owner sign-off (all steps of the plan):** (1) engine bake-off first, with Blender and OpenToonz as the primary
  candidates and Synfig as a reference (installs approved; source changes only as a last resort and recorded);
  (2) projects with their own versioned cast and shared backgrounds, many films per project (Step 5B, D-082);
  (3) films made of acts with several camera angles, editable specs until "export all acts", per-act render with
  staleness (Step 5C, D-083); (4) storage behind a `ProjectStore` so an online database can be added later (D-084,
  Step 14, not now); (5) a desktop app for Apple Silicon Macs with a first-run Setup screen (Step 13, D-081, D-085);
  (6) the five test characters become a "test-cast" project. Not decided: strict 2D vs 2.5D (default strict 2D);
  Tauri needs the Rust toolchain (ask before installing); GUI stack is a proposal.
- **Plan order:** bake-off and the project data layer in parallel; then engine backend and puppet meshes; lifelike
  pass; director v2 on projects and acts (15 s then 60 s); desktop app; later evals, durable pipeline, training.
- **Real motion done (6.1, `0dcf5a0`, `5218159`):** `walk_real`, `run_real`, `wave_real`, `jump_real`, `shrug_real`
  from the CMU mocap database (free for all uses; ~4 MB fetched to `~/ai-studio/mocap/cmu/`), retargeted in code with
  foot-lock, plus an opt-in `params.principles` layer. Verified: 60 new tests, fast suite 803 passed, ruff clean.
  Measured on Kit: foot slide 0.037 vs 0.041 leg lengths, no gain in smoothness numbers; pose sweep defects Kit
  9/34 (26%) old vs 48/108 (44%) new (wave and shrug add none; walk, run, jump add holes and seams from bending
  rigid legs), Bo same rate. Honest result: modest gain, puppets still read as rigid cut-outs. `*_real` stay opt-in.
  Skipped: `sit_real`, `point_real`. Open: offer `walk_real` to the director now or after bendable limbs (held
  until the new engine); add the CMU credit line when film credits exist.
- **Research:** `docs/spikes/engine-options.md` (Blender, OpenToonz, Inochi2D, Godot, AnimeEffects, own renderer,
  AI video; AI video ruled out for the main pipeline).
- **In flight:** 6.2 director taste (uncommitted edits, measurement passes), 6.3 engine bake-off (Blender 5.2.3 and
  OpenToonz installed, spike scripts written, no render results yet), 5B.1 project data layer (just started).

## 2026-10-30: the director works end to end (D-080)

- **Done:** `director/` package and CLI built and pushed (`466f837`). 55 offline tests (fake LLM and fake MCP),
  mutation-checked guards, full suite 760 passed, ruff clean.
- **Verified:** dry run with real qwen3:14b and stubbed slow tools (four stops shown, 15.02 s, 0 refusals). Real
  run with `--auto` from one prompt, using Kit, Bo and the orchard: `films/real-15s/edit/final.mp4`, 15.02 s,
  1080p with audio, 21 model calls, 79 tool calls, 0 refused, about 19 min LLM and 8 min tools (`check_film` 160 s).
- **Found and fixed live:** `check_safety` lone-argument refusal, `compose` blocked by a running ComfyUI, dropped
  optional `line` field, curly apostrophes, scene ids s15/s16.
- **Weak:** planning taste. One character per shot (Kit speaks to an off-screen Bo), poor expression choices (Bo
  grumpy while jumping for joy, Kit sad at the goodbye), no establishing shot, `point` has no target. QA left 2
  advisory issues open.
- **Not done:** the approval stops were not exercised live (only in tests and the dry run); the characters stage and
  the shots fix rounds were never exercised live; Kdenlive untested; 60 s film; Windows node.
- **Open questions for the owner:** (1) improve taste with more craft notes, a better few-shot example, or leave it
  to Step 7 evals; (2) should open QA issues trigger an automatic fix round; (3) story plan takes 85-230 s with
  thinking on: accept, or non-thinking with a retry.

## 2026-10-29: face fix, pale panels and Kit's patch done (D-078); cast bar 4 of 5, sweep 116

Next: the owner chooses the fast path to a first film (Step 5: `edit_mcp`, create-film tool, director), then
returns to refinement (remaining 4B, OpenToonz, evals, training, the generative hidden-area spike, a
sheet-fidelity check for parts that are transparent at rest).

---

## 2026-10-29: owner feedback on Kit's reel: expressions perfect, three-quarter not good

Diagnosis from Kit's contact sheet: the code-drawn face has front-view geometry on a turned head (two equal
round eyes read like spectacles, the far eye is a copy placed from the skeleton, no foreshortening of
brows, nose or mouth); a light green patch on Kit's tail in three-quarter (probably scarf pixels cut into the
tail part); the three-quarter body is a klein redraw (flatter style, shifted proportions); the drawn hands
are not tuned for three-quarter. Queued for when the review reel finishes (so the code under the running
render does not change): (1) a three-quarter face with head-turn foreshortening (far eye and brow narrower,
pupils toward the facing side, nose and mouth toward the snout, turn from the measured turn; the front view
unchanged); (2) the three-quarter cut leftovers, starting with the tail patch; later redraw consistency and
three-quarter hands.

---

## 2026-10-29: cut fixes on by default (D-076); sweep 393 to 116

Round 2's two fixes are the defaults; the cast keeps the pass bar (4 of 5) and the pose sweep finds 116
defects (Kit 44, Mia 27, Bolt 23, Bo 16, Pim 6). Next: the review reel at full size (bending on and off),
the 4B docs, then the owner's call on the generative hidden-area spike and on milestone 2.

---

## 2026-10-28: ear and tail bones and the hand-pose spike done (D-073)

Ears and tails opt-in (Kit gains 5 sweep defects with them on, cause open); hands recommended as
code-drawn vector shapes. Next: hands integration (rig `hands` switch, drawn shapes, motion hooks), the
ear and tail follow-ups (the Kit +5 and test checks), then the review reel and docs.

---

## 2026-10-28: bendable limbs in the cut and more acting done (D-072)

Both pushed, opt-in or additive; 577 tests passed at the time. Next: hands and ear/tail bones (cut and
rig, one session), acting follow-ups (sleepy eyes, laugh mouth, sneak and think pockets), the review
reel with bending on and off at full size, docs. Still the owner's: Kit's parts, the bar's numbers.

---

## 2026-10-28: locator seeds and the Synfig side of bending limbs done (D-071)

Both opt-in, both leave existing builds byte-identical. Next: the cut produces limb images (owns
`puppet/build.py`), and more acting (motions, expressions, talk gestures); then hands, secondary motion,
the review reel.

---

## 2026-10-28: 4B.2 cut defects and 4B.3 locator trial done; two approvals (D-070)

Pim's pose-sweep defects fell 91 to 7, Mia's 43 to 28, Bo's 14 to 11; Kit unchanged. The locator trial
says seeds, not pivots. The owner approved the locator-as-seeds integration and Skeleton Deformation per
limb. Next sessions: locator integration (owns `puppet/build.py`) and the Synfig side of bending limbs
(rig schema, `rig.py`, `sif/`), in parallel; the cut producing limb images follows.

---

## 2026-10-27: Step 4B kickoff (D-069)

The owner approved the 4B brief. Parallel sessions: pose-sweep (done), placement-walk (done), bend-spike
(done), locator-trial (running), cut-defects (started after the sweep).

**Done:** 4B.1 pose sweep (394 defects across the five), 4B.6 placement track and walk, 4B.4 spike
(recommends Skeleton Deformation per limb). **Open questions for the owner:** approve Kit's parts changing
to fix seams; decide the bending approach before hands (4B.5) and the integration start.

---

## 2026-10-27: Step 4 closed (D-068); Step 4B opened

The owner closed Step 4 and sent the carry-overs to Step 4B. `docs/steps/STEP-4B-animation-quality.md`
is a draft for the owner's review (pose sweep first, then the cut defects, a locator for
non-organic characters, bending limbs, hands, secondary motion and walking, a review reel).

**Open questions for the owner:** approve the 4B brief and the production-grade bar's numbers; read
`docs/steps/STEP-5-director.md` and say whether you write the director loop core.

---

## 2026-10-27: Step 4: the cast pass bar is met, 4 of 5 (D-067); 4.10 and the Step 5 brief done

**Done**
- Mia over the bar: a stronger turn prompt, a turn measure that ignores hair, three cut fixes (coat
  strip at the wrist, hair below the neck, a shin beside its bone). Sessions: turn-measure,
  coat-arm-cut.
- Task 4.10: learning notes (depth and layering, consistency without training), a Step 4 section in
  benchmarks.md, the Step 4 brief status (session docs-4-10).
- Step 5 brief drafted for the owner's review: `docs/steps/STEP-5-director.md` (session step5-brief).

**Pass bar (rebuilt, SAM on):** Kit, Bo, Pim, Mia pass; Bolt misses. 4 of 5.

**Verified:** the sessions report 478 tests passing and ruff clean; Kit's parts unchanged. I did
not run the full suite again after the last merge, and nobody viewed Mia's final pose images.

**Open questions for the owner**
1. Close Step 4 now (the bar is met, Bolt goes to Step 4B), or fix Bolt first?
2. Read and approve `docs/steps/STEP-5-director.md`; you decide if you write the director loop core.
3. The production-grade bar's numbers (ROADMAP) still await your confirmation.

---

## 2026-10-27: Step 4: the varied cast measured, 3 of 5 (D-066)

**Done**
- Mia (child) and Bolt (robot) designed and built through `scripts/cast_review.py` (about 28 min
  and 25 min with Docker at 8 GB; Docker is now limited to 2 GB and swap dropped from 14.6 GB to
  3.5 GB used).
- Far-shin coverage 0.85 -> 0.8; touching-leg thigh judged by the leg fit; extra redraw seeds when
  the turn is short. Tests for each; the retry tests fail without the code.
- Qdrant restarted after the Docker change (sound index intact, 4,268 sounds).

**Pass bar (rebuilt, SAM on):** Kit, Bo, Pim pass; Mia (turn 0.40, `shin_r`) and Bolt (limbs, eyes,
head 115%) don't. 3 of 5; the bar is 4.

**Verified:** 473 passed (models excluded), ruff clean; Kit's part images unchanged by these
changes (they only affect reports and the seed retry).

**Not done / open:** Mia's turn, Bolt, the head-size check, dark seams between legs, a Pim rebuild
through MCP. Bolt c3's seed-4 redraw crashes the build (head cut too narrow); Bolt is on c2.

**Next:** try a stronger turn instruction in the redraw prompt for Mia (new characters only; Kit
and Bo keep their redraws), then decide with the owner whether Bolt goes to Step 4B.

---

## 2026-10-27: Step 4: the far elbow disc and white leg highlights (D-063)

**Done**
- The brown elbow disc was my D-062 left half-applied (the paint loop ignored the sleeve decision).
  Fixed; Pim's raised far arm now shows the white sleeve.
- The far leg falling apart: not the near leg covering it, but pale highlights left on the torso.
  `join_leg_highlights` gives them to the leg (pale pixels between its own pixels, in its corridor).
- Tests for each, which fail without their code.

**Verified**
- Kit byte-identical (parts and rig, SAM off); Pim and Bo (both films) change as listed in D-063.
- 468 passed, models excluded; ruff clean.

**Not done:** dark seam dashes between legs (Bo, Kit; fixing them changes Kit), the knee wedge of a
rigid bend, `shin_l` coverage 0.81 on Pim, a Pim rebuild with SAM or through MCP. Mia and Bolt are
not designed yet.

**Note:** the full suite took 1 h 21 min wall once today, mostly waiting (the Mac likely slept);
CPU time was about 2.5 min.

---

## 2026-10-26: Step 4: Pim's loose arms: white clothes were cut out of the silhouette (D-062)

**Diagnosed:** not the limb fit. D-057's gap rule left Pim's white shirt and sleeves (13-15 from the
background, `BG_HOLE` was 15) open as "background seen through", so only their outlines were
figure. The arm fit then followed an outline stroke, and the arms stayed in the torso part.

**Done**
- `puppet/checks.py`: `BG_HOLE` 15 -> 10.
- `puppet/build.py` `complete_hidden`: an upper arm half hidden, with a sleeve of its own colour
  (not the forearm's), is cut as drawn instead of becoming a plain sleeve.
- Tests: a white shirt just off the background stays figure; the far sleeve rules (own colour,
  same fur, mostly hidden). Each fails without its fix.

**Verified**
- Kit and both Bo builds: part images and rig byte-identical before and after (scratch harness,
  SAM off). Pim: front `limbs_ok` true; three-quarter arms and legs follow the drawing (checked on
  an overlay), the far arm no longer leaves a ghost arm on the torso.
- 467 passed, models excluded; ruff clean.

**Not done (Pim, three-quarter):** a brown disc at the far elbow when the arm is raised; small
fragments beside the body at rest; the far leg falls apart in the bent-knee pose; `shin_l`
coverage 0.81 (needs 0.85, the drawn sole is short). Pim was not rebuilt with SAM or through MCP.

**Next:** the elbow disc and the bent-knee far leg (they also affect Bo), then Mia and Bolt.

---

## 2026-10-26: Step 4: small view-only paint is a note (D-061)

**Done**
- `puppet/consistency.py`: paint seen in one view only is reported from 3% of a region, but is a
  problem only from 7%; below that it is a note (`report["notes"]`, `"tolerated": true`).
- Test: a small beak only the turned head shows passes with a note, a hat (9.7%) still fails, and
  the beak test fails without the change.

**Verified**
- Real sheets (scratch harness, SAM off): Kit and Bo (both films) have identical consistency
  reports; Pim's now passes with the beak (4.7%) as a note. 463 passed, models excluded; ruff
  clean.
- Pim's current sheets show no head-size or feet problem (head share 0.352 vs 0.369): those
  findings in the bird trial came from the other candidates.

**Not done:** the 7% limit rests on two characters; re-check with Mia and Bolt. Pim's remaining
problems: SAM rejected, far arm and shins in the three-quarter view, and a full end-to-end rebuild
is still to run. Mia and Bolt are not designed yet.

---

## 2026-10-26: Step 4: the no-nose face fix (D-060)

The owner chose to time-box the varied-cast work to a pass bar and start with the eye finder.

**Done**
- Pass bar recorded (D-060): 4 of 5 (Kit, Bo, Pim, Mia, Bolt) build with matching views, limbs on
  their bones and the face found in both views; the rest is tracked and carried into Step 4B.
- `puppet/build.py` `clean_face`: a face with no dark nose is read again with no nose when the
  mark taken for the nose leaves no eye above it (`no_nose`).
- Tests: the bird-like face (was xfail, now a normal test, fails without the fix) and a guard for
  a single brown eye.

**Verified**
- Before/after on the real sheets (scratch harness, SAM off, existing klein redraws): Kit and Bo
  (both films) identical in cleaned pixels, face anchors and notes. Pim: eyes `[]` -> one eye
  found in each view (the other placed from the skeleton), where before the eye was kept as a
  nose.
- `ruff check` clean; 462 passed, models excluded (2 min 7 s).

**Not done**
- Pim was not rebuilt end to end: only the face step was compared. The other Pim failures are
  still open: SAM rejected (IoU ~0.72), consistency flags the beak and feet, head 110% as tall in
  the three-quarter view, far arm and shins loose.
- Mia (child) and Bolt (robot) have no designs yet (`films/step4-cast` has no `child` candidates).

**Next:** the consistency tolerance for small features (beak, feet), then Pim's head size and
loose limbs, then design Mia and Bolt, then task 4.10.

---

## 2026-10-26: Roadmap: production-grade goal and new steps (D-059)

The owner asked for the missing steps to be added and set the goal: the final output must be
production grade.

**Done**
- `docs/ROADMAP.md`: a production-grade bar (picture, animation, lip-sync, sound, story, rights,
  reliability, deliverables, operations), Step 4B (animation quality), and the old Step 7 split
  into Steps 7 (evals), 8 (durable pipeline), 9 (training), 10 (series), 11 (production release)
  and 12 (future tiers). Each new step has a "done when".
- Step numbers 0–6 are unchanged (stable ids); live references to the old Step 7 now point at the
  new steps (ARCHITECTURE, AGENTS, README, the Step 3/4 briefs, a learning note).
- Docs only: no code, tests or schemas changed.

**Open questions for the owner**
1. Confirm or change the bar's targets (they are proposals), at the latest in the Step 4B brief.
2. How to close Step 4: time-box the varied cast against a pass bar, or close it on Kit and Bo
   and carry the rest into Step 4B.

---

## 2026-10-26: The coding agent: Claude Code → DeepSeek Harness (D-058)

The owner moved from Claude Code to a DeepSeek Harness coding agent and asked to confirm the new
agent could run the project before resuming Step 4. This session did both.

**Proved the new agent can drive the whole pipeline (not just read it):**
- `ruff check .` clean; the full suite passes (460 passed, models excluded, 2 min 20 s).
- All three MCP servers start over stdio from `.mcp.json` and answer real calls: `synfig_mcp`
  (16 tools), `audio_mcp` (7), `comfy_mcp` (9).
- Generated real media through the servers: the Step 3 done-when shot (27 tool calls →
  1080p/240-frame video with two voiced, lip-synced lines, music and SFX, −14.6 LUFS) and a
  background draft through `comfy_mcp` (storybook garden, 1536×576, checks passed).

**Scrapped the Claude Code dependency:**
- `CLAUDE.md` → `AGENTS.md` (agent-neutral; every live reference updated, the historical
  PROGRESS log and DECISIONS entries kept as-is).
- `scripts/run_first_shot.py` rewritten as a scripted MCP client (no `claude` CLI). This
  closes Step 2's done-when: verified 10 tool calls → a 1080p, 240-frame shot with a mouth
  cue track, all checks pass. Transcript: `docs/learning/mcp-first-shot.md`.
- README, ARCHITECTURE, ROADMAP, the Step 2/3 briefs and `docs/learning/mcp.md` now say
  "any MCP client / a coding agent" instead of "Claude Code". D-058 records the change.

**Decisions confirmed with the owner (2026-10-26):**
1. Rename `CLAUDE.md` → `AGENTS.md`.
2. Replace `run_first_shot.py` with a scripted client.
3. Resume Step 4 by fixing the puppet cut on varied characters (`cast_review.py`).
4. Prove the agent can generate media (done, above).

**Bird trial (Pim, same day):** built end to end (~46 min, slow: Docker's 8 GB reservation keeps
VRAM at ~3 GB free and the klein redraw swaps). Both passing sheets (c1, c3) built but their views
differ, and round 2's sheets all failed their checks. Failures to fix, in order:
1. **No eyes found** (both views). Diagnosed: the beak is yellow, so the near-black "nose" finder
   takes a dark feature *above* the eyes for the nose; the "eyes above the nose" band then sits
   above the real eyes and loses them. Fix the eye/nose finder for faces with no dark nose.
2. SAM rejected (IoU ~0.72) → colour-key fallback.
3. Consistency flags the beak yellow and feet orange as view drift (small features).
4. Head 110% as tall in the three-quarter view.
5. Far arm and shins loose in the three-quarter view.
Also fixed `cast_review.py` so it stops before a design round past the build limit.

**Next:** fix the eye finder first (a unit test with a bird-like face that fails without the fix),
then consistency/palette tolerance, then Mia (child) and Bolt (robot), then task 4.10.

---

## 2026-10-23: Step 4 task 4.9: the proof runs end to end; the puppet cut needs to generalise

`scripts/run_step4_shot.py` is a scripted MCP client. It starts the three servers from
`.mcp.json`, makes a new character and a new place from words, then builds and renders a shot
with them using only tool calls. Where the owner would choose, it takes the first candidate
whose checks pass, and if the puppet's views don't match it builds from the next passing sheet
(D-057). The transcript is `docs/learning/mcp-step4-shot.md`.

**Run 2 (the recorded one): 39 tool calls in 49 min, 11 of 12 checks passed**
- Bo, "a cheerful little brown bear cub wearing blue dungarees":
  - 3 sheets, all passing their checks
  - c1's build was rejected (head 116% as tall in the three-quarter view); c2 built with
    consistent views
- The orchard: 2 drafts → plate (tiled finish, 341 s) → 4 layers (469 s). The pan showed no
  hole in 50 frames.
- The shot `films/step4-proof/shots/s01_sh01/shot.mp4`: Bo (three-quarter, facing Pip) waves
  and asks, Pip nods and answers, with music, birdsong and a slow pan. 1080p, 192 frames.
- Progress notifications reached the client over stdio on every art call over 30 s.
- The failed check was the loudness: −15.2 LUFS against −14 ± 1. That is the mixer working as
  designed: it trims the whole mix when a true peak still pokes over −1.5 dBTP after its
  limiter. The check now follows that contract (−16 to −13 LUFS, peaks ≤ −1 dBTP). The
  transcript keeps the run's own result.

**Fixed along the way (each verified on the real sheets; Kit's masks and face detection are
pixel-identical before and after; a unit test for each fails without its fix)**
- Run 1 stopped at the plate: an untiled 3 MP VAE decode failed on MPS ("tensor dims larger
  than INT_MAX"). The plate's VAE encode and decode are now tiled.
- The three-quarter redraw gave Bo a scarf: the klein prompt named Kit's scarf. It now carries
  the character's own description.
- Background between touching legs was cut into the leg parts (white strips): enclosed
  background-coloured regions that surround nothing stay open.
- A muzzle below the skeleton's nose line went to the torso: figure between head pixels, along
  rows or columns, joins the head.
- An eye was taken for the nose and stayed painted, because the real nose sat on the outline.
  Thin strokes are now opened away first, and the biggest compact black blob is the nose.
- Progress news now says what is being made ("c1 drawn (1/3): ok; drawing sheet 2 of 3").

**Bo's face (owner review: "the face is deformed").** In run 2's shot Bo had three eyes,
two noses, one brow over both eyes and a seam across the muzzle. All of it came from one wrong
guess: the near eye was taken for the nose, so that eye was kept, and the drawn face was
anchored to it. With the nose fix and three more (D-057: the snout tip joins the head, a
mouth joined to the nose is painted out, the face zone reaches the snout), Bo was rebuilt
(22 s; the three-quarter redraw is reused) and the shot re-rendered. He now has two eyes where
the drawing had them, a brow over each, one nose, and the mouth on the muzzle, with no seam.
A small speck can remain right at the snout's edge. `films/step4-proof/shots/s01_sh01/shot.mp4`
is the re-rendered shot.

**What the shot still shows (open, D-057)**
- outline dashes beside the body, left behind when the arms are hung
- a seam on the waving arm
- in c2's three-quarter cut, the torso also holds part of the far arm and the dungaree cuffs;
  in the bent-knee test pose the far leg falls apart
- with c1, the redraw made the snout near-white with no outline, and it came out
  transparent; no colour key or SAM mask finds it
- "orchard" came out as hills, houses and plain trees (no apples), and the background prompt
  always asks for a lawn floor (task 4.6)

**Verified**
- The full suite: 460 passed, model tests excluded (2 min 4 s). Ruff clean.
- Kit is unchanged by every fix (masks and face notes compared before and after).

**Not done**
- No full run with all the fixes together. Bo was rebuilt and the shot re-rendered with
  studio_core directly, not through a new MCP run. A run 3 takes about 50 min.
- The three-quarter cut problems above. They come from rules tuned on one character.
  Recommended next: build 3 or 4 varied characters (a bear, a child, a bird, a robot, say)
  and make the cut follow drawings that differ from the skeleton, before closing Step 4. Its
  done-when ("a text description becomes a rigged puppet ... with no manual steps") holds for
  Kit today, not yet in general.

**Open questions for the owner**
1. Fix the cut on varied characters before closing Step 4 (recommended), or close Step 4 and
   carry it into the proposed animation-quality step?
2. Bo's voice is a placeholder (`am_puck`, +2.5 semitones) cast by the script.

---

## 2026-10-23: Step 4 task 4.8 done: the `comfy_mcp` server

The owner passed checkpoint 4 (the meadow pan). A subagent moved the two checkpoint previews
into `studio_core`; this session wrote the server, its tests and the Inspector calls (D-056).

**Built**
- `mcp/comfy_mcp` (workspace member `comfy-mcp`, in `.mcp.json`), with nine tools:
  - `describe_art`: style, characters and places, each with its next step
  - `design_character`, `choose_design`, `build_puppet`, `preview_puppet`
  - `generate_background`, `choose_background`, `split_depth_layers`, `preview_background`
- Long jobs run in a worker thread behind one art lock, with MCP progress notifications
  (elapsed seconds plus the latest news, a heartbeat every 15 s). The previews have a lock each.
- `studio_core/preview/` (subagent): `preview_puppet` and `preview_background` as library
  functions returning results and raising `PreviewError`. Every refusal comes before anything
  is written. The scripts are thin command lines with unchanged outputs.
- `preview_puppet` through MCP refuses a character with no voice (casting belongs to the
  sound server); the script still casts the placeholder.
- New learning section: "Tools that take minutes" in `docs/learning/mcp.md`.

**Verified**
- `tests/test_comfy_mcp.py`, 10 tests through a real MCP client:
  - the tool list, with no engine or model names in what the model sees
  - describe_art's next steps, from a fresh film to a built puppet
  - design and background rounds through the real round code, with ComfyUI faked at
    `run_graph`
  - build, layers and previews mapped to results
  - twelve refusals, none of which reach the GPU
  - two art jobs run one after the other, with increasing heartbeats and a "waiting" message
  - the stdio transport
- The preview refactor: 38 preview tests pass, and both scripts render with exit 0. Kit's
  preview took 15 s at 640x360; the meadow pan found no hole in 21 frames.
- The full suite: 456 passed, model tests excluded (1 min 53 s).
- The Inspector check over all three servers: 45/45 calls as expected, exit 0.
  - comfy_mcp: `describe_art`, `choose_design`, `preview_puppet` (Kit) and
    `preview_background` (no holes) ran for real.
  - Eight requests that must be refused were refused, with messages that name the fix.
  - The first run caught one regression in the check itself: copying Kit into the scratch
    film turned an old "unknown character" refusal into a success. That call now uses an id
    that doesn't exist.

**Not covered yet**
- The GPU tools (design, build, generate, choose_background, split) have only run through MCP
  with fakes or as refusals. Task 4.9 runs them end to end through a scripted client.
- Progress notifications were tested in-process. Whether Claude Code shows them is left for
  4.9.
- The background prompt always asks for a lawn of short grass along the bottom (task 4.6),
  so a beach or a kitchen would get grass. It is worth a look before 4.9 picks a new place.

---

## 2026-10-22/23: Step 4 task 4.7 done: the meadow in layers, panning with no holes

The owner chose meadow c4. Built with three subagents in parallel, plus this session:
- the depth graph and the one-time model comparison
- the ProMax repaint fill graph
- the pan test render with its hole check
- this session: bands, parallax, layers and the orchestrator

**Built**
- `comfy_graphs.depth_map` (subagent): DA3 MONO-LARGE at 1512, chosen over DAv2-Small and
  other resolutions (D-055).
- `comfy_graphs.repaint_fill` (subagent): SDXL plus ProMax "repaint", with the masked pixels
  black in the control image and grey in the latent, and a feathered composite.
- `studio_core/place/layers.py`, `split_depth_layers`:
  - sky, then far / middle / ground cut at histogram valleys, plus an optional foreground
  - islands joined; ground kept connected to the bottom (no torn trees)
  - parallax relative to the ground at the characters' feet, capped so no layer edge
    enters the frame
  - fills within pan reach (SDXL); the sky elsewhere a flat colour
  - feathered compositing; `layers.json` validated; a flat (failed) depth map refused
- `scripts/preview_background.py` (subagent): a pan with an optional character, rendered
  over a magenta probe backdrop, with a hole count and a layer-edge check.

**Verified**
- Meadow split: sky 26%, far 27%, middle 18%, ground 30%; parallax 0.05 / 0.52 / 0.86 / 1.0.
- Pan with Kit (`slow_pan_right`, 6 s, 1080p): no hole in 38 sampled frames, and no layer
  edge entered the frame. Rendered in 77 s.
- The pan reads as depth: the hills and tree line drift slower than the lawn, and the big
  tree slides in whole.
- 440 tests pass, model tests excluded (2 min 50 s). New tests: layers 7, depth 16 (plus 2
  live), fill tests, preview 21.
- Problems found in review and fixed:
  - fill seams (now feathered)
  - fill prompts redrawing near things (now per-layer prompts)
  - SDXL inventing odd shapes in a full-frame sky fill (now limited to pan reach)
  - a near tree's canopy in the ground layer (ground must reach the bottom)
  - a foreground parallax that would show its edge (now capped)

**Costs**
- A split takes about 8–14 min, mostly three fills at about 2.7 min each plus memory
  pressure. Depth takes 5 s.
- A full-size fill isn't feasible on this Mac: over 30 min with swap full.

**Open questions for the owner**
1. Checkpoint 4: does the meadow feel deep enough during the pan? The parallax factors are
   perceptual, and can be tuned.

---

## 2026-10-22: Step 4 task 4.6 done: backgrounds from text

The owner approved Kit's three-quarter view. Built with one subagent in parallel
(`comfy_graphs.finish_plate`: Real-ESRGAN upscale plus a low-denoise SDXL refine), plus this
session.

**Built**
- `studio_core/place/design.py`:
  - `generate_background`: drafts at 1536×576 in the film's style, from a code prompt
    template that keeps the front an open lawn
  - `choose_background`: records the pick, finishes it into `backgrounds/<id>/plate.png`
    (2880×1080), and records everything in `plates.json` (new schema)
- `place/checks.py`: ground-band checks (edges, odd colours, depth), calibrated on real
  drafts.
- `finish_plate` (subagent): `txt2img` now shares its style setup, and its golden JSON is
  byte-identical. The refine takes 10 steps.
- `scripts/background_review.py`: drafts (safe to re-run), a self-contained review page, and
  `--choose`.
- Learning note: `docs/learning/upscale-and-refine.md`.

**Verified**
- First template: big foreground flowers and the stream along the bottom, which the checks
  caught (14% edges, 48% covered).
- With the stronger template, all 4 demo drafts ("a sunny meadow at the edge of a forest with
  a small stream", seeds 11–14) pass, at 120–140 s each.
- c4 finished into the plate in 327 s. The composition matches the draft, the detail is crisp,
  and there are no seams.
- 369 tests pass, model tests excluded, plus the live draft test. ComfyUI kept no copies.

**Open questions for the owner**
1. Which draft for the meadow? I finished c4 (an open lawn across the front).

---

## 2026-10-22: FLUX.2 klein wired into build_puppet (D-053)

The owner approved wiring klein in as proposed in D-052. Built with one subagent in parallel
(`puppet/fit.py`: limbs fitted to the drawing), plus this session.

**Built**
- `puppet/turn.py`:
  - klein redraws the front figure turned, for seeds 1–3
  - ground shadows are dropped
  - each figure is placed where the three-quarter view goes, edges unmixed
  - each sheet is scored with the cut's checks; the best is kept and reused
    (`regenerate_turn`, or `replace=True` to re-place existing edits)
- `build_puppet(three_quarter="klein")` is now the default.
- `puppet/fit.py` (subagent), applied to every view before the cut:
  - arm angles, forearm lengths to the drawn paw, shoulders slid onto the drawn arm
  - legs fitted as bars under the torso
  - drawings that follow the skeleton are left exactly as they were
- `build.py`:
  - arms drawn behind the torso are cut where they emerge, with the hidden stretch painted
    (a mostly hidden upper arm becomes a plain sleeve)
  - a nose finder that works on turned heads (lowest compact black blob)
  - eyes: dots or arcs near the nose, never ear shading
  - the three-quarter face takes the front's eye, brow and mouth sizes
  - wider paws past the wrist

**Bugs found by looking at renders, and fixed**
- a paw floating beside the body (the forearm was too short for the drawn arm)
- leg corridors cutting the tail
- an eye drawn by the ear
- the face lost inside klein's pale face (eyes dropped as islands)
- a scarf chunk riding on the far arm
- a hole in the torso where the far arm had been

**Verified**
- Kit: seed 3 of 3 chosen (turn 108% of asked, consistency clean).
  - Every three-quarter limb passes except one shin (coverage 0.81).
  - Near upper arm on its drawn arm: 24% → 100%.
- Renders of both views (7 s, 1080p, about 35 s each). In the three-quarter view Kit faces
  Pip, waves with the far arm, blinks and talks. The front view is unchanged.
- 322 tests pass, model tests excluded. New tests:
  - limb fitting: 24 (subagent)
  - turn: 6 (shadows, placement, a pale face, best-seed choice, reuse, replace)
- Klein build: about 7.5 min the first time (three edits), then 27 s.

**Known limits**
- A small hard edge at the chin when the head turns.
- Legs fitted as straight bars (bent knees aren't followed).
- Hidden upper arms are plain sleeves.
- The three-quarter style is a little flatter than the SDXL front.

**Open questions for the owner**
1. Does Kit's three-quarter view pass now?

---

## 2026-10-22: FLUX.2 klein 4B installed and trialled for the three-quarter view

The owner approved the install and a trial, with the results to be shown before any wiring.

**Done**
- Downloaded the three files (16.13 GB, Apache-2.0, sha256-verified) in about three minutes,
  and recorded them in `config/models.toml` and MODELS.md.
- `comfy_graphs.flux2_edit` (written by a subagent, in parallel with the download), from
  Comfy-Org's template. Every node checked against our ComfyUI v0.42.1; 10 unit tests.
- `scripts/spikes/flux2_three_quarter.py` runs two rounds of four edits, then places,
  measures and writes `renders/spikes/flux2-three-quarter/step4-demo-kit/review.html`.
- Fixed the turn measure (now the centroid of the face's marks) and the eye-pair choice.
  Rebuilt Kit; nothing changed in its rig.

**Results** (D-052)
- Turn: 56–102% of what was asked, against SDXL's 6%. The same fox in all eight edits, with
  no hat.
- Arms: against the body in round 1, nearly horizontal when asked for 25° in round 2. Ground
  shadows in half of them.
- Time: about 2.5 min per edit, or 4+ min with a pose reference (which didn't help).

**Verified**
- 292 tests pass, model tests excluded.
- The ComfyUI folders kept no copies, and its memory was freed afterwards.

**Open questions for the owner**
1. Wire klein into `build_puppet` as proposed in D-052 (edit the front into the
   three-quarter view, pick by the checks, fit the arms before cutting)?

---

## 2026-10-22: Step 4 task 4.5 done: the three-quarter view, and a consistency check

The owner approved checkpoint 3, including the change to Pip's high-energy wave. They also
asked whether the wave's rigid "rectangle" look and the overall quality will be handled.
- Answer: mesh bending is planned for Step 6 (OpenToonz Plastic). Wrist and hand swaps,
  motion principles, secondary motion, cut-edge outlines and a motion-quality eval are not on
  the roadmap yet.
- Proposed (owner's call): an "animation quality" step between Steps 4 and 5.

Built in parallel:
- a subagent: research on the front → three-quarter edit model
- a subagent: the three-quarter test render
- this session: the two-view cutter and the consistency check

**Built**
- `build_puppet` cuts both figures into one rig (`views.front`, `views.three_quarter`; parts
  in `parts/<view>/`):
  - a three-quarter draw order
  - a face finder that doesn't assume symmetry (nose by solidity, eyes as the two best marks
    above it, pupils filled)
  - the colour rule on every limb
  - far-side three-quarter limbs judged on coverage only
- `puppet/consistency.py`, per region:
  - paint only one view has, from colour histograms
  - head size
  - turn, measured against what the skeleton asked for
- `scripts/preview_puppet.py --view three_quarter` places the character in that view, facing
  Pip.
- Bugs fixed along the way:
  - wrist outlines left on the torso (dark "sticks" at the hips after the arms hang)
  - a pupil left inside an eye's ring
  - a palette comparison that flagged the scarf and missed the hat

**Verified**
- Kit rebuilt in about 14 s with SAM (IoU 0.954 front, 0.951 three-quarter).
  - Front: all limbs pass.
  - Three-quarter: the near thigh carries a piece of tail (drift 0.64, flagged).
- Consistency on Kit: a hat (#afca70) covers 10% of the three-quarter head only, and the turn
  is 5% of what was asked. Head share matches (0.331 vs 0.342).
- Both test renders: 7 s at 1080p in about 35 s each. Kit waves, blinks and talks in both
  views, and I checked the contact sheets.
- 282 tests pass, model tests excluded. New tests:
  - two-view builds: valid rig, the far arm behind, turning the arms back reproduces each
    figure
  - SAM accepted or rejected per view
  - consistency: matching views, a hat in one view, an unturned three-quarter view
  - the preview script, 6 new tests (from the subagent)

**Front → three-quarter fallback, research only (D-051, sources in the subagent's report)**
- FLUX.2 [klein] 4B: Apache-2.0 for everything it needs, about 16.1 GB in bf16 (fp8 doesn't
  run on MPS), native ComfyUI nodes. There is no published evidence that it turns cartoon
  characters cleanly, and its speed on an M4 is unmeasured.
- Alternative: Qwen-Image-Edit-2511 Q4 GGUF with a multiple-angles LoRA (tight on memory).

**Open questions for the owner**
1. Install FLUX.2 klein 4B (about 16 GB) and trial a front → three-quarter edit of Kit, or
   keep front-only puppets for now?
2. Add the proposed animation-quality step between Steps 4 and 5?

**Cleaned up:** scratch debug images. The subagents removed their scratch films and
renders. The dev contact sheet from the three-quarter stand-in was deleted.

---

## 2026-10-22: Step 4 task 4.4 done: Kit is a rigged puppet

The owner chose candidate c3. Built in parallel:
- a subagent: the SAM 2.1 segmentation
- a subagent: the test-render script
- this session: the cutter

**Built**
- `puppet/design.py`: `choose_design` records the chosen candidate.
- `puppet/segment.py` (SAM 2.1 base+ through ComfyUI):
  - Prompts come from the skeleton: tight boxes sized by the colour key, plus points on
    the centre line.
  - fp32 only.
  - Learning note: `docs/learning/segmentation-sam2.md`.
- `puppet/build.py`: `build_puppet` cuts the chosen sheet into Pip-compatible parts:
  - silhouette: colour key ∪ SAM
  - head split by colour
  - limb corridors with a colour rule
  - face painted out, face block from the drawn marks
  - caps on the back part
  - arms turned to hang at rest
  - unmixed edges
  - writes `rig.json` (registered via `register_rig`), `palette.json`, a build report,
    debug images, and `compose()` (a PIL forward-kinematics preview)
  - learning note: `docs/learning/cutting-puppets.md`
- `scripts/preview_puppet.py` (checkpoint 3): Kit and Pip in shot `s00_sh01`. Kit rests,
  waves, blinks and speaks a Kokoro line with Rhubarb lip-sync. The script renders through
  the Synfig backend and writes a contact sheet of key frames found from the tracks.
- `motions/library.py`: the wave keeps the hand clear of the head (Kit's ears hid it). Pip is
  unchanged up to energy 0.75, and stops at 150° instead of 160° above that.
- `comfy_runs.run_graph`: a fresh save-prefix token per run. ComfyUI's cache otherwise
  answered repeated graphs with files already deleted.
- Small changes: `comfy_graphs.Graph` is public, `checks.skeleton_box` is public, and
  `required_files` lists SAM base+.

**Verified**
- Kit's build: 8 s including SAM (IoU 0.946 with the colour key).
  - All 8 limbs on their bones (worst drift 0.33 radius).
  - Face: nose kept, both eyes and the mouth found, 5 marks painted out.
  - The rig validates.
- Test render: 35–46 s for 7 s at 1080p, with audio. I checked the contact sheet frame by
  frame:
  - rest
  - a wave clear of the head
  - eyes closed on the blink
  - the mouth shapes during the line
  - Pip standing alongside
- 274 tests pass, model tests excluded, plus the live model tests (SAM, ComfyUI). New tests:
  - `test_puppet_build.py`, 7 tests on a synthetic fox: the scarf stays on the torso, the
    tail doesn't follow the leg, every pixel belongs to exactly one part, the face is
    painted out with the nose kept, the arms hang, turning the arms back reproduces the
    sheet (IoU > 0.95), and SAM is joined or rejected
  - segmentation, 5 tests
  - the preview timeline, 6 tests
  - the wave's head clearance, 1 test
- First-pass bugs found by looking at renders and fixed:
  - the arm corridors took scarf and tail
  - the paws dropped off
  - a chin cap showed on the scarf
  - fur wisps were left at the shoulders
  - a white fringe on the outline
  - the hidden wave
  - one limb's hole filling took another limb's pixels

**Open questions for the owner**
1. Checkpoint 3: does Kit look right waving, blinking and talking next to Pip? The face is
   Pip's vector face style placed on Kit's drawn features.
2. Kit's voice is a placeholder (c13, af_bella +1.5 semitones). Should we cast Kit properly?
3. The small change to Pip's high-energy wave (150° instead of 160° above energy 0.75):
   is that OK?

**Cleaned up:** scratch debug images. The two subagents removed their scratch films and files.
No ComfyUI copies were left.

---

## 2026-10-22: Step 4 task 4.3 done: `design_character` and the first candidates

**Built**
- `studio_core/puppet/design.py`: `design_character(film_root, id, description, n, seed, fast)`.
  - Each candidate is a turnaround sheet in the film's style, with a recorded seed.
  - Rounds add candidates; `candidates.json` is validated against the new `design` schema.
  - The description passes the shared word check (`studio_core/safety.py`, which `speak`
    now uses too).
- Conditioning: the OpenPose skeleton at 1.0 plus a code-drawn mannequin (`mannequin_image`
  in `skeleton.py`) as weak depth (0.4, first half of the steps). Both share one ControlNet
  loader (`comfy_graphs.txt2img`).
- `studio_core/puppet/checks.py` checks each sheet:
  - a plain background
  - figures grouped by skeleton, with holes filled
  - height and joints on the figure, listing the joints that miss
  - front arms clear of the body
  - extra shapes (props, text, shadows, clutter)
- `comfy_runs.run_graph` now deletes ComfyUI's own copies of outputs and the uploaded
  conditioning images after each run, so the film folder holds the only copy.
- `scripts/design_review.py`: generates the missing candidates (safe to re-run), frees
  ComfyUI, and writes the review page with a skeleton overlay toggle.
- Learning note: `docs/learning/controlnet-conditioning.md`.

**What the experiments showed** (scratch runs, deleted afterwards; details in D-049)
- OpenPose alone: arms rested against the body in 3 of 4 early sheets.
- Weighted face negatives (`(eyes:1.5)`): faces stayed and the arms vanished.
- Fast mode (Lightning, CFG 1): about 1–2 min instead of 4–8, but the negative prompt is
  ignored, so the sheets came back with paper texture, leaves, a signature and extra tails.
- Mannequin depth at 0.6: limbs always clear, but a wooden-doll look. 0.4 for half the steps
  keeps the style.
- The first version of the checks gave false alarms: light clothes split the silhouette.
  Grouping the pieces by skeleton and filling holes fixed it, and a sheet then fails only when
  a look at it agrees.

**Demo: Kit, "a cheerful young fox with a green scarf"** (storybook, normal mode, seeds 101–104)

| Candidate | Time | Checks | By eye |
|---|---|---|---|
| c1 (seed 101) | 267 s | pass | Arms well clear, plain background, no shadow, a closed-eye smile. The 3/4 view is barely turned. |
| c2 (seed 102) | 239 s | fail: 12 extra shapes, 75% of joints | A cluttered sheet (mini foxes, leaves) with a white body suit. Rightly rejected. |
| c3 (seed 103) | 270 s | pass | A fox in a coat, with a tail. The 3/4 view adds a small hat the front lacks. |
| c4 (seed 104) | 328 s | fail: a hand touches the tail | Arms clear otherwise. Shorts in the front view, none in the 3/4. |

- **Faces:** all four have faces (two with closed-eye smiles), so 4.4's face fill is needed.
- **Three-quarter views:** mostly a front view with a slight turn. That is task 4.5's
  problem.
- **Speed:** 10–14 s per step, with swap nearly full during the runs.

**Verified**
- 254 tests pass, model tests excluded. New tests:
  - checks on synthetic sheets drawn from the skeleton: clean, busy background, arm on hip,
    missing view, figure off the pose, light shirt, extra shape, clutter
  - the mannequin itself passes the checks
  - design rounds with a fake ComfyUI: numbering, seeds, validation, refusals, style change
  - ComfyUI copies deleted, and only this run's
  - the design schema with 4 mutation cases
- Live model test `test_one_real_candidate` (fast mode): passes, run together with `test_real_run` (123 s). ComfyUI kept no output copies, and the images uploaded for the run were deleted.

**Open questions for the owner**
1. Checkpoint 2: is the look right, which candidate (if any) should become Kit's puppet,
   and are the faces acceptable given that the build step paints them over?
2. Speed: each normal-mode sheet takes 4–8 min, partly because memory is under pressure
   (swap nearly full). Docker's VM reserves about 8 GB; lowering it is your call. There is
   also a second ComfyUI (port 8189, started by another app, "Montage") running from our
   ComfyUI install.
3. Cleanup: `~/ai-studio/scratch/` (about 510 MB from Steps 0–2, Oct 19–21) and the
   Oct 19–20 images in ComfyUI's output folder predate this task. Delete them?

**Cleaned up:** the experiments' scratch files (96 MB) and 15 images from today's runs in ComfyUI's output and input folders (4.1 smoke, 4.3 experiments, and the demo's copies from before the automatic cleanup).

---

## 2026-10-22: Step 4 started: task 4.1 (ComfyUI plumbing) done

The owner approved the Step 4 brief as written (D-047).

**Step 4 task list**

| Task | Status |
|---|---|
| 4.1 ComfyUI plumbing | **Done**: `studio_core/comfy_runs.py` (`film_style`, `make_room_for_images` with a music guard, `ensure_comfy` starts ComfyUI on demand, `run_graph` uploads, collects, renames and writes `run.json`, `free_comfy`); 5 approved models installed via the manifest. |
| 4.2 Skeleton templates | **Done**: `studio_core/puppet/skeleton.py` (Pip proportions, A-pose, front + three-quarter turnaround on 1344×768, OpenPose image and rig bones from the same joints); 7 tests: keypoints found in the image within 1.5 px, bone directions within 1°, names, roles, parents, limits and draw order identical to Pip (D-048). |
| 4.3 `design_character` (owner checkpoint 2) | **Done; owner chose c3**: `studio_core/puppet/design.py` + `puppet/checks.py`, `schemas/design.schema.json`, `scripts/design_review.py`; 4 candidates for Kit the fox (D-049). |
| 4.4 `build_puppet` (owner checkpoint 3) | **Done; approved by the owner**: `puppet/build.py` (cut, face, caps, hanging arms, rig) + `puppet/segment.py` (SAM 2.1) + `scripts/preview_puppet.py` (test render next to Pip) (D-050). |
| 4.5 Three-quarter view | **Done; FLUX.2 klein wired in (D-052, D-053)**: both views cut into one rig, `puppet/consistency.py` compares them, `preview_puppet.py --view three_quarter`. Kit's 3/4 fails the check (hat, barely turned) (D-051). |
| 4.6 `generate_background` | **Done; owner chose c4**: `place/design.py` (drafts at 1536×576, choose and finish into the 2880×1080 plate), `place/checks.py` (ground band), `comfy_graphs.finish_plate`, `scripts/background_review.py` (D-054). |
| 4.7 `split_depth_layers` (owner checkpoint 4) | **Done; waiting for the owner's review**: `place/layers.py` (DA3 depth, bands, parallax, fills), `comfy_graphs.depth_map` + `repaint_fill`, `scripts/preview_background.py` (pan test with a hole check) (D-055). |
| 4.8 `comfy_mcp` server | To do |
| 4.9 Prove it | To do |
| 4.10 Docs, Step 5 brief | To do |

**Verified**
- Downloads: ProMax ControlNet 2.34 GB, DA3 MONO-LARGE 1.24 GB and SAM 2.1 base+ 0.30 GB from
  Hugging Face, sha256-checked. Real-ESRGAN ×2 from GitHub, with hashes computed once.
- ComfyUI started on demand by `ensure_comfy` in 17 s.
- A smoke graph through `run_graph`: DA3 depth plus a Real-ESRGAN 4× upscale, in 4.5 s. The
  depth map is right even on the flat placeholder meadow: the sky farthest, the path nearest.
- API note: dynamic-combo inputs take dotted keys (`"output": "depth"`,
  `"output.normalization": "min_max"`).
- 5 plumbing tests, including a real SDXL run with its `run.json`. ComfyUI's memory was freed
  afterwards.

## 2026-10-22: Step 3 done; Step 4 brief drafted

**Step 3 in one paragraph:** the director can now make a film's sound through `audio_mcp`.
- **Voices:** characters are cast once (Pip and Bunny by the owner) and speak lines with
  automatic mouth cues. Kokoro is in use, and the Hindi voices work.
- **Music:** composed from a mood at 9.6 GB peak memory (it was 21+ GB).
- **Sound effects:** found by description among 4,268 CC0 sounds, with CLAP in Qdrant and a
  hybrid ranking.
- **The mix:** shots get a full mix (ducked music, −14 LUFS, true-peak safe).
- **The done-when shot** was built only through MCP tool calls and approved by the owner.

**Owner decisions this step:** the brief (D-036), the casting (D-039), the music samples, the
Indian voices (D-042; Parler download deferred), FSD50K's CC0 clips (D-044), the done-when shot
(with the birdsong fix).

**Verified:** see the task table above. The full suite passes (229 tests, ~3 min), with the
`models` tests running Kokoro, Rhubarb, ACE-Step and CLAP. The Inspector check covers both
servers, 32/32.

**Next**
- Owner: review the Step 4 brief (`comfy_mcp`: puppets and backgrounds from text).
- Open: Step 2's Claude Code run (D-035); 3.2b's Parler download when the owner logs in to
  Hugging Face.

## 2026-10-22: Step 3 started: tasks 3.1–3.4 (schemas, voices, lip-sync, music) done

The owner approved the Step 3 brief as written (D-036).

**Step 3 task list**

| Task | Status |
|---|---|
| 3.1 Audio schemas and file layout | **Done**: `schemas/voice`, `line`, `lipsync`, `music`, `sfx_library`; shot schema gains `sfx[].sound` and `music_volume`; semantic checks (cue order and coverage, unique voices, sounds and audio, line/voice consistency); asset checks in `shot_spec` (line metadata, stale mouth cues, chosen sounds in the library, music cues exist); `studio_core/audio/library.py` (manifest loader); files named by id recognized by folder in `validate_file` (D-037). |
| 3.2 Voices: `speak` (owner checkpoint 2: casting) | **Done; cast by the owner** (Pip c12, Bunny c03, D-039): `studio_core/audio/voices.py` (text checks, content-hash cache, one Kokoro batch per call, trim + pitch step + linear-gain loudness, line metadata, stale cues removed), `studio_core/audio/ffmpeg.py`, `scripts/audio/kokoro_batch.py`, 4 casting voices fetched; casting page `scripts/audio/voice_casting.py` (14 candidates × 2 lines) (D-038). Note: `docs/learning/voices-and-loudness.md`. |
| 3.2b Indian voices (Indic Parler-TTS, D-042) | **In progress**: `envs/parler` (pinned; audiotools/protobuf overrides), `scripts/audio/parler_batch.py`, voice.json `engine: parler` + `language` + `speaker`/`pitch`, Parler descriptions written by code, a seed per line, engine dispatch in `speak`, Devanagari text, recognizer by language; Kokoro's 4 Hindi voices work end to end (phonetic cues). **Deferred by the owner (2026-10-22): planned later** together with the Hugging Face login that the gated weights (3.75 GB) need. |
| 3.3 Lip-sync: `lipsync` | **Done**: `studio_core/audio/lipsync.py` (Rhubarb on the final audio with the text, recognizer by language, cache by validity and length, relative `soundFile`, parallel lines); `speak` lip-syncs by default (D-040). Note: `docs/learning/lip-sync.md`. |
| 3.4 Music: `compose` (owner checkpoint 3) | **Done; samples approved by the owner (checkpoint 3, 2026-10-22)**: memory fixed in place (bf16 + PyTorch DiT and VAE only): **21.0 → 9.6 GB** peak for a 10 s cue, no swap, flat to 60 s; `studio_core/audio/music.py` (9 moods, instrument list, caption in code, seeded, cached by hash, Ollama unloaded and ComfyUI refused first, peak footprint measured per cue, trimmed + faded + −20 LUFS); samples page `scripts/audio/music_samples.py` (D-041). |
| 3.5 Sound-effect library and search: `find_sfx` | **Done**: 8 Kenney + 10 OpenGameArt CC0 packs + FSD50K's CC0 eval clips (owner-approved, child-safe filter) → **4,268 sounds, 9.6 h**; BigSoundBank left out per its robots.txt; CLAP in Qdrant with hybrid ranking; spot-check 24/24; remaining gaps: cows, a cartoon boing, a slide whistle (D-043, D-044). Note: `docs/learning/embeddings-and-vector-search.md`. |
| 3.6 The mix | **Done**: `studio_core/audio/mix.py` (dialogue/sfx/music buses, sfx normalization, computed ducking envelope, −14 LUFS gain, 4×-oversampled limiter with a true-peak check), `[mix]` config, `render_shot` writes `mix.wav`; tests measure ducking (−10 dB ± 0.5), sound timing (±10 ms) and loudness (±1 LU, ≤ −1 dBTP) (D-045). |
| 3.7 `audio_mcp` server, and shot tools for sound | **Done**: `mcp/audio_mcp` (7 tools: describe_audio, set_voice, speak, lipsync, compose, find_sfx, preview_mix); `synfig_mcp` gains add_sound_effect, set_music, sound-effect removal, music cues in describe_film; tests through real MCP clients (in-process + stdio, with and without models); Inspector check over both servers 32/32 (D-046). |
| 3.8 Prove it (owner checkpoint 4) | **Done; approved by the owner (checkpoint 4)**: `scripts/run_step3_shot.py` builds the done-when shot with a scripted MCP client over both servers (launched from `.mcp.json`): 27 calls, 109 s. Pip and Bunny speak in their cast voices with mouth cues, plus composed music, birdsong found by description, and a 1080p render. All 6 checks pass (−14.8 LUFS, −1.5 dBTP); transcript `docs/learning/mcp-step3-shot.md`. The owner's note (traffic in the chosen birdsong) was fixed with `find_sfx(avoid=...)` and the shot re-rendered. |
| 3.9 Docs, Step 4 brief | **Done**: Step 3 brief checklist ticked; learning notes (voices and loudness, lip-sync, embeddings and vector search, the memory hunt, MCP with two servers); MODELS (Kokoro voices, CLAP, the sound library); Step 4 brief drafted for review. |

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

**Task 3.2b (part 1) and 3.5 (same day)**
- 3.2b, Indian voices: the Parler engine is built and tested without its weights. Kokoro's 4
  Hindi voices work end to end with phonetic cues. The Parler download waits for the owner's
  Hugging Face command-line login, which the owner chose to do later.
- 3.5, sound-effect library:
  - Sources: Kenney (581 sounds) and OpenGameArt (174), all CC0, with a children's name filter.
  - BigSoundBank is left out: its robots.txt forbids robots on its audio.
  - CLAP in Qdrant with hybrid ranking. The keyword half was needed: pure vectors ranked dice
    above tagged footsteps.
  - The spot-check passes 15/15. **Gap: animal sounds** (and real rain). The approved optional
    fix, FSD50K's CC0 eval clips (6.2 GB), waits for the owner's decision.
- 216 tests pass (~2 min with the `models` tests); ruff is clean.

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
