# Parallax and the camera: how a flat scene feels deep

How a shot's background, characters and camera fit together (`studio_core/scene.py`), and how a
shot spec becomes a finished `shot.mp4` (`studio_core/shot.py`).

## Parallax in one sentence

When a camera moves sideways, near things slide past faster than far things. Cut-out animation
fakes depth by splitting the background into flat layers and sliding each one at its own rate.
That rate is the layer's **parallax factor**:

| factor | meaning | meadow example |
|---|---|---|
| 0 | infinitely far, never moves | (a star field) |
| 0.05 | almost still | sky |
| 0.35 | far away | hills |
| 1 | the ground the characters stand on | meadow (and the characters) |
| 1.4 | closer than the characters, drawn over them | foreground grass |

A camera pan of `p` pixels slides each layer by `-p × factor`. The characters ride the factor-1
plane, so they stay glued to the ground they stand on.

## The scene tree

```
backdrop            solid colour that never moves (fills the edges if the camera zooms out)
camera              scale = zoom(t), about the frame centre
  bg sky            offset = -pan(t) × 0.05
  bg hills          offset = -pan(t) × 0.35
  bg meadow         offset = -pan(t) × 1.0
  characters        offset = -pan(t) × 1.0, each character placed by its feet
  bg foreground     offset = -pan(t) × 1.4   (in_front: drawn over the characters)
```

It's the "nested groups for scene layout" half of D-027: each depth plane is a group with one
animated offset, and the camera is one more group around them all.

## Camera presets are numbers in code

The director picks a move by name (`static`, `slow_pan_left/right`, `push_in`, `pull_out`);
code decides how far and how fast. A slow pan travels 240 design pixels over its duration, a push
zooms ×1.25, and both ease in and out (`halt` interpolation) so the camera never jerks. Rules in
code: the LLM can't ask for a nauseating 3000 px whip pan by accident.

## Design resolution

Scenes are built once at **1920×1080 (120 px per Synfig unit)** and rendered at any size with
`synfig -w -h`. A quick 640×360 preview and the final 1080p frame come from the same `scene.sif`,
so a preview never lies about layout.

## Feet, not hips

A shot spec says where a character **stands**: `position` is the point between its feet, as frame
fractions (`[0.5, 0.92]` = centre, near the bottom). The rig's own origin is its hips (the root
bone), so code computes each rig's feet offset from its rest pose (`rig.ground_offset_px`) and
lifts the root by that much. An LLM saying "Pip stands at the bottom of the frame" means the feet;
if the hips went there, Pip's legs would be cut off.

## From spec to video (`render_shot`)

```
shots/s01_sh01/shot.json   validated (schema + semantic checks)
  → animate()              motions + manual key poses → bone tracks, blink track
  → expression_track()     expressions → brow/rest-mouth switch track
  → dialogue_mouth()       Rhubarb cues of each line, shifted to the line's start → mouth track
  → build_character()      bones + parts + face, per character
  → build_scene()          planes + camera + backdrop → scene.sif
  → synfig                 frames/frame.NNNN.png
  → mix + ffmpeg           mix.wav (dialogue, sound effects, ducked music; task 3.6) + frames → shot.mp4
```

Every arrow is deterministic, tested code. The director only writes `shot.json`.

## Gotchas

- **Layers need spare width for the pan.** A layer that slides `240 × factor` pixels must be at
  least `1920 + 2 × 240 × factor` wide, or its edge shows. The meadow layers are 2880 wide
  (480 px spare on each side), enough for factors up to 2.
- **Zooming out reveals the edges** of every layer. The backdrop fills them with a solid colour
  instead of transparency (which encodes as black).
- **`amix` quietly halves volumes.** ffmpeg's mixer divides by the number of inputs unless you pass
  `normalize=0`. Dialogue lines rarely overlap, so we mix without normalizing.
- **A left-facing character is mirrored**, so a `point` target is mirrored about the character too
  before the arm angle is computed.
