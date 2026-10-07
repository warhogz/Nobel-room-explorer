# blender -b <scene.blend> -P preview_views.py -- <outdir> [engine]
# Quick look renders of the island from several directions (workbench by default, or CYCLES).
import math
import os
import sys

import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
out = args[0]
engine = args[1] if len(args) > 1 else "WORKBENCH"
os.makedirs(out, exist_ok=True)
sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH" if engine == "WORKBENCH" else "CYCLES"
sc.render.resolution_x, sc.render.resolution_y = 900, 600
if engine == "WORKBENCH":
    sh = sc.display.shading
    sh.light = "STUDIO"
    sh.color_type = "TEXTURE"
    sh.show_backface_culling = False
    sh.show_cavity = True
else:
    sc.cycles.samples = 64
    sc.cycles.use_denoising = True
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type != "CPU"
    sc.cycles.device = "GPU"
    sc.view_settings.view_transform = "AgX"
cam_data = bpy.data.cameras.new("pv")
cam_data.lens = 28
cam = bpy.data.objects.new("pv", cam_data)
sc.collection.objects.link(cam)
sc.camera = cam
target = Vector((0, 0, 0.45))
views = {"px": (4, 0, 1.2), "nx": (-4, 0, 1.2), "py": (0, 4, 1.2), "ny": (0, -4, 1.2), "top": (0.01, 0, 5.5),
         "low_px": (3, 1.5, 0.15)}
for name, pos in views.items():
    cam.location = pos
    d = target - Vector(pos)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = os.path.join(out, "view_%s.png" % name)
    bpy.ops.render.render(write_still=True)
print("done")
