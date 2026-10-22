# Promptable segmentation with SAM 2.1 (Step 4)

## What it is
**Segmentation** answers "which pixels belong to this object?" with a mask. **SAM** (Segment
Anything, Meta, Apache-2.0) is a *promptable* segmenter: it was not trained on fixed classes
like "person" or "cat". You tell it which object you mean, and it returns that object's mask.

It works in two stages:

1. An **image encoder** (a Hiera vision transformer) turns the picture, resized so its long
   side is 1024 px, into an embedding. This is the expensive part, done once per image.
2. A small **mask decoder** combines that embedding with the **prompts** and predicts masks.
   It is cheap, so many prompts per image are fine.

SAM 2 adds video tracking. We only use single images. Sizes are tiny, small, base+ and large;
we use **2.1 base+** (323 MB, fp32).

## Prompts
- **Positive points** (label 1): "this pixel is on the object".
- **Negative points** (label 0): "this pixel is not".
- **A box** (x0, y0, x1, y1): "the object fits in here". This is the strongest single
  prompt.
- **A rough mask** (low-resolution logits): rarely needed.

One point alone is ambiguous (the eye, the head, or the whole fox?), so SAM predicts three
candidate masks and a quality score for each. kijai's node keeps the best-scored one.

## How we use it (task 4.4, `puppet/segment.py`)
We don't need a detector to find the character: the **skeleton that steered the
generation** says where it is (see controlnet-conditioning.md). Per view we send:

- the **view's half of the sheet** only (a crop), so the other view can't leak in, and the
  figure is bigger in SAM's 1024 px input (edges are about 3 px per mask cell instead of 5);
- **three positive points** on the body's centre line: the middle of the head, the chest and
  the belly. Hands and feet are left out on purpose, because a drifted limb would put a
  positive point on background;
- a **tight box**: the joints plus the colour-key pixels near them, with a 3% margin.

Then, in code: the enclosed holes are filled, specks are dropped, and the mask is pasted back
into the sheet's frame.

## Why combine it with the colour key
The **colour key** (`puppet/checks.py`) marks pixels far from the background colour. It is
fast and exact at the outline, but blind to colours close to the background. A cream shirt
that touches the background becomes background, and hole filling can't save it, because the
gap isn't enclosed. SAM segments by *shape*, so it keeps the shirt.

- In a test with a pale shirt that touches the background, SAM scored IoU 0.98/0.99 against
  the drawn figure, and the colour key 0.88/0.86.
- The two tools are good at different jobs: the colour key knows **where the figure ends**,
  and SAM knows **what is inside**. So the colour key sizes SAM's box.
- On the c3 fox sheet the two agree at IoU 0.97 per view. SAM's edge sits about one pixel
  inside the colour key's edge, and the colour key also keeps a few wispy fur tufts.

## Gotchas we hit
- **A loose box means "everything".** A skeleton box padded by 20% of the height filled
  almost the whole crop, and SAM returned the background too (front view IoU 0.32). With 8–16%
  padding it worked, but the tail on c3 already reaches 18% past the joints. So the box comes
  from the actual figure (colour key), not from a guessed padding.
- **Negative points on the box corners made it worse** (the three-quarter view dropped from
  0.97 to 0.82). The box corners are already encoded as special points, and a negative point
  in the same place contradicts them. So we use no negative points.
- **`precision` must be fp32.** For fp16 or bf16, kijai's loader rewrites the file name to
  `sam2.1_hiera_base_plus-fp16.safetensors` and *downloads* it from Hugging Face. fp32 uses
  the file we have, and also avoids the fp16 MPS bug (D-017).
- **A list constant is a link in API format.** `["4", 0]` means "output 0 of node 4", so a
  box like `[[x0, y0, x1, y1]]` can't be passed as is. ComfyUI unwraps
  `{"__value__": [...]}` for exactly this case.
- **ComfyUI caches identical graphs.** The same graph queued twice runs nothing the second
  time, and its history names output files that `run_graph` already deleted, so the download
  fails with HTTP 404. A unique `SaveImage` prefix per run forces the (cheap) save to run
  again, while SAM's result still comes from the cache.
- **Speed:** about 2 s in ComfyUI for both views with a cold model load, and 3.4 s in total
  with the colour key and clean-up (M4, MPS).
