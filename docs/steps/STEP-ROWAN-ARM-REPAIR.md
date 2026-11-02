# Rowan arm and shoulder repair — Claude Code handoff

**Status:** owner-authorized focused repair. Start from `main` after `f5425e1`.
**Owner-visible role:** Rowan Arm-Rig Artist. One time-boxed work session (90 minutes), then independent review.

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
best stills. Do not expand into a new character, turnaround, engine change or full film.

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
