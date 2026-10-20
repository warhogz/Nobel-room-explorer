"""Bake-ready Blender scene of the whole kitchen + double-height hall (villa crop from export_room.py).

blender -b --factory-startup -P build_room.py -- <root>
  in : build/export_room/{room.fbx, room_manifest.json}, build/materials_room/{materials.json, tex/},
       build/dump_full/{lights.json, refs.json, render.json} (Corona lights, LightMix), build/dump/objects.json
       (names of the island set from the first file), build/blender/origin.json (web origin = island centre)
  out: build/blender_room/room.blend, room_report.json, tex/perf_*.png

Scene organisation (object custom props drive bake_room.py / export):
  nik_bake = "lightmap" (+ nik_lightmap = size)  : low-poly architecture, joined into atlases LM_Atlas_NN
           = "vertex"                            : dense furniture, irradiance baked to colour attributes (VX_NN)
           = "none"                              : glass, pure emitters (Static_NN)
  Island / Table / Faucets / Plants / Planters    : the hero set, same treatment as the island-only scene
  Floor_Kitchen / Floor_Hall                      : travertine floor split at the kitchen opening
Lights: Corona lights converted to Cycles (radiance units, IES), pre-multiplied by their Corona LightMix layer and
sorted into the web LightMix groups LM_kitchen / LM_env (suns + sky) / LM_pol (8 floor uplights) / LM_ostrov.
"""
import json
import math
import os
import re
import sys
import time

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nikmat import build_material, nik_flags  # noqa: E402

ROOT = sys.argv[sys.argv.index("--") + 1]
B = os.path.join(ROOT, "build")
OUT = os.path.join(B, "blender_room")
TEXOUT = os.path.join(OUT, "tex")
os.makedirs(TEXOUT, exist_ok=True)
MANIFEST = json.load(open(os.path.join(B, "export_room", "room_manifest.json"), encoding="utf-8"))
MATS = json.load(open(os.path.join(B, "materials_room", "materials.json"), encoding="utf-8"))["materials"]
TEX = os.path.join(B, "materials_room", "tex")
ORIGIN = Vector(json.load(open(os.path.join(B, "blender", "origin.json")))["origin_m"])
BOX = MANIFEST["box"]  # x0, x1, y0, y1 (metres, relative to the origin)
FT = 0.3048
T0 = time.time()
report = {}


def log(*a):
    print("[%6.1fs]" % (time.time() - T0), *a, flush=True)


ORIG_NAME = {k: (v.get("origName") or k) for k, v in MATS.items()}


def orig(mat):
    return ORIG_NAME.get(mat.name.split(".")[0], mat.name) if mat else None


def mats_of(o):
    return {orig(m) for m in o.data.materials if m}


# ------------------------------------------------------------------ import + normalise
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
bpy.ops.import_scene.fbx(filepath=os.path.join(B, "export_room", "room.fbx"))
log("fbx imported")
for o in list(scene.objects):
    if o.type != "MESH":
        bpy.data.objects.remove(o)
meshes = [o for o in scene.objects if o.type == "MESH"]
for o in meshes:
    if o.data.users > 1:
        o.data = o.data.copy()
with bpy.context.temp_override(selected_editable_objects=meshes, selected_objects=meshes, active_object=meshes[0]):
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
log("meshes", len(meshes), "faces", sum(len(o.data.polygons) for o in meshes))

# objects with sheared transforms (non-uniform scale under rotation) re-exported with Reset XForm
# (pipeline/max/export_xform_fix.py): their mesh replaces the distorted one, in world space
FIX = os.path.join(B, "export_room", "xform_fix.fbx")
if os.path.exists(FIX):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=FIX)
    fixed = [o for o in bpy.data.objects if o not in before]
    by_name = {o.name: o for o in meshes}
    swapped = flipped = 0

    def outwardness(me):
        """area-weighted sum of (face normal . face centre - centroid): > 0 when the faces point outwards"""
        n = len(me.polygons)
        if not n:
            return 0.0
        nr = np.empty(n * 3, np.float32)
        ce = np.empty(n * 3, np.float32)
        ar = np.empty(n, np.float32)
        me.polygons.foreach_get("normal", nr)
        me.polygons.foreach_get("center", ce)
        me.polygons.foreach_get("area", ar)
        ce = ce.reshape(-1, 3)
        return float((np.einsum("ij,ij->i", nr.reshape(-1, 3), ce - ce.mean(0)) * ar).sum())

    for f in fixed:
        tgt = by_name.get(re.sub(r"\.\d{3}$", "", f.name))
        if f.type == "MESH" and tgt is not None and f.data.vertices:
            f.data.transform(f.matrix_world)
            f.data.transform(Matrix.Translation(-tgt.location))
            # mirrored objects: Reset XForm may leave the faces inside-out; keep the winding the original had
            # (the vertex bake shoots its rays along the normals - inside-out furniture bakes black)
            if outwardness(f.data) * outwardness(tgt.data) < 0:
                f.data.flip_normals()
                flipped += 1
            old = tgt.data
            tgt.data = f.data
            if old.users == 0:
                bpy.data.meshes.remove(old)
            swapped += 1
        bpy.data.objects.remove(f)
    report["xform_fixed"] = swapped
    log("xform fix: replaced", swapped, "of", len(fixed), "flipped", flipped)

# validate against the Max export manifest (world metres, before any processing)
man = {d["name"]: d for d in MANIFEST["objects"]}
bad = []
for o in meshes:
    d = man.get(o.name)
    if not d or not o.data.vertices:
        continue
    co = np.empty(len(o.data.vertices) * 3, np.float32)
    o.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3) + np.array(o.location)
    c1 = (co.min(0) + co.max(0)) / 2
    c0 = (np.array(d["bboxMin_m"]) + np.array(d["bboxMax_m"])) / 2
    err = float(np.linalg.norm(c1 - c0))
    if err > 0.02:
        bad.append((o.name, round(err, 3)))
        # same shape, wrong place (sheared / scaled parents the FBX transform cannot carry, e.g. the Marvelous
        # Designer pillows): put it back where Max has it
        s1 = co.max(0) - co.min(0)
        s0 = np.array(d["bboxMax_m"]) - np.array(d["bboxMin_m"])
        if err > 0.04 and np.all(np.abs(s1 - s0) <= 0.1 * np.maximum(s0, 0.05)):
            o.location += Vector((c0 - c1).tolist())
            report.setdefault("bbox_moved", []).append((o.name, round(err, 3)))
report["bbox_mismatch"] = bad
log("bbox check:", "OK" if not bad else "%d mismatches, worst %s" % (len(bad), sorted(bad, key=lambda x: -x[1])[:5]))
log("moved back:", report.get("bbox_moved"))
if any(n == "Object2121349745" and e > 0.05 for n, e in bad):
    raise SystemExit("island moved during export")

for o in meshes:
    o.location -= ORIGIN
    for uv in list(o.data.uv_layers)[1:]:
        o.data.uv_layers.remove(uv)
    if len(o.data.uv_layers) == 0:
        o.data.uv_layers.new(name="UVMap")
    o.data.uv_layers[0].name = "UVMap"
    for ca in list(o.data.color_attributes):
        o.data.color_attributes.remove(ca)


# ------------------------------------------------------------------ crop to the box (big shells cross it)
def world_bounds(o):
    co = np.empty(len(o.data.vertices) * 3, np.float32)
    o.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3) + np.array(o.location)
    return co.min(0), co.max(0)


MARGIN = 0.3
clip = [BOX[0] - MARGIN, BOX[1] + MARGIN, BOX[2] - MARGIN, BOX[3] + MARGIN]
clipped = 0
for o in meshes:
    if not o.data.vertices:
        continue
    lo, hi = world_bounds(o)
    planes = []
    if lo[0] < clip[0]:
        planes.append((0, clip[0], True))
    if hi[0] > clip[1]:
        planes.append((0, clip[1], False))
    if lo[1] < clip[2]:
        planes.append((1, clip[2], True))
    if hi[1] > clip[3]:
        planes.append((1, clip[3], False))
    if not planes:
        continue
    bm = bmesh.new()
    bm.from_mesh(o.data)
    for axis, val, keep_greater in planes:
        co = Vector((0, 0, 0))
        co[axis] = val - o.location[axis]
        no = Vector((0, 0, 0))
        no[axis] = 1.0
        bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=co, plane_no=no,
                               clear_inner=keep_greater, clear_outer=not keep_greater)
    bm.to_mesh(o.data)
    bm.free()
    clipped += 1
for o in [o for o in meshes if len(o.data.polygons) == 0]:
    meshes.remove(o)
    bpy.data.objects.remove(o)
log("clipped", clipped, "objects to the box; meshes now", len(meshes))

# ------------------------------------------------------------------ materials
built = {}


def material_for(name):
    base = name.split(".")[0]
    if base not in built:
        spec = MATS.get(base)
        if spec is None:
            spec = {"name": base, "baseColor": [0.5, 0.5, 0.5], "roughness": 0.6}
            report.setdefault("missing_materials", []).append(base)
        built[base] = build_material(spec, TEX, base + "__pbr")
    return built[base]


for o in meshes:
    if not o.material_slots:
        o.data.materials.append(material_for("Default"))
    for slot in o.material_slots:
        slot.material = material_for(slot.material.name if slot.material else "Default")
for m in list(bpy.data.materials):
    if not m.name.endswith("__pbr"):
        bpy.data.materials.remove(m)
for m in bpy.data.materials:
    m.name = m.name[:-5]
log("materials", len(built))

# ------------------------------------------------------------------ hero set (same rules as the island-only scene)
OLD = {d["name"] for d in json.load(open(os.path.join(B, "dump", "objects.json"), encoding="utf-8"))}
HERO_RULES = {
    "Island": lambda o: mats_of(o) == {"Material #-2147483589"},
    "Table": lambda o: mats_of(o) == {"Material #76111117"},
    "Faucets": lambda o: mats_of(o) == {"Material #-2147483587"},
    "Plants": lambda o: o.name.startswith(("Avizoon", "Strawberry")),
    "Planters": lambda o: o.name.startswith("Soil"),
}


def join(objs, name):
    objs = [o for o in objs if o.name in bpy.data.objects]
    if not objs:
        return None
    if len(objs) > 1:
        with bpy.context.temp_override(active_object=objs[0], selected_editable_objects=objs, selected_objects=objs):
            bpy.ops.object.join()
    ob = objs[0]
    ob.name = ob.data.name = name
    return ob


hero = {}
for o in [o for o in meshes if o.name in OLD]:
    for g, rule in HERO_RULES.items():
        if rule(o):
            hero.setdefault(g, []).append(o)
            break
    else:
        hero.setdefault("Island", []).append(o)  # sink, base: part of the island block
taken = set()
for g, objs in hero.items():
    taken.update(o.name for o in objs)
    ob = join(objs, g)
    log("hero", g, len(objs), "faces", len(ob.data.polygons))
meshes = [o for o in scene.objects if o.type == "MESH"]
HERO_NAMES = set(hero)

# ------------------------------------------------------------------ floor
FLOOR_MATS = {"travertine7567567", "travertine"}
floor_parts = []
for o in meshes:
    if o.name in HERO_NAMES or not (mats_of(o) & FLOOR_MATS):
        continue
    lo, hi = world_bounds(o)
    if hi[2] - lo[2] < 0.05 and abs(hi[2]) < 0.05:
        floor_parts.append(o)
floor = join(floor_parts, "Floor")
KITCHEN_X = 2.72  # kitchen box opening into the hall
bm = bmesh.new()
bm.from_mesh(floor.data)
bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=Vector((KITCHEN_X, 0, 0)) - floor.location,
                       plane_no=Vector((1, 0, 0)))
bm.to_mesh(floor.data)
bm.free()
bpy.ops.object.select_all(action="DESELECT")
floor.select_set(True)
bpy.context.view_layer.objects.active = floor
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="DESELECT")
bpy.ops.object.mode_set(mode="OBJECT")
for p in floor.data.polygons:
    p.select = (floor.matrix_world @ p.center).x > KITCHEN_X
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.separate(type="SELECTED")
bpy.ops.object.mode_set(mode="OBJECT")
floor.name = floor.data.name = "Floor_Kitchen"
hall = [o for o in bpy.context.selected_objects if o != floor][0]
hall.name = hall.data.name = "Floor_Hall"
bpy.ops.mesh.primitive_plane_add(size=1, location=((BOX[0] + BOX[1]) / 2, (BOX[2] + BOX[3]) / 2, -0.006))
ground = bpy.context.active_object
ground.scale = (BOX[1] - BOX[0] + 1, BOX[3] - BOX[2] + 1, 1)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
ground.name = ground.data.name = "Ground"
ground.data.uv_layers[0].name = "UVMap"
gm = build_material({"name": "Grout", "baseColor": [0.06, 0.045, 0.035], "roughness": 0.8}, TEX, "Grout")
ground.data.materials.append(gm)
log("floor parts", len(floor_parts), "kitchen faces", len(floor.data.polygons), "hall faces", len(hall.data.polygons))
meshes = [o for o in scene.objects if o.type == "MESH"]

# slabs and plinths just under the floor (column bases, thresholds): the parts covered by the floor tiles bake black
# and their lightmap bleeds into the few visible centimetres (black rings around columns), and faces a few mm under
# the floor fight with it. Faces facing up, below the floor top and covered by a floor tile are removed.
floor_bvh = [BVHTree.FromObject(f, bpy.context.evaluated_depsgraph_get()) for f in (floor, hall)]
covered_total = 0
for o in meshes:
    if o in (floor, hall, ground) or o.name in HERO_NAMES:
        continue
    lo, hi = world_bounds(o)
    if lo[2] > 0.0 or lo[2] < -0.5:
        continue
    bm = bmesh.new()
    bm.from_mesh(o.data)
    kill = []
    for fc in bm.faces:
        c = fc.calc_center_median() + o.location
        if fc.normal.z < 0.7 or c.z > -0.001:
            continue
        for fb, fo in zip(floor_bvh, (floor, hall)):
            hit = fb.ray_cast(c - fo.location, Vector((0, 0, 1)), 0.3)
            if hit[0] is not None:
                kill.append(fc)
                break
    if kill:
        bmesh.ops.delete(bm, geom=kill, context="FACES")
        bm.to_mesh(o.data)
        covered_total += len(kill)
    bm.free()
report["under_floor_faces_removed"] = covered_total
log("faces hidden under the floor removed:", covered_total)

# what is left of those slabs is a few-centimetre ring around each column base, 2 cm below the floor: as a sliver of
# an atlas it bakes black. It becomes floor: lifted to floor level and joined to the floor (its lightmap and look).
ring_parts = []
# the plinth slabs are stacked copies in the Max file: coincident faces shadow each other completely in the bake
# (Cycles starts its rays on the other copy) and fight in the web - each ring face is taken once
ring_seen = set()
for o in [o for o in meshes if o not in (floor, hall, ground) and o.name not in HERO_NAMES]:
    if not o.data.polygons or not (mats_of(o) & FLOOR_MATS):
        continue
    lo, hi = world_bounds(o)
    if lo[2] > 0.0 or lo[2] < -0.6:
        continue
    sel = [p.index for p in o.data.polygons
           if p.normal.z > 0.9 and -0.06 < (o.matrix_world @ p.center).z < -0.001
           and orig(o.data.materials[p.material_index]) in FLOOR_MATS]
    if not sel:
        continue
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.faces.ensure_lookup_table()
    faces = [bm.faces[i] for i in sel]
    keep = []
    for f in faces:
        c = f.calc_center_median() + o.location
        k = (round(c.x / 0.003), round(c.y / 0.003), round(f.calc_area() * 1e4))
        if k not in ring_seen:
            ring_seen.add(k)
            keep.append(f)
    ring = bpy.data.meshes.new(o.name + "_ring")
    rb = bmesh.new()
    src_uv = bm.loops.layers.uv.active
    dst_uv = rb.loops.layers.uv.new("UVMap")
    vmap = {}
    for f in keep:
        vs = []
        for v in f.verts:
            if v.index not in vmap:
                co = v.co.copy()
                co.z = -o.location.z  # floor level in world space
                vmap[v.index] = rb.verts.new(co)
            vs.append(vmap[v.index])
        try:
            nf = rb.faces.new(vs)
        except ValueError:  # duplicate face
            continue
        nf.material_index = f.material_index
        if src_uv is not None:
            for nl, ol in zip(nf.loops, f.loops):
                nl[dst_uv].uv = ol[src_uv].uv
    rb.to_mesh(ring)
    rb.free()
    for m in o.data.materials:
        ring.materials.append(m)
    ro = bpy.data.objects.new(o.name + "_ring", ring)
    ro.location = o.location
    scene.collection.objects.link(ro)
    ring_parts.append(ro)
    bmesh.ops.delete(bm, geom=faces, context="FACES")
    bm.to_mesh(o.data)
    bm.free()
for ro in ring_parts:
    lo, hi = world_bounds(ro)
    target = hall if (lo[0] + hi[0]) / 2 > KITCHEN_X else floor
    with bpy.context.temp_override(active_object=target, selected_editable_objects=[target, ro], selected_objects=[target, ro]):
        bpy.ops.object.join()
report["floor_rings_joined"] = len(ring_parts)
log("column-base rings joined to the floor:", len(ring_parts))

# bottom caps flush with the floor top (walls, column bases, furniture): never seen (back faces from above), but in the
# bake they lie on the floor tiles like a lid - the floor under them bakes black and shows as black rings around the
# column bases and black bands along the walls. Removed where a floor tile lies right under them.
floor_bvh = [(BVHTree.FromObject(f, bpy.context.evaluated_depsgraph_get()), f) for f in (floor, hall)]
caps_total = 0
for o in [o for o in scene.objects if o.type == "MESH" and o not in (floor, hall, ground)]:
    mw = o.matrix_world
    n3 = mw.to_3x3()
    bm = bmesh.new()
    bm.from_mesh(o.data)
    kill = []
    for fc in bm.faces:
        c = mw @ fc.calc_center_median()
        if abs(c.z) > 0.004 or (n3 @ fc.normal).normalized().z > -0.9:
            continue
        for fb, fo in floor_bvh:
            if fb.ray_cast(fo.matrix_world.inverted() @ (c + Vector((0, 0, 0.002))), Vector((0, 0, -1)), 0.008)[0] is not None:
                kill.append(fc)
                break
    if kill:
        bmesh.ops.delete(bm, geom=kill, context="FACES_ONLY")
        bm.to_mesh(o.data)
        caps_total += len(kill)
    bm.free()
report["floor_caps_removed"] = caps_total
log("bottom caps lying on the floor removed:", caps_total)
meshes = [o for o in scene.objects if o.type == "MESH"]


# ------------------------------------------------------------------ perforated bronze panels -> flat panels + texture
def pca_frame(co):
    c = co.mean(0)
    u, s, vt = np.linalg.svd(co - c, full_matrices=False)
    return c, vt  # rows: main axis, second, normal


def hull2d(p):
    p = sorted(set(map(tuple, np.round(p, 5))))
    if len(p) < 3:
        return np.array(p)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for q in p:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    for q in reversed(p):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return np.array(lower[:-1] + upper[:-1])


def min_rect_angle(h):
    best = (1e9, 0.0)
    for i in range(len(h)):
        e = h[(i + 1) % len(h)] - h[i]
        a = math.atan2(e[1], e[0])
        R = np.array([[math.cos(-a), -math.sin(-a)], [math.sin(-a), math.cos(-a)]])
        q = h @ R.T
        area = np.ptp(q[:, 0]) * np.ptp(q[:, 1])
        if area < best[0]:
            best = (area, a)
    return best[1]


PERF_MAT = "Material #2147483647"
perf = [o for o in meshes if o.name not in HERO_NAMES and mats_of(o) == {PERF_MAT}]
perf_info = None
if perf:
    # measure the hole pattern on the biggest panel by ray casting through it
    ref = max(perf, key=lambda o: len(o.data.polygons))
    co = np.array([ref.matrix_world @ v.co for v in ref.data.vertices])
    c, ax = pca_frame(co)
    h = hull2d((co - c) @ ax[:2].T)
    a = min_rect_angle(h)
    u = ax[0] * math.cos(a) + ax[1] * math.sin(a)
    v = np.cross(ax[2], u)
    n = ax[2]
    bvh = BVHTree.FromObject(ref, bpy.context.evaluated_depsgraph_get())
    N, S = 400, 0.00025  # 10 x 10 cm patch, 0.25 mm per ray
    hits = np.zeros((N, N), bool)
    for i in range(N):
        for j in range(N):
            p = Vector(c + u * ((j - N / 2) * S) + v * ((i - N / 2) * S) + n * 0.05) - ref.location  # BVH: object space
            hits[i, j] = bvh.ray_cast(p, Vector(-n), 0.1)[0] is not None
    metal = hits.mean()

    def period(sig):
        sig = sig - sig.mean()
        ac = np.correlate(sig, sig, "full")[len(sig) - 1:]
        ac /= ac[0] if ac[0] else 1
        for k in range(3, len(ac) - 1):  # first local max after the first dip below zero
            if ac[k] > ac[k - 1] and ac[k] >= ac[k + 1] and ac[:k].min() < 0 and ac[k] > 0.3:
                return k
        return None
    pu = np.median([p for p in (period(hits[i].astype(float)) for i in range(0, N, 20)) if p] or [0])
    pv = np.median([p for p in (period(hits[:, j].astype(float)) for j in range(0, N, 20)) if p] or [0])
    perf_info = {"panel": ref.name, "metal_fraction": float(metal), "period_u_mm": pu * S * 1000, "period_v_mm": pv * S * 1000}
    log("perforation:", perf_info)
    if pu and pv:
        # tile = an integer number of periods (~6 mm+), resampled to 256 px; holes -> alpha 0
        ku, kv = max(1, int(round(6 / (pu * S * 1000)))), max(1, int(round(6 / (pv * S * 1000))))
        tu, tv = int(pu * ku), int(pv * kv)
        tile = hits[N // 2 - tv // 2:N // 2 - tv // 2 + tv, N // 2 - tu // 2:N // 2 - tu // 2 + tu].astype(np.float32)
        perf_info["tile_m"] = [tu * S, tv * S]
    report["perforation"] = perf_info


def write_png(path, arr):
    """arr: HxWxC float 0..1 (row 0 = top) via a Blender image"""
    h, w = arr.shape[:2]
    c = arr.shape[2] if arr.ndim == 3 else 1
    rgba = np.ones((h, w, 4), np.float32)
    rgba[..., :c] = arr.reshape(h, w, c)
    if c == 1:
        rgba[..., 1] = rgba[..., 2] = rgba[..., 0]
    im = bpy.data.images.new(os.path.basename(path), w, h, alpha=True)
    im.pixels.foreach_set(np.flipud(rgba).ravel())
    im.filepath_raw = path
    im.file_format = "PNG"
    im.save()
    return im


perf_mat = None
if perf_info and perf_info.get("tile_m"):
    # mask (1 = metal) at 256 px, smooth edges; normal map from a bevelled height
    from math import ceil
    ys = np.linspace(0, tile.shape[0] - 1, 256)
    xs = np.linspace(0, tile.shape[1] - 1, 256)
    m = tile[np.clip(np.round(ys).astype(int), 0, tile.shape[0] - 1)][:, np.clip(np.round(xs).astype(int), 0, tile.shape[1] - 1)]
    k = np.ones(5) / 5
    blur = lambda x: np.apply_along_axis(lambda r: np.convolve(np.concatenate([r[-2:], r, r[:2]]), k, "valid"), 1, x)
    hm = blur(blur(m).T).T
    dx = (np.roll(hm, -1, 1) - np.roll(hm, 1, 1)) * 2.5
    dy = (np.roll(hm, -1, 0) - np.roll(hm, 1, 0)) * 2.5
    nrm = np.dstack([-dx, dy, np.ones_like(hm)])
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    write_png(os.path.join(TEXOUT, "perf_mask.png"), hm[..., None])
    write_png(os.path.join(TEXOUT, "perf_nrm.png"), nrm * 0.5 + 0.5)
    spec = dict(MATS[[k for k, v in ORIG_NAME.items() if v == PERF_MAT][0]])
    perf_mat = build_material(spec, TEX, "Perforated_Bronze")
    nt = perf_mat.node_tree
    bsdf = nt.nodes["BSDF"]
    tu_m, tv_m = perf_info["tile_m"]
    # panel UVs are in hole tiles: the bronze textures get their own ~0.6 m repeat
    for tn in [n for n in nt.nodes if n.type == "TEX_IMAGE"]:
        tc0 = nt.nodes.new("ShaderNodeUVMap")
        tc0.uv_map = "UVMap"
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (tu_m / 0.6, tv_m / 0.6, 1.0)
        nt.links.new(tc0.outputs["UV"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], tn.inputs["Vector"])
    for n in [n for n in nt.nodes if n.type == "NORMAL_MAP"]:
        nt.nodes.remove(n)
    tc = nt.nodes.new("ShaderNodeUVMap")
    tc.uv_map = "UVMap"
    nm_t = nt.nodes.new("ShaderNodeTexImage")
    nm_t.image = bpy.data.images.load(os.path.join(TEXOUT, "perf_nrm.png"))
    nm_t.image.colorspace_settings.name = "Non-Color"
    nt.links.new(tc.outputs["UV"], nm_t.inputs["Vector"])
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(nm_t.outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    perf_mat.use_backface_culling = False
    flags = nik_flags(perf_mat)
    flags.update({"perforated": True, "tile_m": perf_info["tile_m"]})
    perf_mat["nik"] = json.dumps(flags)

replaced = 0
if perf_mat:
    tu_m, tv_m = perf_info["tile_m"]
    for o in perf:
        co = np.array([o.matrix_world @ v.co for v in o.data.vertices])
        c, ax = pca_frame(co)
        thick = np.ptp((co - c) @ ax[2])
        if thick > 0.03:
            continue  # not a flat sheet
        h = hull2d((co - c) @ ax[:2].T)
        a = min_rect_angle(h)
        u = ax[0] * math.cos(a) + ax[1] * math.sin(a)
        v = np.cross(ax[2], u)
        pts = [c + ax[0] * p[0] + ax[1] * p[1] for p in h]
        # face the room: normal towards the hall's central axis
        inside = np.array([min(15.0, max(-1.0, c[0])), 0.0, 1.5])
        if np.dot(np.cross(pts[1] - pts[0], pts[2] - pts[0]), inside - c) < 0:
            pts = pts[::-1]
        me = bpy.data.meshes.new(o.name)
        verts = [Vector(p) - o.location for p in pts]
        me.from_pydata([tuple(x) for x in verts], [], [list(range(len(verts)))])
        me.uv_layers.new(name="UVMap")
        for loop in me.loops:
            p = np.array(verts[loop.vertex_index] + o.location) - c
            me.uv_layers[0].data[loop.index].uv = (float(p @ u) / tu_m, float(p @ v) / tv_m)
        me.materials.append(perf_mat)
        old = o.data
        o.data = me
        bpy.data.meshes.remove(old)
        replaced += 1
log("perforated panels replaced:", replaced, "of", len(perf))
report["perforated_replaced"] = replaced

# ------------------------------------------------------------------ decimate dense purchased models
CAP = 12000
# chair seats and backs are seen up close and are all curves: decimated to 12k they read faceted
CAP_SEAT = 40000
SEAT = re.compile(r"^(sitting|chair|stool|seat)", re.I)
dec = 0
for o in scene.objects:
    if o.type != "MESH" or o.name in HERO_NAMES or o.name.startswith(("Floor", "Ground")):
        continue
    f = len(o.data.polygons)
    cap = CAP_SEAT if SEAT.match(o.name) else CAP
    if f > cap:
        md = o.modifiers.new("dec", "DECIMATE")
        md.ratio = cap / f
        md.use_collapse_triangulate = True
        with bpy.context.temp_override(object=o, active_object=o):
            bpy.ops.object.modifier_apply(modifier=md.name)
        dec += 1
log("decimated", dec, "objects; faces now", sum(len(o.data.polygons) for o in scene.objects if o.type == "MESH"))


# ------------------------------------------------------------------ classify + join
def area_of(o):
    a = np.empty(len(o.data.polygons), np.float32)
    o.data.polygons.foreach_get("area", a)
    return float(a.sum())


def kind(o):
    fl = [nik_flags(m) for m in o.data.materials if m]
    if fl and all(f.get("glass") for f in fl):
        return "none"
    if fl and all(f.get("emissive") for f in fl):
        return "none"
    # sparse meshes need texels; dense ones carry the light in their vertices
    return "lightmap" if len(o.data.vertices) / max(area_of(o), 1e-6) < 300 else "vertex"


rest = [o for o in scene.objects if o.type == "MESH" and o.name not in HERO_NAMES and not o.name.startswith(("Floor", "Ground"))]
ground["nik_bake"] = "none"
by_kind = {"lightmap": [], "vertex": [], "none": []}
for o in rest:
    by_kind[kind(o)].append(o)
log({k: len(v) for k, v in by_kind.items()})

TEXEL = 56.0  # lightmap texels per metre in the room atlases
ATLAS = 4096
CAP_AREA = ATLAS * ATLAS * 0.5 / TEXEL ** 2
lm = sorted(by_kind["lightmap"], key=lambda o: tuple(sum(world_bounds(o))[:2] / 2))
chunks, cur, acc = [], [], 0.0
for o in lm:
    ar = area_of(o)
    if cur and acc + ar > CAP_AREA:
        chunks.append(cur)
        cur, acc = [], 0.0
    cur.append(o)
    acc += ar
if cur:
    chunks.append(cur)
atlases = []
for i, ch in enumerate(chunks):
    ob = join(ch, "LM_Atlas_%02d" % i)
    ob["nik_bake"] = "lightmap"
    ob["nik_lightmap"] = ATLAS
    atlases.append(ob)
    log("atlas", ob.name, len(ch), "objects, area %.0f m2" % sum([area_of(ob)]))


def chunked(objs, prefix, max_faces, tag):
    objs = sorted(objs, key=lambda o: (world_bounds(o)[0][0], o.location.y))
    out, cur, acc = [], [], 0
    for o in objs:
        f = len(o.data.polygons)
        if cur and acc + f > max_faces:
            out.append(cur)
            cur, acc = [], 0
        cur.append(o)
        acc += f
    if cur:
        out.append(cur)
    made = []
    for i, ch in enumerate(out):
        ob = join(ch, "%s_%02d" % (prefix, i))
        ob["nik_bake"] = tag
        made.append(ob)
    return made


vx = chunked(by_kind["vertex"], "VX", 350000, "vertex")
st = chunked(by_kind["none"], "Static", 200000, "none")
log("vertex chunks", len(vx), "static chunks", len(st))
LIGHTMAPPED = {"Island": 2048, "Table": 1024, "Planters": 256, "Floor_Kitchen": 2048, "Floor_Hall": 4096}
for name, size in LIGHTMAPPED.items():
    if name in bpy.data.objects:
        bpy.data.objects[name]["nik_bake"] = "lightmap"
        bpy.data.objects[name]["nik_lightmap"] = size
for name in ("Faucets", "Plants"):
    if name in bpy.data.objects:
        bpy.data.objects[name]["nik_bake"] = "none"


# ------------------------------------------------------------------ doubled and buried faces
# The Max scene stacks copies of the same cladding (stair pillar, thresholds) and presses parts onto each other
# (wall and plinth bottoms on slabs). Cycles bakes such faces black - its rays start inside the other copy - and
# three.js z-fights them: the black striped bands at the thresholds and the stair pillar. A face goes when every
# sample point of it is covered within 2 mm by
#   - a same-material face facing the same way, coplanar or in front (one copy stays: a deleted face covers nothing), or
#   - a face pressed onto it from the front, when the space in front of that leads into a closed solid (the first
#     surface a ray meets there is a back face), so no camera ever sees it. A two-sided sheet (open space beyond)
#     keeps both sides.
def doubled_faces(gap=0.002):
    t = time.time()
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    objs = [o for o in scene.objects if o.type == "MESH" and o is not ground and o.data.polygons]
    trees = []
    for o in objs:
        lo, hi = world_bounds(o)
        trees.append((o, BVHTree.FromObject(o, dg), Vector(lo) - Vector((gap,) * 3), Vector(hi) + Vector((gap,) * 3)))
    mat_name = {o.name: [m.name if m else "" for m in o.data.materials] for o in objs}

    def covers(o, p, s, n, mname):
        """covering faces at world point s: (obj name, face index, 'same'|'pressed')"""
        out = []
        for o2, tree, lo, hi in trees:
            if not (lo.x <= s.x <= hi.x and lo.y <= s.y <= hi.y and lo.z <= s.z <= hi.z):
                continue
            for hl, hn, hi_, _ in tree.find_nearest_range(s - o2.location, gap):
                if o2 is o and hi_ == p.index:
                    continue
                dv = hl + o2.location - s
                along = dv.dot(n)
                if along < -2e-4 or (dv - n * along).length > 2e-4:
                    continue
                d = hn.dot(n)
                if d > 0.98:
                    p2 = o2.data.polygons[hi_]
                    if mat_name[o2.name][p2.material_index] == mname:
                        out.append((o2.name, hi_, "same"))
                elif d < -0.98:
                    out.append((o2.name, hi_, "pressed"))
        return out

    cands = []  # (obj, face, [covers per sample point], pressed ok)
    for o in objs:
        if o.name.startswith("Floor"):
            continue
        me = o.data
        names = mat_name[o.name]
        for p in me.polygons:
            if p.area < 1e-4:
                continue
            n = p.normal
            c = p.center
            pts = [c] + [c.lerp(me.vertices[v].co, 0.85) for v in p.vertices]
            per = []
            for s in pts:
                cv = covers(o, p, s + o.location, n, names[p.material_index])
                if not cv:
                    break
                per.append(cv)
            else:
                pressed_ok = False
                if any(k == "pressed" for cv in per for _, _, k in cv):
                    hit, loc, hn, _, _, _ = scene.ray_cast(dg, c + o.location + n * (gap + 5e-4), n, distance=50.0)
                    pressed_ok = bool(hit) and hn.dot(n) > 0.0
                cands.append((o, p.index, per, pressed_ok))
    # one mesh island at a time (candidate faces linked by shared edges), so one whole copy goes and the other stays
    island = {}
    for o in objs:
        mine = [fi for oo, fi, _, _ in cands if oo is o]
        if not mine:
            continue
        parent = {fi: fi for fi in mine}

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        by_edge = {}
        for fi in mine:
            for ek in o.data.polygons[fi].edge_keys:
                if ek in by_edge:
                    parent[find(fi)] = find(by_edge[ek])
                else:
                    by_edge[ek] = fi
        for fi in mine:
            island[(o.name, fi)] = find(fi)
    order = {o.name: i for i, o in enumerate(objs)}
    cands.sort(key=lambda c: (order[c[0].name], island[(c[0].name, c[1])], c[1]))
    deleted = set()
    kill = {}
    counts = {"same": 0, "pressed": 0}
    area = 0.0
    for o, fi, per, pressed_ok in cands:
        kinds = []
        for cv in per:
            k = next((k for on, i, k in cv if k == "same" and (on, i) not in deleted), None)
            if k is None and pressed_ok and any(k2 == "pressed" for _, _, k2 in cv):
                k = "pressed"
            if k is None:
                break
            kinds.append(k)
        else:
            deleted.add((o.name, fi))
            kill.setdefault(o.name, []).append(fi)
            counts["pressed" if "pressed" in kinds else "same"] += 1
            area += o.data.polygons[fi].area
    for name, idx in kill.items():
        o = scene.objects[name]
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[bm.faces[i] for i in idx], context="FACES")
        bm.to_mesh(o.data)
        bm.free()
    report["doubled_faces_removed"] = dict(counts, area_m2=round(area, 2))
    log("doubled/buried faces removed:", counts, "%.1f m2" % area, {k: len(v) for k, v in kill.items()}, "%.0fs" % (time.time() - t))


doubled_faces()

# ------------------------------------------------------------------ lightmap UVs
for o in [o for o in scene.objects if o.type == "MESH" and o.get("nik_bake") == "lightmap"]:
    size = int(o["nik_lightmap"])
    t = time.time()
    lmuv = o.data.uv_layers.new(name="Lightmap")
    o.data.uv_layers["UVMap"].active_render = True
    o.data.uv_layers.active = lmuv
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    margin = 4.0 / size
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=margin, area_weight=0.0,
                             correct_aspect=True, scale_to_bounds=False)
    bpy.ops.uv.pack_islands(rotate=True, margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")
    log("lightmap UV", o.name, size, "faces", len(o.data.polygons), "%.0fs" % (time.time() - t))

# ------------------------------------------------------------------ lights
DUMP = os.path.join(B, "dump_full")
R = json.load(open(os.path.join(DUMP, "refs.json"), encoding="utf-8"))
REN = R[json.load(open(os.path.join(DUMP, "render.json"), encoding="utf-8"))["renderer"]["$ref"]]["props"]
LIGHTS = json.load(open(os.path.join(DUMP, "lights.json"), encoding="utf-8"))
mix_names = REN.get("colormap_lightselect_elementNames") or []
mix_cols = REN.get("colorMap_lightmixColors") or []
mix_ints = REN.get("colorMap_lightmixIntensities") or []
node_layer = {}
ls_index = 0
for el in json.load(open(os.path.join(DUMP, "render.json"), encoding="utf-8"))["renderElements"]:
    e = R[el["$ref"]]
    if e["class"] != "CShading_LightSelect":
        continue
    name = e["props"].get("elementName")
    for nd in e["props"].get("includedNodes") or []:
        if isinstance(nd, dict) and "$node" in nd:
            node_layer.setdefault(nd["$node"], (ls_index, name))
    ls_index += 1


def layer_mix(idx):
    if idx is None or idx >= len(mix_ints):
        return (1.0, 1.0, 1.0), 1.0
    c = mix_cols[idx]
    rgb = c["rgb"] if isinstance(c, dict) else c
    rgb = [x / 255.0 if max(rgb) > 1.5 else x for x in rgb[:3]]
    return tuple(rgb), float(mix_ints[idx])


REST_IDX = next((i for i, n in enumerate(mix_names) if n.startswith("Rest")), None)
ENV_IDX = next((i for i, n in enumerate(mix_names) if n.startswith("Environment")), None)
WEB_GROUP = {"SUN": "env", "SUN BIG": "env", "SUN3": "env", "TOCHKI POL": "pol", "OSTROV": "ostrov"}


def blackbody(t):
    """approximate linear sRGB of a blackbody (Tanner Helland fit, normalised)"""
    t = t / 100.0
    r = 255.0 if t <= 66 else 329.698727446 * (t - 60) ** -0.1332047592
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * (t - 60) ** -0.0755148492
    b = 255.0 if t >= 66 else (0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307)
    c = [max(0.0, min(255.0, x)) / 255.0 for x in (r, g, b)]
    c = [x ** 2.2 for x in c]
    m = max(c)
    return [x / m for x in c]


def coll(name):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if c.name not in scene.collection.children:
        scene.collection.children.link(c)
    return c


IES_K = 14.59  # Cycles IES texture output = candela / IES_K (measured: point light + 036.ies)


def ies_peak(path):
    vals = open(path, encoding="latin-1").read().split("TILT=")[1].split()[1:]
    nums = [float(x) for x in vals]
    n_v, n_h = int(nums[3]), int(nums[4])
    mult = nums[2]
    start = 13 + n_v + n_h
    return max(nums[start:start + n_v * n_h]) * mult


cols = {g: coll("LM_" + g) for g in ("kitchen", "env", "pol", "ostrov")}
made_lights = []
for L in LIGHTS:
    p = L["props"]
    if not p.get("on", True) or L.get("hidden"):
        continue
    M = Matrix([[L["transform"][c][r] for c in range(4)] for r in range(3)] + [[0, 0, 0, 1]])
    pos = Vector(L["pos"]) * FT - ORIGIN
    idx, layer = node_layer.get(L["name"], (REST_IDX, "Rest"))
    group = WEB_GROUP.get(layer, "kitchen")
    mcol, mint = layer_mix(idx)
    if L["class"] == "CoronaSun":
        tgt = Vector((L.get("target") or {}).get("pos", (0, 0, 0))) * FT - ORIGIN
        d = (tgt - pos).normalized()
        ld = bpy.data.lights.new(L["name"], "SUN")
        ld.energy = 1000.0 * float(p.get("intensity", 1.0)) * mint  # ~1 kW/m2 for a real sun, x LightMix
        ld.angle = math.radians(0.53 * float(p.get("sizeMultiplier", 1.0)))
        ld.color = [c * k for c, k in zip(blackbody(5800), mcol)]
        ob = bpy.data.objects.new(L["name"], ld)
        ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        ob.location = pos
        cols["env"].objects.link(ob)
        made_lights.append((ob.name, "env", layer))
        continue
    if not (BOX[0] - 1 <= pos.x <= BOX[1] + 1 and BOX[2] - 1 <= pos.y <= BOX[3] + 1):
        continue
    rot = M.to_3x3()
    sx, sy = rot.col[0].length, rot.col[1].length
    rot = rot.normalized()
    shape = p.get("shape", 0)
    w = float(p.get("width") or 0.1) * FT * sx
    hgt = float(p.get("height") or 0.1) * FT * sy
    L_rad = float(p.get("intensity", 1.0))  # W/(sr m2)
    if p.get("colorMode") == 1:
        col = blackbody(float(p.get("blackbodyTemp", 6500)))
    else:
        c = (p.get("color") or {}).get("rgb", [255, 255, 255])
        col = [(x / 255.0) ** 2.2 for x in c]
    col = [c * k for c, k in zip(col, mcol)]
    ies = None
    if p.get("iesOn") and p.get("iesFile"):
        cand = os.path.join(B, "tex_full", os.path.basename(str(p["iesFile"]).replace("\\", "/")))
        ies = cand if os.path.exists(cand) else None
    if shape == 0:  # sphere, width = radius
        r = max(w, 0.005)
        area = 4 * math.pi * r * r
        ld = bpy.data.lights.new(L["name"], "POINT")
        ld.shadow_soft_size = r
        power = L_rad * math.pi * area
    else:
        if shape == 2:  # disk, width = radius
            area = math.pi * w * w
        elif shape == 3:  # cylinder
            area = 2 * math.pi * w * hgt
        else:
            area = w * hgt
        if ies:
            ld = bpy.data.lights.new(L["name"], "POINT")
            ld.shadow_soft_size = max(0.01, math.sqrt(area / math.pi))
            power = 4 * math.pi * L_rad * area  # peak intensity L*A, IES normalised to its peak below
        else:
            ld = bpy.data.lights.new(L["name"], "AREA")
            ld.shape = "DISK" if shape == 2 else "RECTANGLE"
            ld.size = 2 * w if shape == 2 else w
            ld.size_y = 2 * w if shape == 2 else hgt
            d_ = float(p.get("directionality") or 0.0)
            ld.spread = math.radians(max(10.0, 180.0 * (1.0 - d_)))
            power = L_rad * math.pi * area
    ld.energy = power * mint
    ld.color = col
    ob = bpy.data.objects.new(L["name"], ld)
    ob.matrix_world = Matrix.Translation(pos) @ rot.to_4x4()
    if ies:
        try:
            ld.use_nodes = True
        except Exception:
            pass
        nt = ld.node_tree
        em = next(n for n in nt.nodes if n.type == "EMISSION")
        t = nt.nodes.new("ShaderNodeTexIES")
        t.mode = "EXTERNAL"
        t.filepath = ies
        t.inputs["Strength"].default_value = IES_K / ies_peak(ies)
        nt.links.new(t.outputs["Fac"], em.inputs["Strength"])
    cols[group].objects.link(ob)
    if group == "pol":
        ob["nik_pol"] = True
    made_lights.append((ob.name, group, layer))
# the pleated floor lamp by the corner sofa has no light of its own: in Corona its glowing tube shone through the
# translucent shade. A warm bulb inside the shade (the shade's translucency lets part of it through, the open ends
# throw pools on the floor and the ceiling).
for name, loc, power in (("FloorLamp_bulb", (14.915, 0.755, 0.86), 25.0),):
    ld = bpy.data.lights.new(name, "POINT")
    ld.energy = power
    ld.shadow_soft_size = 0.04
    ld.color = blackbody(2700)
    ob = bpy.data.objects.new(name, ld)
    ob.location = loc
    cols["kitchen"].objects.link(ob)
    made_lights.append((ob.name, "kitchen", "extra"))
report["lights"] = {g: sum(1 for _, gg, _ in made_lights if gg == g) for g in cols}
log("lights", report["lights"])

# pol fixtures: stable index by angle around the island centre (web: one switch per fixture)
pol = sorted(cols["pol"].objects, key=lambda o: math.atan2(o.location.y, o.location.x))
for i, ob in enumerate(pol):
    ob["nik_index"] = i

# ostrov: glow inside the onyx shell (no lights in the file any more): points in the core/shell gap
island = bpy.data.objects["Island"]
ibvh = BVHTree.FromObject(island, bpy.context.evaluated_depsgraph_get())


def ray(o, d):
    loc = ibvh.ray_cast(o - island.location, d.normalized())[0]
    return (loc + island.location, island) if loc is not None else (None, None)


for k in range(8):
    a = 2 * math.pi * k / 8
    d = Vector((math.cos(a), math.sin(a), 0))
    start = Vector((0, 0, 0.25)) + d * 3.0
    shell, ob = ray(start, -d)
    if shell is None:
        continue
    inner, _ = ray(shell - d * 0.002, -d)
    if inner is None:
        continue
    gap = (shell - inner).length
    if gap > 0.06:
        r = (shell - Vector((0, 0, 0.25))).length - gap * 0.5
        ld = bpy.data.lights.new("O_%d" % k, "POINT")
        ld.energy = 12.0
        ld.shadow_soft_size = 0.05
        lo = bpy.data.objects.new("O_%d" % k, ld)
        lo.location = (math.cos(a) * r, math.sin(a) * r, 0.25)
        cols["ostrov"].objects.link(lo)

# emitters (Corona light materials) are switched by the bake script with their group
for m in bpy.data.materials:
    f = nik_flags(m)
    if f.get("emissive"):
        f["group"] = "pol" if f.get("orig") == "Material #-2147483616" else "kitchen"  # floor uplight lenses
        m["nik"] = json.dumps(f)

# world: daylight sky (env group only; strength switched by the bake script)
world = bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
nt = world.node_tree
bg = nt.nodes["Background"]
sky = nt.nodes.new("ShaderNodeTexSky")
try:
    for st in ("MULTIPLE_SCATTERING", "NISHITA", "SINGLE_SCATTERING"):
        try:
            sky.sky_type = st
            break
        except TypeError:
            continue
    sky.sun_disc = False
    sun = next((o for o in cols["env"].objects if o.data.type == "SUN"), None)
    if sun:
        dvec = sun.matrix_world.to_3x3() @ Vector((0, 0, -1))
        sky.sun_elevation = math.asin(max(0.02, -dvec.z))
        sky.sun_rotation = math.atan2(-dvec.y, -dvec.x) + math.pi / 2
except Exception as e:
    log("sky setup", e)
nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
env_mix = layer_mix(ENV_IDX)[1] if ENV_IDX is not None else 0.2
bg.inputs["Strength"].default_value = env_mix
world["nik_env_strength"] = env_mix

report["faces"] = sum(len(o.data.polygons) for o in scene.objects if o.type == "MESH")
report["objects"] = {o.name: {"bake": o.get("nik_bake"), "faces": len(o.data.polygons), "lightmap": o.get("nik_lightmap")}
                     for o in scene.objects if o.type == "MESH"}
json.dump(report, open(os.path.join(OUT, "room_report.json"), "w"), indent=1)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "room.blend"))
log("saved", os.path.join(OUT, "room.blend"), "faces", report["faces"])
