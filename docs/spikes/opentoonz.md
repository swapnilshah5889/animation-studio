# Spike: OpenToonz as the Tier 2/3 engine

**Date:** 2026-10-21. **Time box:** about 3 hours. **Machine:** MacBook Pro M4 (10 cores), 24 GB.
**Version:** OpenToonz 1.8.0 (official GitHub release, Intel build under Rosetta 2).

## Verdict

**Tier 2 engine: yes, with caveats. Tier 3: maybe, as the compositor.**

Python can write a working `.tnz` scene from scratch and `tcomposer` renders it to 1080p PNGs from
the command line, at about 0.04 s per frame. One generated scene covered everything Tier 2 needs:

- PNG-sequence levels timed on twos (swapped drawings)
- a pegbar hierarchy
- eased and linear keyframes for move, rotate and scale
- a real multiplane camera: the engine computes the parallax from each layer's Z depth (measured
  ratios exactly as predicted)
- a compositing fx (blur) with an animated parameter

A Plastic mesh-and-skeleton deformation written entirely from code also rendered.

The caveats are about distribution and operations, not capability:

- The macOS build is **Intel-only and unsigned**, so it runs under Rosetta and needed the owner's
  explicit approval.
- `tcomposer` needs a logged-in GUI session.
- The file format is undocumented. I learned it from the source code.
- Plastic needs a real mesher to look good.

Synfig stays the Tier 1 engine. Nothing in v1 should change.

## What was run, with evidence

### Install (question 1)

- Downloaded `OpenToonz.pkg` (v1.8.0, published 2026-06-19) to `~/ai-studio/downloads/opentoonz/`:
  110,493,957 bytes, SHA-256 `6360efbde7739910d4eefe9d494b6b57e852a3f75bdbeb1e6d75abb84e609d13`.
  This matches the digest GitHub publishes for the asset.
- **The installer was not run.** `pkgutil --expand-full` extracted it and `ditto` copied the app to
  `~/Applications/OpenToonz.app` (255 MB). The package's post-install script would have unpacked
  `stuff.tar.bz2` to `/Applications/OpenToonz/OpenToonz_stuff` and run `chmod -R 777` on it. That
  needs admin, and world-writable is a bad idea anyway. Instead I unpacked the same archive to
  `~/ai-studio/tools/opentoonz-stuff` and pass it with `-TOONZROOT`, which every OpenToonz binary
  accepts.
- **Architecture: x86_64 only.** All 19 binaries and dylibs in `Contents/MacOS` are x86_64:

  ```
  $ file .../MacOS/tcomposer
  Mach-O 64-bit executable x86_64
  $ lipo -info .../MacOS/tcomposer
  Non-fat file: ... is architecture: x86_64
  ```

  The GUI, `tcleanup`, `tconverter` and the farm tools are the same. Bundled Qt is 5.15.2. It runs
  under Rosetta 2, which is already installed.
- **Signature: none.**

  ```
  $ pkgutil --check-signature OpenToonz.pkg
     Status: no signature
  $ codesign -dv OpenToonz.app
  OpenToonz.app: code object is not signed at all
  $ spctl --assess --type execute -vv OpenToonz.app
  OpenToonz.app: rejected
  source=no usable signature
  ```

  `tcomposer` on its own is also rejected. **The owner explicitly approved running this
  non-notarized build.** The approval covers only the app extracted from the official v1.8.0 pkg
  into `~/Applications/OpenToonz.app`, under Rosetta. No installer, no `sudo`, no quarantine
  changes.

### Headless render with `tcomposer` (question 2)

No sample scenes are bundled. So I had OpenToonz itself save a reference scene: a ToonzScript run in
batch mode (see question 5) loaded two PNG levels, filled the cells and called `Scene.save`. Then:

```
$ tcomposer ref_scene.tnz -o render/ref.png -range 1 12 -TOONZROOT ~/ai-studio/tools/opentoonz-stuff
.../ref.0001.png computed   ... (12 frames)
Compositing completed in 0.57 seconds
$ file render/ref.0001.png
PNG image data, 1920 x 1080, 8-bit/color RGBA, non-interlaced
```

- **It needs a window-server session.** `tcomposer` builds a full `QApplication` (from
  `tcomposer.cpp`), and the bundle ships only the `cocoa` Qt platform plugin:

  ```
  $ QT_QPA_PLATFORM=offscreen tcomposer ...
  qt.qpa.plugin: Could not find the Qt platform plugin "offscreen" in ""
  Available platform plugins are: cocoa.
  ```

  It works from any shell in the logged-in user's session (that is how this spike ran). It will not
  work from SSH with no GUI login, or from a LaunchDaemon. The Windows build has the same
  `QApplication` design but doesn't need a display on Windows, which suits the Step 5 render node.
- Output naming: `-o dir/name.png` gives `name.0001.png` and so on.
- Exit codes: `tcomposer` normally exits 0. Once, in a Plastic run, it crashed with SIGSEGV
  *during process exit* (`__cxa_finalize` inside QtGui) after all frames were written. The crash
  report is `tcomposer-2026-10-21-160827.ips`. A wrapper should check the frames on disk, not just
  the exit code.

### Python generates the `.tnz` from scratch (question 3, the core question)

`scripts/spikes/opentoonz_scene.py` (standard library plus Pillow, PEP 723 header, run with
`uv run`) writes three things into `~/ai-studio/scratch/opentoonz-spike/gen/`:

- a minimal project
- 9 placeholder PNGs
- `scenes/meadow_multiplane.tnz` (12 KB): a 4 s, 24 fps, 1080p meadow shot

The shot contains:

- **6 level columns:** sky, hills, ground, Pip (4-drawing PNG walk cycle timed on twos), balloon,
  foreground bushes.
- **Pegbars:**
  - `Peg1` carries Pip across the shot (eased x, linear step bob on y).
  - `Peg2` is a **child of Peg1** (the balloon hand) with its own eased sway rotation.
  - Pip's column rides Peg1 with its pivot at his feet. It has linear squash and stretch (sx/sy),
    an eased lean (rot) and a "pop-in" global scale (sc).
  - The balloon column hangs from Peg2.
- **Multiplane:** sky Z=-3000, hills Z=-1000, ground and Pip Z=0, bushes Z=+350. Each layer's
  `noScaleZ` equals its Z, so it keeps its drawn size. The camera pans 8 inches with ease-in/out.
  In the last second the camera's Z and scale also animate (push-in).
- **Fx:** `STD_blurFx` on the sky (4) and hills (1.5) for depth, plus a keyframed blur on the
  bushes (0 to 6) for a rack focus at the end.

```
$ uv run scripts/spikes/opentoonz_scene.py --render
wrote .../gen/scenes/meadow_multiplane.tnz (11885 bytes), 9 level images
tcomposer exit=0, 96 frames, ...
wrote .../gen/outputs/meadow_multiplane.mp4
$ ffprobe ... ~/ai-studio/spike-samples/opentoonz-sample.mp4
stream|codec_name=h264|width=1920|height=1080|r_frame_rate=24/1|nb_frames=96
```

**The parallax is measured, not just eyeballed.** `scripts/spikes/opentoonz_check_parallax.py`
cross-correlates horizontal bands between two frames:

```
frames 20 -> 30: horizontal shift per band
  sky (Z=-3000)         29 px   ratio  0.25   expected 0.25
  hills (Z=-1000)       58 px   ratio  0.50   expected 0.50
  ground (Z=0)         115 px   ratio  1.00   expected 1.00
  bushes (Z=+350)      178 px   ratio  1.55   expected 1.54
```

**Sample video:** `~/ai-studio/spike-samples/opentoonz-sample.mp4` (96 frames, 450 KiB).

How I verified the format: I compared the generated XML with a scene that OpenToonz itself saved.
I checked every tag against the loaders in the v1.8.0 source (`toonzscene.cpp`, `txsheet.cpp`,
`tstageobject.cpp`, `tdoublekeyframe.cpp`, `sceneproperties.cpp`, `fxdag.cpp`). The loader throws on
unknown tags ("unexpected tag"), so a successful render is real validation, not a silent fallback.

### Plastic, mesh and skeleton from code (question 4, stretch)

**Yes, it works.** `scripts/spikes/opentoonz_plastic.py` writes:

- a flower PNG
- a hand-made triangle mesh `flower_mesh.0001.mesh` (5x13 grid, 96 triangles)
- a scene where the texture column is parented to a `<meshColumn>`, whose pegbar carries
  `<plasticSD>`: a 3-vertex skeleton up the stem and keyframed `Angle` channels on two vertices

`tcomposer` renders the stem swaying left and right next to an undeformed copy (48 frames, about
0.08 s per frame, exit 0 on two runs). How Plastic is stored:

- The **mesh** is a separate level file. OpenToonz writes it LZ4-compressed, but the reader accepts
  plain text: anything starting with `<` is read uncompressed. Format: `<header><version>1 19
  </version><dpi>120 120</dpi></header><mesh><V>n x y ...</V><E>m v0 v1 ...</E><F>f e0 e1 e2 ...
  </F>[<rigidities>...]</mesh>`. Vertices are pixels at the mesh dpi, origin at the image centre,
  y up. Faces list three **edge** indices.
- The **skeleton and its animation** live inside the mesh column's stage object, in the `.tnz`:
  `<plasticSD><VertexDeforms><Name>"Vertex 2"</Name><Hook>2</Hook><VD><Angle>…keyframes…</Angle>
  </VD>…</VertexDeforms><SkelIdsParam>…</SkelIdsParam><Skeletons><SkelId>1</SkelId><Skeleton><V>3
  <Vertex><name>…</name><number>…</number><pos>x y</pos><interpolate>1</interpolate></Vertex>…</V>
  <E>2 0 1 1 2</E></Skeleton></Skeletons></plasticSD>`.
  - Skeleton positions are in Stage units (1 inch = 53.333).
  - Per-vertex `Angle` (degrees, relative to the rest pose), `Distance` and `SO` are ordinary
    keyframe channels.
  - Deformations are matched to skeleton vertices by name.
  - The texture binds by being a child of the mesh column (parent handle not `H…`).

What didn't work at first:

- **Skeleton vertices lying exactly on a mesh edge are silently ignored.** My first skeleton sat on
  the grid's x=0 line, and the texture rendered undeformed. Moving the skeleton 7 px off the grid
  fixed it.
- **With a naive rectangular mesh, the stem tilts almost rigidly instead of bending.** The deformer
  is "as rigid as possible", and the mesh also covers transparent space. Meshes that follow the
  drawing's outline (what the GUI's Meshify command makes) would bend properly.

For production we would need our own outline mesher (contour plus constrained triangulation), or
we would make meshes by hand in the GUI once per character.

### ToonzScript (question 5)

- **API surface** (from `scriptbinding_*.h`):
  - `Scene`: load, save, setCell, getCell, insertColumn, deleteColumn, getLevels, getLevel,
    newLevel, loadLevel
  - `Level`: frames get/set, load, save
  - `Image`, `ImageBuilder` and `Transform` (raster compositing)
  - `Rasterizer`, `OutlineVectorizer`, `CenterlineVectorizer`, `ToonzRasterConverter`
  - `Renderer` (renderScene, renderFrame)
  - `FilePath`, `print`, `run`
- **What it can't do:** there is no API for pegbars or stage objects, keyframes, camera, Z, fx or
  Plastic. It can arrange drawings in the xsheet and batch-convert images, but it **can't animate**.
  The XML route is required for everything that matters to us.
- **It runs outside the interactive GUI.** `OpenToonz -TOONZROOT <stuff> <file>.toonzscript` runs
  the script in batch mode (`main.cpp`: it runs the script before the main window is shown, then
  returns). That is how the reference scene was made: 7 s per run, 19 s on the first launch. It
  still builds a `QApplication` and main window, so it needs the GUI session. It always exits 1, and
  the script must sit inside a project (or OpenToonz falls back to the sandbox).
- **Quirk:** a single-image PNG level has frame id `-`, which `setCell` rejects. Use numbered
  sequences (`name.0001.png`, referenced as `name..png`).
- `Renderer` was not tested. `tcomposer` covers rendering.

### Timings on the M4, under Rosetta (question 6)

Generated meadow scene: 1920x1080, 96 frames, 6 columns, 3 blur fx, PNG output.

| `-nthreads` | wall time for 96 frames (3 runs) | per frame |
|---|---|---|
| all (10) | 3.9 / 4.1 / 4.2 s | **~0.042 s** |
| single | 27.0 / 22.7 / 23.5 s | ~0.25 s |

- Process start-up is about 0.9 s. A later run took 5.6 s, with other work running on the machine
  at the same time.
- PNG encoding ("saving") is more than half of the time.
- Synfig on simple rigs measured 0.03 to 0.04 s per frame (`docs/benchmarks.md`), so the two are
  in the same range.
- I couldn't measure the Rosetta penalty directly, because there is no arm64 OpenToonz build and the
  owner stopped the Tahoma2D comparison. Plastic scenes render at about 0.08 to 0.1 s per frame
  (the deformer uses OpenGL).

## `.tnz` structure notes

```
<tnz framecount="96" version="71.1">          version = file format, not the app version
  <generator>"..."</generator>
  <properties>
    <cameras><camera><cameraSize>16 9</cameraSize><cameraRes>1920 1080</cameraRes>…</camera></cameras>
    <outputs><output name="main"><range>0 95</range><fps>24</fps><path>"+outputs/x.png"</path>
       <bpp>32</bpp><resquality>1</resquality>…</output></outputs>
    <bgColor>r g b m</bgColor> …
  </properties>
  <levelSet><levels>
    <level id='1'>pip <info dpix="120" dpiy="120"/><path>"+inputs/pip..png"</path></level> …
  </levels></levelSet>
  <xsheet>
    <columns>
      <levelColumn id='3'><status>0</status>
        <cells><cell>ROW COUNT <level id='1'/>FID INCREMENT</cell>…</cells>
        <fx><Toonz_columnFx id='4'>…</Toonz_columnFx></fx></levelColumn>
      <meshColumn id='5'>…same cells, no fx…</meshColumn>
    </columns>
    <pegbars>
      <pegbar id="Camera1" activeboth="yes">…<camera>…</camera></pegbar>
      <pegbar id="Table">…</pegbar>
      <pegbar id="Peg1"> <parent handle="B" id="Table" parentHandle="B"></parent>
        <center>cx cy -offx -offy</center> <noScaleZ>z</noScaleZ>
        <x>…</x> <y>…</y> <z>…</z> <so>…</so> <sx>…</sx> <sy>…</sy> <sc>…</sc> <rot>…</rot>
        [<plasticSD>…</plasticSD>] </pegbar>
      <pegbar id="Col1">… (one per column, 1-based) …</pegbar>
    </pegbars>
    <fxnodes><internal>non-column fx definitions</internal>
      <terminal>fx feeding the xsheet node</terminal>
      <xsheet><Toonz_xsheetFx/></xsheet><output><Toonz_outputFx>…source = xsheet…</output>
    </fxnodes>
  </xsheet>
</tnz>
```

- **The file is XML-like, not XML.** It is a custom tokenizer (`TIStream`). Values are
  whitespace-separated tokens, and strings are in double quotes.
- **Object ids:** `id='N'` is an object id. The first occurrence defines the object, and later empty
  tags with the same id refer back to it (levels in cells, column fx in `<terminal>`, fx inputs in
  `<ports>`). Ids must be unique across the file.
- **Cells:** row and frame indices are 0-based (xsheet frame 1 = row 0). `FID` is the frame number
  as written in the file name (`0001`). `INCREMENT` is 1 for a running sequence and 0 for a hold.
- **Units:**
  - x, y and centre are in **inches**. The default camera is 16x9 inches at 1920x1080, so
    1 inch = 120 px, and a level with `dpix=120` maps one image pixel to one output pixel.
  - rot is in degrees, counter-clockwise.
  - sx, sy and sc are ratios (effective scale = sc × sx).
  - Z is in "z units": the camera's focus distance is 1000, and positive Z is toward the camera.
- **Multiplane math** (`TStageObject::perspective`): each column is scaled about the camera by
  `p = (1000 + camZ) / (1000 + camZ - Z)`. `noScaleZ` multiplies the drawing by
  `1 - noScaleZ/1000`. So with `noScaleZ = Z` a layer keeps its drawn size, and on screen it sits at
  `drawing + p × (position - camera)`. That gives a pan speed of `p` relative to the Z=0 plane, and
  a position offset that is also multiplied by `p`. Divide the screen offset you want by `p`.
- **Camera Z keeps the Z=0 plane locked:** objects at Z=0 never change size. Only the relative
  scale of the other planes changes. For a zoom, animate the camera's `sc` (below 1 zooms in).
- **Render order** is by Z, then `so`, then column index.
- **Pivots** (`TStageObject::computeLocalPlacement`): the local transform is
  `T(offset + position) · R · Shear · S · T(-center)`. Set `center` and `offset` to the same point
  to move the pivot without moving the drawing; this is what the GUI writes.
- **Keyframes** (`TDoubleKeyframe`) are listed inside `<keyframes>`, one element per key, and the
  element name is the segment type:
  - `C` constant, `L` linear, `Exp` exponential
  - `S` speed handles, `E` ease in frames, `Ep` ease in percent
  - `Ex` expression, `F` data file, `SimShape`

  The type on the *left* key governs the following segment. The body is `frame value [ease-out]`.
  `<prev>value [ease-in]</prev>` carries the incoming handle (ease-in is stored as a negative
  number). Before the first key and after the last, the value holds. Expressions (`Ex`) could link
  channels; not tested.
- **Project:** `<folder>/<folder>_otprj.xml` lists the folders (`inputs`, `drawings`, `scenes`,
  `extras`, `outputs`, ...). `scenes/scenes.xml` contains
  `<parentProject type="projectFolder">".."</parentProject>`. `tcomposer` walks up from the scene
  looking for `scenes.xml`, so `+inputs/...` paths resolve through the project. That keeps scenes
  portable between the Mac and a Windows render node.
- **Fx ids:** standard fx are `STD_<id>`, for example `STD_blurFx` with parameter `value`
  (identifiers and parameter names are in `toonz/sources/stdfx/*.cpp`). A fx goes in `<internal>`,
  its input port (`<Source>`) refers to the column fx, and `<terminal>` refers to the fx instead of
  the column.

## OpenToonz compared with Synfig for our needs

| Need | Synfig 1.5.5 (v1) | OpenToonz 1.8 |
|---|---|---|
| Generate scenes from code | `.sif` XML, documented-ish | `.tnz`, undocumented but learnable; strict loader |
| Headless render | `synfig` CLI, native arm64, no GUI needed | `tcomposer`, Intel or Rosetta, **needs GUI session**; Windows build available |
| Cut-out rigs and bones | Strong (bones, skeleton deformation) | Pegbar hierarchy and Plastic; less suited to vector puppets |
| Drawn or swapped drawings (limited animation) | Switch layers and image layers; awkward | **Native** (xsheet cells, on twos/threes, PNG sequences) |
| Multiplane parallax | Manual (we compute offsets) | **Native Z camera**, verified ratios |
| Compositing fx | Basic blur/glow layers | **Large fx library** (blurs, glow, light, motion blur, shaders); keyframable |
| Mesh deformation | Skeleton deformation layer | Plastic: works from code, needs a good mesher |
| Speed (1080p, simple scenes) | 0.03–0.04 s/frame | ~0.04 s/frame |
| Mac distribution | Homebrew formula (CLI) | Unsigned pkg, Homebrew cask disabled, Rosetta-dependent |

## Recommendation

1. **Plan on OpenToonz as the Tier 2 engine.** Write a `toonz_mcp` later, in the same style as
   `synfig_mcp`: generate `.tnz`, render with `tcomposer`, check the frames on disk. Make the
   decision (an ADR) when Tier 2 actually starts, not now.
2. **Tier 3: use it as the compositor.** Image-sequence levels of AI in-betweens on twos, plus the
   camera, parallax and fx.
3. **Risks to track:**
   - Rosetta's end of life on macOS (after macOS 27).
   - Unsigned builds.
   - The GUI-session requirement on the Mac.

   Mitigations: render on the Windows node with the Windows build (Step 5), or switch to Tahoma2D's
   native arm64 build. It is the same format and tools. The Tahoma2D notes below show its
   `tcomposer` is arm64 and starts, though it never rendered a scene.
4. **Before building on Plastic:** spend a short task on an outline mesher, or decide to make meshes
   by hand in the GUI once per character.

## Files

- Report: `docs/spikes/opentoonz.md` (this file)
- Generator: `scripts/spikes/opentoonz_scene.py`. `uv run scripts/spikes/opentoonz_scene.py --render`
  regenerates the project, frames and MP4 under `~/ai-studio/scratch/opentoonz-spike/gen/`.
- Parallax check: `scripts/spikes/opentoonz_check_parallax.py`
- Plastic test: `scripts/spikes/opentoonz_plastic.py`
- Sample: `~/ai-studio/spike-samples/opentoonz-sample.mp4`
- Runtime kept outside the repo:
  - `~/Applications/OpenToonz.app`
  - `~/ai-studio/tools/opentoonz-stuff`: the OpenToonz "stuff" folder, which every OpenToonz
    binary needs; pass it with `-TOONZROOT`. The GUI's first batch run added a `sandbox` project
    there.
- Everything else from the spike went to the Trash (downloads, the expanded pkg, the source
  checkouts, scratch scenes and frames, the OpenToonz cache folder, crash reports, Tahoma2D).

## Appendix: Tahoma2D notes (spike stopped at the owner's request)

- Tahoma2D v1.6.3 (2026-09-01), `Tahoma2D-portable-osx-silicon.dmg`, 357,498,726 bytes,
  SHA-256 `22eaa7550dd4773f377a47448d98f01873e8c00afd0ce343dcc496053e098a24`.
- The GUI, `tcomposer`, `tcleanup`, `tconverter` and the farm tools are **native arm64** (`lipo`:
  "architecture: arm64"). The bundle is ad-hoc signed (`TeamIdentifier=not set`), not notarized,
  and `spctl` rejects it. `codesign --verify` also reports a broken seal on the accented-name
  translation folders (`loc/Čeština/*.qm`), which looks like a filename-normalization problem, not
  tampering.
- The owner approved running it. `tcomposer` printed its usage and exited normally. Same options as
  OpenToonz, with `-TAHOMA2DROOT` instead of `-TOONZROOT`, plus `-renderkeysonly` and
  `-rendertofolders`.
- Its `tcomposer` also builds a `QApplication` and ships only the `cocoa` platform plugin, so it has
  the same GUI-session requirement. No sample scenes are bundled.
- Not tested further: the owner switched the spike to OpenToonz. The `.tnz` format is shared, so
  the generator here should work with Tahoma2D's `tcomposer` with only the root flag changed. That
  is unverified.
