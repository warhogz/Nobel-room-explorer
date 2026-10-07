"""Exports the web scene: blender -b build/blender/scene.blend -P export_glb.py -- <out.glb>
Materials are switched to plain Principled (translucency/LightMix data travel as extras), preset cameras added,
lights are not exported (lighting comes from the baked lightmaps)."""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cameras import setup_cameras  # noqa: E402

out = sys.argv[sys.argv.index("--") + 1]
os.makedirs(os.path.dirname(out), exist_ok=True)
sc = bpy.context.scene
for m in bpy.data.materials:
    if not m.node_tree:
        continue
    nt = m.node_tree
    o = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    for l in list(o.inputs["Surface"].links):
        nt.links.remove(l)
    nt.links.new(nt.nodes["BSDF"].outputs[0], o.inputs["Surface"])
    for n in [n for n in nt.nodes if n.name in ("BakeTarget", "TranslMix", "Translucent", "TranslTex")]:
        nt.nodes.remove(n)
setup_cameras(sc)
# camera presets for the web (three.js, Y-up): glTF drops lens shift, so presets travel as JSON
import json  # noqa: E402

from cameras import CAMERAS  # noqa: E402

presets = {}
for name, (pos, look, lens, shift_y, res) in CAMERAS.items():
    presets[name] = {"position": [pos[0], pos[2], -pos[1]], "target": [look[0], pos[2], -look[1]],
                     "lens": lens, "sensor": 36.0, "shiftY": shift_y, "resolution": list(res)}
json.dump(presets, open(os.path.join(os.path.dirname(out), "cameras.json"), "w"), indent=1)
# floor uplight fixtures (web: visible, hoverable, switchable one by one); index = per-light lightmap channel
fixtures = []
pol = bpy.data.collections.get("LM_pol")
for ob in sorted(pol.objects if pol else [], key=lambda o: o.get("nik_index", 0)):
    p = ob.location
    fixtures.append({"index": int(ob.get("nik_index", 0)), "name": ob.name, "position": [p.x, 0.0, -p.y]})
json.dump({"pol": fixtures}, open(os.path.join(os.path.dirname(out), "lights.json"), "w"), indent=1)
for ob in sc.objects:
    if ob.type == "MESH":
        ob.data.uv_layers["UVMap"].active_render = True
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_extras=True, export_cameras=True,
                          export_lights=False, export_yup=True, export_apply=True, export_texcoords=True,
                          export_normals=True, export_tangents=False, export_materials="EXPORT",
                          export_image_format="AUTO", use_selection=False)
print("exported", out, os.path.getsize(out))
