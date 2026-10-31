# New character on both engines: Kenney "Toon Characters 1" through Blender and OpenToonz (2026-10-31)

Why (D-100): Mia was rejected after four rounds of home-made art. This tests the engines on professionally drawn parts: Kenney
"Female person" (CC0). Time box 120 minutes; the time box ran out before the planned extras (see "Not done").
Video: `~/ai-studio/scratch/new-character-test/compare.mp4` (left Blender, right OpenToonz; labels in `compare_labels.txt`),
the two clips, `ev_*/` evidence and the independent `review.md` are in the same folder.

## What was built

- `studio_core/puppet/kenney.py`: re-renders every symbol of the SVG sheet with cairosvg at 12 px per unit (the PNG parts are about
  100 px wide, soft at 1080p) and writes the same `rig.json` the engines read. Each symbol's origin is its joint; the `idle` cell of
  the sheet gives the rest layout (the PIL composite of the rig matches the reference pose). Variants (leg/legBend, head/headFocus/
  headShock/headBack, body/bodyBack) share ONE canvas and pivot, so a texture swap never stretches (`variants.json`). The art has no
  elbow or knee: the arm is one part, the mitten acts as the "forearm" for wave and gestures, the leg is one part with a drawn
  bent variant.
- `scripts/spikes/new_character_test.py` (Blender) and `new_character_opentoonz.py`: the same 6 s bake (walk in, stop, wave, talk
  pose with head tilt, push-in that passes `framing.check_framing`), expression heads and the bent leg swapped per frame. The plate,
  shadow and mux are the same Python compositor as Mia's spike, so the clips differ only in how the engine drew the puppet.
- Tests: `tests/test_kenney_rig.py` (4, skipped without the assets or cairosvg).

## Bugs found by running it (fixed)

1. **Blender harness: the rest armature was unscaled** while meshes and posed bones are scaled, so every part was pulled toward the
   root by (1 - scale) of its distance: a 12% error on Mia at 0.88 (never noticed), a collapsed figure at 0.6. Fixed in
   `engines/blender/build_render.py` (`rest_s`).
2. **OpenToonz adapter** had no part scale, no camera track (static zoom only), no per-frame drawing swaps for parts other than the
   face, and a white opaque background colour. Added: part `sc`, keyed camera `sc/x/y`, drawing variants as xsheet cells, and a
   transparent mode (bg colour alpha 0, no bg column).

## Numbers

| | Blender (EEVEE) | OpenToonz (tcomposer, Rosetta) |
|---|---|---|
| render, 144 frames at 1080p | 16 s (0.11 s/frame) | 15 s (0.10 s/frame) |
| framing rule (head, feet, sides) | passes | same bake |
| foot rule on the bake | float 9 px, sink 21 px (the walk over-lowers the body at some frames), slide 0.03 px | same bake |
| motion spikes (>5x median) | 2 at 1.12 s and 1.17 s (3.7, 3.5; a fast leg swing) | 0 |
| audio | -20.6 LUFS, peak -2 dBFS | same |

## Independent review (a separate agent, `review.md`, 5 of 6 zooms): both clips FAIL

- **Blocker (both):** a plate-green "slab" between the legs on every frame; it reads as a pasted box. My check afterwards: it is the
  plate showing through the transparent gap between the two leg parts (the art has rectangular, widely spaced thighs); the pixel
  equals the ground colour. Fix: a filler part (shorts or skin) between the thighs, or legs closer together. Not fixed in this time box.
- **Major (both):** the talking pose has a grumpy face (the `headFocus` head I chose for talking; use the default head).
- **Major (both):** the wave is a stiff arm wedge ending in a clenched fist, then a horizontal point; there is no open hand drawn in
  the part set.
- **Major (both):** the walk is a shoe shuffle, no leg swing or body bob.
- Minor: fully in frame at 0.25 s; large head on short legs; a thin light-green fringe around fists and shoes (anti-aliasing
  against the transparent plate, a little wider in OpenToonz).
- Framing fine through the push-in (about 125 px head room, 80 px foot room); no pops in `motion.csv`.
- Engines: the same bake looks almost identical. Blender splays and tilts the shoes outward (bow-legged stance, soles off the
  ground line); OpenToonz keeps the feet flat, has cleaner ground contact and a livelier mouth cycle, with a slightly wider green
  fringe. OpenToonz looks slightly better, the difference is small.
- Is the art a real step up from the home-made puppet? **Yes** (properly built face, style matches the plate, clean edges).
  Passable for a children's video? **No, not yet.**

## What worked from code, and what did not

- Worked from code, both engines: building the project from the bake, per-part transforms, drawing swaps, a keyed camera, 1080p
  output with alpha. OpenToonz was driven headless (`tcomposer`) with no GUI step this time.
- **Not done (time box):** Blender NLA/action blending and a mocap-retargeted walk, Track-To camera dolly, Blender parallax planes
  and soft shadow (these were done in the Python compositor, not in Blender), OpenToonz Plastic (the art has no bendy limbs, so it
  was not needed here), the Robot character, a back-view walk, lip sync overlay.

## Recommendation (engine pick)

The two engines are tied on this puppet: speed, edges and motion are equivalent, and every visible defect is in the art use or the
motion, not in the engine. Keep both adapters; pick by what the next step needs (OpenToonz for the xsheet and Plastic on art with
bendy limbs, Blender for anything with real 3D camera or armature features). The next quick wins, in order: close the leg gap,
use the default head for talking, replace the fist wave with an open-hand pose (the pose library has `show`, `cheer` and `talk` PNGs
to draw hands from), and give the walk a real leg swing (these thighs rotate 35 degrees at most; the art needs the knee-bend variant
on the lifted leg, which is wired but only switches above an 8 px lift).
