# Spike: one continuous skinned mesh per character (D-093)

**Question.** Does one triangulated mesh per character, skinned to the existing bones, remove the seams and
detached-part defects of the rigid cut (D-090, D-092)?

**Date:** 2026-10-30. **Time:** about 1.5 h. **Code:** `studio_core/engines/blender/skin.py` (mesh, weights and a
distortion measure), a `build_skinned` branch in `blender/build_render.py` (used when the bake carries `ch["skin"]`),
`scripts/spikes/skinned_measure.py`. Nothing engine-specific entered the bake schema beyond the spike's optional `skin` key
(D-030); no production path changed. Contact sheets (outside the repo): `side-session-notes/.../skinned-kit-sheet.png`
and `skinned-mia-sheet.png`.

## What was built

The rest-pose parts are composited in draw order into one image (the "full character image"). A grid with 8 px cells,
clipped to the alpha silhouette plus one cell, is split into triangles (Kit 3116 vertices, 5818 triangles). Each
vertex is owned by the front-most part at that point. Near a joint it is blended with the neighbouring bone: a
smoothstep along the child bone (half-width 0.6 x the limb's mean width), limited to a band around the bone's axis, so
torso beside an arm is not dragged. Blender renders it with the same armature, the same bake, the same Workbench and
the same defect counter (magenta probe, `check_frame`) as the cut. The head sprite (it carries the per-frame face) stays a
rigid quad on top of the mesh's own head.

## Numbers (frames with a hole or seam)

| | Cut (bendable limbs, Workbench) | One skinned mesh |
|---|---|---|
| Kit, shot s03 (120 frames) | 48 (28 holes, 53 seams) | **15** (11 holes, 11 seams) |
| Mia, shot s04 (72 frames) | 42 (4 holes, 43 seams) | **32** (32 seams) |
| Render time per frame (960x540) | 0.024 s | 0.023 s |

Weight settings tried on Kit (blend, band): 0.6/1.0 gives 15, 0.4/0.6 gives 15, 0.25/0.5 gives 15, 1.2/2.0 gives 35.
The single-mesh count moved little; the smear below did not change with any of them.

## What the count does not show (looked at, one sheet per character plus three extra Kit sheets)

The hole/seam counter only sees magenta showing through. A single mesh has no gap to show: wherever a limb moves away
from the body, the triangles between them **stretch** instead, and the texture smears.

- **Kit waving (frame 60):** the raised arm is a streaked, plank-like fan of stretched sleeve and torso texture.
- **Kit jump (90 to 110):** the thighs crumple and fold over each other at the hips; the crossing arm smears.
- **Mia talking gesture (frames 20 to 35):** the gesturing arm drags a fan of smeared coat down the whole side.
- Walk: mild fringes at the knees and tail, far smaller than in the waving and jumping frames.

My own distortion measure (linear blend skinning in numpy, the share of rest area whose triangles stretch above 1.6x,
squash, or fold) flags 80 of 120 Kit frames and 37 of 72 Mia frames and folds in about 100 of 120 Kit frames. It is
not calibrated: it ranks the waving frame (the worst by eye) below the walk frames, because the smear is a small area.
Treat it as "folds exist", not as a score. The seam and hole counts fell mostly because stretched and folded triangles
fill the gaps, which is no better to look at than the gaps were.

## What worked, what did not

- **Worked:** no per-joint seams by construction; the legs standing, the idle and small motions look clean and
  seamless; cost is the same as the cut (0.023 s per frame), the build is about 120 lines, weights come from the part
  masks with no hand work.
- **Did not work:** any big limb motion (wave, gesture, jump, walking legs crossing). The mesh is one connected sheet, so a
  limb that leaves the body drags the texture of the hidden area under it (the torso under the sleeve is painted over in the
  composite) and the in-between triangles. Wider blending does not help: it spreads the smear (35 defect frames).
  Legs crossing fold the mesh in z-flat 2D, where a part cut would simply layer one over the other.

## Recommendation: drop

Do not adopt a single connected skin as the character representation. It trades seams for smear and folds on exactly the
motions that make animation lifelike. The two things it would still need (the hidden torso under each arm painted in, and
mesh islands cut apart at the limbs so triangles do not bridge them) turn it back into separate parts with overlaps,
which is what the cut already is. If the lifelike pass wants more, test instead: (a) parts cut as separate meshes with
the bendable-limb weights (what the engines already do) plus a generative fill of the hidden area under front parts,
and (b) a draw-order switch for crossing legs (the real fix for the crossing defect), neither of which this spike covers.
