# The Synfig `.sif` format, for code generation

What our generator (`studio_core/sif/`) needs to know about Synfig's XML scene format, learned by
writing files and rendering them with the Synfig 1.5.5 CLI. Every claim below was checked by a
render; the evidence is in `tests/test_sif_*.py`, `tests/fixtures/smoke/smoke.sif` and the Step 1
demo (`scripts/sif_demo.py`).

> Status: written before the owner's hand-made scenes exist (Step 1 task 1.1). A "What the GUI
> writes" section is added once `tests/fixtures/handmade/scene_*.sif` arrive.

## Files

- `.sif` is plain XML; `.sifz` is the same XML gzipped. We generate `.sif` (diff-able).
- Render headless: `synfig scene.sif -t png -o frames/frame.png` writes
  `frame.0000.png`, `frame.0001.png`, … Options: `--begin-time 12f`, `--end-time 47f`,
  `-w 1920 -h 1080` (override size), `-T <threads>`. `--layer-info=<type>` prints a layer's
  parameters; `--layers` lists all layer types.
- CLI quirks: `synfig --version` exits with code **3**; the Homebrew build warns
  "Unable to find module mod_jpeg" (harmless: we use PNG); a parse error prints the line and
  `Unable to load file` and exits non-zero.

## Canvas

```xml
<canvas version="1.2" width="1920" height="1080" xres="2834.645669" yres="2834.645669"
        view-box="-8.0 4.5 8.0 -4.5" antialias="1" fps="24" begin-time="0f" end-time="167f"
        bgcolor="1.0 1.0 1.0 1.0">
  <name>...</name>
  <layer .../>  <!-- bottom-most first -->
</canvas>
```

- **Units, not pixels.** Geometry is in Synfig *units*. `view-box="left top right bottom"` maps the
  pixel frame onto units: the origin is the **centre** and **y points up**. 1920×1080 with
  `view-box="-8 4.5 8 -4.5"` means 120 px per unit. (Synfig's default is 60 px/unit.)
  `studio_core.sif.Space` converts.
- **Time** attributes accept seconds (`2s`) and frames (`36f`). We always write frames: exact,
  and no float drift. `end-time` is inclusive: `0f`..`167f` is 168 frames.
- **Layer order:** layers are listed bottom-first. Later layers draw on top.
- `xres`/`yres` (dots per metre) do not matter for PNG output.

## Layers we use

Every layer: `<layer type="..." active="true" exclude_from_rendering="false" version="..."
desc="name">` + `<param name="...">value</param>` children. Missing params take defaults, so
the generator only writes what it sets. Versions (from `--layer-info`): group 0.3, switch 0.0,
import 0.1, rectangle 0.2, circle 0.2, skeleton 0.1. No GUIDs are needed for the CLI.

| Layer | Key params | Notes |
|---|---|---|
| `import` | `filename` (string, path relative to the .sif), `tl`, `br` (vectors) | Stretches the PNG between the top-left and bottom-right corners, in units. `..` in the path works. |
| `group` | `origin` (vector), `transformation` (composite), `canvas` (inline `<canvas>` with child layers) | The building block of a cut-out rig. |
| `switch` | same as group + `layer_name` (string) | Shows only the child whose `desc` equals `layer_name`. Mouth shapes. |
| `rectangle` | `color`, `point1`, `point2` | |
| `circle` | `color`, `origin`, `radius` (real) | |

### Group transform (measured)

```xml
<param name="origin"><vector><x>0</x><y>0</y></vector></param>
<param name="transformation">
  <composite type="transformation">
    <offset><vector><x>1.1</x><y>1.2</y></vector></offset>
    <angle><angle value="30"/></angle>
    <skew_angle><angle value="0"/></skew_angle>
    <scale><vector><x>1</x><y>1</y></vector></scale>
  </composite>
</param>
```

Rendering a test square at local (1, 0) under different settings showed:

**`point_in_parent = offset + R(angle) · scale · (point_in_group − origin)`**, with angles in
degrees, counter-clockwise.

| origin | offset | angle | scale | square lands at |
|---|---|---|---|---|
| (0,0) | (0,0) | 0 | 1 | (1, 0) |
| (0,0) | (0,0) | 90 | 1 | (0, 1) |
| (1,0) | (0,0) | 0 | 1 | (0, 0) |
| (1,0) | (1,0) | 90 | 1 | (1, 0) (rotates in place) |
| (0,0) | (2,1) | 0 | 1 | (3, 1) |
| (0,0) | (0,0) | 0 | 2 | (2, 0) |

**Our cut-out convention** (`ImportLayer.with_pivot`): draw each part so its pivot pixel sits at
the group's local (0, 0), keep `origin = (0, 0)`, and set `offset` to where that joint sits in
the parent's space. Then `angle` rotates the part around its joint, and nesting groups gives
forward kinematics: the forearm group inside the upper-arm group follows the upper arm and adds
its own rotation (verified in the demo).

## Animation: `<animated>` and waypoints

Any parameter (or any part of a composite, like `offset` or `angle`) can be replaced by:

```xml
<animated type="angle">
  <waypoint time="0f"  before="halt" after="halt"><angle value="0"/></waypoint>
  <waypoint time="12f" before="halt" after="halt"><angle value="150"/></waypoint>
</animated>
```

- `type` is the value type: `angle`, `vector`, `real`, `color`, `string`, `bool`, ...
- `before`/`after` set the interpolation into and out of the waypoint.
- **Interpolation names in the file differ from the GUI:** `halt` (GUI "Ease In/Out"), `linear`,
  `clamped` (the default), `constant` (step), `auto` (GUI "TCB"). `ease` is rejected by the
  parser. Strings and bools can only use `constant`.

Measured x position of a square moving −3 → 1 → 3 with waypoints at frames 0, 12, 24:

| frame | linear | halt (ease) | clamped | auto (TCB) |
|---|---|---|---|---|
| 0 | −3.00 | −3.00 | −3.00 | −3.00 |
| 3 | −2.00 | −2.38 | −1.94 | −1.96 |
| 6 | −1.00 | −1.00 | −0.84 | −0.88 |
| 9 | 0.00 | 0.38 | 0.19 | 0.14 |
| 12 | 1.00 | 1.00 | 1.00 | 1.00 |
| 15 | 1.50 | 1.31 | 1.59 | 1.64 |
| 18 | 2.00 | 2.00 | 2.09 | 2.12 |
| 24 | 3.00 | 3.00 | 3.00 | 3.00 |

What that means for the motion library:
- `linear` changes speed abruptly at each waypoint. It's mechanical; use it only for steady pans.
- `halt` comes to a full stop at **every** waypoint (an S-curve per segment). Good for poses held
  between moves and for the ends of a wave, but a wave built only from `halt` looks like a
  series of separate moves.
- `clamped` keeps the speed through intermediate waypoints without overshooting. It's the right
  default for continuous motion (walk cycles, waves passing through the middle).
- `auto` (TCB) is similar but can overshoot on sharp reversals.

## Switch layers (mouths)

```xml
<layer type="switch" version="0.0" desc="mouth">
  <param name="layer_name">
    <animated type="string">
      <waypoint time="0f"  before="constant" after="constant"><string>X</string></waypoint>
      <waypoint time="24f" before="constant" after="constant"><string>A</string></waypoint>
    </animated>
  </param>
  <param name="canvas"><canvas> <layer ... desc="A"/> <layer ... desc="X"/> </canvas></param>
</layer>
```

The change is **frame-exact**: frame 23 shows X, frame 24 shows A (measured). If two children
share a name, the topmost wins. `studio_core.sif.lipsync.mouth_track` turns Rhubarb's
`mouthCues` into these waypoints. A cue at t seconds shows from frame ceil(t × fps); same-frame
cues keep the later one; repeats collapse.

## Bones (Skeleton layer)

Researched in the Synfig v1.5.5 source (`valuenode_bone.cpp`, `valuenode_bonelink.cpp`,
`loadcanvas.cpp`, `layer_skeleton.cpp`, `layer_skeletondeformation.cpp` on
[github.com/synfig/synfig](https://github.com/synfig/synfig/tree/v1.5.5)) and verified by
rendering. Working examples: `tests/fixtures/sif_examples/bones_arm_minimal.sif` and
`deform_limb.sif`. `tests/test_sif_examples.py` renders them and checks the forearm tip against a
forward-kinematics prediction, within 1.5 px.

**Structure.** Bones live in a `<bones>` section of the **root** canvas (an inline canvas raises
"Inline canvas cannot have a `<bones>` section"). It must come **before** any layer that refers
to a bone; otherwise there are parse errors and the CLI aborts. A global `bone_root` is the
parent of top-level bones:

```xml
<bones>
  <bone_root type="bone_object" guid="00000000000000000000000000000B00"/>
  <bone type="bone_object" guid="00000000000000000000000000000B01">
    <name><string>upper_arm</string></name>
    <parent><bone_valuenode type="bone_object" guid="00000000000000000000000000000B00"/></parent>
    <origin><vector><x>-3</x><y>1</y></vector></origin>   <!-- in the parent's space -->
    <angle><animated type="angle">...waypoints...</animated></angle>  <!-- relative to parent -->
    <scalex><real value="1"/></scalex>
    <length><real value="3"/></length>
  </bone>
  <!-- child bone: parent = B01, origin (3, 0) = the parent's tip -->
</bones>
```

- **Required links:** `name`, `parent`, `origin`, `angle`, `scalex`, `length`. **Optional:**
  `scalelx`, `width`, `tipwidth`, `bone_depth` (omitting them renders identically).
- **Two kinds of reference:** `<bone_valuenode type="bone_object" guid=.../>` is a handle to a
  bone (used for `parent` and in `bone_link`). `<bone type="bone_object" guid=.../>` is the bone
  value (used in skeleton lists and deformation pairs). Mixing them up gives "wrong type for
  Parent".
- **GUIDs:** any 32 hex digits, unique within the file. A generator can derive them
  deterministically (e.g. a hash of character + bone name).
- **Bone math:** world = parent · translate(origin) · rotate(angle) · scale(scalex, 1). `scalex`
  scales the children too; `scalelx` scales only this bone. `length`/`width`/`tipwidth` only
  shape the bone's drawing and its deformation influence.

**Linking art to a bone.** Put each part in a group and replace the group's `transformation`
with a `bone_link`. Draw the art in **bone-local space**: pivot at (0, 0), +x along the bone.

```xml
<param name="transformation">
  <bone_link type="transformation">
    <bone><bone_valuenode type="bone_object" guid="...B01"/></bone>
    <base_value><composite type="transformation">...identity...</composite></base_value>
    <translate><bool value="true"/></translate> <rotate><bool value="true"/></rotate>
    <skew><bool value="true"/></skew> <scale_x><bool value="true"/></scale_x>
    <scale_y><bool value="true"/></scale_y>
  </bone_link>
</param>
```

All seven children and the `type` attribute are mandatory. The GUI's "Link to Bone" stores a
non-identity `base_value` (the inverse of the bone's pose at link time), so art can stay in world
coordinates; a generator can keep `base_value` the identity instead.

**Skeleton layer** (`type="skeleton"`): draws the bones as editable handles in the GUI. The CLI
does not need it; with `exclude_from_rendering="true"` it renders byte-identically to a file
without it.

**Skeleton Deformation** (`type="skeleton_deformation"`): bends the layers below it with pairs of
(rest bone, pose bone) over a grid (`point1`/`point2`, `x_subdivisions`/`y_subdivisions`). It
needs separate rest and pose bone chains. Pixels outside the rest bones' width disappear.
`deform_limb.sif` bends one striped limb smoothly at an elbow.

**Bone gotchas (all reproduced):**
- A missing `bone_root` or an unknown GUID gives "Unexpected element <bone_valuenode>".
- Linking an import layer's `tl`/`br` corners to bones stretches and even mirrors the image
  (corners move, but the image stays axis-aligned). Link the group's transformation instead.
- GUI-style `length = 1` with the visible length in `scalelx` stretches linked art.
- A missing PNG is only a warning: the part renders blank and the exit code is 0. Validate files
  before rendering.
- Synfig 1.5.5 has no inverse kinematics (IK) node; IK, if needed, is solved in Python.

## Rig technique: nested groups vs bones (Step 1, checkpoint 2)

Both were verified to render identical poses (pixel-identical at the rest pose, PSNR above
100 dB elsewhere) at the same speed (25 arms, 48 frames, 1080p: 3.04 s vs 3.05 s).

| | Nested groups | Bones |
|---|---|---|
| Hierarchy | nesting in the file | GUID parent references in one `<bones>` block |
| Draw order | a child always draws inside its parent's group | **independent of the hierarchy** (far arm behind the torso, hand in front of a prop) |
| Bending one image | not possible | **Skeleton Deformation** |
| Stretch one segment | scales its children too | `scalelx` stretches only that bone |
| Generator complexity | lowest: no IDs, ~1x XML | GUIDs + ordering rules, ~1.6–1.9x XML |
| Editable in the GUI as a rig | groups only | bone handles a person can drag |
| IK | none | none |

**Agent's recommendation, pending the owner's scenes:** **bones for characters** (one
`<bones>` block per character, deterministic GUIDs, a flat group per part with a `bone_link`,
art in bone-local space, the skeleton layer kept but excluded from rendering), and **nested
groups for scene-level transforms** (character placement, camera, props, parallax). The
deciding reasons: cut-out puppets need draw order independent of the hierarchy (the far arm
behind the body), and deformation for bendy limbs. The extra XML is generator code, which is
unit-testable. Also add a validator before every render (bones first, all links present, every
GUID resolves, every image exists), because the CLI fails silently or aborts on these mistakes.

## Gotchas

- y is **up** in units but **down** in pixels. Convert in one place (`Space.to_units`).
- `end-time` is inclusive.
- A group's `origin` is the pivot in **local** coordinates; moving it without changing `offset`
  shifts the content (see the table).
- Image paths are relative to the `.sif` file, not the working directory.
- Melt is slow on PNG sequences. Encode shot frames with ffmpeg (Step 0 benchmarks).
