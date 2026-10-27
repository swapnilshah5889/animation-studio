# Spike: a local vision model as the face and joint locator

**Question.** The cut finds face parts and limb joints with pixel rules (`clean_face` in
`puppet/build.py`, `fit.py`). They were tuned on organic characters and fail on Bolt (no eyes
found in the front view, limbs off their bones). Can `qwen3-vl:8b-instruct` (Ollama, Apache-2.0,
D-018) locate them instead, or at least seed the rules?

**Not integrated.** Script: `scripts/spikes/vision_locator.py` (re-run with
`cd studio_core && uv run --no-sync python ../scripts/spikes/vision_locator.py`, tables with
`--summarize`). Raw answers and annotated crops: `films/step4-cast/spikes/vision_locator/`
(git-ignored).

## Method

- 5 characters × 2 views (front = left half of the 1344x768 sheet, three-quarter = right half,
  from the klein redraw sheet the cut used) × 2 prompts × 2 runs = 40 calls. Temperature 0, think
  off, `format` = JSON schema with 16 required points (eyes, nose or beak tip, mouth, and
  shoulder, elbow, wrist, hip, knee, ankle on each side).
- Prompts: **plain**, and **som** (Set-of-Mark: the skeleton template's expected joints and
  eyes/nose drawn as 22-px numbered red dots, the model told they are likely off and asked for
  the real positions).
- Qwen3-VL answers on a **0..1000 grid** relative to the image, not in pixels. The prompt says so
  and the script converts.
- Ground truth, no hand labelling: the skeleton after the cut's own `fit_limbs` on its silhouette
  mask (joints), `report.json` `nose_px`, and `rig.json` face block (eyes, mouth; head-part
  pixels moved to the sheet by the head pivot = neck). Error = distance / head height (neck to
  head top, about 246 px).
- **Caveat on truth.** It is the cut's own result. It is sound for Kit, Bo, Pim, Mia (their cuts
  pass) and wrong for Bolt, so Bolt's numbers below measure disagreement with a wrong answer.
  Bolt was judged by eye from one image (front, plain prompt, predictions in red, the cut's
  points in green).

## Finding 1: it swaps left and right

The model read "left" as the image's left in 68 of 70 point pairs (plain) and 69 of 70 (som),
despite the "character's own left" instruction. Scored literally the errors are 0.5 to 1.3 head
heights. A real integration must not trust the labels: match each pair to the geometry (the
figure's mid-line), which is easy. All numbers below match each left/right pair to its nearest
truth (`side_agnostic` in the script).

## Results

Median error in head heights (points in brackets), passing cast (Kit, Bo, Pim, Mia):

| part | plain | som |
|---|---|---|
| eyes | 0.05 (16) | 0.15 (16) |
| nose or beak | 0.03 (6) | 0.05 (6) |
| mouth | 0.09 (8) | 0.09 (8) |
| shoulders | 0.15 | 0.10 |
| elbows | 0.15 | 0.12 |
| wrists | 0.13 | 0.12 |
| hips | 0.14 | 0.07 |
| knees | 0.12 | 0.07 |
| ankles | 0.15 | 0.09 |

(0.1 head heights is about 25 px on a 246 px head, and the cut's own limb radius is 20 to 26 px.)

| | plain | som |
|---|---|---|
| points asked | 160 | 160 |
| no answer | 0 | 0 |
| outside the figure (12 px tolerance) | 0 | 1 |
| within 0.15 head heights of truth | 63% | 81% |
| median seconds per image | 29.0 | 29.1 |
| peak Ollama resident memory | 7.9 GB | 8.0 GB |
| run 1 vs run 2 moved: median / max | 0.000 / 0.136 | 0.000 / 0.327 |

Time: model load 2 s once; 40 calls took 1121 s in all. Memory is the sum of RSS of all Ollama
processes sampled every 0.5 s (weights 6.2 GB plus the image and cache); GPU-side use was not
measured separately.

Plain is better for eyes (the dots pull the eyes toward the template, 0.15 vs 0.05); som is
better for every joint (about 0.07 to 0.12 vs 0.12 to 0.15). The two could be combined: plain
for the face, som for the limbs.

## Bolt (the case that matters)

Judged by eye on the front view, plain prompt: the eyes land inside the two yellow ovals (about
10 px, 0.04 head heights, from their centres), the mouth is on the smile, the wrists sit on the
hand ends, shoulders at the top of the arms, knees and ankles on the legs, with elbows and
knees pulled a little to the outside edge (about 20 px). The cut's own points were visibly wrong
(eyes at the skeleton's fallback spot on the forehead and nose line, elbows and wrists inside
the torso side). The model was right where the pixel rules were wrong. Because the numbers in
the tables for Bolt are measured against the wrong cut (eyes 0.10 / 0.08, joints 0.05 to 0.16),
they are not an accuracy figure; I did not hand-label Bolt, and the three-quarter view was not
inspected by eye. The Bolt nose has no truth (Bolt has no nose).

## Recommendation

- **Accurate enough?** For finding **where** things are, yes: roughly 0.1 head heights (25 px) in
  the median, no failed answers, right order of the body. It is not accurate enough to place
  pivots by itself: 19% of points (som) are further than 0.15 head heights off, and answers
  move up to 0.33 between runs on a hard point. For Bolt's eyes and limbs it found what the
  pixel rules missed.
- **Fits on this Mac?** Yes, as a separate stage: about 8 GB resident, 29 s per image
  (one call per view and prompt: about 1 minute for both views of one prompt, 2 minutes with
  both prompts), run once per cut, not per frame. It must run with ComfyUI and other Ollama
  models unloaded (the one-large-model rule); `unload` it before the next ComfyUI job.
- **Integration shape** (keep the pixel rules as the check):
  1. After the silhouette, ask the model (plain for face parts, som for joints); swap each pair
     by geometry; keep results in the build report.
  2. Use answers only as **seeds**: the existing rules run in a window around them (for the face,
     look for the dark or coloured blob near the model's eye; for limbs, start the fit at the
     model's shoulder, elbow and wrist), instead of the skeleton's template.
  3. Check: if a pixel rule finds a part within about 0.15 head heights of the seed, keep the
     pixel result (it is exact); if not, fall back to the seed, and flag it in the report. A seed
     outside the figure mask, or a part both methods place differently by more than 0.3 head
     heights, fails the build for a human look.
  4. Results are cached per character and view (deterministic at temperature 0 in 2 of 2 runs
     for the median point, so the cache is safe to reuse).
- **Next, before integrating:** hand-label Bolt (and one organic character) for a real error
  figure, test an image at 2x resolution for the joints, and test a pixel-coordinate variant
  against the 0..1000 grid.

## Not measured

GPU memory separately from RSS, the Windows node, temperature above 0, other models,
three-quarter accuracy for Bolt by eye, and error against hand-labelled truth.
