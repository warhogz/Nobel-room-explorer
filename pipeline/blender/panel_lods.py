"""Flat stand-ins for the perforated bronze sheets: the far LOD of each real panel (Unreal: panel_lods_ue.py).

blender -b --factory-startup -P panel_lods.py -- <root>
  in : build/ue/scene.json (objects with the perforated brass material), build/ue/meshes/SM_Metal*.fbx
  out: build/ue/panel_lods/<name>_Flat.fbx  two back-to-back quads on the sheet's mid-plane, same pivot and axes as the
       original FBX, UV 1 = one hole tile (12.5 x 13 mm), so the mip-filtered hole mask replaces the sub-pixel holes
"""
import json
import os
import sys

import bpy
import numpy as np

ROOT = sys.argv[sys.argv.index("--") + 1]
UE = os.path.join(ROOT, "build", "ue")
OUT = os.path.join(UE, "panel_lods")
os.makedirs(OUT, exist_ok=True)
TILE_U, TILE_V = 0.0125, 0.013  # m, measured in build_room.py (perforation period)
scene = json.load(open(os.path.join(UE, "scene.json"), encoding="utf-8"))
perf = {k for k, v in scene["materials"].items() if v.get("origName") == "Material #2147483647"}
panels = [o for o in scene["objects"] if set(o["materials"]) <= perf and o["materials"]]
print("panels", len(panels))

for o in panels:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=os.path.join(UE, o["fbx"]))
    ob = next(x for x in bpy.data.objects if x.type == "MESH")
    me = ob.data
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    # import may leave a transform on the object: work in its local space, export with the same transform
    c = co.mean(0)
    w, v = np.linalg.eigh(np.cov((co - c).T))
    n, a2, a1 = v[:, 0], v[:, 1], v[:, 2]  # smallest spread = normal
    pr = co - c
    u0, u1 = (pr @ a1).min(), (pr @ a1).max()
    v0, v1 = (pr @ a2).min(), (pr @ a2).max()
    mid = c + n * (pr @ n).mean()
    corners = [mid + a1 * u + a2 * vv for u, vv in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))]
    # metres in the scene = FBX units after import scale; the UV tile is in metres of the real sheet
    sc = ob.matrix_world.to_scale()[0]
    uvs = [((u - u0) * sc / TILE_U, (vv - v0) * sc / TILE_V) for u, vv in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))]
    verts = [tuple(p) for p in corners]
    flat = bpy.data.meshes.new(o["name"] + "_Flat")
    flat.from_pydata(verts + verts, [], [(0, 1, 2, 3), (7, 6, 5, 4)])  # front and back
    flat.update()
    lay = flat.uv_layers.new(name="UVMap")
    for poly in flat.polygons:
        for li in poly.loop_indices:
            lay.data[li].uv = uvs[flat.loops[li].vertex_index % 4]
    flat.materials.append(me.materials[0] if me.materials else bpy.data.materials.new("Perf"))
    fo = bpy.data.objects.new(o["name"] + "_Flat", flat)
    bpy.context.scene.collection.objects.link(fo)
    fo.matrix_world = ob.matrix_world.copy()
    bpy.data.objects.remove(ob)
    bpy.ops.object.select_all(action="DESELECT")
    fo.select_set(True)
    bpy.context.view_layer.objects.active = fo
    bpy.ops.export_scene.fbx(filepath=os.path.join(OUT, o["name"] + "_Flat.fbx"), use_selection=True,
                             object_types={"MESH"}, mesh_smooth_type="FACE", use_tspace=False, add_leaf_bones=False,
                             bake_anim=False, path_mode="STRIP", embed_textures=False, apply_unit_scale=True,
                             apply_scale_options="FBX_SCALE_NONE", axis_forward="-Z", axis_up="Y")
    print("flat", o["name"], round((u1 - u0) * sc, 3), "x", round((v1 - v0) * sc, 3), "m")
print("done")
