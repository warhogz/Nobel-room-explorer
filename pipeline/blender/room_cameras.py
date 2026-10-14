"""Client render cameras taken straight from the Corona cameras of the villa file (build/dump_full/cameras.json).

Corona: horizontal fov, auto vertical tilt (two-point perspective) and a near clipping plane that cuts through the
walls in front of the camera. Here: a level camera with vertical lens shift reproducing the tilt, clip_start = the
Corona near clip. Coordinates: Blender/island-local (metres, Z-up).
"""
import json
import math
import os

from mathutils import Matrix, Vector

FT = 0.3048
# web preset id -> (Corona camera, render resolution)
RENDER_CAMERAS = {
    "030": ("Corona Camera039", (2000, 1414)),
    "08": ("Corona Camera008", (1414, 2000)),
    "10": ("Corona Camera010", (1414, 2000)),
    "12": ("Corona Camera012", (1414, 2000)),
    "28": ("Corona Camera027", (1414, 2000)),
}


def load(root, origin):
    cams = {c["name"]: c for c in json.load(open(os.path.join(root, "build", "dump_full", "cameras.json"), encoding="utf-8"))}
    out = {}
    for pid, (name, res) in RENDER_CAMERAS.items():
        c = cams[name]
        t = c["transform"]
        M = Matrix([[t[col][row] for col in range(3)] for row in range(3)])
        fwd = -(M @ Vector((0, 0, 1))).normalized()  # Max cameras look down their local -Z
        pos = Vector(c["pos"]) * FT - Vector(origin)
        p = c["props"]
        w, h = res
        tan_h = math.tan(math.radians(p["fov"]) / 2)  # Corona fov is horizontal
        tan_big = tan_h * max(w, h) / w
        lens = 18.0 / tan_big  # 36 mm sensor on the larger side
        pitch = math.asin(max(-1.0, min(1.0, fwd.z)))
        shift_y = math.tan(pitch) * lens / 36.0
        yaw_dir = Vector((fwd.x, fwd.y, 0)).normalized()
        out[pid] = {
            "corona": name, "position": tuple(pos), "dir": tuple(yaw_dir), "lens": lens, "shift_y": shift_y,
            "resolution": res, "clip": (p.get("clippingNear") or 0.0) * FT if p.get("enableClipping") else 0.0,
        }
    return out


def setup(scene, presets):
    import bpy

    made = {}
    for pid, cp in presets.items():
        cd = bpy.data.cameras.get("Cam_" + pid) or bpy.data.cameras.new("Cam_" + pid)
        cd.lens = cp["lens"]
        cd.sensor_fit = "AUTO"
        cd.sensor_width = 36
        cd.shift_y = cp["shift_y"]
        cd.clip_start = max(0.05, cp["clip"])
        cd.clip_end = 200
        ob = bpy.data.objects.get("Cam_" + pid) or bpy.data.objects.new("Cam_" + pid, cd)
        if ob.name not in scene.collection.objects:
            scene.collection.objects.link(ob)
        ob.location = cp["position"]
        yaw = math.atan2(cp["dir"][1], cp["dir"][0])
        ob.rotation_euler = (math.pi / 2, 0, yaw - math.pi / 2)
        made[pid] = ob
    return made
