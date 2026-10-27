# Consistency without training

*Tasks 4.3-4.5, D-053, D-057, D-060, D-061, D-062, D-063, D-066.*

## The problem
A character must look like the same character from the front and turned three-quarters, in
every shot. The usual answer is a character LoRA (a small trained add-on). Step 4 gets far
enough without training, by drawing the character **once** and making everything else follow.

## The ingredients
- **One generation per character.** The design sheet is drawn once (4-8 min each) and the
  chosen one is cut into parts. The rig reuses those parts in every shot, so the character
  cannot drift between frames: it is the same pixels.
- **The skeleton drawn in code as conditioning.** We draw the pose skeleton ourselves and
  feed it to the ProMax ControlNet, so the figure stands where the rig expects and the cut
  finds limbs where the bones are (see `controlnet-conditioning.md`).
- **FLUX.2 klein redraw for the three-quarter view (D-053).** An image *edit* model takes
  the front figure and redraws it turned. Same face, clothes and colours come from the
  picture itself, not from a prompt. The prompt carries the character's own description and
  asks for nothing added (an early prompt said "scarf" and every character got one).

## Checks, because the model can still be wrong
Each view is scored by code before the build (`puppet/consistency.py`, `puppet/turn.py`):
- **Paint histograms:** colours one view has and the other lacks (a hat in only one view).
  Compared by histogram, not palette, so rare colours stay rare. Paint from 3% of a region
  is reported; only 7% is a problem (D-061), since a profile legitimately shows a beak.
- **Head size:** the three-quarter head must be about as tall as the front head (10% tolerance).
- **Turn:** how far the figure actually turned; at least 0.5 is required. SDXL's own
  attempt scored 6%, klein's edits 56-102%.
- **Best of seeds:** seeds 1-3 are drawn and the best score kept. If none turns far enough,
  seeds 4-6 are tried one at a time until one does (D-066). Results are reused, so rebuilding
  a character doesn't redraw it (a rebuild took 27 s against 7.5 min the first time).

## Calibration lessons
Rules fitted to one character fail on the next. The checks needed correcting as the cast grew:
- **White clothes treated as background (D-062).** Pim's shirt sat 13-15 from his near-white
  background, inside the "gap" threshold, so it was cut out of the figure and arms landed in
  the torso. Threshold 15 -> 10 (gaps between touching legs measure 5-7).
- **A short sole scoring 0.81 (D-066).** Kit, Bo and Pim all drew a sole shorter than the
  skeleton's, so far-shin coverage 0.85 failed with drift near zero. Threshold 0.85 -> 0.8.
- **Touching legs (D-066).** Bo's dungaree legs merge, so a thigh read as drifted by a radius;
  the thigh now passes when the leg fit already found the skeleton on the legs.
- **Unchanged-Kit rule:** every fix was verified to leave Kit's part images byte-identical.

## Where it stops
Mia misses on turn (0.40 best of six) and Bolt, a robot, on limbs and head size: the cut's
rules assume organic limbs. Pass bar was 4 of 5; measured 3 of 5 (D-060, D-066).

## What LoRAs add in Step 9
A trained character LoRA makes *new* drawings (new poses, expressions, scenes) look like the
character, which one reused sheet cannot. Until then the cut-out approach is consistent by
construction but limited to the poses the rig can make.
