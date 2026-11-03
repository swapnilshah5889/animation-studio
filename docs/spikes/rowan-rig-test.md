# Spike: Rowan front-only rig test (D-107, 2026-11-02)

## Follow-up: single generated arm-art candidate rejected (2026-11-03)

After the owner approved one scratch-only art candidate, one local ComfyUI generation ran (SDXL Base +
StorybookRedmondV2, seed 9401, batch 1, 295 s; no retries or seed search). Output and provenance are under
`~/ai-studio/scratch/rowan-arm-art-v1/`. No canonical image, rig, or repository code was changed.

The independent reviewer returned **FAIL for integration** after reviewing two stills. At full-character scale the
left arm reads as a hanging olive garment panel, not a limb. No cuff, wrist, palm, or thumb makes the open hand
recognizable. The sleeve color is off-model relative to Rowan's mint shirt, and a detached rust sliver sits beside it.
Face, cap, collar, opposite arm and foliage remain consistent. Layer separation, hidden pixels, rigging and motion were
not assessed. This candidate is rejected; do not integrate it or generate another without a new owner decision.

**Question:** can Rowan's approved painted watercolour art (D-106) move well as a 2.5D cut-out rig in Blender,
before we spend more on turnaround views?

**Initial answer: yes, after review round 3. Current answer: not yet.** The independent reviewer passed round 3 with three
minors, but a focused orchestrator review found a major snap in the arm raise. The no-major feasibility gate is not met
until that motion is corrected and reviewed again. The artwork remains on-model and the camera/head motion work, but this
is not production-ready.

## What was built

All of it is local, with the canonical's own model and style (SDXL Base 1.0 + StorybookRedmondV2, D-106) and no
downloads. Generated media lives in `~/ai-studio/scratch/rowan-rig-test/`, outside the repo.

| Layer | How it was made |
|---|---|
| Figure cut | SAM 2.1 (ComfyUI) with points on the canonical; specks dropped with `puppet/segment.clean` |
| Plate (1824x1024) | A new painted forest clearing in the canonical's airy palette, made from scratch. Outpainting around a kept canonical patch showed a visible box, so it was dropped |
| Closed eyes, mouths A / O / smile | A detailer-style inpaint: the face crop is enlarged 4x, repainted at full denoise, shrunk and pasted back, then cut as feathered patches |
| Wave drawing | The far arm repainted raised, best of two seeds by eye, then the arm cut with SAM as its own part |
| Rig | Blender 5.2.3 headless, unlit (emission) image planes in depth. The body is one drawing (rest or wave) with breathing about the waist; the head pivots at the neck; patches swap on visibility keys; the arm turns about the shoulder |

Scripts: `scripts/spikes/rowan_rig_test.py` (`gen` jobs, then `layers`) and `scripts/spikes/rowan_rig_blend.py`
(builds and renders 144 frames at 1080p in about 90 s; `--check` prints bounds, `--range a b` renders a few frames).

## Review rounds (independent)

1. **NEEDS WORK** with three majors:
   - the mouths did not read;
   - the wave popped in fully raised;
   - the cap touched the top edge at the end.

   The verdict on the question was "yes, with fixes".
2. **FAIL**, with one blocker: a flat black "O" on the mouth for two frames at 4.75 s. The round-1 majors were fixed.
3. **PASS.** Minors left:
   - the talking shapes are small and faint at film scale;
   - the first wave in-between throws the arm far out in one frame, and the sleeve looks puffy at the horizontal;
   - the face stays worried while waving.

## Gotchas found (worth keeping)

- **Blender `matrix_world` is stale after setting `location`** until `view_layer.update()`. Parenting with a stale
  matrix shifted every layer by its pivot, and only the boots showed in frame.
- **A hidden parent does not hide its children at render time.** Every child of a swapped drawing needs the same
  visibility keys.
- **EEVEE "Blended" transparency sorts by object origin, not by pixel depth.** Overlay patches whose origin sat
  farther away than the head's were drawn under it, so blinks and mouths never showed. Use "Dithered" (depth-tested).
- **Coplanar dithered overlays fight for depth**, which gave the black mouth. Give every overlay its own depth.
- **Low-denoise inpaint (0.7 to 0.85) barely changes a small mouth.** Repaint an enlarged crop at full denoise
  instead. "Tongue visible" in a prompt gives a tongue sticking out; "open smile" read as a gasp.

## What this means for the slice

The storybook limited-animation plan still looks promising for gentle camera and acting, but this test changed the arm
lesson: use one neutral, on-model arm drawing that rotates continuously; a pose-specific repaint used as the rest pose
creates a persistent art mismatch. The open risks for the 30 s film are a walk (shot 1 and shot 4) and the three-quarter
views (the AI turnaround failed before).

## Orchestrator visual review (2026-11-02; focused follow-up supersedes gate verdict)

I inspected the final `clip.mp4` using `skills/animation-review/`: a 12-frame sheet, motion data, and three crops (face,
wave, mouth). On the first pass, I recorded **PASS for the narrow feasibility question**, not production readiness.
Rowan stays recognizable; the painted plate is visually compatible; the head/face remain together; framing holds; and
the camera push is smooth. The full-frame difference statistic was median 2.015, maximum 3.94, with no 5x-median spikes.

### Focused wave-sequence follow-up

After the owner questioned the arm raise, I generated a 12-frame sheet of 1.3–1.9 s and re-read the arm keys in
`scripts/spikes/rowan_rig_blend.py`. Revised verdict: **NEEDS WORK for the motion-foundation gate**. The arm is down at
1.48 s; the replacement body/arm drawing appears at 1.52 s with the arm nearly horizontal; by 1.62 s the arm is near
vertical. The hard visibility swap combined with rapid rotations reads as a snap, a major motion defect. The global
frame-change statistic missed it because the arm occupies a small share of the frame. Sequence evidence is in
`~/ai-studio/scratch/rowan-rig-test/wave-sequence-review/`.

Focused review file: `~/ai-studio/scratch/rowan-rig-test/wave-sequence-review/review.md`.

I retain the independent review's other three findings: the in-between sleeve is puffy and hand small, the face stays
worried while waving, and the talking mouth is faint at full-frame scale. The prototype still demonstrates consistent
appearance and a smooth camera, but not a walk, turn, three-quarter view, audio, or complete rig. Breathing and sway were
not inspected in motion. The clip should not be presented as having cleared the D-107 no-major gate until the arm raise
is corrected and independently reviewed; no fix has been started.

## Arm-raise fix (2026-11-02, after the focused review)

Owner approved the fix. Two attempts, each reviewed by a fresh independent reviewer frame by frame on a cropped interval
(`skills/animation-review/README.md` now asks for this at every drawing swap or fast limb move):

1. **Cross-fade:** the rest body faded out while the raised arm rose from behind the body over 0.5 s. **NEEDS WORK.**
   The rise was smooth and the snap was fixed, but the cross-fade read as a dissolve. The sleeve went see-through, the
   arm was missing for 2 to 4 frames, and on the way down it reappeared from nothing. Lesson: **never swap or fade
   between two drawings of a moving limb; use one part that only rotates.**
2. **One rotating arm part:** the raised-arm drawing hangs at the side as the rest pose and rotates continuously, with no
   swap at all. **NEEDS WORK, one major.** The motion is fixed (steps of about 25 degrees, no pop, no spike), but the
   arm drawing is off-model at rest. It has a puffy faceted shoulder cap about 1.5 times the other sleeve's width and a
   washed-out forearm with a band at the elbow. It was repainted for the raised pose only and now shows for all 6 s.

**Where it stands:** the motion method is proven (continuous rotation of painted parts, no pops). The no-major gate is
still not met, and the blocker is now art: the rig needs a **rig-ready part set**, each limb drawn once in a neutral pose
with its hand and matching the canonical (slim sleeve, an elbow, an open hand), not repainted per pose. That is an art
task for the owner to decide on. Stopped here, without more polishing rounds.

### Orchestrator and independent shoulder-sequence re-review (2026-11-02)

I inspected the current clip with a cropped 12-frame shoulder sequence from 1.3–3.3 s, the rest/raised crops, and the
canonical reference, under `~/ai-studio/scratch/rowan-rig-test/review-current/`. A fresh Independent Animation Reviewer
also checked the sequence sheet against the canonical. Both confirm the arm remains visible and moves continuously, with
no swap or snap. Both find **one major**: the sleeve projects as a detached-looking puffy block at the shoulder and its
contour changes awkwardly as it lifts/lowers; the pale narrow forearm reads as a separate strip. At rest, the shoulder
is about 1.5x the opposite sleeve's width. Final verdict remains **NEEDS WORK**; the issue is shoulder/arm anatomy and
model matching. The independent reviewer saw no second major in the sampled sheet, but did not review playback or
full-resolution crops. No code or art changes were made. The blocker and path forward are recorded in `PROGRESS.md` and
`HANDOFF.md`.

## Rowan arm replacement and five-pose gate (2026-11-03)

The approved canonical's far arm is partly hidden by the vest and backpack; the visible sleeve alone is not a complete
moving limb. One bounded replacement attempt used a local inpaint (arm seed 9201), a SAM mask, and one torso-restoration
inpaint (seed 9301), then split the arm into overlapping upper-arm, forearm, and hand planes. Generated media stayed
outside the repository.

The first five-pose render showed a solid black upper arm. A separate read-only code diagnosis found a Blender depth
bug: `plane()` baked depth into mesh coordinates and then assigned the same depth to the pivoted object's location,
placing the upper arm coplanar with its shoulder occluder. A paired depth correction removed that artifact in the rerender.

The depth-corrected stills were independently reviewed with the repository visual rubric. Verdict: **NEEDS WORK**.
Two majors remain: the hand is a thin pink streak/spike with no readable palm, and the arm lift reveals a vivid lime-green
patch between the vest and backpack. At rest, the hand/cuff blends into the pack. The canonical face and costume remain
recognizable. Motion between poses, timing, audio, and a full clip were not reviewed. The pose gate is not met; do not
render a clip from these layers.

Evidence: `~/ai-studio/scratch/rowan-arm-candidate-v3/render/poses/` and the independent report at
`~/ai-studio/scratch/rowan-arm-candidate-v3/render/review.md`. The depth correction is a verified narrow technical fix,
but the broader candidate code remains uncommitted because the art gate fails. Further pivot or mask tweaks will not
solve the missing hand silhouette or hidden garment art; resume at the rig-ready-art gate, not with animation polish.
