# Staging
> Where characters stand in the frame (feet fractions), who faces whom, and how the camera helps.

**When to use:** when adding characters and choosing the camera.

**How:** a position is where the feet touch the ground, as a fraction of the frame: `[0.5, 0.92]` is
centre, near the bottom. Two characters: about `[0.33, 0.92]` and `[0.67, 0.92]`, facing each other
(`facing` right for the left one). One character: `[0.5, 0.92]`, or off-centre toward the open space
they face. Keep feet low and similar in height so they stand on the same ground. Cameras: `static` for
dialogue, `push_in` toward an emotional beat, `slow_pan_left`/`slow_pan_right` to follow travel or reveal
a place, `pull_out` to end. One camera move per shot, and none during a key line.

**What fails and why:** characters closer than 0.2 apart overlap and hide each other. A character at
the frame edge is cropped (QA reports it). A push_in on a wide shot crops the sides.

Note: the numbers here are starting rules from the tool descriptions, not measured.
