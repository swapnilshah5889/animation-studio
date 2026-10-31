# Character-art proof: canonical design, then reference-conditioned turnaround

**Status: owner-approved 2026-10-31 (D-105, amended by D-106).** This is a design-only prerequisite to the vertical
slice, not an animation step. Blender remains the engine. Rain and Snow remain technical rig baselines, not approved
film characters.

## Stage 1: one canonical illustration (current task)

Create one original, age-appropriate child character around 8–10 years old in a detailed drawn storybook style that fits
the painted forest. The first multi-view attempt failed because the model generated several different characters. Do not
ask it for a turnaround sheet yet.

- One full-body front or gentle three-quarter view only. Include a distinct silhouette, clear face, layered clothing,
  and a few meaningful small motifs/material details. Keep details readable at full-body scale and use a restrained
  palette related to the forest.
- Face: exactly two level eyes, small nose and mouth, balanced child proportions; no extra marks that resemble eyes.
- Include a short written design description and an optional enlarged crop of the same face. Do not include extra
  characters, clothing-only panels, or other views.
- Judge style against the existing painted forest plate. Do not regenerate or modify the plate.

## Stage 2: more views (only after owner approval of Stage 1)

Use the approved canonical image as the visual reference for additional front, three-quarter and side views. Review
whether face, hair, proportions, colors, clothing and motifs remain the same. The independent reviewer and owner must
approve the turnaround sheet before rigging begins.

## Scope and limits

- Use installed local models only; no downloads, installs or new dependencies. Runtime must remain local.
- One focused session per stage, maximum 45 minutes; a small number of controlled refinements to the same approved
  design are allowed. Do not produce variants or advance stages without owner approval.
- Save images outside the repository under `~/ai-studio/scratch/character-art-proof/`.
- Follow the agent-neutral visual-review procedure and rubric in `skills/animation-review/` and
  `docs/craft/visual-review.md`. The artist cannot be the only reviewer.
- Do not rig or animate until the owner approves the reviewed turnaround sheet.

## Stage 1 done when

1. The single character has a normal, readable face and distinct child silhouette.
2. The illustration has deliberate detail without clutter and reads well at full-body and face-detail sizes.
3. The art style is compatible with the painted forest plate.
4. Independent review finds no blocker or major.
5. Record model/prompt/seed, output and verdict in `docs/PROGRESS.md`; commit and push; show the image and wait for owner
   approval before Stage 2.

If the image still fails independent review, stop and report the findings. Do not generate turnarounds or broaden scope.
