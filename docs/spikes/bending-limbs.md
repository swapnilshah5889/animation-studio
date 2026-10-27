# Spike: bending limbs (4B.4)

**Question.** Can a limb bend instead of showing two rigid rectangles, using the Synfig backend, and at what cost?

**Script:** `scripts/spikes/bend_limb.py` (`uv run --project studio_core python scripts/spikes/bend_limb.py`).
It uses the `studio_core.sif` builder read-only and renders Pip's elbow (+70° relative bend, upper arm swung 20°)
and knee (−70°, thigh swung 25°) three ways, at 1920×1080, with the Synfig 1.5.5 CLI.
Outputs (git-ignored): `renders/spikes/bending-limbs/contact-sheet.png`, `results.json`, `work/*/scene.sif`.

Test art is Pip's fixture parts (`tests/fixtures/characters/pip`), pasted into one straight limb image
(upper part over lower part at the rig's joint). Kit's parts were not tried. Pip's art is plain capsules with a
dark outline, so a seam arc shows where the two parts overlap in the "one image". A real cut of a real drawing
would not have that seam (see risks).

## The three approaches

| | Approach | What it is |
|---|---|---|
| **B** | baseline: two parts + cap | two bone-linked groups; the child part carries a disc of the figure's own pixels around the joint (what `add_caps` does today) |
| **A** | Skeleton Deformation | ONE limb PNG, a `skeleton_deformation` layer under the same group, a static *rest* chain and the rig's *pose* chain, paired |
| **C** | overlap + alpha ramp | two parts; the child extends 26–30 px above the joint (under the parent), the parent's alpha ramps linearly from 1 to 0 across ±20–24 px of the joint (0.75 × limb half-width) |

## Results (all measured; one limb per frame, 1080p, M4, Synfig CPU)

| | B baseline | A deformation | C overlap |
|---|---|---|---|
| CLI renders it? | yes | **yes**, no warnings | yes |
| Render, elbow bent (median of 3, whole process) | 0.361 s | 0.381 s | 0.374 s |
| Render, knee bent | 0.371 s | 0.392 s | 0.374 s |
| Cost over an empty 1080p canvas (0.352 s) | +0.01 / +0.02 s | **+0.03 / +0.04 s** | +0.02 s |
| `.sif` size, one limb | 6.4 KB, 153 elements | 6.7 KB, 156 elements | 6.4 KB, 153 elements |
| Layers / bones for one limb | 2 groups + 2 images / 2 | 1 group + 1 image + 1 deform / **4** (2 rest + 2 pose) | 2 groups + 2 images / 2 |
| PNGs per limb | 2 | **1** | 2 |
| Silhouette area bent / straight (elbow, knee) | 1.00, 1.01 | **0.96, 0.97** | 1.04, 1.07 |
| Rest pose vs B rest, max pixel diff | n/a | 107/255 (edge pixels) | 46/255 |

Fixed cost of one `synfig` process is ~0.35 s, so the per-frame deltas matter only relative to each other. A character has up to
four limbs, so A is roughly +0.1–0.16 s per frame (extrapolated from one limb, **not measured on a whole character**).
Shot renders are one process for all frames, so the real ratio should be smaller; measure it in the first integration step.

Grid density (`x/y_subdivisions`, elbow, bent): 12×48 = 0.380 s but the silhouette shrinks to 61 177 px (holes);
24×96 = 0.381 s, 72 959 px; 48×192 = 0.391 s, 73 706 px. Time barely moves, so use 48×192 (or finer in y).

Extra checks: A inside a scaled (0.6) and moved parent group renders to 0.974× the silhouette area of B in the same group
(so it follows the placement transform; I compared areas, I did not look at that image).

## What the contact sheet shows

`renders/spikes/bending-limbs/contact-sheet.png`, rows elbow +70° and knee −70°, columns B, A, C:

- **B**: two clean rigid shapes; the cap makes the outer corner round, but the inside of the bend is a straight
  overlap and the cap's cut edge is jagged. This is "rectangular", just tidier.
- **A**: the only one where the shape really *bends*: the outer edge curves, the width tapers through the joint. Artifacts:
  a pinched notch on the inner side of the bend (elbow), a background-coloured hole/crease at the inner knee, a
  slightly narrower limb there (area 0.96–0.97), and the seam arc of the straight composite sheared along. Edges are slightly soft/speckled
  (the image is resampled through a grid).
- **C**: no hole, but ghosted outline arcs where the fading part overlaps the extension, and a hard square corner
  of the extension poking out at the outer bend (elbow bottom-left, knee right). The corner is because the extension is a
  rectangle; a disc-shaped extension should remove it (not tried). Still two rigid pieces; only the joint is softened.

## A: what it needs (verified)

`synfig --layer-info=skeleton_deformation` lists: `bones` (list of pairs: rest bone, pose bone), `point1`/`point2`
(grid bounds), `x_subdivisions`/`y_subdivisions`, plus the usual amount and blend method. The format is in
`tests/fixtures/sif_examples/deform_limb.sif` (already tested); the script generates the same thing with the builder:

- A **static rest chain** in `<bones>` (angles of the rest pose) and the **pose chain** (the rig's animated bones), each pair in
  `static_list type="pair_bone_object_bone_object"`. The pose chain parents to the real skeleton, the rest chain to `bone_root`.
- **Rest bones need `width` and `tipwidth`**: that is the influence radius; pixels outside every rest bone's capsule disappear.
  I used 1.1 × the limb half-width. `Bone.to_xml` writes neither today.
- The deformation layer sits **in the same group, after the image in the file (above it)**, and warps everything below it in that canvas.
  Grid bounds are in the group's local units and must cover the whole image plus the bent range.
- A new layer class (`SkeletonDeformation`) and a rest-bone width. In this spike that was ~45 lines on top of `studio_core.sif`.

## What changes in the project (not edited)

- **`puppet/build.py`** today cuts one part per bone (`assign_parts`, `add_caps`, `_cut_view`). A deformable limb needs a
  `limb` image covering the upper and lower bone's pixels as one continuous drawing (the figure mask over both bones, no caps),
  with the hidden part behind a bent joint inpainted (`complete_hidden`/`paint_from` already exist). Caps become unnecessary for those
  limbs. Draw-order among limbs and torso is unchanged.
- **`schemas/rig.schema.json`**: `part` needs to carry a chain (e.g. `bones: [upper, lower]` instead of one `bone`, with `pivot_px` for the first
  bone and the joint positions in the image), or a new `limb` object (`file`, `size_px`, `bones: [..]`, `joint_px`). It stays engine-neutral (D-030):
  "this image is deformed by these bones" is a rig fact; rest/pose chains, widths and grids are Synfig details and
  belong in `studio_core/engines/synfig/`.
- **Synfig backend**: for each such limb emit the rest chain, the deformation layer and one image (bone widths from the part width).
  Other engines (OpenToonz plastic tool) have an equivalent mesh deformer, so the schema fact translates.
- **Motion/limits** are unchanged (the pose chain is the same bones).

## Recommendation

**Adopt A (Skeleton Deformation) for arms and legs, behind a per-limb switch, keeping B as the fallback.**
It is the only approach that actually bends, it costs ~0.03–0.04 s per limb at 1080p on this machine, and the XML is only ~5% bigger.
C is cheap and keeps the two-part cut, but it is still rigid pieces with ghosting and corners, so it is the wrong direction for the
"rectangular" complaint.

**Risks of A**
1. Inner-bend pinch and crease at 70°: needs tuning (bone width, overlap of rest capsules, a joint inpaint). I did not eliminate them.
2. Area loss (3–4%) and soft edges from the grid resample; coarse grids lose pixels (see grid test). Use a fine grid.
3. The cut must produce one clean, continuous limb with the hidden region painted. On real redraws (Kit, Mia) that is the hard part;
   I did not test it. A seam between sleeve and forearm will be sheared too.
4. 2 extra rest bones per limb, a pairing that must stay in sync with the pose chain, and the layer deforms only things in its own
   group: hands/shoes that are separate parts must still be linked to the pose bones.
5. Only a still pose per limb was rendered here; the animated case is covered by `deform_limb.sif`, not by this spike.
   Cost on a full character and a full shot is extrapolated, not measured.

## Smallest first integration step

1. In `studio_core/sif`: add `width`/`tipwidth` to `Bone` and a `SkeletonDeformation` layer (as in the script), with a unit test that renders a
   straight and a bent limb and checks the elbow tip against forward kinematics (like `test_sif_examples.py`).
2. Hand-make ONE limb image for Pip's left arm (`upper_arm_l` + `forearm_l` as one PNG) and switch only that arm in a `build_rig` output to A, behind a
   rig flag; render the wave (4B.4) and look at the elbow at its extreme pose and at 8 s of motion.
3. Only if that looks good, change the cut (`build.py`) and the rig schema to emit limb images.
