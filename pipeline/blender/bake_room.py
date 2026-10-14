"""Bakes the room: lightmaps for atlases / floor / hero set, irradiance colour attributes for dense furniture.

blender -b build/blender_room/room.blend -P bake_room.py -- <out_dir> [samples] [objects|*] [groups|*] [vx_samples]
-> <out_dir>/<Object>_<group>.exr, bake_manifest.json, and room_baked.blend (colour attributes LM_<group> on VX_*)

Groups (web LightMix): kitchen (all artificial light, pre-mixed with the Corona LightMix), env (suns + sky),
pol (8 floor uplights, one bake per light), ostrov (inner island glow). pol/ostrov only on the island zone.
Material modes while baking: translucency branch on, glass -> transparent stand-in, metals -> diffuse proxy
(the web uses their lightmap as specular occlusion), emitters only lit in their own group.
The Island is baked with white colours (web: lightMap x base colour, emissive = ostrov x translucency map).
"""
import json
import os
import sys
import time

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nikmat import nik_flags  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
OUT = args[0]
SAMPLES = int(args[1]) if len(args) > 1 else 512
ONLY_OBJ = set(args[2].split(",")) if len(args) > 2 and args[2] != "*" else None
ONLY_GRP = set(args[3].split(",")) if len(args) > 3 and args[3] != "*" else None
VX_SAMPLES = int(args[4]) if len(args) > 4 else SAMPLES
os.makedirs(OUT, exist_ok=True)

sc = bpy.context.scene
sc.render.engine = "CYCLES"
prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.compute_device_type = "OPTIX"
prefs.get_devices()
for d in prefs.devices:
    d.use = d.type != "CPU"
sc.cycles.device = "GPU"
sc.cycles.samples = SAMPLES
sc.cycles.use_denoising = False
sc.cycles.max_bounces = 8
sc.cycles.diffuse_bounces = 4
sc.cycles.glossy_bounces = 2
sc.cycles.transmission_bounces = 8
sc.cycles.transparent_max_bounces = 16
sc.cycles.sample_clamp_indirect = 10.0  # fireflies from tiny bright emitters through glossy paths (OIDN does the rest)
sc.render.bake.margin = 16
sc.render.bake.margin_type = "EXTEND"
sc.render.bake.use_clear = True

WORLD_STRENGTH = sc.world.get("nik_env_strength", 0.2)
BG = sc.world.node_tree.nodes["Background"]
GROUPS = [g for g in ("kitchen", "env", "pol", "ostrov")
          if g == "env" or (bpy.data.collections.get("LM_" + g) and len(bpy.data.collections["LM_" + g].objects))]
ISLAND_ZONE = {"Island", "Table", "Planters", "Floor_Kitchen"}
PER_LIGHT = {"pol"}
t_all = time.time()


def log(*a):
    print("[%6.1fs]" % (time.time() - t_all), *a, flush=True)


# ------------------------------------------------------------------ material modes
ORIG = {}


def remember(m):
    if m.name in ORIG:
        return
    b = m.node_tree.nodes.get("BSDF")
    if b is None:
        return
    ORIG[m.name] = {"metallic": b.inputs["Metallic"].default_value,
                    "emission": b.inputs["Emission Strength"].default_value}


def material_mode(m, mode, group=None):
    """mode: export | bake | bake_white"""
    nt = m.node_tree
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    bsdf = nt.nodes.get("BSDF")
    if out is None or bsdf is None:
        return
    remember(m)
    f = nik_flags(m)
    surf = bsdf
    if mode != "export":
        if nt.nodes.get("TranslMix"):
            surf = nt.nodes["TranslMix"]
        if f.get("glass") and nt.nodes.get("BakeShader"):
            surf = nt.nodes["BakeShader"]
    for l in list(out.inputs["Surface"].links):
        nt.links.remove(l)
    nt.links.new(surf.outputs[0], out.inputs["Surface"])
    o = ORIG[m.name]
    bsdf.inputs["Metallic"].default_value = 0.0 if mode != "export" else o["metallic"]
    bsdf.inputs["Emission Strength"].default_value = (
        o["emission"] if mode == "export" or f.get("group", "kitchen") == group else 0.0)
    white = mode == "bake_white"
    for node, owner, sock in ((nt.nodes.get("BaseTex"), bsdf, "Base Color"),
                              (nt.nodes.get("TranslTex"), nt.nodes.get("Translucent"), "Color")):
        if node is None or owner is None:
            continue
        inp = owner.inputs[sock]
        for l in list(inp.links):
            nt.links.remove(l)
        if white:
            inp.default_value = (1, 1, 1, 1)
        else:
            nt.links.new(node.outputs["Color"], inp)


def all_mats():
    return [m for m in bpy.data.materials if m.node_tree]


def set_group(g, light_mask=None):
    for c in bpy.data.collections:
        if c.name.startswith("LM_"):
            c.hide_render = c.name != "LM_" + g
    if light_mask is not None:
        for l, on in light_mask:
            l.hide_render = not on
    BG.inputs["Strength"].default_value = WORLD_STRENGTH if g == "env" else 0.0
    for m in all_mats():
        material_mode(m, "bake", g)


def set_target(obj, image):
    for slot in obj.material_slots:
        m = slot.material
        if not m:
            continue
        nt = m.node_tree
        n = nt.nodes.get("BakeTarget") or nt.nodes.new("ShaderNodeTexImage")
        n.name = "BakeTarget"
        n.image = image
        n.location = (900, 400)
        nt.nodes.active = n


def save_exr(img, path):
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.image_settings.color_depth = "16"
    sc.render.image_settings.exr_codec = "ZIP"
    img.save_render(path, scene=sc)


manifest_path = os.path.join(OUT, "bake_manifest.json")
manifest = json.load(open(manifest_path)) if os.path.exists(manifest_path) else {"objects": {}, "vertex": {}}


def bake_image(obj, key):
    size = int(obj["nik_lightmap"])
    name = "%s_%s" % (obj.name, key)
    img = bpy.data.images.get(name) or bpy.data.images.new(name, size, size, alpha=False, float_buffer=True)
    img.colorspace_settings.name = "Linear Rec.709"
    set_target(obj, img)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    t = time.time()
    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"DIRECT", "INDIRECT"}, uv_layer="Lightmap", margin=16,
                        use_clear=True, target="IMAGE_TEXTURES")
    save_exr(img, os.path.join(OUT, name + ".exr"))
    px = img.pixels[:: max(4, (size * size * 4) // 400000 // 4 * 4)]
    lum = sorted(0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2] for i in range(0, len(px) - 3, 4))
    stats = {"p50": lum[len(lum) // 2], "p99": lum[int(len(lum) * 0.99)], "max": lum[-1]}
    e = manifest["objects"].setdefault(obj.name, {"size": size, "files": {}})
    e["size"] = size
    e["files"][key] = {"file": name + ".exr", "stats": stats}
    log("BAKED %-24s %4dpx %6.1fs p50=%.4f p99=%.4f" % (name, size, time.time() - t, stats["p50"], stats["p99"]))
    bpy.data.images.remove(img)


def jobs_for(g):
    if g in PER_LIGHT:
        lights = sorted(bpy.data.collections["LM_" + g].objects, key=lambda o: o.get("nik_index", 0))
        return [("%s_%d" % (g, i), [(l2, l2 is l) for l2 in lights]) for i, l in enumerate(lights)]
    return [(g, None)]


targets = [o for o in sc.objects if o.type == "MESH" and o.get("nik_bake") == "lightmap"]
vx = [o for o in sc.objects if o.type == "MESH" and o.get("nik_bake") == "vertex"]
log("lightmap targets", [o.name for o in targets], "vertex objects", len(vx))

# ------------------------------------------------------------------ lightmaps
for obj in targets:
    if ONLY_OBJ and obj.name not in ONLY_OBJ:
        continue
    groups = GROUPS if obj.name in ISLAND_ZONE else ["kitchen", "env"]
    for g in groups:
        if ONLY_GRP and g not in ONLY_GRP:
            continue
        for key, mask in jobs_for(g):
            set_group(g, mask)
            if obj.name == "Island":
                for slot in obj.material_slots:
                    material_mode(slot.material, "bake_white", g)
            bake_image(obj, key)
        for l in bpy.data.collections["LM_" + g].objects:
            l.hide_render = False
    json.dump(manifest, open(manifest_path, "w"), indent=1)

# ------------------------------------------------------------------ vertex irradiance (all VX objects in one bake)
if vx and (not ONLY_OBJ or "VX" in ONLY_OBJ):
    sc.cycles.samples = VX_SAMPLES
    for g in ["kitchen", "env"]:
        if ONLY_GRP and g not in ONLY_GRP:
            continue
        set_group(g)
        for o in vx:
            me = o.data
            a = me.color_attributes.get("LM_" + g) or me.color_attributes.new("LM_" + g, "FLOAT_COLOR", "POINT")
            me.color_attributes.active_color = a
        bpy.ops.object.select_all(action="DESELECT")
        for o in vx:
            o.select_set(True)
        bpy.context.view_layer.objects.active = vx[0]
        t = time.time()
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"DIRECT", "INDIRECT"}, target="VERTEX_COLORS")
        manifest["vertex"][g] = {"objects": [o.name for o in vx], "samples": VX_SAMPLES}
        log("BAKED vertex %-8s %d objects %.1fs" % (g, len(vx), time.time() - t))
    json.dump(manifest, open(manifest_path, "w"), indent=1)

# ------------------------------------------------------------------ restore + save
for c in bpy.data.collections:
    if c.name.startswith("LM_"):
        c.hide_render = False
BG.inputs["Strength"].default_value = WORLD_STRENGTH
for m in all_mats():
    material_mode(m, "export")
    bt = m.node_tree.nodes.get("BakeTarget")
    if bt:
        m.node_tree.nodes.remove(bt)
manifest["samples"] = SAMPLES
json.dump(manifest, open(manifest_path, "w"), indent=1)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(os.path.dirname(bpy.data.filepath), "room_baked.blend"))
log("total done")
