"""OpenToonz back end: bake JSON -> project folder with a generated `.tnz` -> `tcomposer`.

The `.tnz` format is undocumented; the structure here was learned from the OpenToonz source in the
earlier spike (docs/spikes/opentoonz.md) and checked by rendering. Plastic (mesh + skeleton)
deformation bends the limbs; every other part is a plain pegbar with keyed position and rotation.
"""
