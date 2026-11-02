# Project handoff

**As of:** 2026-11-02 (updated after Rowan arm-fix re-review)
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
- **Front-only feasibility rig:** built as a six-second, 1080p24 2.5D plane-and-swap prototype. The arm raise now uses
  one continuously rotating arm image, with no drawing swap, fade, snap or missing frames. Independent review and the
  orchestrator's re-review both say **NEEDS WORK, one major**: in the raise, the puffy sleeve reads as a detached block
  at the shoulder and changes contour awkwardly; the pale, narrow forearm reads as a separate strip. It is off-model
  and the shoulder/arm integration looks broken. The motion-foundation no-major gate is not met.
- **Production rig/film:** not started. The prototype does not provide a walk, turn, or three-quarter view; do not treat
  its review as approval of the 30-second slice. The arm-art major remains open.
- **Generation:** stopped. No image-generation process should be assumed to be running.
- **Pending:** a bounded correction to the neutral arm and shoulder artwork is needed before the owner reviews the
  motion foundation. Keep the limb a single continuously moving part, but redraw the neutral sleeve/shoulder attachment
  to match the canonical's slim sleeve, with a plausible elbow and open hand. Then get an independent review. The
  turnaround remains unapproved.
- **Latest verified repository state before this documentation update:** `main` was at `56753dd`. The arm motion fix,
  review findings and current art blocker are recorded in `docs/PROGRESS.md` and `docs/spikes/rowan-rig-test.md`.

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

**Result 2026-11-02:** the first focused review found a snap; the attempted cross-fade caused ghosting and missing arm
frames. The current single-arm version fixes that motion defect. A fresh independent reviewer and the orchestrator
both found one major in the current clip: the sleeve reads as a detached puffy block at the shoulder through the raise,
and the pale narrow forearm reads as a separate strip. The no-major gate is still not met. The focused sequence is under
`~/ai-studio/scratch/rowan-rig-test/review-current/shoulder-sequence/`; the independent report is
`~/ai-studio/scratch/rowan-rig-test/review-arm-fix.md`.

**D-107:** the owner approved testing Rowan's front-view painted art as a 2.5D cut-out rig before doing more turnaround
work. That test is complete. The AI turnaround remains on hold. A manual/layered turnaround has not been approved.

**What the prototype actually contains:** a SAM-cut full-body drawing, a separate head, one arm image part, eye/mouth
swap patches, and a painted background. Blender stacks them as image planes; the arm rotates continuously from rest to
wave without a drawing swap, with a small head tilt, a slight body scale change, and a camera push-in. It does **not**
have independently rigged upper/lower arms, separate legs, elbow/knee mesh deformation, or a walk cycle.
See `docs/spikes/rowan-rig-test.md` and `scripts/spikes/rowan_rig_blend.py` for exact details.

**Gate now:** the arm motion is continuous, but the shoulder/arm attachment still looks broken and off-model. Do not
treat this as a pass or start the slice or more turnaround generation yet. The next bounded task is to redraw the neutral
arm and shoulder attachment to match the canonical (slim sleeve, plausible elbow, open hand), keep one continuous arm
drawing through the move, and obtain a fresh independent review. The turnaround remains on hold.

The current `docs/steps/STEP-SLICE.md` still contains legacy Rain/Snow task descriptions below its D-107 gate. Reconcile
those before implementation. The current direction is storybook-style limited animation: use cuts instead of full
turns; only add views that the story needs. Choose and approve a turnaround method before producing it.

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
