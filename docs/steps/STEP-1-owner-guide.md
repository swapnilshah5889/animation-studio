# Step 1: owner's guide (tasks 1.0 and 1.1)

Your hands-on part of Step 1: install Synfig Studio, then build one short cut-out scene by hand,
**twice** (once rigged with nested groups, once with bones). About 1–2 hours. The agent turns your
files into documentation and a Python generator, so the more "normal" your usage, the better.

Placeholder art is ready in `tests/fixtures/handmade/parts/` (regenerate with
`uv run scripts/make_placeholder_parts.py`). `parts.json` lists each part's **pivot**: the pixel
where it should rotate, e.g. the shoulder at the top of `upper_arm.png`.

| File | Size (px) | Pivot (px from top-left) |
|---|---|---|
| `background.png` | 2880×1080 (wider than the frame, so it can pan) | — |
| `torso.png` | 200×280 | 100, 260 (hips) |
| `head.png` | 220×300 | 110, 285 (neck) |
| `upper_arm.png` | 56×150 | 28, 20 (shoulder) |
| `forearm.png` | 52×150 | 26, 18 (elbow) |
| `mouth_A.png`, `mouth_E.png`, `mouth_X.png` | 90×50 | center |

Synfig docs: [quick start](https://synfig.readthedocs.io/en/latest/quick_start.html),
[animation mode](https://synfig.readthedocs.io/en/latest/main_concepts/animation_mode.html),
[waypoints](https://synfig.readthedocs.io/en/latest/main_concepts/waypoints.html),
[interpolations](https://synfig.readthedocs.io/en/latest/interpolations.html),
[group layer](https://synfig.readthedocs.io/en/latest/layers/group.html),
[switch group](https://synfig.readthedocs.io/en/latest/layers/switch_group.html),
[skeleton layer](https://synfig.readthedocs.io/en/latest/layers/skeleton.html),
[skeleton tool](https://synfig.readthedocs.io/en/latest/tools/skeleton.html),
[linking](https://synfig.readthedocs.io/en/latest/main_concepts/linking.html).

## 1.0 Install Synfig Studio (5 min)

1. Open `~/ai-studio/downloads/synfig-1.5.5/SynfigStudio-1.5.5.dmg` and drag **SynfigStudio** to
   Applications.
2. Open it. macOS refuses (the app is unsigned). Go to **System Settings → Privacy & Security**,
   scroll to the message about SynfigStudio and click **Open Anyway**. It runs under Rosetta 2
   (already installed), so the first start is slow.
3. In `config/studio.toml`, delete the `deferred = { synfig_studio = ... }` line, then run
   `uv run scripts/doctor.py`. `synfig_studio` should now be OK.

## 1.1 Build the scene

### Variant (a): nested groups → save as `tests/fixtures/handmade/scene_groups.sif`

1. **Canvas:** File → New. Canvas → Properties: Image size **1920×1080**, Time: **24 fps**, end
   time **10s** (240 frames).
2. **Background:** File → Import → `background.png`. Put it in a group, then in **animation
   mode** (the button at the bottom right of the canvas; the canvas gets a red border) set the
   group's offset at 0s and at 10s so the background slides left slowly. That gives two waypoints
   on a vector.
3. **Puppet parts:** import `torso.png`, `head.png`, `upper_arm.png`, `forearm.png`. Build the
   hierarchy with groups (select layers, then group them in the Layers panel):
   - `puppet` group: contains torso, a `head` group, and an `arm` group
     - `arm` group: contains `upper_arm` and a `forearm` group
       - `forearm` group: contains `forearm`
   For each group, move its **origin** (the pivot) to the joint: Ctrl+drag the group's origin
   handle, or type the Origin parameter in the Params panel. Shoulder for `arm`, elbow for
   `forearm`, neck for `head`.
4. **Wave:** in animation mode, rotate the `arm` group at ~1s, 1.5s, 2s, 2.5s (up, down, up,
   down), and the `forearm` group a little too. Rotate the `head` group a few degrees as a nod.
5. **Interpolation:** in the Timetrack panel, right-click one of the arm's waypoints and change it
   to **Linear**, and another to **Ease In/Out**. Leave the rest at default. (We need to see how
   each is written in the file.)
6. **Mouth:** import the three `mouth_*.png` files and put them in a **Switch Group** (New Layer
   → Other → Switch Group, then move them in; name the layers `A`, `E`, `X`). Place it on the
   head, inside the `head` group. In animation mode, change the Switch's **Active Layer Name** at
   a few times, e.g. X at 0s, A at 2s, E at 2.3s, X at 2.8s.
7. **Check:** File → Render (or preview) and watch it once.
8. **Save uncompressed:** File → Save As → `tests/fixtures/handmade/scene_groups.sif`. Use the
   `.sif` extension, **not** `.sifz` (gzip). Keep the PNGs next to it: copy them from `parts/` into
   `tests/fixtures/handmade/`, or let Synfig use the `parts/` paths; both are fine, but say which.

### Variant (b): bones → save as `tests/fixtures/handmade/scene_bones.sif`

Same scene, but rig the arm with the **Skeleton tool** (Alt+O) instead of nested groups:

1. With the Skeleton tool, drag from the shoulder to the elbow (upper-arm bone), then, with that
   bone active, drag from the elbow to the wrist (forearm bone, a child of the first).
2. Link the parts to the bones: select the part (or its group's transformation handle) together
   with a bone, right-click → **Link to Bone**.
3. Animate the wave by rotating the **bones** in animation mode.
4. Save as `tests/fixtures/handmade/scene_bones.sif`.

If bones fight you, stop after 20–30 minutes and write down what was confusing. That is a useful
result too: it tells us which technique the generator should use.

### Tell the agent when you're done

Note anything surprising (e.g. "the origin handle jumps when I group") in a few lines in this
file or in chat. The agent then documents the format from your files (task 1.2), compares the
two rigs, and recommends one in DECISIONS.md (owner checkpoint 2).
