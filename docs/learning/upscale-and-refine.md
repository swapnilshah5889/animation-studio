# Big backgrounds on a small budget: draft, upscale, refine (task 4.6)

A background plate is 2880×1080: the 1920×1080 frame plus room for the camera to pan.
SDXL can't draw that well directly.

## Why not generate at 2880×1080?
SDXL was trained on about 1 megapixel, in a set of aspect-ratio "buckets". Far from them it
repeats things: two suns, a forest that tiles. So the composition is made at **1536×576**,
an 8:3 bucket, and enlarged afterwards.

## Upscaling with a GAN (Real-ESRGAN)
Real-ESRGAN is a small network (BSD-3) trained to invent plausible detail when enlarging,
here 4× (1536×576 → 6144×2304), then scaled down to the plate size. The `anime_6B` variant is
tuned for flat colours and clean lines, which suits picture-book art. It is fast because it
works in tiles. Watch for seams in very flat areas.

## The low-denoise refine (img2img)
An upscaled image is sharp but soft-detailed: no new brush strokes, just bigger ones. So the
plate goes back through SDXL as **img2img**:
- encode it to a latent
- add only a little noise (`denoise` 0.3: 30% of the way back toward pure noise)
- denoise it with the same style and prompt

Low noise means SDXL can redraw texture and edges at the new size, but can't move the
mountains. Higher values (above about 0.45) start to change the composition.

## Gotchas
- **Steps:** ComfyUI runs every step at any denoise. 10 steps are plenty for a light refine
  and keep a ~3 MP pass on an M4 to a few minutes. The style's own 25 steps would take far
  longer.
- **Draft many, finish one:** the finish is the slow part, so only the chosen draft gets it.
- **Kid-safe negatives** are in both passes, because SDXL here runs at CFG > 1.

## Checking the ground without a model
Characters stand along the bottom of the frame, so that strip must be open ground. Two
cheap measures catch most problems:
- **Edges:** soft SDXL painting has gentle gradients, and outlined flowers or rocks create
  strong ones. Use a low threshold (20 on 0–255 luma), measured after a small blur.
- **Odd colours:** the share of the strip far from its own main colours. A pond that fills
  the whole strip *is* the main colour, so this can't see it. That needs a vision check.
