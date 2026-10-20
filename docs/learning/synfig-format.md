# The Synfig `.sif` format, for code generation

What our generator (`studio_core/sif/`) needs to know about Synfig's XML scene format, learned by
writing files and rendering them with the Synfig 1.5.5 CLI. Every claim below was checked by a
render; the evidence is in `tests/test_sif_*.py`, `tests/fixtures/smoke/smoke.sif` and the Step 1
demo (`scripts/sif_demo.py`).

> Status: first version written before the owner's hand-made scenes exist (Step 1 task 1.1).
> A "What the GUI writes" section is added once `tests/fixtures/handmade/scene_*.sif` arrive.

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

_To be completed from the bone research and the owner's `scene_bones.sif` (Step 1 checkpoint 2:
nested groups vs bones)._

## Gotchas

- y is **up** in units but **down** in pixels. Convert in one place (`Space.to_units`).
- `end-time` is inclusive.
- A group's `origin` is the pivot in **local** coordinates; moving it without changing `offset`
  shifts the content (see the table).
- Image paths are relative to the `.sif` file, not the working directory.
- Melt is slow on PNG sequences. Encode shot frames with ffmpeg (Step 0 benchmarks).
