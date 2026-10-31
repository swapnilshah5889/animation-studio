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

## Round 3: rules that look at the whole shot, not one frame

- **Framing is a rule on the bake.** `framing.check_framing` pushes the character's box (hair top from the head bone, lowest
  sole) through each frame's camera and fails when head room, foot room or side room drop under a margin. The first push-in was
  chosen by eye and cropped the hair and the boots; no frame-by-frame look caught it until a reviewer did.
- **Feet are measured, not eyeballed.** `motions/gait.foot_report` reads the shin joints from the bake: *float* (the lower sole
  above the ground while walking), *sink*, and *slide* (x drift over a run of frames where a sole is planted). Three bugs were
  hiding behind a plausible picture: the boot art had 10 empty rows (Mia hovered 10 px), a torso lean swung both planted feet
  (the legs hang from the torso: `smooth.ground_legs` counter-rotates the thighs), and the walk ended mid-swing so the last foot
  skidded in (first and last step are now half steps that start and land at zero speed).
- **Gotcha:** a swinging foot's height depends on its leg tilt (`rise`), so a lift in the thigh's shift channel has to add the
  planted foot's drop and subtract its own tilt rise, or the foot sinks at landing.
- **Head shape is a function too.** `hairline_y(box, x)` (a parting that sweeps down to the temples) and side locks placed along
  the face's contour replace a flat fringe over straight capsules, which is what made the face read as a rectangle.
