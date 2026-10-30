# Animation engines for cut-out puppets: what the bake-off taught

Details and numbers: `docs/spikes/engine-bakeoff.md`. Installed versions and licences: `docs/ENGINES.md`.

## One bake, many engines
Keep the scene in **our** data and give each engine a *baked* answer: per frame, each bone's joint position and
world direction. The engine only has to place images and bend limbs. Why: the motion (mocap retargeting,
placement, foot locks) is ours and tested; an engine that re-solves it (its own IK, easing, bone rolls) would
play a slightly different motion. With a bake the three engines agreed to 0.6 grey levels on average.

## Blender, headless, as a 2D tool
- `Blender --background --factory-startup --python script.py -- args`. Arguments after `--` are yours.
- Flat 2D = an **orthographic** camera, **emission-only** materials (an Image Texture into Emission, alpha
  into a Mix with Transparent): no lighting, so colours stay the art's colours. Layers are ordered by a tiny
  Z step. Nothing has perspective depth, so it stays 2D.
- Set `view_transform = "Standard"`, otherwise Filmic/AgX changes every colour.
- Skin a limb as one mesh grid with two vertex groups (upper bone, lower bone) and a smoothstep weight across
  the joint; set poses by assigning `pose_bone.matrix` parents first (call `view_layer.update()` between).
- Render engines on an M4, 960x540: Workbench 0.03 s/frame, EEVEE 0.15 (works without a display, Metal),
  Cycles CPU 8 samples 0.23, and Cycles is the closest to a 128-sample reference. Compare **decoded pixels**
  between runs: PNG files from Blender differ in a header while the pixels are identical.
- Blender's bundled Python has no Pillow or numpy of ours; pass sizes and data in the JSON.

## OpenToonz from code
- Plastic = a mesh level (`.mesh`) + a skeleton stored in the mesh column's pegbar (`plasticSD`); the texture
  column is a child of the mesh column. A mesh that follows the outline bends; a rectangular one tilts rigidly
  (the deformer is as-rigid-as-possible).
- Vertices on a mesh edge are silently ignored; the end vertex's `Angle` bends the last segment about the middle
  vertex (positive = same sign as a pegbar `rot`).
- The macOS build is Intel under Rosetta. **`tcomposer -nthreads 4` crashes randomly (heap corruption) and loses
  frames; `-nthreads 1` is stable.** Always count frames on disk; do not trust the exit code.

## Measuring a cut: what a defect count can and cannot say
Hole/seam counts on a magenta probe are dominated by the **art** (hair gaps are in every pose) and move by about
a quarter between two render engines of the same geometry (anti-aliased slivers). Compare **against the
straight pose of the same engine**, and sweep one joint at a time. A count cannot see whether a bend is a smooth
curve or a hinge; that needs eyes.
