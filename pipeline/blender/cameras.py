"""Preset cameras matching the client renders (island-local coords, metres, Z-up).
Two-point perspective like the Corona originals: camera kept level, framing via lens shift.

Used by: setup_cameras() from other scripts, and standalone:
blender -b scene.blend -P cameras.py -- <outdir> [samples] [groups]   -> renders cam_<name>.png for comparison
"""
import math
import os
import sys

import bpy
from mathutils import Vector

# name: (position, look-at (yaw only), lens mm (36mm sensor), shift_y, resolution)
# solved against the client renders with web/src/dev/solveCamera.ts (silhouette + point fit, rms 0.7-6.7 px);
# look-at = point of the view ray nearest to the island centre (orbit pivot in the web viewer)
CAMERAS = {
    "030": ((0.67, -6.609, 1.183), (0.602, 0.006), 35.57, 0.1273, (2000, 1414)),
    "08": ((4.56, 0.022, 1.12), (-0.0, 0.016), 25.71, 0.0489, (1414, 2000)),
    "10": ((3.437, -2.301, 1.121), (0.278, 0.333), 22.84, 0.0589, (1414, 2000)),
    "12": ((-4.999, -0.03, 1.1), (0.0, -0.03), 32.19, 0.1425, (1414, 2000)),
}


def setup_cameras(scene):
    made = {}
    for name, (pos, look, lens, shift_y, res) in CAMERAS.items():
        cd = bpy.data.cameras.get("Cam_" + name) or bpy.data.cameras.new("Cam_" + name)
        cd.lens = lens
        cd.sensor_fit = "AUTO"
        cd.sensor_width = 36
        cd.shift_y = shift_y
        cd.clip_start = 0.05
        cd.clip_end = 100
        cd["nik_resolution"] = list(res)
        ob = bpy.data.objects.get("Cam_" + name) or bpy.data.objects.new("Cam_" + name, cd)
        if ob.name not in scene.collection.objects:
            scene.collection.objects.link(ob)
        ob.location = pos
        yaw = math.atan2(look[1] - pos[1], look[0] - pos[0])
        ob.rotation_euler = (math.pi / 2, 0, yaw - math.pi / 2)
        made[name] = ob
    return made


if __name__ == "__main__" and "--" in sys.argv:
    args = sys.argv[sys.argv.index("--") + 1:]
    out = args[0]
    samples = int(args[1]) if len(args) > 1 else 96
    groups = args[2].split(",") if len(args) > 2 else ["LM_kitchen", "LM_ostrov", "LM_pol"]
    os.makedirs(out, exist_ok=True)
    sc = bpy.context.scene
    cams = setup_cameras(sc)
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type != "CPU"
    sc.cycles.device = "GPU"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"
    for c in bpy.data.collections:
        if c.name.startswith("LM_"):
            c.hide_render = c.name not in groups
    if "LM_kitchen" not in groups and sc.world:
        sc.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0
    for name, ob in cams.items():
        res = CAMERAS[name][4]
        sc.render.resolution_x, sc.render.resolution_y = res[0] // 2, res[1] // 2
        sc.camera = ob
        sc.render.filepath = os.path.join(out, "cam_%s.png" % name)
        bpy.ops.render.render(write_still=True)
    print("done")
