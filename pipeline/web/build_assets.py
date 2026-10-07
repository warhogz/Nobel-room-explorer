"""Builds web assets from the Blender outputs.

python build_assets.py <root>
  in : build/web/scene.glb, build/bake/*.exr + bake_manifest.json, build/web/cameras.json
  out: web/public/assets/{scene.glb, lightmaps.json, cameras.json, lm/*.ktx2}

Lightmaps: HDR -> RGBM (range 16, per-file pre-scale stored in lightmaps.json) -> KTX2 UASTC + zstd, linear.
Decode in shader: rgb = tex.rgb * tex.a * 16 / scale.
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
PUB = os.path.join(ROOT, "web", "public", "assets")
LM_OUT = os.path.join(PUB, "lm")
TMP = os.path.join(B, "web_tmp")
for d in (PUB, LM_OUT, TMP):
    os.makedirs(d, exist_ok=True)
RGBM_RANGE = 16.0
ENV = dict(os.environ)
ENV["PATH"] = ";".join([r"C:\Program Files\nodejs", os.path.join(os.environ["APPDATA"], "npm"),
                        r"C:\Program Files\KTX-Software\bin", ENV.get("PATH", "")])


def run(cmd):
    print(">", subprocess.list2cmdline(cmd), flush=True)
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


# ---------------------------------------------------------------- lightmaps
bm = json.load(open(os.path.join(B, "bake", "bake_manifest.json")))
lm_manifest = {"rgbmRange": RGBM_RANGE, "samples": bm.get("samples"), "objects": {}}
PER_LIGHT_RE = re.compile(r"^(\w+?)_(\d+)$")
for obj, info in bm["objects"].items():
    entry = {"size": info["size"], "groups": {}}
    # per-light groups (e.g. pol_0..pol_7): luminance only, 4 lights per RGBA texture, sqrt-encoded, shared scale
    per = {}
    for k, f in info["files"].items():
        m = PER_LIGHT_RE.match(k)
        if m:
            per.setdefault(m.group(1), {})[int(m.group(2))] = f
    for g, files in per.items():
        n = max(files) + 1
        lums = []
        for i in range(n):
            a = load_exr(os.path.join(B, "bake", files[i]["file"]))
            lums.append(a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722)
        S = max(float(np.percentile(l, 99.95)) for l in lums) or 1.0
        urls = []
        for t in range(0, n, 4):
            chans = [np.sqrt(np.clip(lums[i] / S, 0, 1)) if i < n else np.zeros_like(lums[0]) for i in range(t, t + 4)]
            png = os.path.join(TMP, "%s_%s_p%d.png" % (obj, g, t // 4))
            Image.fromarray((np.dstack(chans) * 255 + 0.5).astype(np.uint8), "RGBA").save(png)
            ktx = os.path.join(LM_OUT, "%s_%s_p%d.ktx2" % (obj, g, t // 4))
            run(["ktx", "create", "--format", "R8G8B8A8_UNORM", "--assign-tf", "linear", "--encode", "uastc",
                 "--uastc-quality", "2", "--zstd", "18", png, ktx])
            urls.append("assets/lm/%s_%s_p%d.ktx2" % (obj, g, t // 4))
        entry.setdefault("perLight", {})[g] = {"count": n, "scale": S, "encoding": "sqrt", "urls": urls}
        print("  lm %-8s %-8s per-light x%d scale=%.3f" % (obj, g, n, S))
    for g, f in sorted(info["files"].items()):
        if PER_LIGHT_RE.match(g) or g in per:
            continue
        a = load_exr(os.path.join(B, "bake", f["file"]))
        mx = a.max(axis=-1)
        ref = float(np.percentile(mx, 99.9))
        scale = 12.0 / ref if ref > 1e-6 else 1.0
        v = a * scale
        m = np.clip(v.max(axis=-1, keepdims=True) / RGBM_RANGE, 0, 1)
        m = np.ceil(m * 255.0) / 255.0
        rgb = np.where(m > 0, v / np.maximum(m * RGBM_RANGE, 1e-8), 0)
        rgba = np.dstack([np.clip(rgb, 0, 1), m])
        # EXR rows are top-down like PNG; glTF/three flipY=false for KTX2 -> keep orientation, flip in shader uv
        png = os.path.join(TMP, "%s_%s.png" % (obj, g))
        Image.fromarray((rgba * 255 + 0.5).astype(np.uint8), "RGBA").save(png)
        ktx = os.path.join(LM_OUT, "%s_%s.ktx2" % (obj, g))
        run(["ktx", "create", "--format", "R8G8B8A8_UNORM", "--assign-tf", "linear", "--encode", "uastc",
             "--uastc-quality", "2", "--zstd", "18", png, ktx])
        entry["groups"][g] = {"url": "assets/lm/%s_%s.ktx2" % (obj, g), "scale": scale,
                              "p50": f["stats"]["p50"], "p99": f["stats"]["p99"]}
        print("  lm %-8s %-8s scale=%.3f  %d KB" % (obj, g, scale, os.path.getsize(ktx) // 1024))
    lm_manifest["objects"][obj] = entry
# translucency colour maps (not part of glTF): material name -> KTX2 (sRGB, UASTC, mipmapped)
mats = json.load(open(os.path.join(B, "materials", "materials.json"), encoding="utf-8"))["materials"]
os.makedirs(os.path.join(PUB, "tex"), exist_ok=True)
lm_manifest["textures"] = {}
for name, m in mats.items():
    tr = (m.get("translucency") or {}).get("colorTex")
    if not tr:
        continue
    stem = os.path.splitext(tr)[0]
    out = os.path.join(PUB, "tex", stem + ".ktx2")
    run(["ktx", "create", "--format", "R8G8B8_SRGB", "--encode", "uastc", "--uastc-quality", "2", "--zstd", "18",
         "--generate-mipmap", os.path.join(B, "materials", "tex", tr), out])
    lm_manifest["textures"][name] = "assets/tex/%s.ktx2" % stem
json.dump(lm_manifest, open(os.path.join(PUB, "lightmaps.json"), "w"), indent=1)

# ---------------------------------------------------------------- scene.glb
src = os.path.join(B, "web", "scene.glb")
t1, t2, t3, t4 = (os.path.join(TMP, "s%d.glb" % i) for i in range(1, 5))
gt("optimize", src, t1, "--compress", "false", "--texture-compress", "false", "--flatten", "false", "--join", "false",
   "--instance", "false", "--palette", "false", "--simplify", "false", "--prune-solid-textures", "true",
   # lightmap UVs (TEXCOORD_1) are used by runtime materials only -> must not be pruned
   "--prune-attributes", "false")
# hero materials (onyx island, walnut table) + all normal maps: UASTC; everything else ETC1S
gt("uastc", t1, t2, "--pattern", "*2147483589_nrm*", "--level", "2", "--resize", "2048", "--rdo",
   "--rdo-lambda", "1.0", "--zstd", "18")
t2b = os.path.join(TMP, "s2b.glb")
gt("uastc", t2, t2b, "--pattern", "*2147483589*", "--level", "2", "--rdo", "--rdo-lambda", "1.0", "--zstd", "18")
t2 = t2b
gt("uastc", t2, t3, "--pattern", "*76111117*", "--level", "2", "--zstd", "18")
gt("uastc", t3, t4, "--slots", "normalTexture", "--level", "1", "--zstd", "18")
t5 = os.path.join(TMP, "s5.glb")
gt("etc1s", t4, t5, "--quality", "200")
gt("meshopt", t5, os.path.join(PUB, "scene.glb"), "--level", "high")
print("scene.glb %.1f MB" % (os.path.getsize(os.path.join(PUB, "scene.glb")) / 2 ** 20))
shutil.copy(os.path.join(B, "web", "cameras.json"), os.path.join(PUB, "cameras.json"))
shutil.copy(os.path.join(B, "web", "lights.json"), os.path.join(PUB, "lights.json"))
print("done")
