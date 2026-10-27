"""Full-detail room (build_room.py with NIK_UE=1) -> files the Unreal build script imports.

blender -b build/blender_ue/room_ue.blend --factory-startup -P export_ue.py -- <root>
  in : build/blender_ue/room_ue.blend, build/materials_ue/materials.json,
       build/export_chandelier/chandelier.fbx + build/materials_chandelier_ue (the sculpture, hidden in Option 9)
  out: build/ue/meshes/SM_*.fbx  one mesh per object, pivot at the object origin (metres, Blender axes)
       build/ue/scene.json       objects, materials, lights, cameras - all positions already in Unreal space

Unreal space: centimetres, left-handed Z-up: (x, y, z)_ue = 100 * (x, -y, z)_blender. The FBX meshes stay in Blender
axes; the importer applies the same mapping (checked against the bounds written here, see build_level.py).
"""
import json
import math
import os
import re
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blender"))
import room_cameras  # noqa: E402

ROOT = sys.argv[sys.argv.index("--") + 1]
B = os.path.join(ROOT, "build")
OUT = os.path.join(B, "ue")
MESHES = os.path.join(OUT, "meshes")
os.makedirs(MESHES, exist_ok=True)
MATS = json.load(open(os.path.join(B, "materials_ue", "materials.json"), encoding="utf-8"))["materials"]
CH_MATS = json.load(open(os.path.join(B, "materials_chandelier_ue", "materials.json"), encoding="utf-8"))["materials"]
ORIGIN = Vector(json.load(open(os.path.join(B, "blender", "origin.json")))["origin_m"])
scene = bpy.context.scene


def ue(v):
    return [round(v[0] * 100, 4), round(-v[1] * 100, 4), round(v[2] * 100, 4)]


def ue_dir(v):
    v = Vector(v).normalized()
    return [round(v[0], 6), round(-v[1], 6), round(v[2], 6)]


def flags(m):
    try:
        return json.loads(m.get("nik", "{}"))
    except Exception:
        return {}


# ------------------------------------------------------------------ chandelier (full geometry, one mesh per material)
before = set(bpy.data.objects)
bpy.ops.import_scene.fbx(filepath=os.path.join(B, "export_chandelier", "chandelier.fbx"))
ch = [o for o in bpy.data.objects if o not in before]
for o in [o for o in ch if o.type != "MESH"]:
    ch.remove(o)
    bpy.data.objects.remove(o)
for o in ch:
    if o.data.users > 1:
        o.data = o.data.copy()
with bpy.context.temp_override(selected_editable_objects=ch, selected_objects=ch, active_object=ch[0]):
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
by_mat = {}
for o in ch:
    o.location -= ORIGIN
    for uv in list(o.data.uv_layers)[1:]:
        o.data.uv_layers.remove(uv)
    if not o.data.uv_layers:
        o.data.uv_layers.new(name="UVMap")
    o.data.uv_layers[0].name = "UVMap"
    base = o.material_slots[0].material.name.split(".")[0] if o.material_slots and o.material_slots[0].material else "Default"
    by_mat.setdefault(base, []).append(o)
ch_spec = {}
GLASS_TARGET = 450000  # faces of the glass sculpture (1.8 M non-Nanite triangles cost every frame and every shadow)
for base, objs in by_mat.items():
    spec = dict(CH_MATS.get(base, {"name": base, "baseColor": [0.5, 0.5, 0.5], "roughness": 0.5, "metallic": 0.0}))
    if spec.get("transmission"):
        total = sum(len(o.data.polygons) for o in objs)
        ratio = min(1.0, GLASS_TARGET / max(total, 1))
        for o in objs:
            f = len(o.data.polygons)
            if ratio < 1.0 and f > 500:
                md = o.modifiers.new("dec", "DECIMATE")
                md.ratio = max(ratio, 500.0 / f)
                md.use_collapse_triangulate = True
                with bpy.context.temp_override(object=o, active_object=o):
                    bpy.ops.object.modifier_apply(modifier=md.name)
        print("chandelier glass %d -> %d faces" % (total, sum(len(o.data.polygons) for o in objs)))
    mid = "CH_" + base
    spec["name"] = mid
    ch_spec[mid] = spec
    mat = bpy.data.materials.new(mid)
    if spec.get("transmission"):
        mat["nik"] = json.dumps({"glass": True, "orig": spec.get("origName")})
    for o in objs:
        o.data.materials.clear()
        o.data.materials.append(mat)
    with bpy.context.temp_override(active_object=objs[0], selected_editable_objects=objs, selected_objects=objs):
        bpy.ops.object.join()
    objs[0].name = objs[0].data.name = "Chandelier_" + re.sub(r"[^A-Za-z0-9]+", "_", spec.get("origName") or base).strip("_")
    objs[0]["nik_bake"] = "none"
print("chandelier parts", {k: len(v) for k, v in by_mat.items()})

# ------------------------------------------------------------------ meshes
used = set()


def asset_name(name):
    s = "SM_" + re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")
    n, k = s, 1
    while n.lower() in used:
        k += 1
        n = "%s_%d" % (s, k)
    used.add(n.lower())
    return n


objects = []
mat_used = {}
meshes = [o for o in scene.objects if o.type == "MESH" and o.data.polygons]
for i, o in enumerate(meshes):
    # build_room applies rotation / scale into the mesh; anything left over goes into the data as well
    basis = o.matrix_world.copy()
    loc = basis.to_translation()
    rest = Matrix.Translation(-loc) @ basis
    if not all(abs(rest[r][c] - (1.0 if r == c else 0.0)) < 1e-6 for r in range(4) for c in range(4)):
        o.data.transform(rest)
    o.matrix_world = Matrix.Identity(4)
    co = np.empty(len(o.data.vertices) * 3, np.float32)
    o.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    lo, hi = Vector(co.min(0).tolist()), Vector(co.max(0).tolist())
    name = asset_name(o.name)
    slots = []
    for m in o.data.materials:
        mname = m.name if m else "Default"
        slots.append(mname)
        mat_used.setdefault(mname, flags(m) if m else {})
    # one FBX per object, pivot = object origin
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    o.name = name
    path = os.path.join(MESHES, name + ".fbx")
    bpy.ops.export_scene.fbx(filepath=path, use_selection=True, object_types={"MESH"}, use_mesh_modifiers=True,
                             mesh_smooth_type="FACE", use_tspace=False, add_leaf_bones=False, bake_anim=False,
                             path_mode="STRIP", embed_textures=False, apply_unit_scale=True,
                             apply_scale_options="FBX_SCALE_NONE", axis_forward="-Z", axis_up="Y")
    o.matrix_world = Matrix.Translation(loc)
    objects.append({
        "name": name, "source": o.get("nik_src", o.name), "fbx": os.path.relpath(path, OUT).replace("\\", "/"),
        "location": ue(loc), "faces": len(o.data.polygons), "bake": o.get("nik_bake"),
        # local bounds in Unreal axes (y flips: min/max swap)
        "boundsMin": [lo.x * 100, -hi.y * 100, lo.z * 100], "boundsMax": [hi.x * 100, -lo.y * 100, hi.z * 100],
        "materials": slots,
    })
    if i % 50 == 0:
        print("exported %d/%d %s" % (i + 1, len(meshes), name), flush=True)

# ------------------------------------------------------------------ materials
materials = {}
REPORT = json.load(open(os.path.join(B, "blender_ue", "room_report.json"), encoding="utf-8"))
PERF = REPORT.get("perforation") or {}  # only with NIK_UE_FLAT_PANELS=1
for mname, fl in mat_used.items():
    spec = ch_spec.get(mname) or MATS.get(mname)
    if mname == "Perforated_Bronze":
        # the flat panels (build_room.py): the brass of the original, plus the hole mask / bevel normal at 1 UV = 1 hole tile
        base_key = next(k for k, v in MATS.items() if v.get("origName") == "Material #2147483647")
        spec = dict(MATS[base_key], name="Perforated_Bronze",
                    perforated={"tile_m": PERF.get("tile_m"), "metal_fraction": PERF.get("metal_fraction"),
                                "mask": os.path.join(B, "blender_ue", "tex", "perf_mask.png").replace("\\", "/"),
                                "normal": os.path.join(B, "blender_ue", "tex", "perf_nrm.png").replace("\\", "/")})
    if spec is None:
        m = bpy.data.materials.get(mname)
        bsdf = m.node_tree.nodes.get("BSDF") if m and m.use_nodes else None
        col = list(bsdf.inputs["Base Color"].default_value)[:3] if bsdf else [0.5, 0.5, 0.5]
        spec = {"name": mname, "baseColor": col, "roughness": bsdf.inputs["Roughness"].default_value if bsdf else 0.6,
                "metallic": 0.0}
    materials[mname] = dict(spec, flags=fl)

# ------------------------------------------------------------------ lights
lights = []
for cname in ("LM_kitchen", "LM_env", "LM_pol", "LM_ostrov"):
    col = bpy.data.collections.get(cname)
    for ob in (col.objects if col else []):
        ld = ob.data
        M = ob.matrix_world
        fwd = M.to_3x3() @ Vector((0, 0, -1))  # Blender lights shine down their local -Z
        up = M.to_3x3() @ Vector((0, 1, 0))
        d = {"name": ob.name, "group": cname[3:], "type": ld.type, "location": ue(M.to_translation()),
             "forward": ue_dir(fwd), "up": ue_dir(up), "watts": ld.energy, "color": list(ld.color),
             "radius": getattr(ld, "shadow_soft_size", 0.0)}
        if ld.type == "AREA":
            d.update(shape=ld.shape, size=ld.size, sizeY=ld.size_y, spread=math.degrees(ld.spread))
        if ld.type == "SUN":
            d.update(angle=math.degrees(ld.angle))
        if ld.node_tree:
            ies = next((n for n in ld.node_tree.nodes if n.type == "TEX_IES"), None)
            if ies:
                d.update(ies=os.path.abspath(bpy.path.abspath(ies.filepath)))
        lights.append(d)

# ------------------------------------------------------------------ cameras (the client renders)
cameras = {}
for pid, c in room_cameras.load(ROOT, ORIGIN).items():
    w, h = c["resolution"]
    cameras[pid] = {"corona": c["corona"], "location": ue(c["position"]), "forward": ue_dir(c["dir"]), "lens": c["lens"],
                    "sensor": [36.0, 36.0 * h / w] if w >= h else [36.0 * w / h, 36.0],
                    "shiftMm": c["shift_y"] * 36.0, "resolution": [w, h], "near": c["clip"] * 100}

world = scene.world
json.dump({"objects": objects, "materials": materials, "lights": lights, "cameras": cameras,
           "textures": os.path.join(B, "materials_ue", "tex").replace("\\", "/"),
           "envStrength": float(world.get("nik_env_strength", 1.0)) if world else 1.0},
          open(os.path.join(OUT, "scene.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("done: objects", len(objects), "materials", len(materials), "lights", len(lights), "faces",
      sum(o["faces"] for o in objects))
