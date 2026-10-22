# ControlNet conditioning (Step 4)

## What it is
A diffusion model like SDXL turns noise into an image, guided by the prompt. A **ControlNet**
is a second network, trained alongside a frozen copy of the model's encoder. It reads an
extra *condition image* (a pose skeleton, a depth map, edges) and adds its features into the
model at every denoising step. The prompt decides *what* to draw; the condition decides
*where*.

We use one **union** ControlNet (xinsir union ProMax, Apache-2.0) that understands many
condition types. `SetUnionControlNetType` tells it which one an image is ("openpose", "depth",
"repaint", ...). A union model saves memory: one 2.5 GB file covers every condition we need,
and two conditions can share a single loaded copy.

## The three knobs
- **strength:** how loudly the condition speaks. At 1.0 the pose is followed closely. At 0.4
  it is a suggestion the prompt can override.
- **start / end** (fractions of the steps): when it speaks. Early steps settle composition
  and silhouette; late steps settle details and texture. A condition that ends at 0.5 shapes
  the body, then lets the style paint it freely.
- **Several conditions** are applied in a chain. Each adds its pull to the same steps.

## How we use it (task 4.3)
Generated characters must become cut-out puppets, so their joints must be where the rig
says. Instead of estimating a pose *from* an image (OpenPose models are non-commercial), we
**draw the condition in code** from the same numbers as the rig (`puppet/skeleton.py`):

1. `pose_image`: an OpenPose stick figure at strength 1.0 for all steps (*where the joints
   are*).
2. `mannequin_image`: a grey body on black, read as depth, at strength 0.4 for the first half
   of the steps (*where the body isn't*). It keeps the arms off the torso.

## Gotchas we hit
- **OpenPose alone isn't a silhouette.** It only places joints, and SDXL happily rests the arms
  against a wide body (or hides them under a tail) while the joints still land "on" the
  figure.
- **Too much shape control flattens the style.** At strength 0.6 the mannequin turned a fox
  into a white wooden doll and ignored the three-quarter turn.
- **Negative prompts need CFG > 1.** Few-step "Lightning" sampling runs at CFG 1, where the
  negative prompt is ignored entirely. "No text, no leaves, plain background" stopped working
  in fast mode.
- **Prompts can't remove what the training data always has.** Cartoon characters always have
  faces, and heavy weighting (`(eyes:1.5)`) disturbed other parts of the image instead. Fix
  such things in code after generation.
- **Check with pixels, not hopes.** Cheap geometry checks (silhouette, joints on figure, gap
  between arm and hip) caught every pose failure we saw by eye. They needed hole filling,
  because a white shirt inside a dark outline looks like background to a colour key.
