# Rowan component-motion proofs

**Status:** owner-approved 2026-11-03 (D-111). Four bounded proofs run in parallel up to the agent service's hard cap
of two active subagents; remaining proofs begin as slots open. This is a feasibility gate before any full animation
test; it is not a production rig.

## Shared rules

- Character design source: `~/ai-studio/scratch/character-art-proof/rowan-assembled-front-v3.png`.
- Keep each proof in its own scratch directory under `~/ai-studio/scratch/rowan-component-proofs/<component>/`.
- Use direct-generated component art with Rowan v3 as the reference. Do not cut moving parts from the flattened
  character. Keep every generated layer's source and prompt, and report unknown generator/license provenance.
- If the needed complete component or covered underpainting cannot be made without cutting the flattened image, report
  **FAIL / not feasible** with evidence. Do not fake a pass by animating only a crop, silhouette, or camera.
- One 2-second test, 24 fps, 720p or smaller. Render the clip plus a 12-frame contact sheet; review at normal speed and
  frame by frame. Use `skills/animation-review/README.md` and `docs/craft/visual-review.md`.
- Each author reports the tested motion range, motion/art limitations, artifacts, file paths, render settings, and
  whether tests are reproducible. Author self-review is not an acceptance review.
- A different reviewer reviews each clip independently. Pass requires no blocker or major and no visible art mismatch,
  pop, gap, detached part, or frame spike in the tested range. All four must pass before the full animation test.
- No shared source-code edits, full-body animation, full film, or production rigging in this step.

## Parallel proofs

| Proof | Minimum motion | Key risks to inspect |
|---|---|---|
| Head and face | One gentle nod/sway and one natural blink | Face stays attached and normal; eye identity/color; hair and head move together; no face sliding |
| Arm and shoulder | Shoulder-led raise to about 90 degrees, two small waves, controlled lower | Complete sleeve/skin underlap; shoulder and elbow connection; open hand readable; no puffy shoulder, gaps, or swaps |
| Leg and foot | Two in-place walk steps with alternating planted feet | Hip/thigh underlay; knee and ankle continuity; no scissor crossing, foot slide, or garment holes |
| Torso | Two seconds of subtle breathing and a small weight shift | Chest/vest remain coherent; neck follows; no stretching, texture swimming, or garment separation |

## Gate sequence

1. Authors build/render in separate scratch locations, with no more than two active at once. Start the next author as
   soon as a slot opens.
2. After every output exists, independent reviewers inspect in parallel, up to the same two-agent cap. No reviewer may
   review their own work.
3. Orchestrator checks the four reports and artifacts. Failed proofs are recorded and repaired only within their original
   scope. No full animation test until all four pass independently.
4. Once all four pass, prepare a separate brief for one short full-character animation test.

## Provenance and cleanup

All generated art and clips remain outside Git. Record which generation tool/model created each component and its known
license. Unknown provenance blocks production use. Keep only source assets, the rendered clip, contact sheet, and review
evidence for each proof; remove disposable intermediates created by that proof after verification.
