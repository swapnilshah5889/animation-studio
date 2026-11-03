# Project handoff

**As of:** 2026-11-03 (updated after the open-asset character foundation test)
**Purpose:** concise, agent-neutral continuation brief for any coding agent using this repository. `AGENTS.md`, the
roadmap, decision log, progress log, and current step brief remain authoritative; this file
points to the current state and next gate rather than replacing those sources.

## Current direction

The project is pursuing one owner-reviewed vertical slice before resuming the broader studio roadmap. The end product
should look like drawn 2D/2.5D children's animation. Blender is the active engine; OpenToonz is parked for a later hero
tier and Synfig is legacy. Rain and Snow are technical rig baselines, not approved film characters. See D-101 through
D-106 and the Reset section of `docs/ROADMAP.md`.

## Current stop point

- **Open-asset foundation test (latest, 2026-11-03):** KayKit Adventurers 2.0 Rogue plus KayKit Character
  Animations 1.1 (both CC0 1.0, commercial use and modification allowed, attribution optional; verified on
  https://kaylousberg.itch.io/kaykit-adventurers, https://kaylousberg.itch.io/kaykit-character-animations and the
  bundled `License.txt`). The test is a 5.5 s 1080p24 Blender clip driven only by the asset's NLA actions (walk, idle,
  wave) plus a 4-key head layer: `~/ai-studio/scratch/character-foundation-test/render/foundation_test.mp4`. The
  independent review is **NEEDS WORK** with 3 majors: a feet pop at the walk-to-idle stop (f50-55), a mitten-fist hand
  so the wave reads as fist-shaking, and the result reads as a cel-shaded 3D game asset rather than drawn 2D. The
  head turn, arm attachment and walk contact were judged good. Not approved. Do not iterate, switch assets or adopt it
  without an owner decision; the options are in `docs/PROGRESS.md` (2026-11-03 entry). Asset and render live only in
  scratch; the asset is not yet recorded in `docs/MODELS.md`.
- **Canonical art:** Rowan's single front-view illustration is approved by the owner. The independent reviewer found one
  minor eye-gaze imbalance; the owner accepted it. The image and face crop are outside the repository at
  `~/ai-studio/scratch/character-art-proof/canonical/`.
- **Turnaround:** not approved. The reference-conditioned three-quarter and side views changed the canonical red back
  garment and rounded cap. Bounded corrections did not resolve those details; the final cap edit retained a visor and
  top button and cropped Rowan at the thighs. Independent review returned **NEEDS WORK**.
- **Front-only feasibility rig:** the existing six-second, 1080p24 Blender prototype remains a technical experiment,
  not an approved film. The continuous arm rotation fixed the earlier snap, but the shoulder/sleeve still looked off-model.
  A bounded replacement-arm attempt failed its five-pose review. The depth correction removes a black upper arm, but
  the exposed vest/backpack patch and hand still failed. One owner-approved, scratch-only generated arm-art candidate
  was then independently rejected: its arm reads as an olive garment panel, with no readable hand, and its color is
  off-model. Neither failed candidate is integrated or approved.
- **Production rig/film:** not started. The prototype does not provide a walk, turn, or three-quarter view; do not treat
  its review as approval of the 30-second slice. The arm-art major remains open.
- **Generation:** stopped after the one explicitly approved art candidate. Do not start another seed search, reroll, or
  full clip without a new owner decision. All generation and renders so far are local;
  none is a production asset.
- **Latest pose proof:** five stills (`rest`, `low`, `horizontal`, `raised`, `horizontal_head_tilt`) were built from the
  current uncommitted candidate, then independently reviewed. The black-arm issue was depth ordering, not black pixel
  data. After correcting depth, the independent verdict is **NEEDS WORK**, with two majors: the lime-green exposed patch
  and the thin unreadable hand. Neither is fixed by the depth change. Evidence is under
  `~/ai-studio/scratch/rowan-arm-candidate-v3/render/poses/` and the reviewer report is
  `~/ai-studio/scratch/rowan-arm-candidate-v3/render/review.md`.
- **Latest art-only test:** one approved local generated candidate (seed 9401) was independently rejected; it is not
  integrated. At full-figure scale the arm reads as an olive garment panel with no recognizable hand, its color is
  off-model, and a rust sliver is detached. The reviewer saw two stills only. Candidate and generation provenance are
  under `~/ai-studio/scratch/rowan-arm-art-v1/`.
- **Next:** treat the pose gate as failed. Do not build a clip from this candidate. The next art pass needs to supply a
  convincing on-model arm, readable open hand, and coherent vest/backpack/armhole underlay before the limb is rigged.
  One deterministic depth correction is verified visually; the remaining art failures are not solved by more pivot
  tweaks. The one approved generated-art candidate also failed; select a different art-authoring route before any more
  work.
  `docs/steps/STEP-ROWAN-ARM-REPAIR.md` is the current task brief.
- **Latest verified code fix:** the depth correction is committed as `ef50721`; the subsequent progress clarification is
  `c7459b2`. Art experiments remain scratch-only. The current arm-art blocker is recorded in `docs/PROGRESS.md`,
  `docs/steps/STEP-ROWAN-ARM-REPAIR.md`, and `docs/spikes/rowan-rig-test.md`.

The detailed evidence, model/settings, seeds, reviewer scope, and scratch artifact paths are in
`docs/spikes/character-art-proof.md`. The chronological project record is `docs/PROGRESS.md`; older entries describe
historical work, not necessarily active roadmap direction.

## What exists from earlier project phases

Earlier work built a local MCP-based animation pipeline, a local LLM director, edit and QA tools, a project store, and
editable multi-act film/export support. The older puppet pipeline, Mia/Kenney art, and early film/reel results did not
meet the visual bar. The 2026-10-31 reset deliberately pauses those broader features until the vertical slice passes.
Treat them as existing code/history, not permission to expand scope now. The reset and why it happened are recorded in
`docs/ROADMAP.md` and D-101.

## Previous gate and current recommendation

**Result 2026-11-03:** the source sleeve did not contain the hidden anatomy needed for a moving arm. A replacement arm
plus a generated torso restoration was layered and rendered in five poses. The initial black upper arm was a doubled
depth offset in Blender; correcting the offset made the painted arm visible. The resulting hand and underlay still
fail review. The earlier shoulder sequence evidence remains under
`~/ai-studio/scratch/rowan-rig-test/review-current/shoulder-sequence/`; current five-pose evidence is above.

**D-107:** the owner approved testing Rowan's front-view painted art as a 2.5D cut-out rig before doing more turnaround
work. That test is complete. The AI turnaround remains on hold. A manual/layered turnaround has not been approved.

**What the prototype actually contains:** a SAM-cut full-body drawing, a separate head, one arm image part, eye/mouth
swap patches, and a painted background. Blender stacks them as image planes; the arm rotates continuously from rest to
wave without a drawing swap, with a small head tilt, a slight body scale change, and a camera push-in. It does **not**
have independently rigged upper/lower arms, separate legs, elbow/knee mesh deformation, or a walk cycle.
See `docs/spikes/rowan-rig-test.md` and `scripts/spikes/rowan_rig_blend.py` for exact details.

**Gate now:** the depth correction passed its narrow visual check (the black arm is gone), but the overall pose gate did
not pass. The green underlay and unreadable hand are visible major defects. Do not render the six-second clip or start
the production slice from this candidate. The turnaround remains on hold.

The current `docs/steps/STEP-SLICE.md` still contains legacy Rain/Snow task descriptions below its D-107 gate. Reconcile
those before implementation. The current direction is storybook-style limited animation: use cuts instead of full
turns; only add views that the story needs. Choose and approve a turnaround method before producing it.

## Working rules for the next agent

1. Read `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md` (especially Reset), `docs/DECISIONS.md`,
   `docs/PROGRESS.md`, this handoff, and the current step brief before acting.
2. Keep the art repair bounded to the two reviewed majors. Use one working session at a time; name roles clearly, such
   as **Arm Art Integrator** or **Independent Animation Reviewer**.
3. Use installed local models only; no downloads or installs. Do not run a new seed search or build unrelated
   candidates. Keep generated media outside the repo. Do not delete files you did not create.
4. Review the actual images, not just metrics or the artist's self-review. The author cannot be the only reviewer.
5. Keep the owner updated with a concise table headed **Done**, **In progress**, **Pending approval**, and
   **Planned for future**.
6. Update `docs/PROGRESS.md` and the relevant spike/decision docs at the end. Commit and push only the task's verified,
   intended files; never force-push.

## Workspace caution

At the last status check, `scripts/run_first_shot.py` had an unrelated local modification and `.codex/` was untracked.
They were not part of the Rowan documentation work. Inspect ownership before changing, staging, deleting, or committing
them.
