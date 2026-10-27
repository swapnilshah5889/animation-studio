# Monocular depth and layering a picture

*Task 4.7, D-055. How a flat generated background becomes parallax layers.*

## The problem
A parallax pan moves near things faster than far things. A generated background is one flat
picture, so nothing says what is near. We need a depth value per pixel, then cut the picture
into layers and give each its own speed.

## Monocular depth estimation
- **What it is:** a network that takes *one* image and returns a *relative* depth map. No
  second camera, no motion. It works because it has seen millions of pictures and learned
  cues: things lower in the frame are usually nearer, far things are hazier and smaller,
  known objects have known sizes.
- **Relative, not metric.** The map says "this is nearer than that", normalized to 0..1. It
  does not say metres. Fine for us: we only need an order and a rough spread.
- **Why Depth Anything 3 MONO-LARGE (D-055):** compared on our meadow, it separated
  branches at resolution 1512 in about 5 s, with a real sky head (sky is exactly 0). DAv2-Small
  gave soft halos and put the distant tree line as far as the sky. DA3's values are linear in
  depth, not disparity (1/distance). Licence and files: `docs/MODELS.md`.

## Bands and parallax factors
- **Bands:** sky (the farthest region touching the top), then far, middle and ground, cut at
  the 35% and 70% depth quantiles. Each cut then moves to a valley of the depth histogram,
  because a cut through a busy depth level slices objects in half. Tiny bands merge into the
  band around them. A foreground band exists only for things clearly nearer than the ground
  at their own row.
- **Parallax factors:** ground = 1.0, measured at the characters' feet. Other bands get their
  nearness over the ground's, a *perceptual* multiplane spread, not physics. Sky is 0.05.
  Factors are capped so no layer edge enters the frame during a pan.

## Fill behind
A near layer sliding away uncovers what was behind it, which the plate never had. Each farther
layer is repainted where nearer layers hide it, by SDXL with the ProMax ControlNet in
"repaint" mode. The hole is black in the control image and grey in the latent, so the
removed object doesn't creep back. Only the reach a pan can uncover (plus a margin) is
filled; the sky is filled everywhere. Per-layer prompts matter: one shared prompt made the
fills redraw near things.

## Gotchas
- **Depth models fail quietly.** At resolution 2520 DA3 ran out of Metal memory and returned
  an all-black map with no error. A flat map is now refused. Check outputs, not just exit codes.
- **Resolution is a trade.** 1008 merged branches, 2016 added sky specks and was 3x slower.
- **Memory.** One large model at a time; a split takes 8-14 min, mostly three fills at about
  2.7 min each. A full-size fill was not feasible (over 30 min, swap full), so fills run small
  and are scaled back.
- **Prove it with a probe.** Pan over a magenta backdrop (`scripts/preview_background.py`);
  any magenta pixel is a hole.

See also: `parallax-and-camera.md`, `controlnet-conditioning.md`, `upscale-and-refine.md`.
