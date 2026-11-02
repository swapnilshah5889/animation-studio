# Project handoff

**As of:** 2026-11-02 (updated after D-107)
**Purpose:** concise, agent-neutral continuation brief. This is for Claude Code, Codex, and any other agent using this
repository. `AGENTS.md`, the roadmap, decision log, progress log, and current step brief remain authoritative; this file
points to the current state and next gate rather than replacing those sources.

## Current direction

The project is pursuing one owner-reviewed vertical slice before resuming the broader studio roadmap. The end product
should look like drawn 2D/2.5D children's animation. Blender is the active engine; OpenToonz is parked for a later hero
tier and Synfig is legacy. Rain and Snow are technical rig baselines, not approved film characters. See D-101 through
D-106 and the Reset section of `docs/ROADMAP.md`.

## Current stop point

- **Canonical art:** Rowan's single front-view illustration is approved by the owner. The independent reviewer found one
  minor eye-gaze imbalance; the owner accepted it. The image and face crop are outside the repository at
  `~/ai-studio/scratch/character-art-proof/canonical/`.
- **Turnaround:** not approved. The reference-conditioned three-quarter and side views changed the canonical red back
  garment and rounded cap. Bounded corrections did not resolve those details; the final cap edit retained a visor and
  top button and cropped Rowan at the thighs. Independent review returned **NEEDS WORK**.
- **Rigging/animation:** not started for Rowan. Do not rig from the failed turnaround.
- **Generation:** stopped. No image-generation process should be assumed to be running.
- **Latest verified repository state before this handoff:** local `main` was at `27e230f`, with the turnaround failure
  recorded in `docs/PROGRESS.md` and `docs/spikes/character-art-proof.md`.

The detailed evidence, model/settings, seeds, reviewer scope, and scratch artifact paths are in
`docs/spikes/character-art-proof.md`. The chronological project record is `docs/PROGRESS.md`; older entries describe
historical work, not necessarily active roadmap direction.

## What exists from earlier project phases

Earlier work built a local MCP-based animation pipeline, a local LLM director, edit and QA tools, a project store, and
editable multi-act film/export support. The older puppet pipeline, Mia/Kenney art, and early film/reel results did not
meet the visual bar. The 2026-10-31 reset deliberately pauses those broader features until the vertical slice passes.
Treat them as existing code/history, not permission to expand scope now. The reset and why it happened are recorded in
`docs/ROADMAP.md` and D-101.

## Next decision and recommended path

**Result 2026-11-02:** the rig test passed independent review (round 3 PASS, three minors), see
`docs/spikes/rowan-rig-test.md`. Waiting for the owner to watch the clip.

**Decided 2026-11-02 (D-107):** before any more turnaround work, run a **front-only rig test** of Rowan. The risky
question is whether this painted watercolour art can move well as a 2.5D cut-out rig in Blender (painted cut-outs failed
in the first film and the engine bake-off), so it is tested first and cheaply. The hand-authored turnaround is on hold
until the rig test passes.

**Rig test (one bounded task, about 90 min):**
1. Cut the approved canonical (`~/ai-studio/scratch/character-art-proof/canonical/rowan-canonical.png`) into layers:
   head, hair, cap, torso with the red back garment, upper and lower arms, hands, legs. Fill areas hidden behind parts
   with local inpainting in the same model and style (SDXL Base 1.0 + StorybookRedmondV2, settings in
   `rowan-notes.json`). Add 3 to 4 mouth shapes and open/closed eyes in the same style.
2. Rig in Blender (flat layers in depth, bones, mesh bending at elbows and knees) and render 6 s, front-facing: breathe,
   blink, talk, a small head tilt, a wave, and a slow camera push-in over a painted background.
3. Independent review (`skills/animation-review/README.md`, `docs/craft/visual-review.md`), then the owner watches it.

**Done when:** no blocker or major in the independent review, and the owner says the art moves well enough to build the
slice on. If it fails, record why and bring the owner one recommendation; do not try a new art or engine route alone.

If it passes: make the other views (hand-authored layered turnaround, only as many views as the slice needs), then
continue `docs/steps/STEP-SLICE.md`. The slice favours storybook-style limited animation: front and three-quarter
views, cuts between shots instead of full turns, a short walk with feet hidden by grass or one simple side-view cycle.

## Working rules for the next agent

1. Read `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md` (especially Reset), `docs/DECISIONS.md`,
   `docs/PROGRESS.md`, this handoff, and the current step brief before acting.
2. Get owner approval for the hand-authored turnaround approach before starting it. One working session at a time; use
   a focused role name such as **Turnaround Artist** or **Independent Character Reviewer** in user-facing updates.
3. Use installed local models only; no downloads, installs, new candidates, or changes of direction without approval.
   Keep generated media outside the repo. Do not delete files you did not create.
4. Review the actual images, not just metrics or the artist's self-review. The author cannot be the only reviewer.
5. Keep the owner updated with a concise table headed **Done**, **In progress**, **Pending approval**, and
   **Planned for future**.
6. Update `docs/PROGRESS.md` and the relevant spike/decision docs at the end. Commit and push only the task's verified,
   intended files; never force-push.

## Workspace caution

At the last status check, `scripts/run_first_shot.py` had an unrelated local modification and `.codex/` was untracked.
They were not part of the Rowan documentation work. Inspect ownership before changing, staging, deleting, or committing
them.
