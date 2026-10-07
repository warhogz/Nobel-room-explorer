"""Bakes per-group HDR lightmaps (irradiance, colour excluded) for every object with a "nik_lightmap" size.

blender -b build/blender/scene.blend -P bake_lightmaps.py -- <out_dir> [samples] [objects] [groups]
-> <out_dir>/<Object>_<group>.exr  (+ bake_manifest.json)

Groups = collections LM_* (lights) + LM_env (the world only: bronze room bounce), like Corona LightMix layers.
The Island is baked with its translucency branch active and *white* colours, so that
  island LM_ostrov ~= fraction * light arriving from inside  -> web: emissive = LM * translucency texture
  island LM_kitchen/LM_pol ~= front irradiance               -> web: lightMap (multiplied by base colour)
Other objects see the textured island (correct colour bleeding).
"""
import json
import os
import sys
import time

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
OUT = args[0]
SAMPLES = int(args[1]) if len(args) > 1 else 1024
ONLY_OBJ = set(args[2].split(",")) if len(args) > 2 and args[2] != "*" else None
ONLY_GRP = set(args[3].split(",")) if len(args) > 3 and args[3] != "*" else None
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
sc.cycles.transmission_bounces = 8
sc.render.bake.margin = 16
sc.render.bake.margin_type = "EXTEND"
sc.render.bake.use_clear = True

WORLD_STRENGTH = sc.world.node_tree.nodes["Background"].inputs["Strength"].default_value
light_groups = sorted(c.name for c in bpy.data.collections if c.name.startswith("LM_"))
groups = light_groups if "LM_env" in light_groups else light_groups + ["LM_env"]
PER_LIGHT = {"LM_pol"}  # baked light by light
targets = [o for o in sc.objects if o.type == "MESH" and o.get("nik_lightmap")]


def material_mode(mat, mode):
    """mode: 'export' (Principled only), 'bake' (translucency branch), 'bake_white' (bake + white colours)"""
    nt = mat.node_tree
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    bsdf = nt.nodes.get("BSDF")
    mix = nt.nodes.get("TranslMix")
    surf = mix if (mix and mode != "export") else bsdf
    for l in list(out.inputs["Surface"].links):
        nt.links.remove(l)
    nt.links.new(surf.outputs[0], out.inputs["Surface"])
    base_tex = nt.nodes.get("BaseTex")
    tr_tex = nt.nodes.get("TranslTex")
    white = mode == "bake_white"
    for node, sock_owner, sock in ((base_tex, bsdf, "Base Color"), (tr_tex, nt.nodes.get("Translucent"), "Color")):
        if node is None or sock_owner is None:
            continue
        inp = sock_owner.inputs[sock]
        for l in list(inp.links):
            nt.links.remove(l)
        if white:
            inp.default_value = (1, 1, 1, 1)
        else:
            nt.links.new(node.outputs["Color"], inp)


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


def all_mats():
    return [m for m in bpy.data.materials if m.node_tree]


def bake_one(obj, size, key):
    name = "%s_%s" % (obj.name, key)
    img = bpy.data.images.get(name) or bpy.data.images.new(name, size, size, alpha=False, float_buffer=True)
    img.colorspace_settings.name = "Linear Rec.709"
    set_target(obj, img)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    t = time.time()
    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"DIRECT", "INDIRECT"}, uv_layer="Lightmap",
                        margin=16, use_clear=True, target="IMAGE_TEXTURES")
    path = os.path.join(OUT, name + ".exr")
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.image_settings.color_depth = "16"
    sc.render.image_settings.exr_codec = "ZIP"
    img.save_render(path, scene=sc)
    px = list(img.pixels[:: max(1, (size * size * 4) // 400000)])
    lum = sorted(0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2] for i in range(0, len(px) - 3, 4))
    stats = {"p50": lum[len(lum) // 2], "p99": lum[int(len(lum) * 0.99)], "max": lum[-1]}
    manifest["objects"][obj.name]["files"][key] = {"file": name + ".exr", "stats": stats}
    print("BAKED %-22s %4dpx %6.1fs p50=%.4f p99=%.4f max=%.3f" % (name, size, time.time() - t, stats["p50"],
                                                                 stats["p99"], stats["max"]), flush=True)


manifest = {"samples": SAMPLES, "groups": groups, "objects": {}}
t_all = time.time()
for obj in targets:
    if ONLY_OBJ and obj.name not in ONLY_OBJ:
        continue
    size = int(obj["nik_lightmap"])
    is_island = obj.name == "Island"
    for m in all_mats():
        material_mode(m, "bake")
    if is_island:
        for slot in obj.material_slots:
            material_mode(slot.material, "bake_white")
    manifest["objects"][obj.name] = {"size": size, "files": {}}
    for g in groups:
        if ONLY_GRP and g not in ONLY_GRP:
            continue
        for c in light_groups:
            bpy.data.collections[c].hide_render = c != g
        sc.world.node_tree.nodes["Background"].inputs["Strength"].default_value =             WORLD_STRENGTH if g == "LM_env" else 0.0
        if g in PER_LIGHT:
            # every light of the group on its own -> individually switchable in the viewer
            lights = sorted(bpy.data.collections[g].objects, key=lambda o: o.get("nik_index", 0))
            jobs = [("%s_%d" % (g[3:], i), [l2 is l for l2 in lights], lights) for i, l in enumerate(lights)]
        else:
            jobs = [(g[3:], None, [])]
        for key, mask, lights in jobs:
            for l, on in zip(lights, mask or []):
                l.hide_render = not on
            bake_one(obj, size, key)
        for l in bpy.data.collections[g].objects if g in bpy.data.collections else []:
            l.hide_render = False

for c in light_groups:
    bpy.data.collections[c].hide_render = False
sc.world.node_tree.nodes["Background"].inputs["Strength"].default_value = WORLD_STRENGTH
for m in all_mats():
    material_mode(m, "export")
    bt = m.node_tree.nodes.get("BakeTarget")
    if bt:
        m.node_tree.nodes.remove(bt)
mpath = os.path.join(OUT, "bake_manifest.json")
old = json.load(open(mpath)) if os.path.exists(mpath) else {"objects": {}}
for k, v in manifest["objects"].items():
    old.setdefault("objects", {}).setdefault(k, {"size": v["size"], "files": {}})
    old["objects"][k]["size"] = v["size"]
    old["objects"][k]["files"].update(v["files"])
old["samples"], old["groups"] = SAMPLES, groups
json.dump(old, open(mpath, "w"), indent=1)
print("total %.1fs" % (time.time() - t_all))
