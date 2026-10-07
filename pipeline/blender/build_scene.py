"""Builds the bake-ready Blender scene from the Max FBX export + compiled materials.

blender -b --factory-startup -P build_scene.py -- <root>
  <root>/build/export/scene.fbx, <root>/build/materials/{materials.json,tex/}
  -> <root>/build/blender/scene.blend, origin.json
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector

ROOT = sys.argv[sys.argv.index("--") + 1]
B = os.path.join(ROOT, "build")
OUT = os.path.join(B, "blender")
os.makedirs(OUT, exist_ok=True)
MATS = json.load(open(os.path.join(B, "materials", "materials.json"), encoding="utf-8"))["materials"]
TEX = os.path.join(B, "materials", "tex")

ISLAND_SRC = "Object2121349745"
GROUPS = {  # joined object name -> rule on source object
    "Island": lambda o: mats_of(o) == {"Material #-2147483589"},
    "Table": lambda o: mats_of(o) == {"Material #76111117"},
    "Faucets": lambda o: mats_of(o) == {"Material #-2147483587"},
    "Plants": lambda o: o.name.startswith(("Avizoon", "Strawberry")),
    "Planters": lambda o: o.name.startswith("Soil"),
}
LIGHTMAPPED = {"Island": 2048, "Table": 1024, "Planters": 256, "Floor": 2048}
FLOOR_SIZE = 14.0  # large enough for the light to fall off naturally before the web fade
FLOOR_TILE = (0.60, 1.18)  # metres covered by one repeat of the 564x1105 travertine texture


def mats_of(o):
    return {m.name.split(".")[0] for m in o.data.materials if m}


# ------------------------------------------------------------------ import + normalize
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
bpy.ops.import_scene.fbx(filepath=os.path.join(B, "export", "scene.fbx"))
meshes = [o for o in scene.objects if o.type == "MESH"]
for o in list(scene.objects):
    if o.type != "MESH":
        bpy.data.objects.remove(o)
with bpy.context.temp_override(selected_editable_objects=meshes, selected_objects=meshes, active_object=meshes[0]):
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

# ---- validate against the Max scene dump (ground truth before any export processing)
FT = 0.3048
dump = {d["name"]: d for d in json.load(open(os.path.join(B, "dump", "objects.json"), encoding="utf-8"))}
bad = []
for o in meshes:
    d = dump.get(o.name)
    if not d or "min" not in d:
        continue
    vs = [o.matrix_world @ v.co for v in o.data.vertices]
    c1 = Vector([(min(v[i] for v in vs) + max(v[i] for v in vs)) / 2 for i in range(3)])
    c0 = Vector([(a + b) / 2 * FT for a, b in zip(d["min"], d["max"])])
    err = (c1 - c0).length
    if err > 0.02:
        bad.append((o.name, round(err, 3)))
print("bbox check vs Max dump:", "OK" if not bad else bad)
if any(e > 0.05 for _, e in bad):
    raise SystemExit("geometry moved during export: %s" % bad)


def outward_ratio(o):
    cs = [o.matrix_world @ Vector(c) for c in o.bound_box]
    c = sum(cs, Vector()) / 8
    n3 = o.matrix_world.to_3x3().inverted().transposed()
    out = tot = 0.0
    for p in o.data.polygons:
        a = p.area
        tot += a
        if (n3 @ p.normal).dot((o.matrix_world @ p.center) - c) > 0:
            out += a
    return out / max(tot, 1e-9)


r = outward_ratio(bpy.data.objects[ISLAND_SRC])
print("island outward-facing area ratio: %.2f" % r)
if r < 0.5:
    raise SystemExit("island normals point inward")

# origin: island footprint centre (Max dump, metres) at Max floor level z=0
d = dump[ISLAND_SRC]
origin = Vector(((d["min"][0] + d["max"][0]) / 2 * FT, (d["min"][1] + d["max"][1]) / 2 * FT, 0.0))
for o in meshes:
    o.location -= origin
json.dump({"origin_m": list(origin), "note": "web/blender coords = Max world (metres, Z-up) - origin_m"},
          open(os.path.join(OUT, "origin.json"), "w"), indent=1)

# one UV layer named UVMap (Max channel 1) per mesh, so joins merge cleanly
for o in meshes:
    uvs = o.data.uv_layers
    if len(uvs) == 0:
        uvs.new(name="UVMap")
    first = uvs[0].name
    for u in [u.name for u in uvs][1:]:
        uvs.remove(uvs[u])
    uvs[first].name = "UVMap"
    for ca in list(o.data.color_attributes):
        o.data.color_attributes.remove(ca)


# ------------------------------------------------------------------ materials
def img(name, color):
    im = bpy.data.images.load(os.path.join(TEX, name), check_existing=True)
    im.colorspace_settings.name = "sRGB" if color else "Non-Color"
    return im


def build_material(spec, mname=None):
    m = bpy.data.materials.new(mname or spec["name"])
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (900, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.name = "BSDF"
    bsdf.location = (500, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bc = spec.get("baseColor", [0.8, 0.8, 0.8])
    bsdf.inputs["Base Color"].default_value = (*bc[:3], 1.0)
    if spec.get("baseColorTex"):
        t = nt.nodes.new("ShaderNodeTexImage")
        t.name = "BaseTex"
        t.image = img(spec["baseColorTex"], True)
        t.location = (-400, 300)
        nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
        if spec.get("alphaMode") == "MASK":
            r = nt.nodes.new("ShaderNodeMath")
            r.operation = "ROUND"  # glTF exporter reads ROUND as alpha clip at 0.5
            nt.links.new(t.outputs["Alpha"], r.inputs[0])
            nt.links.new(r.outputs[0], bsdf.inputs["Alpha"])
    bsdf.inputs["Metallic"].default_value = spec.get("metallic", 0.0)
    bsdf.inputs["Roughness"].default_value = min(1.0, max(0.0, spec.get("roughness", 0.5)))
    if spec.get("roughnessTex"):
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = img(spec["roughnessTex"], False)
        t.location = (-400, 0)
        nt.links.new(t.outputs["Color"], bsdf.inputs["Roughness"])
    bsdf.inputs["IOR"].default_value = spec.get("ior", 1.5) if spec.get("ior", 1.5) < 4 else 1.5
    if spec.get("normalTex"):
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = img(spec["normalTex"], False)
        t.location = (-400, -300)
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.uv_map = "UVMap"
        nm.inputs["Strength"].default_value = spec.get("normalScale", 1.0)
        nm.location = (0, -300)
        nt.links.new(t.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    if spec.get("doubleSided"):
        m.use_backface_culling = False
    else:
        m.use_backface_culling = True
    nik = {}
    tr = spec.get("translucency")
    if tr:
        # bake-only branch: Mix(Principled, Translucent) is switched in by the bake script
        tn = nt.nodes.new("ShaderNodeBsdfTranslucent")
        tn.name = "Translucent"
        tn.location = (500, -400)
        if tr.get("colorTex"):
            t = nt.nodes.new("ShaderNodeTexImage")
            t.name = "TranslTex"
            t.image = img(tr["colorTex"], True)
            t.location = (-400, -650)
            nt.links.new(t.outputs["Color"], tn.inputs["Color"])
        else:
            tn.inputs["Color"].default_value = (*tr["color"], 1)
        mix = nt.nodes.new("ShaderNodeMixShader")
        mix.name = "TranslMix"
        mix.inputs["Fac"].default_value = tr["fraction"]
        mix.location = (720, -200)
        nt.links.new(bsdf.outputs["BSDF"], mix.inputs[1])
        nt.links.new(tn.outputs["BSDF"], mix.inputs[2])
        nik["translucency"] = {"fraction": tr["fraction"], "colorTex": tr.get("colorTex")}
    if nik:
        m["nik"] = json.dumps(nik)
    return m


built = {}


def material_for(name):
    base = name.split(".")[0]
    if base not in built:
        spec = MATS.get(base)
        if spec is None:
            print("WARN no compiled material for", base)
            spec = {"name": base, "baseColor": [0.5, 0.5, 0.5]}
        built[base] = build_material(spec, base + "__pbr")
    return built[base]


for o in meshes:
    for i, slot in enumerate(o.material_slots):
        if slot.material:
            slot.material = material_for(slot.material.name)
for m in list(bpy.data.materials):
    if not m.name.endswith("__pbr"):
        bpy.data.materials.remove(m)
for m in bpy.data.materials:
    m.name = m.name[:-5]

# ------------------------------------------------------------------ join groups
groups = {}
for o in meshes:
    for g, rule in GROUPS.items():
        if rule(o):
            groups.setdefault(g, []).append(o)
            break
    else:
        print("WARN ungrouped", o.name)
for g, objs in groups.items():
    with bpy.context.temp_override(active_object=objs[0], selected_editable_objects=objs, selected_objects=objs):
        bpy.ops.object.join()
    objs[0].name = g
    objs[0].data.name = g
    print("joined", g, len(objs), "faces", len(objs[0].data.polygons))

# ------------------------------------------------------------------ placeholder floor (travertine)
bpy.ops.mesh.primitive_plane_add(size=FLOOR_SIZE, location=(0, 0, 0))
floor = bpy.context.active_object
floor.name = floor.data.name = "Floor"
floor["nik_placeholder"] = True
uv = floor.data.uv_layers[0]
uv.name = "UVMap"
for loop in floor.data.loops:
    co = floor.data.vertices[loop.vertex_index].co
    uv.data[loop.index].uv = (co.x / FLOOR_TILE[0], co.y / FLOOR_TILE[1])
fm = build_material(dict(MATS["Material 111111"], name="Floor_Travertine"))
floor.data.materials.append(fm)

# ------------------------------------------------------------------ lightmap UVs
for name, size in LIGHTMAPPED.items():
    o = bpy.data.objects[name]
    lm = o.data.uv_layers.new(name="Lightmap")
    o.data.uv_layers["UVMap"].active_render = True
    o.data.uv_layers.active = lm
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    if name == "Floor":
        for loop in o.data.loops:
            co = o.data.vertices[loop.vertex_index].co
            lm.data[loop.index].uv = (co.x / FLOOR_SIZE + 0.5, co.y / FLOOR_SIZE + 0.5)
        continue
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    margin = 4.0 / size
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=margin, area_weight=0.0,
                             correct_aspect=True, scale_to_bounds=False)
    bpy.ops.uv.pack_islands(rotate=True, margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")
    o["nik_lightmap"] = size
    print("lightmap UV", name, size)
floor["nik_lightmap"] = LIGHTMAPPED["Floor"]


# ------------------------------------------------------------------ lights (approximation of LightMix groups)
def coll(name):
    c = bpy.data.collections.new(name)
    scene.collection.children.link(c)
    return c


def add_light(c, name, kind, loc, power, rot=(0, 0, 0), **kw):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = power
    for k, v in kw.items():
        setattr(ld, k, v)
    ob = bpy.data.objects.new(name, ld)
    ob.location = loc
    ob.rotation_euler = rot
    c.objects.link(ob)
    return ob


island = bpy.data.objects["Island"]
depsgraph = bpy.context.evaluated_depsgraph_get()


def ray(origin_v, direction):
    hit, loc, nrm, idx, ob, _ = scene.ray_cast(depsgraph, origin_v, direction.normalized())
    return (loc, ob) if hit else (None, None)


# probe the island: inner core vs outer shell along horizontal rays (cast from outside inward)
probe = []
for z in (0.06, 0.25, 0.5):
    for k in range(16):
        a = 2 * math.pi * k / 16
        d = Vector((math.cos(a), math.sin(a), 0))
        start = Vector((0, 0, z)) + d * 3.0
        shell, ob = ray(start, -d)
        if shell is None or ob.name != "Island":
            continue
        inner, ob2 = ray(shell - d * 0.002, -d)
        gap = (shell - inner).length if inner is not None else None
        probe.append({"z": z, "angle": round(math.degrees(a)), "shell_r": round((shell - Vector((0, 0, z))).length, 3),
                      "gap": round(gap, 3) if gap else None})
json.dump(probe, open(os.path.join(OUT, "island_probe.json"), "w"), indent=1)

c_k, c_o, c_p = coll("LM_kitchen"), coll("LM_ostrov"), coll("LM_pol")
# kitchen: ceiling downlights (~3 m) over island and table + soft chandelier/ceiling bounce
for i, (x, y) in enumerate([(-0.3, -0.7), (-0.3, 0.7), (0.35, -0.7), (0.35, 0.7), (1.25, -0.35), (1.25, 0.35)]):
    add_light(c_k, "K_spot_%d" % i, "SPOT", (x, y, 3.0), 60.0, spot_size=math.radians(55), spot_blend=0.6,
              shadow_soft_size=0.03)
add_light(c_k, "K_soft", "AREA", (0.3, 0, 3.1), 250.0, shape="RECTANGLE", size=2.5, size_y=3.5)

# ostrov: glow inside the onyx shell (lights in the gap between core and shell, low)
for p in probe:
    if p["z"] == 0.25 and p["gap"] and p["gap"] > 0.06 and p["angle"] % 45 == 0:
        a = math.radians(p["angle"])
        r = p["shell_r"] - p["gap"] * 0.5
        add_light(c_o, "O_%d" % p["angle"], "POINT", (math.cos(a) * r, math.sin(a) * r, 0.25), 12.0,
                  shadow_soft_size=0.05)

# pol: N recessed floor uplights evenly spaced along the island base contour, POL_OFFSET outside it,
# tilted slightly towards the onyx (grazing light). Each one is baked separately (switchable in the web).
N_POL, POL_OFFSET, POL_TILT = 8, 0.14, math.radians(12)
contour = []
for k in range(720):
    a = 2 * math.pi * k / 720
    d = Vector((math.cos(a), math.sin(a), 0))
    o = Vector((0, 0, 0.04)) + d * 4.0
    for _ in range(6):  # skip the table pedestal etc. until the island is hit
        hit, ob = ray(o, -d)
        if hit is None or ob.name == "Island":
            break
        o = hit - d * 0.002
    if hit is not None and ob.name == "Island":
        contour.append(Vector((hit.x, hit.y, 0)))
seg = [(contour[i] - contour[i - 1]).length for i in range(len(contour))]
total = sum(seg)
pedestal = Vector((1.19, 0.0, 0))


def contour_at(s):
    s %= total
    for i in range(len(contour)):
        if s <= seg[i]:
            p0, p1 = contour[i - 1], contour[i]
            t = s / seg[i] if seg[i] > 0 else 0
            p = p0.lerp(p1, t)
            tan = (p1 - p0).normalized()
            n = Vector((tan.y, -tan.x, 0))
            if n.dot(p) < 0:
                n = -n
            return p, n
        s -= seg[i]
    return contour[0], contour[0].normalized()


# choose the phase that keeps fixtures away from the table pedestal
best = max((min(((contour_at(ph * total / N_POL / 24 + i * total / N_POL)[0] - pedestal).length
                 for i in range(N_POL))), ph) for ph in range(24))[1]
for i in range(N_POL):
    p, n = contour_at(best * total / N_POL / 24 + i * total / N_POL)
    pos = p + n * POL_OFFSET
    aim = Vector((-n.x * math.sin(POL_TILT), -n.y * math.sin(POL_TILT), math.cos(POL_TILT)))
    # soft-edged grazing uplight: wide feathered cone, soft shadows
    ob = add_light(c_p, "P_%d" % i, "SPOT", (pos.x, pos.y, 0.012), 7.0, spot_size=math.radians(62), spot_blend=0.92,
                   shadow_soft_size=0.05)
    ob.rotation_euler = aim.to_track_quat("-Z", "Y").to_euler()
    ob["nik_index"] = i
print("pol fixtures:", [tuple(round(v, 3) for v in o.location[:2]) for o in c_p.objects])

# env: soft bounce from the (absent) room - a large dim area light above the island, so the floor light
# falls off with distance (the world alone lit the floor evenly to its edge -> visible disc in the viewer)
c_e = coll("LM_env")
add_light(c_e, "E_bounce", "AREA", (0.3, 0, 3.6), 520.0, shape="DISK", size=7.0)
for ob in c_e.objects:
    ob.data.color = (1.0, 0.86, 0.72)
for ob in c_k.objects:
    ob.data.color = (1, 1, 1)
scene.world = bpy.data.worlds.new("World")
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.32, 0.22, 0.14, 1)  # bronze room bounce
scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.12

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "scene.blend"))
print("saved", os.path.join(OUT, "scene.blend"), "lights", len(c_k.objects), len(c_o.objects), len(c_p.objects))
