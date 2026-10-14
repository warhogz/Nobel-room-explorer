"""Quick Cycles previews of the room from the client render cameras (light/material sanity check before baking).

blender -b build/blender_room/room.blend -P preview_room.py -- <root> <outdir> [samples] [views] [groups] [scale]
"""
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import room_cameras  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
ROOT, OUT = args[0], args[1]
SAMPLES = int(args[2]) if len(args) > 2 else 64
VIEWS = args[3].split(",") if len(args) > 3 and args[3] != "*" else list(room_cameras.RENDER_CAMERAS)
GROUPS = args[4].split(",") if len(args) > 4 and args[4] != "*" else ["kitchen", "env", "pol", "ostrov"]
SCALE = float(args[5]) if len(args) > 5 else 0.35
os.makedirs(OUT, exist_ok=True)
origin = json.load(open(os.path.join(ROOT, "build", "blender", "origin.json")))["origin_m"]
sc = bpy.context.scene
cams = room_cameras.setup(sc, room_cameras.load(ROOT, origin))
sc.render.engine = "CYCLES"
prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.compute_device_type = "OPTIX"
prefs.get_devices()
for d in prefs.devices:
    d.use = d.type != "CPU"
sc.cycles.device = "GPU"
sc.cycles.samples = SAMPLES
sc.cycles.use_denoising = True
sc.cycles.sample_clamp_indirect = 20.0
sc.view_settings.view_transform = "AgX"
sc.view_settings.look = "AgX - Base Contrast" if "AgX - Base Contrast" in [l for l in ["AgX - Base Contrast"]] else "None"
sc.view_settings.exposure = float(os.environ.get("NIK_EXPOSURE", "0"))
for c in bpy.data.collections:
    if c.name.startswith("LM_"):
        c.hide_render = c.name[3:] not in GROUPS
if "env" not in GROUPS:
    sc.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0
for m in bpy.data.materials:  # glass as in the bake: no caustic paths
    nt = m.node_tree
    if nt and nt.nodes.get("BakeShader") and nt.nodes.get("BSDF"):
        out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
        mix = nt.nodes.new("ShaderNodeMixShader")
        lp = nt.nodes.new("ShaderNodeLightPath")
        nt.links.new(lp.outputs["Is Shadow Ray"], mix.inputs[0])
        nt.links.new(nt.nodes["BSDF"].outputs[0], mix.inputs[1])
        nt.links.new(nt.nodes["BakeShader"].outputs[0], mix.inputs[2])
        nt.links.new(mix.outputs[0], out.inputs["Surface"])
for pid in VIEWS:
    ob = cams[pid]
    w, h = room_cameras.RENDER_CAMERAS[pid][1]
    sc.render.resolution_x, sc.render.resolution_y = int(w * SCALE), int(h * SCALE)
    sc.camera = ob
    sc.render.filepath = os.path.join(OUT, "view_%s.png" % pid)
    bpy.ops.render.render(write_still=True)
    print("rendered", pid, flush=True)
