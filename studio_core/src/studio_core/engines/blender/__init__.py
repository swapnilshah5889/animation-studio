"""Blender back end: `build_render.py` runs inside `blender --background --python`.

    blender --background --python build_render.py -- BAKE.json OUT_DIR
            [--engine EEVEE|WORKBENCH|CYCLES]
            [--size 960x540] [--rigid] [--frames 0-23]

It reads the engine-neutral bake (`studio_core.engines.bake`), builds a flat 2D scene: an
orthographic camera, emission-only (unlit) textured meshes, an armature with the rig's bones.
`launch.py` is the Python-side wrapper (command line, timing, memory).
"""
