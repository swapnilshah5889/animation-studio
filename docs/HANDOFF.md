# Project handoff

**As of:** 2026-11-02
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

**Pending owner approval:** switch to a hand-authored, layered turnaround for Rowan. This is the recommendation because
the local reference-edit workflow repeatedly altered the same defining costume details. Do not begin this alternative
until the owner approves it and its done-when is agreed.

If approved, the next task should be one bounded art task, not rigging: create matching full-body front, three-quarter,
and side views from the approved canonical, preserving the cap without a projecting brim, the same red back garment,
face, proportions, palette, clothing, and motifs. Keep all views fully framed. Have an independent reviewer compare each
view against the canonical, record issues and evidence, and stop if there is a blocker or major. Show the reviewed sheet
to the owner and wait for explicit approval before rigging. Use the agent-neutral procedure in
`skills/animation-review/README.md` and rubric in `docs/craft/visual-review.md`.

After a turnaround is both independently reviewed and owner-approved, continue the vertical slice in
`docs/steps/STEP-SLICE.md`: rig and verify the character in Blender, pass the 2D/2.5D drawn-look gate, then build and
review the 30-second four-shot film. The slice is complete only when the independent review has no blocker or major and
the owner says the film passes. Only then propose the next roadmap brief.

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
