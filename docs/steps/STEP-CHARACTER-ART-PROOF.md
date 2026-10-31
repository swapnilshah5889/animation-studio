# Character-art proof: one original detailed child character

**Status: owner-approved 2026-10-31 (D-105).** This is a design-only prerequisite to the vertical slice, not a new
animation step. Keep Blender as the engine. Rain and Snow remain technical rig baselines, not approved film characters.

## Goal

Create one original child-character concept that feels fully designed and belongs in the existing painted forest. The
previous Rain attempts showed that shader tweaks cannot bridge the style gap. This proof changes the art source, not the
engine or story scope.

## Art direction

- Original, age-appropriate child character, about 8–10 years old; do not imitate a named studio or living artist.
- Drawn storybook illustration with a clear silhouette, intentional layered clothing, recognizable small motifs/material
  details, and a restrained palette related to the forest. Details should read at full-body scale instead of becoming noise.
- Normal face: two level eyes, small nose and mouth, balanced proportions; no extra facial marks that resemble eyes.
- Present front and three-quarter views of the same design plus one face detail, with a short written design description.
- Place the character in a still over the existing forest plate to judge style coherence. Do not redraw or regenerate the plate.

## Scope and limits

- Use the already-installed local SDXL + StoryBook model and pipeline recorded in `docs/MODELS.md`; no downloads or new
  dependencies. Fully local.
- One character only, one focused session, maximum 45 minutes. It may make a small number of controlled refinements to
  the same design, but must not start character variants, rigging, animation, or a story/engine change.
- Save images outside the repository under `~/ai-studio/scratch/character-art-proof/`.
- Run the agent-neutral visual-review procedure and rubric. The artist cannot be the only reviewer.

## Done when

1. The face is normal and readable at full-body and face-detail sizes.
2. The design has deliberate, useful detail without clutter and a silhouette that is distinct at a glance.
3. The character and existing forest read as one illustrated world.
4. An independent reviewer returns no blocker or major finding.
5. Record prompts/model/seed, outputs and verdict in `docs/PROGRESS.md`; commit and push. **Then show the owner and
   wait for approval before rigging.**

If the local model cannot keep views consistent or the independent review still finds a major, stop and report; do not
automatically broaden the art or animation scope.
