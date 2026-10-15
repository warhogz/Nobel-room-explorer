"""Web assets for the full room (same format as build_assets.py, plus room atlases and vertex lightmaps).

python build_room_assets.py <root>
  in : build/web_room/{room.glb, cameras.json, lights.json, vertex_lm.json}, build/bake_room/*.exr + bake_manifest.json,
       build/materials_room/materials.json, build/blender_room/tex (perforation mask)
  out: web/public/assets/{scene.glb, lightmaps.json, cameras.json, lights.json, lm/*.ktx2, tex/*.ktx2}

Lightmaps: HDR -> KTX2 E5B9G9R9 (true HDR, no block compression: RGBM through 4x4 block codecs showed as
squares on dark ceilings) + zstd, mipmapped; room atlases capped at 2048. Decoded like RGBM with alpha 1 and
scale = range, so the shaders are unchanged. Per-light groups (pol_0..7): luminance, 4 lights per RGBA texture,
sqrt-encoded (UASTC).
"""
import json
import os
import re
import shutil
import subprocess
import sys

import numpy as np
import OpenEXR
from PIL import Image

ROOT = os.path.abspath(sys.argv[1])
B = os.path.join(ROOT, "build")
SRC = os.path.join(B, "web_room")
BAKE = os.path.join(B, "bake_room")
PUB = os.path.join(ROOT, "web", "public", "assets")
LM_OUT = os.path.join(PUB, "lm")
TEX_OUT = os.path.join(PUB, "tex")
TMP = os.path.join(B, "web_room_tmp")
for d in (PUB, LM_OUT, TEX_OUT, TMP):
    os.makedirs(d, exist_ok=True)
RGBM_RANGE = 16.0
PART = 45 * 2 ** 20  # scene.glb pieces, under GitHub's 50 MB warning
ENV = dict(os.environ)
ENV["PATH"] = ";".join([r"C:\Program Files\nodejs", os.path.join(os.environ["APPDATA"], "npm"),
                        r"C:\Program Files\KTX-Software\bin", ENV.get("PATH", "")])
ONLY = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else {"lm", "glb", "tex"}  # "sizes" alone: only the byte table


def run(cmd):
    print(">", subprocess.list2cmdline(cmd)[:300], flush=True)
    r = subprocess.run(subprocess.list2cmdline(cmd), env=ENV, shell=True, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit("command failed")
    return r.stdout


def gt(*args):
    return run(["gltf-transform", *args])


def load_exr(p):
    with OpenEXR.File(p) as f:
        ch = f.channels()
        if "RGB" in ch:
            a = ch["RGB"].pixels
        elif "RGBA" in ch:
            a = ch["RGBA"].pixels[..., :3]
        else:
            a = np.dstack([ch[c].pixels for c in ("R", "G", "B")])
    return np.nan_to_num(np.asarray(a, np.float32), nan=0.0, posinf=0.0, neginf=0.0).clip(0, None)


def ktx(png, out, mips):
    cmd = ["ktx", "create", "--format", "R8G8B8A8_UNORM", "--assign-tf", "linear", "--encode", "uastc",
           "--uastc-quality", "3", "--zstd", "18"]
    if mips:
        cmd.append("--generate-mipmap")
    run(cmd + [png, out])


lm_path = os.path.join(PUB, "lightmaps.json")
if "lm" in ONLY:
    bm = json.load(open(os.path.join(BAKE, "bake_manifest.json")))
    lm_manifest = {"rgbmRange": RGBM_RANGE, "samples": bm.get("samples"), "objects": {}}
    PER_LIGHT_RE = re.compile(r"^(\w+?)_(\d+)$")
    for obj, info in bm["objects"].items():
        size = info["size"]
        mips = size >= 4096 or obj.startswith("LM_Atlas") or obj == "Floor_Hall"
        entry = {"size": size, "groups": {}, "mipmaps": mips}
        per = {}
        for k, f in info["files"].items():
            m = PER_LIGHT_RE.match(k)
            if m:
                per.setdefault(m.group(1), {})[int(m.group(2))] = f
        for g, files in per.items():
            n = max(files) + 1
            lums = []
            for i in range(n):
                a = load_exr(os.path.join(BAKE, files[i]["file"]))
                lums.append(a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722)
            S = max(float(np.percentile(l, 99.95)) for l in lums) or 1.0
            urls = []
            for t in range(0, n, 4):
                chans = [np.sqrt(np.clip(lums[i] / S, 0, 1)) if i < n else np.zeros_like(lums[0]) for i in range(t, t + 4)]
                png = os.path.join(TMP, "%s_%s_p%d.png" % (obj, g, t // 4))
                Image.fromarray((np.dstack(chans) * 255 + 0.5).astype(np.uint8), "RGBA").save(png)
                ktx(png, os.path.join(LM_OUT, "%s_%s_p%d.ktx2" % (obj, g, t // 4)), False)
                urls.append("assets/lm/%s_%s_p%d.ktx2" % (obj, g, t // 4))
            entry.setdefault("perLight", {})[g] = {"count": n, "scale": S, "encoding": "sqrt", "urls": urls}
            print("  lm %-14s %-8s per-light x%d scale=%.3f" % (obj, g, n, S))
        hdr_size = min(size, 2048)
        entry["size"] = hdr_size if mips else size
        for g, f in sorted(info["files"].items()):
            if PER_LIGHT_RE.match(g):
                continue
            out = os.path.join(LM_OUT, "%s_%s.ktx2" % (obj, g))
            cmd = ["ktx", "create", "--format", "E5B9G9R9_UFLOAT_PACK32", "--zstd", "19"]
            if hdr_size != size:
                cmd += ["--width", str(hdr_size), "--height", str(hdr_size)]
            if mips:
                cmd.append("--generate-mipmap")
            run(cmd + [os.path.join(BAKE, f["file"]), out])
            # alpha samples as 1: rgb * 1 * range / range = linear HDR
            entry["groups"][g] = {"url": "assets/lm/%s_%s.ktx2" % (obj, g), "scale": RGBM_RANGE, "encoding": "rgb9e5",
                                  "p50": f["stats"]["p50"], "p99": f["stats"]["p99"]}
            scale = RGBM_RANGE
            print("  lm %-14s %-8s scale=%.3f  %d KB" % (obj, g, scale, os.path.getsize(out) // 1024))
        lm_manifest["objects"][obj] = entry
    lm_manifest["vertex"] = json.load(open(os.path.join(SRC, "vertex_lm.json")))
    json.dump(lm_manifest, open(lm_path, "w"), indent=1)

if "tex" in ONLY:
    lm_manifest = json.load(open(lm_path))
    # translucency colour maps + perforation mask (not part of glTF)
    mats = json.load(open(os.path.join(B, "materials_room", "materials.json"), encoding="utf-8"))["materials"]
    lm_manifest["textures"] = {}
    for name, m in mats.items():
        tr = (m.get("translucency") or {}).get("colorTex")
        if not tr:
            continue
        stem = os.path.splitext(tr)[0]
        out = os.path.join(TEX_OUT, stem + ".ktx2")
        if not os.path.exists(out):
            run(["ktx", "create", "--format", "R8G8B8_SRGB", "--encode", "uastc", "--uastc-quality", "2", "--zstd", "18",
                 "--generate-mipmap", os.path.join(B, "materials_room", "tex", tr), out])
        lm_manifest["textures"][m.get("origName") or name] = "assets/tex/%s.ktx2" % stem
    run(["ktx", "create", "--format", "R8_UNORM", "--assign-tf", "linear", "--encode", "uastc", "--zstd", "18",
         "--generate-mipmap", os.path.join(B, "blender_room", "tex", "perf_mask.png"), os.path.join(TEX_OUT, "perf_mask.ktx2")])
    lm_manifest["textures"]["perf_mask"] = "assets/tex/perf_mask.ktx2"
    json.dump(lm_manifest, open(lm_path, "w"), indent=1)

if "glb" in ONLY:
    src = os.path.join(SRC, "room.glb")
    t = [os.path.join(TMP, "s%d.glb" % i) for i in range(8)]
    gt("optimize", src, t[1], "--compress", "false", "--texture-compress", "false", "--flatten", "false", "--join",
       "false", "--instance", "false", "--palette", "false", "--simplify", "false", "--prune-solid-textures", "true",
       "--prune-attributes", "false")  # lightmap UVs (TEXCOORD_1) / vertex lightmaps are used by runtime materials
    # big visible surfaces (walls, ceilings, floor, sofas, rugs...) and every fabric / leather: UASTC 2K;
    # the onyx hero stays 4K; small things ETC1S 1K
    areas = json.load(open(os.path.join(SRC, "material_area.json")))
    mats = json.load(open(os.path.join(B, "materials_room", "materials.json"), encoding="utf-8"))["materials"]
    big = sorted(k for k, m in mats.items() if areas.get(k, 0) > 2.5 or m.get("surface"))
    print("high-quality materials:", len(big))
    pat_big = "*{%s}_*" % ",".join(big)
    gt("uastc", t[1], t[2], "--pattern", "*2147483589_*nrm*", "--level", "2", "--resize", "2048", "--rdo",
       "--rdo-lambda", "1.0", "--zstd", "18")
    gt("uastc", t[2], t[3], "--pattern", "*2147483589*", "--level", "2", "--rdo", "--rdo-lambda", "1.0", "--zstd", "18")
    # every other normal map: 1K is plenty for bevels / grain
    gt("uastc", t[3], t[4], "--slots", "normalTexture", "--level", "1", "--resize", "1024", "--rdo", "--rdo-lambda", "2",
       "--zstd", "18")
    gt("uastc", t[4], t[5], "--pattern", pat_big, "--slots", "baseColorTexture", "--level", "2", "--resize", "2048",
       "--rdo", "--rdo-lambda", "3", "--zstd", "18")
    gt("etc1s", t[5], t[6], "--quality", "255", "--resize", "1024")
    # per-vertex light (RGBM in _NIKK/_NIKE): 8 bit is the precision it was encoded for
    run(["node", os.path.join(ROOT, "pipeline", "web", "quantize_vertex_light.mjs"), t[6], t[7]])
    final = os.path.join(TMP, "scene.glb")
    gt("meshopt", t[7], final, "--level", "high")
    print("scene.glb %.1f MB" % (os.path.getsize(final) / 2 ** 20))
    # GitHub refuses files over 100 MB and hosts like Vercel skip Git LFS: ship the scene in plain-git pieces
    split_dir = os.path.join(PUB, "scene")
    shutil.rmtree(split_dir, ignore_errors=True)
    os.makedirs(split_dir)
    if os.path.exists(os.path.join(PUB, "scene.glb")):
        os.remove(os.path.join(PUB, "scene.glb"))
    data = open(final, "rb").read()
    parts = []
    for i in range(0, len(data), PART):
        name = "scene/scene_%d.bin" % (i // PART)
        open(os.path.join(PUB, name), "wb").write(data[i:i + PART])
        parts.append("assets/" + name)
    lm_manifest = json.load(open(lm_path))
    lm_manifest["parts"] = {"assets/scene.glb": parts}
    json.dump(lm_manifest, open(lm_path, "w"), indent=1)
    for f in ("cameras.json", "lights.json"):
        shutil.copy(os.path.join(SRC, f), os.path.join(PUB, f))
# download sizes for an honest preloader: every file the viewer fetches before showing the scene
lm_manifest = json.load(open(lm_path))
files = {u: None for u in lm_manifest.get("parts", {}).get("assets/scene.glb", ["assets/scene.glb"])}
files["assets/chandelier.glb"] = None
for info in lm_manifest["objects"].values():
    for g in info.get("groups", {}).values():
        files[g["url"]] = None
    for pl in info.get("perLight", {}).values():
        for u in pl["urls"]:
            files[u] = None
for u in lm_manifest.get("textures", {}).values():
    files[u] = None
sizes = {u: os.path.getsize(os.path.join(ROOT, "web", "public", u)) for u in files
         if os.path.exists(os.path.join(ROOT, "web", "public", u))}
lm_manifest["bytes"] = sizes
json.dump(lm_manifest, open(lm_path, "w"), indent=1)
print("download total %.1f MB in %d files" % (sum(sizes.values()) / 2 ** 20, len(sizes)))
print("done")
