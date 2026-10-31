"""Render the Rain look-test pair (Blender 5.2+, local assets only).

Run with the project Python, not Blender's bundled Python:
    BG=$(find ~/ai-studio/scratch/slice-look/background-work -name draft.png -print -quit)
    uv run --project studio_core python scripts/spikes/slice_look.py \
      --outdir ~/ai-studio/scratch/slice-look \
      --background "$BG"

The script launches Blender headlessly for the painterly 2.5D render, then makes a
flat-colour/outlines 2D treatment and a labelled comparison image with Pillow.
It never saves changes into the source rig.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

try:
    import bpy
    from mathutils import Vector

    IN_BLENDER = True
except ModuleNotFoundError:
    IN_BLENDER = False


RAIN_BLEND = Path.home() / "ai-studio/assets/blender-studio-rigs/rain/Rain v3.3/rain_v3.2.blend"
BLENDER = Path("/opt/homebrew/bin/blender")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--background", type=Path, required=True)
    parser.add_argument("--rain", type=Path, default=RAIN_BLEND)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--render-pass", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def blender_render(args: argparse.Namespace) -> None:
    scene = bpy.context.scene
    rig = bpy.data.objects.get("RIG-rain")
    if rig is None or rig.type != "ARMATURE":
        raise RuntimeError("Rain armature RIG-rain was not found")

    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 64
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    with contextlib.suppress(TypeError):
        scene.view_settings.look = "AgX - Medium High Contrast"

    # Keep the pose inside the official rig: disable the UI script, use the documented
    # IK hand targets, and lower both wrists to relaxed positions beside the thighs.
    settings = rig.pose.bones.get("Properties_IKFK")
    if settings is None:
        raise RuntimeError("Rain's Properties_IKFK control was not found")
    settings["ik_arm_left"] = 1.0
    settings["ik_arm_right"] = 1.0
    bpy.context.view_layer.update()
    for side, sign in (("L", 1.0), ("R", -1.0)):
        hand = rig.pose.bones.get(f"IK-Hand.{side}")
        if hand is None:
            raise RuntimeError(f"Rain's IK-Hand.{side} control was not found")
        matrix = hand.matrix.copy()
        matrix.translation = Vector((sign * 0.34, -0.025, 0.76))
        hand.matrix = matrix
        hand.rotation_mode = "XYZ"
        hand.rotation_euler = (0.0, sign * 1.57079632679, 0.0)
    body = bpy.data.objects.get("GEO-rain-body")
    if body and body.data.shape_keys:
        for name, value in (("FingerBends1", 0.24), ("FingerBends2", 0.18), ("FingerBends3", 0.12)):
            key = body.data.shape_keys.key_blocks.get(name)
            if key:
                key.value = value
    bpy.context.view_layer.update()
    rig.location.x = -0.9
    bpy.context.view_layer.update()

    # Rig widgets are editor controls, not film elements.
    for obj in bpy.data.objects:
        if obj.name.startswith("WGT-"):
            obj.hide_render = True

    # An emissive, painted plate stays identical in both comparisons.
    image = bpy.data.images.load(str(args.background.resolve()), check_existing=True)
    bg_mesh = bpy.data.meshes.new("LOOK-meadow-plate-mesh")
    bg_mesh.from_pydata(
        [(-4.4, -1.65, 0), (4.4, -1.65, 0), (4.4, 1.65, 0), (-4.4, 1.65, 0)],
        [],
        [(0, 1, 2, 3)],
    )
    uv = bg_mesh.uv_layers.new(name="UVMap")
    for loop, coords in zip(uv.data, ((0, 0), (1, 0), (1, 1), (0, 1)), strict=True):
        loop.uv = coords
    bg = bpy.data.objects.new("LOOK-meadow-plate", bg_mesh)
    scene.collection.objects.link(bg)
    bg.location = (0, 1.8, 0.75)
    bg.rotation_euler.x = 1.57079632679
    mat = bpy.data.materials.new("LOOK-painted-plate")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = image
    tex.interpolation = "Linear"
    emission = nodes.new("ShaderNodeEmission")
    output = nodes.new("ShaderNodeOutputMaterial")
    links.new(tex.outputs["Color"], emission.inputs["Color"])
    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    bg.data.materials.append(mat)

    # Same perspective camera and character placement for both looks.
    target = Vector((0.0, 0.0, 0.92))
    camera_data = bpy.data.cameras.new("LOOK-camera")
    camera = bpy.data.objects.new("LOOK-camera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = (0.0, -6.0, 1.48)
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera_data.lens = 50
    camera_data.dof.focus_distance = (target - camera.location).length
    camera_data.dof.aperture_fstop = 5.6
    camera_data.dof.aperture_blades = 6
    scene.camera = camera

    world = scene.world or bpy.data.worlds.new("LOOK-world")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes.get("Background").inputs["Color"].default_value = (0.23, 0.29, 0.22, 1)
    world.node_tree.nodes.get("Background").inputs["Strength"].default_value = 0.42

    def area_light(
        name: str,
        location: tuple[float, float, float],
        power: float,
        size: float,
        color: tuple[float, float, float],
    ) -> None:
        light_data = bpy.data.lights.new(name, "AREA")
        light_data.energy = power
        light_data.shape = "DISK"
        light_data.size = size
        light_data.color = color
        light = bpy.data.objects.new(name, light_data)
        scene.collection.objects.link(light)
        light.location = location
        light.rotation_euler = (target - light.location).to_track_quat("-Z", "Y").to_euler()

    area_light("LOOK-warm-key", (-3.0, -4.0, 4.6), 500, 3.8, (1.0, 0.79, 0.52))
    area_light("LOOK-soft-fill", (2.8, -3.2, 2.5), 180, 3.2, (0.68, 0.82, 1.0))
    area_light("LOOK-rim", (0.5, 1.0, 3.6), 360, 2.5, (1.0, 0.68, 0.36))

    args.outdir.mkdir(parents=True, exist_ok=True)
    scene.camera.data.dof.use_dof = True
    scene.render.filepath = str((args.outdir / "render_base.png").resolve())
    bpy.ops.render.render(write_still=True)

    # Build the distinct 2D candidate with per-material three-tone EEVEE ramps,
    # preserving each source material's texture colour and alpha.
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.name.startswith("GEO-rain-"):
            continue
        for index, original in enumerate(list(obj.data.materials)):
            if original is None or not original.use_nodes:
                continue
            toon = original.copy()
            toon.name = f"LOOK-2D-{original.name}"
            nodes, links = toon.node_tree.nodes, toon.node_tree.links
            principled = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
            output = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
            if principled is None:
                continue
            output = output or nodes.new("ShaderNodeOutputMaterial")
            base_socket = principled.inputs["Base Color"]
            alpha_socket = principled.inputs["Alpha"]
            diffuse = nodes.new("ShaderNodeBsdfDiffuse")
            diffuse.inputs["Color"].default_value = (1, 1, 1, 1)
            to_rgb = nodes.new("ShaderNodeShaderToRGB")
            to_bw = nodes.new("ShaderNodeRGBToBW")
            ramp = nodes.new("ShaderNodeValToRGB")
            cr = ramp.color_ramp
            cr.interpolation = "CONSTANT"
            cr.elements[0].color = (0.42, 0.48, 0.40, 1)
            cr.elements[1].position = 0.72
            cr.elements[1].color = (1.0, 1.0, 1.0, 1)
            middle = cr.elements.new(0.42)
            middle.color = (0.72, 0.78, 0.67, 1)
            multiply = nodes.new("ShaderNodeMixRGB")
            multiply.blend_type = "MULTIPLY"
            multiply.inputs["Fac"].default_value = 1.0
            if base_socket.is_linked:
                links.new(base_socket.links[0].from_socket, multiply.inputs["Color1"])
            else:
                multiply.inputs["Color1"].default_value = base_socket.default_value
            emission = nodes.new("ShaderNodeEmission")
            links.new(diffuse.outputs["BSDF"], to_rgb.inputs["Shader"])
            links.new(to_rgb.outputs["Color"], to_bw.inputs["Color"])
            links.new(to_bw.outputs["Val"], ramp.inputs["Fac"])
            links.new(ramp.outputs["Color"], multiply.inputs["Color2"])
            links.new(multiply.outputs["Color"], emission.inputs["Color"])
            if alpha_socket.is_linked or alpha_socket.default_value < 0.999:
                transparent = nodes.new("ShaderNodeBsdfTransparent")
                mix_shader = nodes.new("ShaderNodeMixShader")
                if alpha_socket.is_linked:
                    links.new(alpha_socket.links[0].from_socket, mix_shader.inputs["Fac"])
                else:
                    mix_shader.inputs["Fac"].default_value = alpha_socket.default_value
                links.new(transparent.outputs["BSDF"], mix_shader.inputs[1])
                links.new(emission.outputs["Emission"], mix_shader.inputs[2])
                links.new(mix_shader.outputs["Shader"], output.inputs["Surface"])
                with contextlib.suppress(AttributeError, TypeError):
                    toon.surface_render_method = "DITHERED"
            else:
                links.new(emission.outputs["Emission"], output.inputs["Surface"])
            obj.data.materials[index] = toon

    camera_data.dof.use_dof = False
    scene.render.filepath = str((args.outdir / "render_2d_base.png").resolve())
    bpy.ops.render.render(write_still=True)


def make_2d_and_compare(args: argparse.Namespace) -> None:
    from PIL import Image, ImageDraw, ImageFilter, ImageOps

    source = Image.open(args.outdir / "render_base.png").convert("RGB")
    toon_source = Image.open(args.outdir / "render_2d_base.png").convert("RGB")
    painterly = ImageOps.posterize(source, bits=5)
    soft_edges = (
        source.convert("L").filter(ImageFilter.GaussianBlur(1.3)).filter(ImageFilter.FIND_EDGES)
    )
    soft_mask = soft_edges.point(lambda value: 74 if value > 47 else 0)
    ink = Image.new("RGB", source.size, (43, 54, 45))
    painterly = Image.composite(ink, painterly, soft_mask)
    painterly.save(args.outdir / "look_2_5d.png", optimize=True)

    hsv = toon_source.convert("HSV")
    hue, saturation, value = hsv.split()
    value = value.point(lambda level: 74 if level < 82 else 158 if level < 166 else 238)
    flat = Image.merge("HSV", (hue, saturation, value)).convert("RGB")
    edges = flat.convert("L").filter(ImageFilter.GaussianBlur(1.3)).filter(ImageFilter.FIND_EDGES)
    mask = edges.point(lambda level: 255 if level > 72 else 0).filter(ImageFilter.MaxFilter(3))
    flat.paste(Image.new("RGB", flat.size, (30, 47, 47)), mask=mask)
    flat.save(args.outdir / "look_2d.png", optimize=True)
    (args.outdir / "render_base.png").unlink()
    (args.outdir / "render_2d_base.png").unlink()

    width, height = 960, 540
    pair = Image.new("RGB", (width * 2, height + 46), (247, 242, 224))
    draw = ImageDraw.Draw(pair)
    draw.text((24, 14), "FLAT 2D LOOK", fill=(34, 47, 42))
    draw.text((width + 24, 14), "PAINTERLY 2.5D LOOK", fill=(34, 47, 42))
    pair.paste(flat.resize((width, height), Image.Resampling.LANCZOS), (0, 46))
    pair.paste(painterly.resize((width, height), Image.Resampling.LANCZOS), (width, 46))
    pair.save(args.outdir / "compare.png", optimize=True)

    metadata = {
        "created_utc": datetime.now(UTC).isoformat(),
        "character": "Rain, Blender Studio rig, CC-BY 4.0",
        "background": str(args.background.resolve()),
        "background_seed": 1031,
        "background_style": "storybook (local SDXL Base 1.0 + Storybook LoRA)",
        "resolution": [source.width, source.height],
        "camera": "50mm perspective, identical framing for both looks",
        "pose": "Rain rig IK hand targets lowered beside thighs",
        "2d_treatment": (
            "EEVEE three-tone material ramp plus three-level value quantization "
            "and restrained ink edges"
        ),
        "2_5d_treatment": (
            "EEVEE, 5-bit color, subtle ink edges, warm key and rim, soft fill, depth of field"
        ),
    }
    (args.outdir / "look_test.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"LOOK_TEST_OK {args.outdir / 'compare.png'}")


def main() -> None:
    if IN_BLENDER:
        argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
        args = parse_args(argv)
        blender_render(args)
        return

    args = parse_args(sys.argv[1:])
    if not args.background.is_file() or not args.rain.is_file():
        raise FileNotFoundError("the Rain rig and background image must both exist")
    args.outdir.mkdir(parents=True, exist_ok=True)
    command = [
        str(BLENDER),
        "-b",
        str(args.rain),
        "--python",
        str(Path(__file__).resolve()),
        "--",
        "--render-pass",
        "--outdir",
        str(args.outdir.resolve()),
        "--background",
        str(args.background.resolve()),
        "--rain",
        str(args.rain.resolve()),
        "--width",
        str(args.width),
        "--height",
        str(args.height),
    ]
    subprocess.run(command, check=True)
    if (
        not (args.outdir / "render_base.png").is_file()
        or not (args.outdir / "render_2d_base.png").is_file()
    ):
        raise RuntimeError(
            "Blender returned without producing both look render bases; see its error output above"
        )
    make_2d_and_compare(args)


if __name__ == "__main__":
    main()
