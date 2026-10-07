# Builds build/dump/SUMMARY.md from the JSON produced by dump_scene.py (run with any Python 3).
import json
import os
import sys

D = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "..", "build", "dump")
J = lambda n: json.load(open(os.path.join(D, n), encoding="utf-8"))
R = J("refs.json")
info, render, objs = J("scene_info.json"), J("render.json"), J("objects.json")
ren = R[render["renderer"]["$ref"]]["props"]
TEXDIR = os.path.join(D, "..", "..", "3DMAX", "TEXTURE")
have = set()
try:
    import zipfile
    for z in os.listdir(TEXDIR):
        if z.endswith(".zip"):
            have |= {os.path.basename(n).lower() for n in zipfile.ZipFile(os.path.join(TEXDIR, z)).namelist()}
except FileNotFoundError:
    pass

out = []
P = out.append
P("# Scene dump summary\n")
P("- File: `%s`" % info["maxFile"])
P("- Max: %s, units: %s (scale %s), renderer: %s, output %dx%d" % (
    info["maxVersion"][-2:], info["units"]["systemType"], info["units"]["systemScale"], info["renderer"],
    *info["renderSize"]))
P("- Loaded nodes: %s" % info["counts"])
P("- Layers: %d, batch views: %d (cameras: %s)" % (
    len(info["layers"]), len(info["batchViews"]),
    sorted({str(v.get("camera")) for v in info["batchViews"]})))
P("")
P("## Batch views (enabled)\n")
P("| view | output | size | camera |\n|---|---|---|---|")
for v in info["batchViews"]:
    if v.get("enabled"):
        P("| %s | %s | %sx%s | %s |" % (v["name"], os.path.basename(v["outputFilename"]), v["width"], v["height"],
                                       v.get("camera")))

P("\n## Tone mapping pipeline (Corona, as stored: first = top of chain)\n")
k = ren["colorMap_pipeline"]["$ref"]
while k:
    e = R[k]
    props = {p: v for p, v in e["props"].items() if p not in ("colorMappingOperator_nextOperator", "colorMappingOperator_id")}
    P("- **%s** %s" % (e["class"].replace("OperatorPlugin", ""),
                       ", ".join("%s=%s" % (p.replace("colorMappingOperator_", ""), v) for p, v in props.items())))
    nxt = e["props"].get("colorMappingOperator_nextOperator")
    k = nxt["$ref"] if isinstance(nxt, dict) else None

P("\n## LightMix (renderer colorMap_lightmix*)\n")
names = ren.get("colormap_lightselect_elementNames") or []
cols = ren.get("colorMap_lightmixColors") or []
ints = ren.get("colorMap_lightmixIntensities") or []
ena = ren.get("colorMap_lightmixEnabledLayers") or []
P("| # | element | enabled | color (0-1) | intensity |\n|---|---|---|---|---|")
for i, n in enumerate(names):
    P("| %d | %s | %s | %s | %s |" % (i, n, ena[i] if i < len(ena) else "", cols[i] if i < len(cols) else "",
                                      round(ints[i], 3) if i < len(ints) else ""))

P("\n## Render elements\n")
for el in render["renderElements"]:
    e = R[el["$ref"]]
    nodes = e["props"].get("includedNodes") or e["props"].get("nodes") or []
    P("- %s `%s` nodes=%d" % (e["class"], e["props"].get("elementName", e.get("name", "")),
                               len(nodes) if isinstance(nodes, list) else 0))

P("\n## Other renderer settings\n")
for key in sorted(ren):
    if key.startswith(("bloomGlare_", "denoise_", "colorMap_", "colormap_", "bg_source", "lights_enviro")) \
            and "lightmix" not in key.lower() and "lightselect" not in key.lower():
        P("- `%s` = %s" % (key, str(ren[key])[:120]))

P("\n## Materials used by loaded objects\n")
seen = set()
texrefs = {}


def walk(k, path):
    if k in seen:
        return
    seen.add(k)
    e = R[k]
    for p, v in e["props"].items():
        if isinstance(v, str) and p.lower() in ("filename", "bitmapfilename", "iesfile") and v:
            texrefs.setdefault(v, set()).add(path)
        vals = v if isinstance(v, list) else [v]
        for x in vals:
            if isinstance(x, dict) and "$ref" in x:
                walk(x["$ref"], path)


for o in objs:
    m = o.get("mtl")
    if m and m["id"] and m["id"] not in seen:
        top = R[m["id"]]
        P("- `%s` (%s)" % (m["name"], m["class"]))
        walk(m["id"], m["name"])
P("\n## Texture files referenced by those materials\n")
P("| file | in zip | used by |\n|---|---|---|")
for f, users in sorted(texrefs.items()):
    b = os.path.basename(f.replace("\\", "/"))
    P("| %s | %s | %s |" % (b, "yes" if b.lower() in have else "**no**", ", ".join(sorted(users))))

open(os.path.join(D, "SUMMARY.md"), "w", encoding="utf-8").write("\n".join(out) + "\n")
print("\n".join(out))
