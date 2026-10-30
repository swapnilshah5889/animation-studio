"""Engine back ends and the engine-neutral hand-off they share (D-030).

`bake.bake_shot` turns a shot spec into per-frame world transforms of every part (engine-neutral
JSON: stage pixels, y up). Each engine package (`blender/`, `opentoonz/`, `synfig/`) reads that
bake and builds and renders its own scene. Nothing engine-specific enters the schemas.
"""
