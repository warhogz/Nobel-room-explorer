"""Chandelier sculpture -> web GLB (loaded after the room; not baked: glass + bronze shade from the room probes).

blender -b --factory-startup -P build_chandelier.py -- <root>
  in : build/export_chandelier/{chandelier.fbx, room_manifest.json}, build/materials_chandelier/{materials.json, tex/}
  out: build/web_room/chandelier.glb
"""
import json
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nikmat import build_material  # noqa: E402

ROOT = sys.argv[sys.argv.index("--") + 1]
B = os.path.join(ROOT, "build")
SRC = os.path.join(B, "export_chandelier")
MATS = json.load(open(os.path.join(B, "materials_chandelier", "materials.json"), encoding="utf-8"))["materials"]
TEX = os.path.join(B, "materials_chandelier", "tex")
ORIGIN = Vector(json.load(open(os.path.join(B, "blender", "origin.json")))["origin_m"])
CAP = 2500  # faces per glass piece (the sculpture has ~400 of them)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=os.path.join(SRC, "chandelier.fbx"))
for o in list(bpy.context.scene.objects):
    if o.type != "MESH":
        bpy.data.objects.remove(o)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
for o in meshes:
    if o.data.users > 1:
        o.data = o.data.copy()
with bpy.context.temp_override(selected_editable_objects=meshes, selected_objects=meshes, active_object=meshes[0]):
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
print("meshes", len(meshes), "faces", sum(len(o.data.polygons) for o in meshes))
for o in meshes:
    o.location -= ORIGIN
    for uv in list(o.data.uv_layers)[1:]:
        o.data.uv_layers.remove(uv)
    if not o.data.uv_layers:
        o.data.uv_layers.new(name="UVMap")
    o.data.uv_layers[0].name = "UVMap"
    f = len(o.data.polygons)
    if f > CAP:
        md = o.modifiers.new("dec", "DECIMATE")
        md.ratio = CAP / f
        md.use_collapse_triangulate = True
        with bpy.context.temp_override(object=o, active_object=o):
            bpy.ops.object.modifier_apply(modifier=md.name)
built = {}
for o in meshes:
    for slot in o.material_slots:
        base = slot.material.name.split(".")[0] if slot.material else "Default"
        if base not in built:
            spec = MATS.get(base, {"name": base, "baseColor": [0.5, 0.5, 0.5]})
            built[base] = build_material(spec, TEX, "Chandelier_" + (spec.get("origName") or base).replace("#", "").replace(" ", "_"))
        slot.material = built[base]
for m in list(bpy.data.materials):
    if m not in built.values():
        bpy.data.materials.remove(m)
# one mesh per material
by = {}
for o in meshes:
    by.setdefault(o.material_slots[0].material.name, []).append(o)
for name, objs in by.items():
    with bpy.context.temp_override(active_object=objs[0], selected_editable_objects=objs, selected_objects=objs):
        bpy.ops.object.join()
    objs[0].name = objs[0].data.name = name
    print("joined", name, len(objs), "faces", len(objs[0].data.polygons))
out = os.path.join(B, "web_room", "chandelier.glb")
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_extras=True, export_yup=True, export_apply=True,
                          export_texcoords=True, export_normals=True, export_materials="EXPORT", export_vertex_color="NONE")
print("exported", out, os.path.getsize(out))
