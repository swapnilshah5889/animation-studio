# Cutting a generated picture into a puppet (task 4.4)

How `studio_core/puppet/build.py` turns a generated character sheet into the parts of a
cut-out puppet, and the image-processing ideas it uses. Decisions: D-048, D-050.

## Why it's mostly geometry
The picture was generated *on* a skeleton we drew (`skeleton.py`, ControlNet). So we already
know where every joint is. We never ask a model where the elbow is. We decide, for every
pixel, which bone carries it.

## Ideas worth knowing

- **Colour key + segmentation model.**
  - A colour key ("anything far from the background colour is figure") is exact on clean
    outlines but loses pale clothes that touch a pale background.
  - SAM 2.1 segments by shape from a box and a few points, but trims fine fur.
  - The union gets both. When the two disagree a lot, the model's prompt went wrong:
    measure the agreement (IoU) and fall back.
- **Hole filling.** Regions of "background" that the border can't reach are inside the
  figure: a white shirt within an outline, or the eyes inside a head. Flood the background
  from the border; whatever stays unreached is figure.
- **Corridors.** For each limb, every pixel gets a position along the bone (t, 0 at the
  joint, 1 at the next) and a distance from it (d). A limb owns pixels with 0 ≤ t ≤ 1 and
  |d| below about 1.4 limb radii; the nearest bone wins. The radius is measured on the
  picture: cross-sections from the bone line outward to the first background pixel. Use
  the lower quartile, since a scarf behind an arm only ever makes cross-sections *wider*.
- **Colour consistency.** A corridor can sweep in something else (a scarf end, a tail).
  Sample the limb's own colours from its core, and refuse corridor pixels that match none
  of them.
- **Diffusion inpainting** (`paint_from`). To paint over a mark, repeatedly give each
  unknown pixel next to known ones the average of its known neighbours, one ring per step.
  It's crude next to learned inpainting, but right for flat cartoon colours, and it needs
  no model and no license.
- **Local contrast.** "Dark" is relative. A brow stroke on a cream muzzle is lighter than the
  orange fur's shadows. Compare each pixel with a blurred copy of its surroundings.
- **Joint caps.** When a forearm turns at the elbow, the corner of its straight cut edge
  swings out and leaves a gap. Give the part drawn *behind* a disc over the joint, painted in
  its own colours. It is invisible at rest and fills the gap in motion.
- **Alpha unmixing.** An antialiased outline pixel is a blend: c = a·figure + (1 − a)·bg.
  Estimate a from the distance to the background colour, then solve for the figure colour.
  Without this, a cut-out keeps a light halo of its old background.
- **Rest pose vs generation pose.** Generate with arms out, so they can be cut cleanly, but
  rig with arms hanging, so motions tuned on one rest work on all. Turning the parts about
  their joints changes the rest without touching the rig format.

## Gotchas we hit
- A "faceless" head never came out of SDXL. Painting the face out afterwards was easier
  than fighting the prompt (D-049).
- Every cap on a *front* part changed the rest look. Caps go on the back part only.
- One limb's hole filling took another limb's pixels. Track which pixels are already
  claimed, and test that every figure pixel belongs to exactly one part.
- A wave tuned on a small-headed puppet hides behind a fox's ears. Motions that move a hand
  near the head should check the rig's geometry (`_clear_raise`).
