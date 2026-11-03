# Rowan arm and shoulder repair

**Status:** focused repair in progress; current candidate is **NEEDS WORK** after independent review. No production clip is
authorized from the current candidate.
**Owner-visible role:** Rowan Arm Art Integrator, followed by an independent animation reviewer.

## Goal

Repair Rowan's waving arm so the shoulder, sleeve, forearm and hand look like one believable, on-model limb in the
existing six-second front-view test. The current arm moves continuously, but in the raise it reads as a detached puffy
block at the shoulder; its outline changes awkwardly, and the pale narrow forearm reads as a separate strip. At rest,
the sleeve is about 1.5 times the opposite sleeve's width. The hand is too small to read clearly as an open wave. The
latest verdict is **NEEDS WORK, one major**.

## Recommended approach

Treat this as a small art and joint-layout repair, not another timing pass:

1. Use the approved Rowan canonical as the strict style and proportion reference:
   `~/ai-studio/scratch/character-art-proof/canonical/rowan-canonical.png`.
2. Preserve the face, torso, clothing, backpack, background, framing and colors outside the arm area. If editing the
   artwork, use a tightly masked arm/shoulder crop; do not regenerate Rowan or the whole frame. Use installed local
   tools/models only.
3. Draw the arm in a neutral pose first: a slim sleeve matching the canonical, with consistent shirt color/shading, a
   plausible shoulder overlap, readable elbow/cuff and an open hand with a clear palm/finger silhouette. Avoid a bulb
   shoulder, pale forearm, elbow color band, tiny hand or detached-looking strip.
4. For the wave, rig overlapping upper-arm/sleeve, forearm and hand pieces with shoulder, elbow and wrist pivots.
   Overlap the pieces enough to hide seams through the range. Do not rotate the whole raised-pose drawing as one rigid
   plank; do not swap or cross-fade between pose-specific limb drawings.
5. Render four stills first: rest, about 45 degrees, horizontal and raised. Check the shoulder attachment and hand
   silhouette in all four before rendering the six-second clip. Then inspect a cropped shoulder/arm sequence through
   both the raise and lower.

If a clean layered arm cannot be made from the approved art within the time box, stop and report the limitation with the
best stills. Do not expand into a new character, turnaround, engine change or full film. Do not start repeated image
generation rounds. The current failure points to missing/poor arm and underlay art; pivot changes alone cannot make
the hand or exposed vest/backpack patch look correct.

## Done when

- At rest, sleeve width, color and shading fit the canonical and do not make Rowan lopsided.
- In all four poses and the clip, shoulder-to-sleeve, elbow, cuff and hand remain connected, with no gaps, detached
  shapes, abrupt contour changes, see-through transitions or hand jumps.
- The hand reads as an open hand at normal playback size, not a tiny nub.
- Raise and lower look continuous at normal speed. Review the cropped joint sequence frame by frame; a pop or broken
  attachment is a **major** under `docs/craft/visual-review.md`.
- A fresh **Independent Animation Reviewer**, who did not make the art or rig, reviews the result against the canonical
  using `skills/animation-review/README.md`. No major findings are required to pass this repair gate. The owner then
  reviews the clip before slice work proceeds.

## Files and guardrails

- Current rig: `scripts/spikes/rowan_rig_blend.py`.
- Generated layers, renders and review evidence stay outside Git under `~/ai-studio/scratch/rowan-rig-test/`.
- Read `AGENTS.md`, `docs/HANDOFF.md`, `docs/spikes/rowan-rig-test.md` and the review rubric before editing.
- Do not delete unrelated files. Run focused tests/lint if code changes. Record verification in `docs/PROGRESS.md`,
  then commit and push only this task's verified changes.

## Additions (orchestrator review, 2026-11-02)

- **How the arm art is made:** an agent cannot hand-draw. Inpaint a new arm on the canonical (same SDXL + StorybookRedmondV2
  settings), hanging relaxed a little away from the body with an open hand, so it sits mostly outside the torso and can
  be cut with SAM. Then split it at the elbow and wrist with rounded overlap caps (see `add_caps` and `cut_limb` in
  `studio_core/src/studio_core/puppet/build.py`) so no seam shows when the joints turn.
- **No canonical hand exists:** one hand is in a pocket and the other is behind the backpack. The open hand is a new
  design, so the reviewer judges it on style and readability, not on matching the reference.
- **Elbow bend stays moderate** (under about 60 degrees), because the shading is baked into the paint.
- **Regression check in the review:** blinks (1.1, 2.3, 4.7 s), talking (3.2 to 4.6 s), smile (from 4.9 s), headroom at
  the end, and no black or stray patch on the face.

## Resumable task list (resume from the first open gate)

Outputs live in `~/ai-studio/scratch/rowan-rig-test/`. Script: `scripts/spikes/rowan_rig_test.py` (jobs) and
`scripts/spikes/rowan_rig_blend.py` (rig).

- [x] **T1** Bounded repair brief and done-when written.
- [x] **T2 (rejected)** Earlier `arm_neutral` generated several poor candidates; none supplied a usable neutral arm.
- [x] **T3 (rejected)** The earlier cutout rig rendered, but independent review found detached shoulder and off-model sleeve.
- [x] **T4 (failed)** Replacement arm/underlay candidate rendered to five still poses. A doubled Blender depth offset
  made the arm black; the deterministic depth correction removed the black arm.
- [x] **T5 (failed gate)** Independent review of the depth-corrected five-pose sheet returned **NEEDS WORK**: the hand
  is a thin streak and the exposed vest/backpack area is lime green. No full clip was rendered.
- [ ] **T6 (open)** Resolve the two art defects with a coherent arm/hand and garment underlay, then rerender only the
  five still poses. Do not run another seed search or clip before this gate passes.
- [ ] **T7 (open)** After the pose gate passes, render the short arm sequence, inspect it independently, update the
  spike and progress notes, and commit only verified task files.

## Historical result (2026-11-02): the first layered arm candidate failed

- **T2** took three tries. Try 1 described Rowan in the prompt, and the model painted whole small children into the arm
  area. Try 2, with an arm-only prompt, gave one usable arm (sleeve too wide and green, the hand read like toes). Try 3
  used a slim mask and four seeds: seed 9107 has a slim, on-model sleeve with a cuff (its hand is green), and seed 9105
  has a good skin-coloured open hand. The pieces were taken from both.
- **T3:** the sleeve was split at the elbow with a colour-matched cap, and the hand was moved under the cuff. Two
  cutting bugs were fixed on the way: the sleeve was clipped to the mask line, and SAM took a leaf with the hand.
- **T4 fails by eye** (`~/ai-studio/scratch/rowan-rig-test/poses.png`). At low, horizontal and raised the sleeve swings
  away from a gap at the shoulder, the upper arm reads as a bulky block, and the hand is a sliver. Why: the inpainted
  sleeve hugs the body and has **no shoulder joint art**, meaning no round top that tucks under the vest. Its only pivot
  is the sleeve's top edge, and the hand generation is unreliable. The fix needs real joint design (a round shoulder
  cap overlapping under the torso, a pivot inside the body), and that is art authoring, not more rig code.
- Not done then: the clip gate was blocked by the failed still poses. A later independent review and the second
  candidate's result are recorded above and in `docs/PROGRESS.md`.

## Latest result (2026-11-03): depth fixed, art gate still fails

The second candidate used local seed 9201 arm art, SAM masking, and one torso restoration (seed 9301). A five-pose
render initially showed a black upper arm. Independent code diagnosis found that `plane()` baked the depth into the
mesh and then assigned it again to the pivoted object's location, making the upper arm coplanar with the shoulder
occluder. The paired depth correction in `scripts/spikes/rowan_rig_blend.py` was rerendered; the sleeve is now teal.

A fresh independent reviewer saw the updated five-pose sheet and returned **NEEDS WORK**. Two majors remain:

- The hand reads as a pink streak or spike, with no palm silhouette.
- Lifting the arm exposes a vivid lime-green patch between vest and backpack.

The cuff/hand also blends into the backpack at rest. Evidence is under
`~/ai-studio/scratch/rowan-arm-candidate-v3/render/poses/`; the independent report is
`~/ai-studio/scratch/rowan-arm-candidate-v3/render/review.md`. No motion timing, full clip, audio, or production rig was
reviewed. Keep the incomplete art/layer candidate uncommitted. The narrowly scoped depth correction may be isolated in
its own commit; it does not make the candidate pass.
