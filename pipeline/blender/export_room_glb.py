"""Exports the baked room for the web: blender -b build/blender_room/room_baked.blend -P export_room_glb.py -- <out_dir>
-> <out_dir>/room.glb, cameras.json, lights.json, vertex_lm.json

- materials back to plain Principled (bake-only nodes removed); nik flags travel as material extras
- VX_* objects: baked irradiance colour attributes LM_kitchen / LM_env -> RGBM (range 16, per-group scale) in the
  custom glTF attributes _NIKK / _NIKE (Blender 5.2 writes all but the last COLOR_n attribute as white)
"""
import json
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import room_cameras  # noqa: E402

ARGS = sys.argv[sys.argv.index("--") + 1:]
OUT = ARGS[0]
# --lite: the phone scene - the island set, the kitchen floor and the furniture standing around the island
LITE = "--lite" in ARGS
os.makedirs(OUT, exist_ok=True)
sc = bpy.context.scene
RANGE = 16.0

for m in bpy.data.materials:
    if not m.node_tree:
        continue
    nt = m.node_tree
    o = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if o is None or "BSDF" not in nt.nodes:
        continue
    for l in list(o.inputs["Surface"].links):
        nt.links.remove(l)
    nt.links.new(nt.nodes["BSDF"].outputs[0], o.inputs["Surface"])
    for n in [n for n in nt.nodes if n.name in ("BakeTarget", "TranslMix", "Translucent", "TranslTex", "BakeShader")]:
        nt.nodes.remove(n)

# ---- vertex lightmaps -> RGBM colour attributes
vx = [o for o in sc.objects if o.type == "MESH" and o.get("nik_bake") == "vertex"]
scales = {}
for g in ("kitchen", "env"):
    vals = []
    for o in vx:
        a = o.data.color_attributes.get("LM_" + g)
        if a is None:
            continue
        buf = np.empty(len(a.data) * 4, np.float32)
        a.data.foreach_get("color", buf)
        vals.append(buf.reshape(-1, 4)[:, :3].max(1))
    if not vals:
        continue
    allv = np.concatenate(vals)
    ref = float(np.percentile(allv, 99.9)) if allv.size else 1.0
    scales[g] = 12.0 / ref if ref > 1e-6 else 1.0
for o in vx:
    me = o.data
    for g, tag in (("kitchen", "_NIKK"), ("env", "_NIKE")):
        a = me.color_attributes.get("LM_" + g)
        n = len(me.vertices)
        rgbm = np.zeros((n, 4), np.float32)
        if a is not None and g in scales:
            buf = np.empty(len(a.data) * 4, np.float32)
            a.data.foreach_get("color", buf)
            v = np.nan_to_num(buf.reshape(-1, 4)[:, :3]).clip(0, None) * scales[g]
            mm = np.clip(v.max(1, keepdims=True) / RANGE, 0, 1)
            mm = np.ceil(mm * 255.0) / 255.0
            rgb = np.where(mm > 0, v / np.maximum(mm * RANGE, 1e-8), 0)
            rgbm = np.hstack([np.clip(rgb, 0, 1), mm]).astype(np.float32)
        b = me.attributes.new(tag, "FLOAT_COLOR", "POINT")
        b.data.foreach_set("color", rgbm.ravel())
    for g in ("kitchen", "env"):
        a = me.color_attributes.get("LM_" + g)
        if a is not None:
            me.color_attributes.remove(a)
    o["nik_vertex_lm"] = True
json.dump({"range": RANGE, "scales": scales, "objects": [o.name for o in vx]},
          open(os.path.join(OUT, "vertex_lm.json"), "w"), indent=1)
print("vertex lightmaps", len(vx), scales)

# ---- visible area per material (texture budget: big surfaces get 2K high-quality textures)
import numpy as _np  # noqa: E402

areas = {}
for ob in sc.objects:
    if ob.type != "MESH":
        continue
    me = ob.data
    a = _np.empty(len(me.polygons), _np.float32)
    me.polygons.foreach_get("area", a)
    mi = _np.empty(len(me.polygons), _np.int32)
    me.polygons.foreach_get("material_index", mi)
    s = ob.matrix_world.to_scale()
    k = abs(s.x * s.y)
    for i, slot in enumerate(ob.material_slots):
        if slot.material:
            areas[slot.material.name] = areas.get(slot.material.name, 0.0) + float(a[mi == i].sum()) * k
json.dump(areas, open(os.path.join(OUT, "material_area.json"), "w"), indent=1)

# ---- cameras: the Corona cameras of the client renders (presets travel as JSON: glTF drops lens shift)
ROOT = os.path.abspath(os.path.join(os.path.dirname(bpy.data.filepath), "..", ".."))
origin = json.load(open(os.path.join(ROOT, "build", "blender", "origin.json")))["origin_m"]
presets = {}
for name, cp in room_cameras.load(ROOT, origin).items():
    pos, d = cp["position"], cp["dir"]
    t = max(1.0, -(pos[0] * d[0] + pos[1] * d[1]))  # orbit pivot: point of the view ray nearest to the island
    look = (pos[0] + d[0] * t, pos[1] + d[1] * t)
    presets[name] = {"position": [pos[0], pos[2], -pos[1]], "target": [look[0], pos[2], -look[1]],
                     "lens": cp["lens"], "sensor": 36.0, "shiftY": cp["shift_y"], "resolution": list(cp["resolution"]),
                     "near": cp["clip"], "corona": cp["corona"]}
json.dump(presets, open(os.path.join(OUT, "cameras.json"), "w"), indent=1)
fixtures = []
pol = bpy.data.collections.get("LM_pol")
for ob in sorted(pol.objects if pol else [], key=lambda o: o.get("nik_index", 0)):
    p = ob.location
    fixtures.append({"index": int(ob.get("nik_index", 0)), "name": ob.name, "position": [p.x, p.z, -p.y]})
json.dump({"pol": fixtures}, open(os.path.join(OUT, "lights.json"), "w"), indent=1)

if LITE:
    import bmesh  # noqa: E402

    KEEP = {"Island", "Table", "Faucets", "Plants", "Planters", "Floor_Kitchen"}
    # island zone in Blender metres (island centre = origin): inside the kitchen walls, below the pendant height
    ZX, ZY, ZZ = (-1.9, 2.6), (-2.0, 2.0), 1.6
    for ob in list(sc.objects):
        if ob.type != "MESH":
            if ob.type not in ("CAMERA",):
                bpy.data.objects.remove(ob)
            continue
        if ob.name in KEEP:
            continue
        if ob.get("nik_bake") not in ("vertex", "none"):
            bpy.data.objects.remove(ob)
            continue
        # dense furniture chunks: whole pieces (connected parts) whose centre stands in the island zone
        me = ob.data
        nv = len(me.vertices)
        co = np.empty(nv * 3, np.float32)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3) + np.array(ob.matrix_world.translation, np.float32)
        ev = np.empty(len(me.edges) * 2, np.int64)
        me.edges.foreach_get("vertices", ev)
        ev = ev.reshape(-1, 2)
        lab = np.arange(nv)
        while True:  # connected components by label propagation
            m = np.minimum(lab[ev[:, 0]], lab[ev[:, 1]])
            new = lab.copy()
            np.minimum.at(new, ev[:, 0], m)
            np.minimum.at(new, ev[:, 1], m)
            new = new[new]
            if np.array_equal(new, lab):
                break
            lab = new
        cnt = np.bincount(lab, minlength=nv).astype(np.float64)
        cen = np.stack([np.bincount(lab, co[:, k], minlength=nv) for k in range(3)], 1) / np.maximum(cnt, 1)[:, None]
        inside = (ZX[0] < cen[:, 0]) & (cen[:, 0] < ZX[1]) & (ZY[0] < cen[:, 1]) & (cen[:, 1] < ZY[1]) & (cen[:, 2] < ZZ)
        keep_v = inside[lab]
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.verts.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not keep_v[v.index]], context="VERTS")
        bm.to_mesh(me)
        bm.free()
        if not me.polygons:
            bpy.data.objects.remove(ob)
    for m in list(bpy.data.materials):
        if m.users == 0:
            bpy.data.materials.remove(m)
    print("lite objects", {o.name: len(o.data.polygons) for o in sc.objects if o.type == "MESH"})
json.dump([o.name for o in sc.objects if o.type == "MESH"], open(os.path.join(OUT, "objects.json"), "w"), indent=1)

for ob in sc.objects:
    if ob.type == "MESH" and "UVMap" in ob.data.uv_layers:
        ob.data.uv_layers["UVMap"].active_render = True
out = os.path.join(OUT, "room.glb")
kw = dict(filepath=out, export_format="GLB", export_extras=True, export_cameras=True, export_lights=False,
          export_yup=True, export_apply=True, export_texcoords=True, export_normals=True, export_tangents=False,
          export_materials="EXPORT", export_image_format="AUTO", use_selection=False)
bpy.ops.export_scene.gltf(**kw, export_vertex_color="NONE", export_attributes=True)
print("exported", out, os.path.getsize(out))
