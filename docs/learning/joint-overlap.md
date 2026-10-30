# Joint overlap: drawing what the sheet never showed

**What it is.** A cut-out puppet is made of rigid pieces. Where a thigh passes behind the coat or an arm lies
over the body, the character sheet shows only the front piece, so the piece *behind* was never drawn there. The
cut stops it at the edge of what was visible. Move the joint and the hidden edge slides out from under its
neighbour: a hole, or a hairline of background. Animators (and Spine/Moho riggers) fix this by painting the
hidden part by hand, so each piece reaches well under the next one. We do the same in code:
`studio_core/puppet/overlap.py`.

**The idea, in one rule.** A part may only grow into pixels that a part *in front of it* already covers, near
its joints, and the new pixels are painted from the part's own colours. Because they are under something
opaque, the picture at rest does not change; bending the joint is what reveals them.

**Why the rule is this shape.**
- *Only under opaque pixels.* The figure's outer edge is antialiased (partly transparent). Growth under that
  ring would show at rest as a fringe, so the cover is "mask AND alpha is 1", eroded by 2 px.
- *Near the joint, scaled with the limb.* A reach of 1.35 limb radii. Measured on Kit: 3x that made the
  sweep far worse (106 defect frames against 39), because pixels painted by diffusion far from the joint are
  smears that show up as soon as the part turns.
- *In the rest frame, not the sheet's.* The sheet draws arms in an A-pose; `hang_arms` turns the art after the
  cut so they rest hanging. What hides what has to be judged in the hanging pose, or the growth lands where
  nothing hides it. This was found the hard way: the first version changed the rest picture by 0.8 to 3.4 % of
  its pixels.
- *Notches are different.* A bite in an outline that other parts surround (Kit's tail, cut through by a leg
  in the sheet) is closed with a morphological closing, because it is visible when the leg moves.

**Gotchas.**
- `_cut_view` imports `overlap` lazily (it needs helpers from `build`, circular otherwise). A long rebuild
  therefore picks up whatever `overlap.py` is on disk when it first reaches that call: do not edit or
  mutation-test the module while a rebuild or sweep is running (we polluted one sweep that way).
- A rest-pose pixel diff between two builds of the same part is noisy at 1 px (the crop origin moves, pivots are
  rounded to 0.1); judge "thick blobs where the visible owner changes", not raw pixel counts.
- The pose-sweep checker counts a thin gap between two limbs (legs crossing in a jump, a hand beside a thigh)
  as a seam. That is the pose, not a cut defect, and no overlap can fix it. See `docs/spikes/joint-overlap.md`.
