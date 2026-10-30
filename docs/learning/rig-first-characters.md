# Rig-first characters, a parametric face and smooth motion

Why a cut-out character made by cutting one painted picture never looks production-grade, and what we do instead
(D-095, spike `docs/spikes/rigged-character-test.md`).

## Design for the rig, not for the poster

A painted still has no pixels for a hidden forearm, has light baked in, and has one pose. Cut into parts, every
rotation reveals what was never drawn. **Rig-first** reverses it: decide the skeleton, then draw each part as a
complete shape that already contains its own joint (a round cap hidden under the parent). Flat colours plus one shade
crescent per part stay consistent when the part rotates; a soft painted shadow does not.

## A face is a function, not a find

Detecting eyes in a painted head and keeping what you find gives whatever the detector hit (a curl, a cheek mark).
`face_layout.py` instead computes every feature from the head box and a handful of proportions and clamps each to a
legal range. The limits are tested over the whole parameter space, so the LLM and the art can no longer produce a
face with eyes on the cheeks. Gotcha: limits must be shares of the *visible skin*, not of the head with its hair.

## Head turn without new art

Sliding features toward the turn, narrowing the far eye and sliding the nose further reads as a turn up to roughly 0.6
of a full profile; beyond that you need a turned part set. The function reports `needs_turned_set` instead of faking it.

## Switches versus numbers

A blink or a mouth letter stored as a switch changes in one frame. Storing the face as numbers (eye openness, mouth
open/width/round, smile, brow) and smoothing those numbers means every in-between frame is a real drawing. Closing
should be faster than opening, and the mouth should lead the sound by about a frame.

## Pops and speed caps

Where two actions meet, keys jump. Smooth only around detected jumps (so real fast motion is untouched), then enforce
a per-bone speed cap with alternating forward/backward slew limiting (each pass moves values toward their
neighbours, so it converges). `Clip.max_speed_dps` declares a cap the same way `Clip.limits` declares a range.
