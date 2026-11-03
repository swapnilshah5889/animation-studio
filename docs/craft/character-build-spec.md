# Character build spec
> What a fully built 2D character contains, how it is packaged, and the checks that decide "fully built" (D-109, D-110).

**When to use:** before commissioning, generating or accepting any character, and before any rigging or animation.
A character is built once, then extended only when a story needs something new (an outfit, a held prop, an extra view).

**Why:** every 2D failure so far came from animating art that was never fully built. Rowan had one front painting, so
when the arm moved there was nothing drawn under the sleeve (D-107). Rain and KayKit were 3D (D-109).
A fully built character avoids that: every part is drawn complete, joints are planned, and every view matches.

## 1. Deliverables

Two tiers. **Slice minimum** is enough for the 30-second slice (walk, wave, two spoken lines). **Full** is the standing
target for any recurring character.

| Item | Slice minimum | Full |
|---|---|---|
| Views, each a complete part set (section 2) | front, three-quarter, side profile | adds back; the second three-quarter and side only if the design is asymmetric |
| Hands, per side and per view where visible (section 4) | rest, open-palm wave, fist | adds point, grip/hold, open back-of-hand, a counting/spread hand |
| Mouth set (section 5) | 9 shapes in front and three-quarter | all used views |
| Eyes and brows (section 5) | open, half, closed; brows neutral, raised, frown | adds a look-left/right pupil offset and squint |
| Expressions, built from face parts (section 5) | neutral, happy, surprised, worried | adds sad, angry (mild, kid-appropriate), thinking |
| Model sheet: one composite image of all views side by side on height lines | yes | yes |
| Pose-proof sheet (section 7) | yes | yes |
| `character.json` (section 6) | yes | yes |
| Palette file (named swatches with hex values) | yes | yes |

Mirroring: a left-facing view may be produced by flipping the right-facing one only if nothing on the design is
one-sided (a parting, a badge, a bag on one shoulder). If anything is, both sides are drawn.

## 2. Parts per view

Each part is its own layer, named exactly as below. L and R are the **character's own** left and right.

- **Head:** `head` (skull and face base without features), `hair_back` (behind the head), `hair_front`
  (fringe and side locks in front of the face), `ear_L`, `ear_R` (where visible), `nose`, and any hat or headband
  as its own part.
- **Face features:** `eye_L_white`, `eye_L_iris`, `eye_L_lid` (and the same for R), `brow_L`, `brow_R`, and the
  mouth set (section 5).
- **Body:** `neck`, `chest`, `hips` (chest and hips separate so the torso can bend or twist a little).
- **Arms, per side:** `arm_upper_L`, `arm_lower_L`, `hand_L_<pose>`, and the same for R.
- **Legs, per side:** `leg_upper_L`, `leg_lower_L`, `foot_L`, and the same for R.
- **Secondary parts** that should move on their own: each a part of its own (for example `scarf_end`,
  `backpack`, `cape`, `hair_tail`), so overlap and follow-through can be animated.

## 3. Rules every part must follow

1. **Drawn complete, including what is hidden.** Draw each part as if it were seen alone. Where another part covers
   it, keep painting underneath:
   - the upper arm continues under the sleeve and shoulder;
   - the chest is painted fully behind the arms;
   - the neck runs up under the head;
   - the thigh tops run under the hips or clothing.

   This is the single most important rule. It is what was missing for Rowan's arm.
2. **Round joints that overlap.** At each joint (neck, shoulder, elbow, wrist, hip, knee, ankle), both pieces end in
   the same circle centred on the pivot. The joint end overlaps the next part by at least 15% of the part's length,
   so a bend of up to about 120 degrees shows no gap or notch. Clothing that crosses a joint (a sleeve cuff, a hem)
   belongs to one part only.
3. **Pivots marked:** one point per part at its joint centre (section 6).
4. **Same canvas, registered:** every part of a view is on one shared canvas, in its rest position. Stacking all the
   layers in draw order reproduces the model-sheet view exactly.
5. **Clean edges:** transparent background, straight (non-premultiplied) alpha, and no colour halo, stray pixels,
   cast shadows or background colour baked into any part.
6. **Lighting baked the same way everywhere:** if cel shadow shapes are painted in, the light comes from the same
   direction (upper left by default) on every part and every view. No shadow from one part is painted onto another,
   because it would be wrong as soon as the parts move.
7. **Consistent across views:** identical palette (from the palette file), line weight, proportions on height lines
   (head, shoulder, waist, knee, sole) and design details (clothing, hair shape, accessories).
8. **Resolution:** the full character is at least 2000 px tall in every view (at least 3000 px is better, for close-ups
   and 4K later). Hands and the mouth set are drawn at the same scale as the body, not separately resized.
9. **Age-appropriate design.** No real studio's or living artist's name or recognisable style in any prompt or brief.

## 4. Hands

Hands carry most of the acting, so they get their own set. Each hand is a single part with the wrist circle at the
same pivot, so they can be swapped at any frame. Open hands show a clear palm, thumb and finger silhouette at
full-figure size, never a nub or a mitten that reads as a fist (the KayKit finding). Fingers may be simplified (three
fingers and a thumb is fine) if the whole cast uses the same convention.

## 5. Face sets

- **Mouths:** the nine lip-sync shapes our pipeline uses (Rhubarb A-H and X; see `lip-sync.md`):
  - X rest;
  - A closed for M, B, P;
  - B slightly open with teeth;
  - C open, for E;
  - D wide open, for A;
  - E rounded, for O;
  - F puckered, for OO and W;
  - G teeth on lip, for F and V;
  - H tongue up, for L.

  Every shape shares one anchor point and fits inside the same face area.
- **Eyes:** separate white, iris/pupil and lid layers, so pupils can move and lids can blink. Every eye shape stays
  inside the face, with two level eyes about one eye-width apart (`visual-review.md`).
- **Expressions** are combinations of brow, eye and mouth parts, listed by name in `character.json` (section 6).
  Draw extra parts only where a combination cannot carry the feeling. See `expressions.md`.

## 6. Packaging (engine-neutral)

```
<character>/
  character.json
  palette.json
  model_sheet.png
  pose_proof.png
  provenance.md
  views/<view>/<part>.png                    one transparent PNG per part, full view canvas, rest position
  views/<view>/hands/hand_L_<pose>.png
  views/<view>/mouth/mouth_<A..H|X>.png
  views/<view>/eyes/..., brows/...
  source/                                    the original layered file (.kra, .psd, .ora or .svg), kept as-is
```

The `views/<view>/` names are `front`, `three_quarter_L`, `three_quarter_R`, `side_L`, `side_R` and `back`.
(`three_quarter_L` means the character turns toward its left.)

`character.json` holds:
- `name`, `height_px`, `views`, and `light_direction`;
- for each view: `parts` with `file`, `pivot_px` [x, y] and `parent`; the `draw_order` from back to front; and
  `swap_sets` for hands, mouths and eyes;
- `expressions`, a map from name to the face parts used.

Parents form the hierarchy, for example hips, then chest, then neck, then head, and chest, then upper arm, then lower
arm, then hand.

A layered source file alone is acceptable at handover only if its layer names and a pivot layer (one dot per part)
follow this spec. The export to the layout above is then done in code.

`provenance.md` records:
- who or what made it (artist name or credit; or the AI model, its license and seeds);
- the tools used;
- that commercial use is permitted.

Record anything AI-made in `docs/MODELS.md` style.

## 7. Acceptance: when is a character "fully built"?

All four gates, in order:

1. **Package check (code).** Every required file and layer is present and correctly named. Canvases match within a
   view. Each part has a pivot inside or on its joint circle. Alpha is clean (no semi-transparent halo wider than
   2 px). The palette matches across views. Stacking the layers in draw order equals `model_sheet.png` for that view.
2. **Underlay check (code plus a look).** At each joint, the child part is opaque over the whole joint circle, and
   the covered region of the parent has paint, not a hole. Rotate each child to its joint limits and render: there
   must be no transparent gap, notch or uncovered area.
3. **Pose proof (stills, independent review).** For each view, assemble and render a rest pose, arm raised about
   150 degrees with the elbow bent, the walk contact and passing poses, a head tilt, the open-palm wave and two
   expressions. A different agent reviews them with `skills/animation-review` and `visual-review.md`, against the
   model sheet. A pass means no blocker and no major: limbs attached, bends that look like bends, hands that read,
   faces on-model, and every view the same character.
4. **Owner approval** of the model sheet and the pose-proof sheet.

Only after all four gates may rigging for motion or animation begin (D-109). Any later addition (new hand, outfit or
view) goes through gates 1 to 3 for the new parts.

## What fails and why

| Failure | Why | This spec's guard |
|---|---|---|
| Rowan's arm showed a black patch, then a green one, and an unreadable hand | there was no hidden art under the sleeve; parts were cut from one painting | rules 1 and 2, gate 2 |
| The turnaround changed Rowan's cap and garment | views were generated separately with no shared sheet | rule 7, gates 3 and 4 |
| KayKit's fist read as fist-shaking | there was no open-hand drawing | section 4 |
| Mia and Kenney were rejected on looks | parts were correct but the design was plain | owner approval of the design before building |
