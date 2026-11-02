# Spike: Rowan front-only rig test (D-107, 2026-11-02)

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

The storybook limited-animation plan holds: drawing swaps plus rotations on painted layers read well when the
camera and acting stay gentle. A wave or any new pose costs one repainted drawing and its in-betweens. The open risks
for the 30 s film are a walk (shot 1 and shot 4) and the three-quarter views (the AI turnaround failed before).

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
