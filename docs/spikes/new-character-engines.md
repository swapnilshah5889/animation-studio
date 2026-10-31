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


## Fix round (one round, Blender is the engine from here: D-101)

Changes (the four findings): (1) the thighs sit 4 units closer and a code-drawn **pelvis** part (shorts colour above, skin below,
sampled from the leg art) closes the gap; the leg canvas is symmetric about the hip so the foot point sits under it (the first
walk measured float 9 px / sink 21 px because the leg image was wider on one side). (2) the default head replaces `headFocus`
for talking. (3) an **open hand drawn by code** (palm, four fingers, thumb; the set has only a mitten) is swapped in for the
wave (2.0 to 3.4 s). (4) `walk_step` now works on one-piece legs (no shin), the foot lift is applied inside the stride solver
(`lift_gain`, so the sole still lands on the ground), arms swing 2.6x with the hand trailing. Foot rule on the bake after the
fix: float 1.5 px, sink 6.9 px, slide 6.8 px (thresholds in `tests/test_kenney_rig.py`: 4, 8 and 8; the old numbers were 9 and 21).

Two bugs the render exposed: the Blender harness never **reverted a swapped texture** (a bent leg or the open hand stayed on
until another swap), which made the first Blender clip look bow-legged; fixed in `build_render.py` (a part not in
`part_images` goes back to its own drawing). OpenToonz's transparent background bled white edge pixels; the background colour is
now `0 0 0 0` in transparent mode.

**Independent review (a separate agent, `review.md`, 5 of 5 zooms): Blender NEEDS WORK, OpenToonz NEEDS WORK** (no blocker, two
majors each, the same in both). Previous findings: leg gap PARTLY (gone and the shoes touch, but a hairline seam and a boxy lower
body remain, now a major); grumpy face PARTLY (the mouth smiles, but the brows still slant inward, the right brow is clipped by the
fringe and the pupils sit in the outer corners during the tilt); fist wave FIXED (open fingers at about 2.2 to 2.5 s, but the
wave is small, brief and sideways); shuffle walk FIXED (legs alternate, shoes lift, the head bobs). Remaining: **major** the face
still reads stern or sceptical (3 to 6 s); **major** the standing lower body is stacked rectangles with fused feet, flat soles and
the seam; minor the shoes cross in an X at about 1.0 s and 1.5 s; minor an odd half-white, half-brown mouth; minor audio
-20.6 LUFS. The motion.csv walk spikes (0.8 to 1.5 s) are a fast legitimate leg swing, not a pop (4.4 s and 5.75 to 5.9 s are mouth and
eye changes). Engines: no visible difference (mean luma difference 0.16 of 255, per-frame motion equal to 0.01; no fringes);
every remaining defect is in the shared art. Better than the first version: yes. Passable for a children's TV series: not yet,
borderline; the reviewer expects two small art fixes (brows, leg and shoe stance) to get it through.

Open (skipped by instruction): Track-To dolly, Blender NLA and a mocap-retargeted walk, OpenToonz Plastic (OpenToonz is parked,
D-101), the Robot character, a back-view walk, a wider wave (raise the arm higher, longer hold).
