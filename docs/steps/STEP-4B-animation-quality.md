# Step 4B: Animation quality: puppets that hold up on screen

> **Status: draft, for the owner's review.** Opened 2026-10-27 when Step 4 closed (D-068). Proposed
> decisions below are not approved yet.

**Goal:** make the finished picture and the motion read as professional work, not as a correct test
render. This is where the picture and animation rows of the production-grade bar (ROADMAP) are met
for cut-out films. Everything stays engine-neutral (D-030) and controlled (D-064): no generated
video, AI makes the art, our tools animate.

**Out of scope:** the director (Step 5), a second animation engine (Step 6), training (Step 9), new
art styles (they come with Step 6 backends).

## What Step 4 left for this step (carry-overs, measured, from D-057, D-062 to D-067)
- **Bolt (robot, candidate c2):** limbs off their bones in both views, no eyes in the front view, views
  inconsistent (head 115% as tall). The cut's rules assume organic limbs and dark eyes.
- **Mia:** the bent-knee pose breaks up; the far arm shows almost nothing in a wave.
- **All characters:** dark seam dashes between the legs (Bo, Kit; fixing them changes Kit, so the
  owner approves the Kit change), the knee wedge of a rigid bend, outline dashes beside the body and a
  seam on the waving arm (Bo).
- **Unlooked-at:** nobody has viewed the final three-quarter pose images of the Mia coat-arm fixes.
- **Calibrated on five characters:** limits of 7% (paint), 0.8 (far shin), 0.5 (turn), 10% (head size).
  Re-check them on new characters.

## Owner checkpoints
1. Approve this brief and the production-grade bar's numbers (ROADMAP).
2. Look at the review reel (task 4B.7) and say what still reads as wrong.
3. Approve any change to Kit's built parts (task 4B.2).

## Proposed design decisions (the owner may overrule)
| Topic | Proposal | Why |
|---|---|---|
| Robots and other non-organic characters | A vision model (qwen3-vl 8B, Apache-2.0) locates the face and limb joints as boxes; the pixel rules check and refine them | Rules tuned on organic characters keep needing new cases; a locator generalises. Needs a trial first (accuracy on the five-character cast, seconds per image) |
| Bending limbs | Synfig skeleton deformation on one limb image, or a two-part cut with a rounded joint cap | The rigid two rectangles look stiff (D-053 open item) |
| Hands | 3 to 5 swappable hand poses per character (open, point, fist, wave), cut from a drawn sheet or redrawn from the hand | Hand shape carries acting |
| Secondary motion | Ears and tails as their own bones with follow-through | They are rigid with the head or torso today |
| Moving through a shot | A placement track (position over time) in the shot spec, and a real walk across the frame in the three-quarter view | Placement is fixed per shot (D-033) |
| Checks | A pose sweep that renders every motion at its extremes and fails on holes, seams or detached parts | A pass bar that a number can fail, as the cast bar did |

## Tasks (to be sized; each ends in a verified, committed change)
- **4B.1 The pose sweep:** render every motion at its extremes for the five-character cast through
  the Synfig backend; hole, seam and detached-part checks; a contact sheet. First, because it makes the
  other tasks measurable.
- **4B.2 Cut defects:** the carry-overs above (seams between legs, wave-arm seam, outline dashes,
  Mia's bent knee and far arm), each with a test that fails without it.
- **4B.3 Non-organic characters:** the face and limb locator trial and, if it works, its integration
  (Bolt as the test).
- **4B.4 Bending limbs.**
- **4B.5 Hands.**
- **4B.6 Secondary motion and a placement track, then a walk across the frame.**
- **4B.7 Review reel:** the cast performing every motion, for the owner.
- **4B.8 Docs:** learning notes (cut-out animation principles in code), DECISIONS, PROGRESS, MODELS if a
  model is added, and the Step 5 brief updated for what changed.

## Done when
- The cast (the five characters, including Bolt) performs every motion in a review reel that passes
  the pose sweep with no hole, seam or detached part, and the owner's review of the reel.
- Limbs bend, hands swap, ears and tails follow through, and a character walks across the frame in the
  three-quarter view.
- Learning notes, DECISIONS, PROGRESS updated; work committed and pushed.

## Risks
- **Speed on the Mac:** a vision-model locator and bent-limb renders add compute; measure before
  committing (one large model at a time).
- **Overfitting to five characters:** the cast is small. Add characters as the cut changes, and keep
  the part-hash comparison (Kit unchanged) as the regression guard.
- **Kit's built parts:** the owner approved them; any change needs the owner's OK (4B.2).
