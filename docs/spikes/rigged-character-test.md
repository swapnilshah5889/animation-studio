# Spike: one character designed for rigging (Mia), a parametric face, smooth motion (D-095)

Question (from `owner-review-bakeoff.md`): the owner said the characters, not the engines, look bad. Is a
character **drawn as parts, in a flat style, with a computed face** enough to fix that, and what does it cost?
Result: the clip is in `~/ai-studio/scratch/rigged-character-test/clip.mp4` (6 s, 1080p, with the two spoken lines),
the contact sheet in `sheet.png` next to it. Time spent: about 2.5 hours of one session. Nothing else was touched.

## 1. The face bug, with numbers (old Mia, `films/step4-cast/characters/child/rig.json`)

Head image 409 x 327 px (hair included); the visible skin at eye height is 212 px wide.

| Measure | Front view | Three-quarter view | Should be |
|---|---|---|---|
| eye spacing, centre to centre | 165 px = **78% of the skin width** (40% of the head incl. hair) | 77 px | 30 to 46% of the skin width |
| both eyes' outer edges | 223 px apart: **wider than the skin (212)**, so the eyes sit on the cheek edge | n/a | inside 78% of it |
| eye height difference | 11 px (a tilted eye line) | 29 px | 0 |
| mouth x minus eye midpoint | **-48.7 px** (left of centre) | **-27.1 px** (beside the near eye) | within 6% of the face width |
| mouth drop below the eye line | 57 px = 18% of the head height | 96 px | 14% or more, 72 to 90% down the face |

Why: `puppet/build.py clean_face` *finds* marks in the painted head (nearest the skeleton's guess) and keeps
whatever it finds. The painted head had huge dark curls and a hairline mark near the cheek, so the "eyes" snapped
to the outer marks and the "mouth" to a dark mark off the centre line. Nothing checks proportions. The face was
also baked into one head sprite, so a head turn could only roll the whole head in the image plane (the bake-off
turn was a +14 degree roll, never a yaw), and the three-quarter view's anchors had no relation to the front's.

## 2. The fix: `studio_core/face_layout.py` (rules in code)

Every feature is *computed* from the head's bounding box and proportions, then clamped to hard limits
(`LIMITS`, the contract):

- `FaceBox.from_head_bbox` takes hair out of the bbox (fringe 30% of the height, side hair 13% of the width each).
- eye gap 30 to 46% of the face width, eye width 10 to 20%, eye line 42 to 62% down, mouth 72 to 90% down and at
  least 14% below the eyes, mouth no wider than 80% of the eye gap, nothing's centre within 10% of the face edge,
  eyes level, mouth under the eyes' midpoint (6% tolerance), nose between eyes and mouth.
- It is anchored to the head part (a head layer composited per frame, so it moves with the head bone).
- **Head turn** (`yaw` -1..1): the whole face slides toward the turn (15% of the face width at most), the nose
  slides 1.35 times as far (it sits in front of the face plane), the far eye narrows 30%, the spread shrinks 14%;
  past 0.6 `needs_turned_set` says a real turned head set should be used (reported, not hidden).
- `check_layout` lists every violated rule; `layout_face` clamps and reports each correction.

`tests/test_face_layout.py`: 13 tests, among them a sweep of 243 styles x 7 yaws x 3 head sizes (all legal), the old
Mia numbers (clamped, mouth centred), turn symmetry, nose-furthest, scale with head size, the bad-face detector.
Schema: `face.layout` added to `schemas/rig.schema.json` (optional; old rigs unchanged).

## 3. The character: `studio_core/puppet/flat.py` (drawn as parts, flat style)

**Route taken: construct the character by code, complete parts, small palette.** Every part is a full shape:
limbs are capsules with round ends (shoulder, elbow, knee, hip circles hide under the parent, so any rotation shows no
cut edge and no gap), hands are mittens with a thumb, boots and cuffs are in the part, the head is three layers
(skin, face, fringe) so brows can slide under the hair. Colours are solid fills; each part has one shade crescent on
its right edge, so a rotated part stays consistent (no baked soft shadow, no gradient, no outline). The curly
hair-back is one part, the two hair locks are bones of role `ear`, so the existing follow-through layer swings them
after the head with no new code. Mia is a `FlatSpec` (palette and proportions): another character is another spec.

What I tried first and what failed (local FLUX.2 klein 4B edit of Mia's existing sheet figure, 768x1024, 4 steps,
~150 s per image on the M4, outputs only in scratch): two prompts asking for a "flat vector cut-out puppet, neutral
A-pose, arms away from the body, legs apart, no shading". Measured result: the model keeps the original's painted
look, colours are not controlled (12 to 13 colours above 0.5% share, no fixed palette), the arms touch the body at
3 of 4 rows measured in prompt "a" and 1 of 4 in "b" (limbs not reliably separated), and nothing guarantees the hidden
part of a limb exists: the model draws what it sees. Each output would still need SAM cutting, hand completion and a
manual check, so it is neither cheaper nor safer than constructing the parts. Rejected for the limbs. The route is
still the right one for **new characters' look** (design sheet, palette, hair and costume ideas) which the spec then
takes from; a later spike could regenerate each part from an A-pose sheet with inpainting for hidden areas.

## 4. Smooth motion: `studio_core/motions/smooth.py` (deterministic, tested, opt-in)

- `Clip.max_speed_dps` (new, declared like `Clip.limits`), `speed_caps`, `blend_pops` (smooth *only around* one-frame
  jumps above 9 degrees, so a walk keeps its shape) and `limit_step` (alternating forward/backward slew limit): the
  action seams (walk to wave) no longer pop.
- `eye_series` (lids close in about 3 frames, open slower), `mouth_series` (Rhubarb letters as numbers, the mouth
  leads the sound by one frame and eases between shapes), `expression_series` (0.35 s smootherstep crossover),
  `eased_track` (head turn, camera), `crossfade_alpha` (shot transition).
- The face is drawn per frame from those numbers (`engines/face_flat.py`), so a half-blink and a half-open mouth are
  real drawings; the bake (`engines/bake.py`) carries `frames[].face` when the shot has `"smooth": {}`.
  Camera moves (`camera.move = "track"`, eased zoom/pan) and transparent renders were added to the bake and the Blender
  harness for the 2.5D composite. 11 tests in `tests/test_smooth.py`.

Numbers (`scripts/spikes/rigged_character_motion.py`, the 6 s shot, smoothing off then on):

| | off | on |
|---|---|---|
| one-frame jumps above 9 degrees (all bones) | 71 | 20 |
| largest one-frame step | 46.2 deg | 19.9 deg |
| jerk (RMS of the 3rd difference), mean over bones | 5.01 | 0.93 |
| face: largest one-frame change of eye openness | 0.50 (a switch) | 0.39 (a blink closes over 3 frames) |
| face: largest one-frame change of mouth opening | 0.52 | 0.12 |

The 20 remaining jumps are the wave's own fast swing (right arm, forearm), real motion, not seams.

## 5. The clip

`scripts/spikes/rigged_character_test.py`: Mia walks in, waves while saying "Look, Bo! A red balloon!", turns her head
(yaw 0.55, eyes lead it) while saying "Up, up, up!", with the real mocap walk and wave and the follow-through hair.
Wide camera drifting right, then a **matching cut with an 8-frame cross-fade** (frame 70) to a slow push-in close-up:
one bake, two camera tracks. Blender (EEVEE, transparent) renders Mia at 1920x1080 in about 0.1 s per frame; the plate is
composited in Python: six flat layers (sky, far and mid hills, trees, ground with fence, foreground tufts) with
parallax factors 0, 0.15, 0.4, 0.7, 1.0, 1.3 and a soft contact shadow, so the camera move reads as depth (2.5D, no 3D).
The whole run (render, composite, encode with the two lines mixed) takes about 50 s.

**Defect counter** (same checker and same close-up shot B as the engine bake-off, Blender EEVEE, 960x540, magenta probe):

| | frames with a defect | holes | seams | largest |
|---|---|---|---|---|
| old painted Mia (`engine-bakeoff/metrics.json`) | 44 of 72 | 27 | 38 | 63 px |
| new flat Mia | **3 of 72** | 0 | 3 | 28 px |

Caveat: that shot has little limb bending and the counter measures holes and seams, not looks. The new parts are
constructed to overlap, so low numbers are expected; the picture is what counts (below).

## 6. What still looks wrong (honest)

I looked at one contact sheet. Mia now reads as one consistent character in the style of her background, with a normal
face that follows the head turn, but she is **not production ready**:

- Front view only. The walk shows legs swinging in the image plane (a sideways shuffle); a real walk needs a side or
  three-quarter set of parts. The head turn is a 2.5D slide (fine to about yaw 0.6), not a turned head.
- Simple art: no hand poses beyond a mitten, hands are small at wide-shot size, no foot flex, no clothing folds.
  Style is "clean vector", not hand-drawn or textured, and she is a code template (humanoid child).
- The hair is a very large mass and hides the ears; the curls do not animate beyond two swinging locks.
- Arms are behind the coat, so an arm raised across the body would pass behind it.
- Painted backgrounds from the library will clash with this style; the placeholder plate is code.
- Sound is mixed but not checked against the cues by ear. I did not review the clip frame by frame (token budget).

## 7. Recommendation for all characters and backgrounds

1. Keep this route: **a rig-first part set per character** (complete shapes, one palette, one shade crescent, parts on a
   skeleton), with the parametric face and the smoothing layer on by default for every flat character.
2. Cost per character: about 2 hours the first time (design the spec, check by eye), then minutes per new human-like
   character that reuses the template (a spec of colours and proportions; no GPU, no model). Animals need a template of
   their own (tail, ears, muzzle): about half a day each for the first of a kind. Generated design sheets can supply the
   palette and costume; they should not supply the pixels of the parts.
3. Add a side view and a three-quarter view as spec-driven part sets (same skeleton, different drawing function) so
   walks and big head turns are real; then turn sets replace the yaw slide beyond 0.6.
4. Backgrounds: draw layers in the same flat style by code or a layered vector tool; a painted AI plate with baked
   light cannot sit next to flat characters. Keep the 2.5D layer factors (0 to 1.3) and the contact shadow.
5. Owner decision needed: is the flat vector look the film's look? If hand-drawn texture is wanted, the same rig-first
   split still applies, but the part art comes from an artist or a per-part generation pass.

## Files

`studio_core/face_layout.py`, `puppet/flat.py`, `engines/face_flat.py`, `motions/smooth.py` (new);
`engines/bake.py`, `engines/face_sprite.py`, `engines/blender/build_render.py`, `motions/timeline.py`, `principles.py`,
`schemas/rig.schema.json` (extended, defaults unchanged); `scripts/spikes/rigged_character_test.py`,
`rigged_character_motion.py`; tests `test_face_layout.py`, `test_smooth.py`. Learning note: `docs/learning/rig-first-characters.md`.
