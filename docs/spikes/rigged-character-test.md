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

## Round 2 (D-096): the independent review's findings

The independent review of `clip.mp4` said NEEDS WORK (face within spec; two-plus majors). Fixes, one round plus a framing
touch-up, all with tests (`tests/test_flat_round2.py`, 11 tests):

1. **Ghost crossfade (major).** The 8-frame dissolve between the wide and close framings showed two Mias and doubled trees.
   Now one continuous camera push-in (`rigged_character_test.CAM`), and a rule `smooth.transition_for(zoom_a, zoom_b,
   character_in_both)`: a dissolve between two scenes that both contain the character at scales more than 1.25x apart is a
   "cut". Test: the ghost case is a cut; the clip's camera is a keyed push-in with no CUT constant.
2. **Neck (major).** The neck was a block in the head image drawn over the coat. Now it belongs to the torso: a narrow tapered
   neck (at most 16% of the head width) behind a collar band, with an under-chin shade; the head image ends at the chin.
3. **Hair (major).** Clipped circles and rectangles became one smoothed shape: the pieces are unioned, blurred and cut at half
   (`_smooth`), the fringe is a cut cap with a scalloped edge, the images have 46 px of room so no curl is clipped (that was
   the flat top), the dark shade slab is gone. Tests: each hair image is one component, nothing touches the image border,
   the outline never jumps more than 6 px per column, no flat run on top.
4. **Walk.** Legs: coat shortened and boots reduced, so the visible leg is 27.7% of the height (11% before) and the boots 9.1%
   (14%); test `leg_ratios`. New motion `walk_step` (`motions/library.py`, in the shot schema): `walk_cycle`'s planted feet plus
   a 1.2 to 1.7 times higher eased foot lift, a knee bend on the lifted leg (declared via `Clip.limits`), a body bob at every
   step and a small torso sway. Hands: the mitten image was clipped by a 22 px pad (the "gap"); now 48 px, the hand starts under
   the cuff and the cuff is drawn over it (test: skin and cuff touch along an edge, nothing clipped). Pupils converge 9% toward
   the nose.

Verification: `clip_v2.mp4`, `sheet_v2.png` in `~/ai-studio/scratch/rigged-character-test/`; `review_v2/review.md` is the
**independent** review, `review_v2/review_self.md` my own. `motion.csv` spikes above 5x median: 0 (round 1: one of 6.5x at
the dissolve).

**Independent verdict: NEEDS WORK** (no blocker, three majors). My self-review said PASS; it was wrong on the framing (I
looked at a sheet from before my last camera change) and too kind on the walk and the hair. Round-1 findings: dissolve FIXED,
neck PARTLY fixed, hair NOT fixed, walk NOT fixed. Findings of the independent review:

| # | Sev | Time | Finding |
|---|---|---|---|
| 1 | major | 3.75 to 6.0 s | After the push-in the hair top touches or is clipped by the top edge and the boots are cut off from about 4.25 s: no head room. Fix: anchor on face and chest with 8 to 10% head room, or scale less; add a check that the head box stays inside the frame |
| 2 | major | 0.25 to 2.0 s | Walk: short thin legs under a big head, a scissor cross at 1.25 s, almost no arm swing, a shuffle (28% legs is still short next to the head). Fix: longer and thicker legs, longer stride with contact/pass/up poses, arm counter-swing, hip bob |
| 3 | major | whole clip | Hair is a helmet with square scalloped lobes and the face is a near-rectangle: round the skull and jaw, taper the hair, curve the bob lobes |
| 4 | minor | talking frames | Neck still reads as a tan rectangle in a bowl-shaped collar: taper into jaw and collar, make the collar a fold |
| 5 | minor | 2.0 to 3.0 s | Dead hold (8 frames under 0.3 change) after the walk, then a rigid straight arm: add a settle, bend the elbow |
| 6 | minor | 3.25 s, 5.25 s | Half-lidded sideways eyes read sly or sleepy: keep lids higher, gaze at the listener |
| 7 | minor | 4.0 to 5.5 s | Body nearly frozen while talking: small nods, weight shifts, hair settle |

Not checked by the reviewer: lip-sync, foot sliding, hair and arm follow-through. Reviewer's frank take: would not pass for
children's TV; the face is acceptable now, but the framing, the stick-leg shuffle and the helmet hair are not.

**My own list of what is still wrong** (not contradicted): a small brown square under the hem at 0.75 s, the two hair tones
meeting in a hard step, a front-view-only walk, no hair follow-through on the turn, a tree highlight like a half moon in the
plate. I did not listen to the audio and did not rerun the defect counter on the new art.

**Status:** round 2 stopped by instruction after two fix passes. The face and the transition are fixed and tested; the
character is not production ready. The owner decides whether to continue.

### Head turn moves the whole head (D-097)

The owner's bug report on `clip_v2`: on a turn only the inner face moved, the skin, hair and locks stayed put, so the face slid
like a sticker (the first independent review had called this a major). Cause, confirmed in code: `face_layout` yaw only shifted
the features inside the head image.

Fix (scoped: walk, framing and hair shape untouched): `face_layout.head_warp(yaw, head_w)` is a piecewise-linear horizontal map
about the head's vertical axis (shift 8% of the head width at yaw 1; the side turned toward narrows 4%, the far side 22%, so it
tucks). `engines/face_flat.warp_image` applies it to the composed head (skin, face, fringe) and, from `write_flat_sprites`, to
`hair_back` and both side locks, which use a lagged yaw (`smooth_lag`, about 0.12 s, baked as `yaw_hair`) so the lobes trail the
head. The Blender harness swaps those part images per frame (`frames[].part_images`). The features still slide within the head
(parallax, the nose most), so they move more than the outline. Lock images got more room (the shift would clip them).
Rules in code, tested over yaw -1..1 in 0.05 steps on Mia's real art (`tests/test_head_turn.py`, 140 cases): the warp is
identity at 0, mirrors, is monotone (nothing folds); eye edges, nose and mouth corners stay inside the warped skin; the head's
shift is at least 40% of the face's shift (`MIN_HEAD_SHARE`) and the nose moves more than the face, the face more than the head;
the warped chin still covers at least 60% of the neck width at the collar (never detaches); turned parts keep their size and are
not clipped; the hair lags and settles without overshoot.

Render: `scripts/spikes/rigged_turn_test.py` gives `turn_test.mp4` (3 s, silent: look left, right, back) and `turn_sheet.png`
(+ `turn_sheet_times.txt`) in `~/ai-studio/scratch/rigged-character-test/`. **Independent review (a separate agent, rubric item "on a
turn the head moves as a whole"): PASS**, no blocker or major, `review_turn/review.md`: the outline narrows (about 290 to 255
px) and shifts about 42 px at yaw 0.9, hair and locks move with it, the features move about 75 px (parallax) and stay inside the
skin, the head stays on the collar, the hair lags about 14 px mid-swing, 0 motion spikes. Its minors: the far side locks do not
tuck more than the near ones (reads as squash plus slide, not a three-quarter silhouette); square skin corners show beside the
fringe; the neck stays centred while the head slides (no gap); the swing through centre (0.55 s) reads as a whip; the hair top
is about 20 px from the frame top in this test (framing). Not checked by the reviewer: frames between the sheet times, the
body (the coat looked slightly sheared on the small sheet, unverified), walking, audio. A turn up to about yaw 0.6 reads as a
turn; beyond it a real turned part set is still needed.


## Round 3 (D-098): framing, walk, head shape

Owner: "fix mia". Scope: the three majors of the independent review of `clip_v2`, plus cheap minors. `clip_v3.mp4` and `sheet_v3.png` are in
`~/ai-studio/scratch/rigged-character-test/`.

**Framing (major 1).** `studio_core/framing.py`: per frame the character's box (hair top from the head bone, lowest sole, head width
either side of the torso) goes through that frame's camera; `check_framing` fails under a margin (head 5%, feet 4%, sides 3% of
the frame). The old push-in fails it (boots cut at the end); the new keys (zoom 1.0 to 1.3, Mia at scale 0.88) pass on all 144 frames.
Choice: the end of the push-in is a full-body medium shot, not a close-up, because the rule forbids cropping head and feet.

**Walk (major 2).** Choice, justified: a lateral walk with the front-view puppet (walk toward camera was rejected: the plate scrolls
sideways with parallax, and a side-view part set does not exist; it is the right answer for a later round). Changes: legs 140+160 px
and thicker (visible legs 28% to 35% of height, boots 9%); `walk_step` has a wider opposite arm swing (about 2.5x) with a following
elbow; the first and last step are half steps that start and land at zero speed (the old walk ended mid-swing and the foot skidded
in); a swung foot's height accounts for its tilt; `smooth.ground_legs` counter-rotates the thighs against the torso lean (legs hang
from the torso, so a 5 degree lean slid both feet 26 px). Two bugs found by measuring: the boot art had 10 empty rows, so Mia
hovered 10 px above the ground in every frame (now cropped at the sole); and the settle after the stop slid the feet 30 px. Rule in
code, `motions/gait.foot_report` on the bake: float 1.3 px, sink about 5 px for two take-off frames, planted-run slide under 4 px
(thresholds 4, 6 and 4; the old walk floated 9 to 14 px).

**Head (major 3).** `puppet/flat._head_parts`: a rounder dome with a curl edge, a parted fringe (`hairline_y`, an arch that sweeps to
the temples, no flat band or square skin corner), side locks placed along the face contour, two round bob lobes. Tests: silhouette
solidity at least 0.93, the hairline is monotone and an arch, no step in the visible skin width.

**Independent review of the FULL clip (a separate agent, `review_v3/review.md`): NEEDS WORK** (no blocker, two majors; my
expectation was better, so this is the verdict):
- Major, 2.0 to 3.0 s, wave: a short stub comes out from behind the hair, the forearm points horizontally and no shoulder or elbow
  shows, so it reads as a hand growing from the head. (Not touched this round: I did not look at the wave arm.)
- Major, 0.2 to 1.7 s, walk: straight tube legs with no knees, crossing at 0.2 and 0.5 s, small arm counter-swing, the shadow
  gaps under the boots at 1.1 to 1.4 s (a small float), no settle at the stop. Leg lift and stride are real now.
- Minors: hair is still a bonnet dome and the face a wide rounded rectangle; the neck is hidden under the collar; body frozen
  while talking (change 0.27 mean); lids half closed at 0.5 and 3.25 s (sly or sleepy); slight scale growth in the walk.
- Previous majors: framing FIXED; walk PARTLY; helmet hair and boxy face PARTLY (now minor).
- The spikes at 0.88 and 0.92 s are a fast legitimate leg swing (2.84 against 2.73 to 2.77 around), not a pop.
- Owner complaints: eyes and mouth wrong NO; motion not smooth PARTLY; head turns only inner face not testable (no turn in the clip;
  the separate turn test passed, but its art is the old head, not rerun on the new one); production ready NO.
- Not checked by the reviewer: foot sliding, neck, lip sync, audio, any head turn.

**Remaining defects (honest):** wave arm in front of the hair with a visible shoulder-elbow chain; knees (a bend or a drawn knee
shape on straight tube legs), crossing legs in the passing pose, a settle at the stop; body motion while talking; mid-blink lids;
neck does not follow a turn; the turn test was not rerun on the round-3 head; a three-quarter part set; shadow gap in the walk
(the code check says float 1.3 px, so the shadow position, not the foot, is the first suspect); lip sync and audio by ear.
