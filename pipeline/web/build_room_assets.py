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
# NIK_LITE=1: the phone scene (export_room_glb.py --lite -> build/web_lite) into web/public/assets-lite, lightmaps and
# textures at 1K (the onyx at 2K); the translucency maps / perforation mask are shared with the full set
LITE = os.environ.get("NIK_LITE") == "1"
# NIK_MOBILE=1: the whole room for phones (web/public/assets-mobile): ~1/5 of the triangles, ETC1S 1K textures, lightmaps
# as 8 bit log-encoded UASTC (any GPU: no HDR texture formats on phones; a half float fallback is 8 bytes a texel)
MOBILE = os.environ.get("NIK_MOBILE") == "1"
PUB_NAME = "assets-lite" if LITE else "assets-mobile" if MOBILE else "assets"
SRC = os.path.join(B, "web_lite" if LITE else "web_room")
BAKE = os.path.join(B, "bake_room")
PUB = os.path.join(ROOT, "web", "public", PUB_NAME)
LM_OUT = os.path.join(PUB, "lm")
TEX_OUT = os.path.join(PUB, "tex") if MOBILE else os.path.join(ROOT, "web", "public", "assets", "tex")
TMP = os.path.join(B, "web_lite_tmp" if LITE else "web_mobile_tmp" if MOBILE else "web_room_tmp")
LM_MAX = 1024 if MOBILE else 2048
MOBILE_BIG = set()  # (mixer render targets are half float: 2K would cost 43 MB each on a phone)
# phones show the evening only: its lightmaps keep their full resolution (downsized 2K -> 1K the charts bled into
# each other: torn light, hot spots); the daylight group, barely visible at night, goes to 1K
LITE_ENV = 1024
for d in (PUB, LM_OUT, TEX_OUT, TMP):
    os.makedirs(d, exist_ok=True)
RGBM_RANGE = 16.0
HQ_MATERIALS = {"M4922", "M5796"}  # travertine floor, white marble
PART = 20 * 2 ** 20  # scene.glb pieces: under GitHub's 50 MB warning and Cloudflare Pages' 25 MB per file
ENV = dict(os.environ)
ENV["PATH"] = ";".join([r"C:\Program Files\nodejs", os.path.join(os.environ["APPDATA"], "npm"),
                        r"C:\Program Files\KTX-Software\bin", ENV.get("PATH", "")])
# phones keep LockBorder too: Permissive with a large error scrambled the wood-block mosaic walls and frayed thin edges;
# the mosaic (light per vertex of every block) keeps the desktop density
if MOBILE:
    ENV["NIK_SIMP_GENTLE"] = "M15025"
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


def encode_hdr(job):
    """EXR -> box-filtered to size -> fp16 EXR -> UASTC HDR 4x4 KTX2 (BC6H on desktop, ASTC HDR where it exists), via the
    WASI build of basisu (build/tools/basisu); mips for the big atlases"""
    src, out, size, mips, name = job
    a = load_exr(src)
    f = a.shape[0] // size
    if f > 1:
        a = a.reshape(size, f, size, f, 3).mean((1, 3))
    wd = os.path.join(TMP, "hdr_" + name)
    os.makedirs(wd, exist_ok=True)
    OpenEXR.File({"compression": OpenEXR.ZIP_COMPRESSION, "type": OpenEXR.scanlineimage},
                 {"RGB": np.clip(a, 0, 65000).astype(np.float16)}).write(os.path.join(wd, "in.exr"))
    tools = os.path.join(ROOT, "build", "tools", "basisu")
    cmd = ["node", "--no-warnings", os.path.join(tools, "run.mjs"), os.path.join(tools, "basisu_st.wasm"), "-hdr_4x4",
           "-file", "in.exr", "-output_file", "out.ktx2"] + (["-mipmap"] if mips else [])
    r = subprocess.run(cmd, cwd=wd, env=ENV, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not os.path.exists(os.path.join(wd, "out.ktx2")):
        raise SystemExit("basisu failed for %s: %s" % (name, r.stdout[-2000:]))
    shutil.move(os.path.join(wd, "out.ktx2"), out)
    shutil.rmtree(wd, ignore_errors=True)
    return name, os.path.getsize(out)


def encode_log(job):
    """EXR -> box-filtered to size -> 8 bit log encoding (v = log2(1 + c/c0) / k, dithered) -> UASTC LDR KTX2.
    Returns the decode constants for the shader: c = c0 * (exp2(v * k) - 1)"""
    src, out, size, mips, name = job
    a = load_exr(src)
    f = a.shape[0] // size
    if f > 1:
        a = a.reshape(size, f, size, f, 3).mean((1, 3))
    R = max(0.5, float(np.percentile(a, 99.99)) * 1.25)
    c0 = R / 16384.0
    k = float(np.log2(1.0 + R / c0))
    v = np.log2(1.0 + np.minimum(a, R) / c0) / k * 255.0
    rng = np.random.default_rng(7)
    v = v + (rng.random(v.shape, dtype=np.float32) + rng.random(v.shape, dtype=np.float32) - 1.0) * 0.5  # triangular dither
    rgba = np.dstack([np.clip(v + 0.5, 0, 255).astype(np.uint8), np.full(v.shape[:2], 255, np.uint8)])
    png = os.path.join(TMP, "log_%s.png" % name)
    Image.fromarray(rgba, "RGBA").save(png)
    ktx(png, out, False)
    os.remove(png)
    return name, os.path.getsize(out), [c0, k]


def run_hdr_jobs(jobs):
    from concurrent.futures import ThreadPoolExecutor
    res = {}
    with ThreadPoolExecutor(max_workers=int(os.environ.get("NIK_JOBS", "6"))) as ex:
        for r in ex.map(encode_log if MOBILE else encode_hdr, jobs):
            print("  lm %-24s %6d KB" % (r[0], r[1] // 1024), flush=True)
            res[r[0]] = r[2:] and r[2]
    return res


lm_path = os.path.join(PUB, "lightmaps.json")
if "lm" in ONLY:
    bm = json.load(open(os.path.join(BAKE, "bake_manifest.json")))
    lm_manifest = {"rgbmRange": RGBM_RANGE, "samples": bm.get("samples"), "objects": {}}
    PER_LIGHT_RE = re.compile(r"^(\w+?)_(\d+)$")
    present = set(json.load(open(os.path.join(SRC, "objects.json")))) if os.path.exists(os.path.join(SRC, "objects.json")) else None
    hdr_jobs = []
    logs = []
    for obj, info in bm["objects"].items():
        if present is not None and obj not in present:
            continue
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
                im = Image.fromarray((np.dstack(chans) * 255 + 0.5).astype(np.uint8), "RGBA")
                if im.width > LM_MAX:
                    im = im.resize((LM_MAX, LM_MAX), Image.LANCZOS)
                im.save(png)
                ktx(png, os.path.join(LM_OUT, "%s_%s_p%d.ktx2" % (obj, g, t // 4)), False)
                urls.append("%s/lm/%s_%s_p%d.ktx2" % (PUB_NAME, obj, g, t // 4))
            entry.setdefault("perLight", {})[g] = {"count": n, "scale": S, "encoding": "sqrt", "urls": urls}
            print("  lm %-14s %-8s per-light x%d scale=%.3f" % (obj, g, n, S))
        hdr_size = min(size, 2048 if (MOBILE and obj in MOBILE_BIG) else LM_MAX)
        if MOBILE:
            mips = False  # the mixer samples 1:1, the direct (big atlas) path is not used on phones
            entry["mipmaps"] = False
        entry["size"] = hdr_size
        for g, f in sorted(info["files"].items()):
            if PER_LIGHT_RE.match(g):
                continue
            out = os.path.join(LM_OUT, "%s_%s.ktx2" % (obj, g))
            gsize = min(hdr_size, LITE_ENV) if LITE and g == "env" else hdr_size
            hdr_jobs.append((os.path.join(BAKE, f["file"]), out, gsize, mips, "%s_%s" % (obj, g)))
            # alpha samples as 1: rgb * 1 * range / range = linear HDR
            entry["groups"][g] = {"url": "%s/lm/%s_%s.ktx2" % (PUB_NAME, obj, g), "scale": 1.0 if MOBILE else RGBM_RANGE,
                                  "encoding": "log" if MOBILE else "rgb9e5", "p50": f["stats"]["p50"], "p99": f["stats"]["p99"]}
            logs.append((entry["groups"][g], "%s_%s" % (obj, g)))
        lm_manifest["objects"][obj] = entry
    consts = run_hdr_jobs(hdr_jobs)
    if MOBILE:
        for grp, name in logs:
            grp["log"] = consts[name]
    lm_manifest["vertex"] = json.load(open(os.path.join(SRC, "vertex_lm.json")))
    # sections written by the other steps (tex, glb) survive a lightmaps-only run
    if os.path.exists(lm_path):
        old = json.load(open(lm_path))
        for k in ("textures", "parts"):
            if k in old:
                lm_manifest[k] = old[k]
    json.dump(lm_manifest, open(lm_path, "w"), indent=1)

if "tex" in ONLY and LITE:  # only the island onyx glows in the phone scene: its translucency map at 2K
    lm_manifest = json.load(open(lm_path))
    mats = json.load(open(os.path.join(B, "materials_room", "materials.json"), encoding="utf-8"))["materials"]
    lm_manifest["textures"] = {}
    os.makedirs(os.path.join(PUB, "tex"), exist_ok=True)
    for name, m in mats.items():
        tr = (m.get("translucency") or {}).get("colorTex")
        if not tr or m.get("origName") != "Material #-2147483589":
            continue
        stem = os.path.splitext(tr)[0]
        png = os.path.join(TMP, stem + "_2k.png")
        Image.open(os.path.join(B, "materials_room", "tex", tr)).convert("RGB").resize((2048, 2048), Image.LANCZOS).save(png)
        run(["ktx", "create", "--format", "R8G8B8_SRGB", "--encode", "uastc", "--uastc-quality", "2", "--zstd", "18",
             "--generate-mipmap", png, os.path.join(PUB, "tex", stem + ".ktx2")])
        lm_manifest["textures"][m["origName"]] = "%s/tex/%s.ktx2" % (PUB_NAME, stem)
    json.dump(lm_manifest, open(lm_path, "w"), indent=1)
elif "tex" in ONLY:
    os.makedirs(TEX_OUT, exist_ok=True)
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
            tsize = "1024" if MOBILE else "2048"
            run(["ktx", "create", "--format", "R8G8B8_SRGB", "--encode", "uastc", "--uastc-quality", "2", "--zstd", "18",
                 "--width", tsize, "--height", tsize, "--generate-mipmap", os.path.join(B, "materials_room", "tex", tr), out])
        lm_manifest["textures"][m.get("origName") or name] = "%s/tex/%s.ktx2" % (PUB_NAME, stem)
    run(["ktx", "create", "--format", "R8_UNORM", "--assign-tf", "linear", "--encode", "uastc", "--zstd", "18",
         "--generate-mipmap", os.path.join(B, "blender_room", "tex", "perf_mask.png"), os.path.join(TEX_OUT, "perf_mask.ktx2")])
    lm_manifest["textures"]["perf_mask"] = "%s/tex/perf_mask.ktx2" % PUB_NAME
    json.dump(lm_manifest, open(lm_path, "w"), indent=1)

if "glb" in ONLY:
    src = os.path.join(SRC, "room.glb")
    t = [os.path.join(TMP, "s%d.glb" % i) for i in range(8)]
    t3b = os.path.join(TMP, "s3b.glb")
    gt("optimize", src, t[1], "--compress", "false", "--texture-compress", "false", "--flatten", "false", "--join",
       "false", "--instance", "false", "--palette", "false", "--simplify", "false", "--prune-solid-textures", "true",
       "--prune-attributes", "false")  # lightmap UVs (TEXCOORD_1) / vertex lightmaps are used by runtime materials
    # furniture lit per vertex: ~half the triangles at walking distance (ratio / error: NIK_SIMPLIFY="0.5,0.004")
    ratio, err = os.environ.get("NIK_SIMPLIFY", "0.3,0.006" if MOBILE else "0.5,0.004").split(",")
    if float(ratio) < 1:
        simp = os.path.join(TMP, "s1_simplified.glb")
        run(["node", "--max-old-space-size=16000", os.path.join(ROOT, "pipeline", "web", "simplify_furniture.mjs"), t[1], simp, ratio, err])
        os.replace(simp, t[1])
    if MOBILE:  # the rest of the geometry too (plants, static furniture, faucets), gently
        simp = os.path.join(TMP, "s1_simplified.glb")
        run(["node", "--max-old-space-size=16000", os.path.join(ROOT, "pipeline", "web", "simplify_furniture.mjs"), t[1], simp, "0.4", "0.006",
             "Static_,Plants,Faucets"])
        os.replace(simp, t[1])
    # big visible surfaces (walls, ceilings, floor, sofas, rugs...) and every fabric / leather: UASTC 2K;
    # the onyx hero stays 4K; small things ETC1S 1K
    if MOBILE:
        # onyx hero 2K UASTC; floor stone / marble ETC1S 2K; everything else ETC1S 1K, normals 256 (bevel grain only)
        gt("uastc", t[1], t[2], "--pattern", "*2147483589_*nrm*", "--level", "2", "--resize", "1024", "--rdo", "--rdo-lambda", "2",
           "--zstd", "18")
        gt("uastc", t[2], t[3], "--pattern", "*2147483589*", "--level", "2", "--resize", "2048", "--rdo", "--rdo-lambda", "3", "--zstd", "18")
        gt("uastc", t[3], t[4], "--slots", "normalTexture", "--level", "0", "--resize", "256", "--rdo", "--rdo-lambda", "4", "--zstd", "18")
        gt("etc1s", t[4], t[5], "--pattern", "*{%s}_*" % ",".join(sorted(HQ_MATERIALS)), "--slots", "baseColorTexture", "--quality", "255",
           "--resize", "2048")
        gt("etc1s", t[5], t[6], "--quality", "200", "--resize", "1024")
        run(["node", os.path.join(ROOT, "pipeline", "web", "quantize_vertex_light.mjs"), t[6], t[7]])
        final = os.path.join(TMP, "scene.glb")
        gt("meshopt", t[7], final, "--level", "high")
        print("scene.glb %.1f MB" % (os.path.getsize(final) / 2 ** 20))
    if not MOBILE:
        areas = json.load(open(os.path.join(SRC, "material_area.json")))
        mats = json.load(open(os.path.join(B, "materials_room", "materials.json"), encoding="utf-8"))["materials"]
        big = sorted(k for k, m in mats.items() if areas.get(k, 0) > 2.5 or m.get("surface"))
        print("high-quality materials:", len(big))
        # UASTC stays for what is seen from close by as a whole surface: onyx / translucent stone, the floor stone, marble;
        # the rest of the big materials (fabric, leather, wood, paint...) is ETC1S at 2K: a fifth of the bytes
        hq = [k for k in big if k in HQ_MATERIALS or mats[k].get("translucency")]
        other = [k for k in big if k not in hq]
        print("UASTC 2K:", hq, " ETC1S 2K:", len(other))
        hero, nrm, base, small = ("2048", "2048", "2048", "1024") if not LITE else ("2048", "1024", "1024", "512")
        gt("uastc", t[1], t[2], "--pattern", "*2147483589_*nrm*", "--level", "2", "--resize", hero, "--rdo",
           "--rdo-lambda", "1.0", "--zstd", "18")
        gt("uastc", t[2], t[3], "--pattern", "*2147483589*", "--level", "2", "--resize", "4096" if not LITE else hero, "--rdo",
           "--rdo-lambda", "2.0", "--zstd", "18")
        # every other normal map: 1K is plenty for bevels / grain (512 on phones)
        # (big surfaces keep 1K normals; bevels and grain of everything else read the same at 512)
        gt("uastc", t[3], t3b, "--pattern", "*{%s}_*nrm*" % ",".join(hq), "--level", "1", "--resize", "1024" if not LITE else "512",
           "--rdo", "--rdo-lambda", "4", "--zstd", "18")
        gt("uastc", t3b, t[4], "--slots", "normalTexture", "--level", "1", "--resize", "512", "--rdo",
           "--rdo-lambda", "4", "--zstd", "18")
        gt("uastc", t[4], t[5], "--pattern", "*{%s}_*" % ",".join(hq), "--slots", "baseColorTexture", "--level", "2",
           "--resize", base, "--rdo", "--rdo-lambda", "4", "--zstd", "18")
        t5b = os.path.join(TMP, "s5b.glb")
        gt("etc1s", t[5], t5b, "--pattern", "*{%s}_*" % ",".join(other), "--slots", "baseColorTexture", "--quality", "255",
           "--resize", base)
        gt("etc1s", t5b, t[6], "--quality", "255", "--resize", small)
        # per-vertex light (RGBM in _NIKK/_NIKE): 8 bit is the precision it was encoded for
        run(["node", os.path.join(ROOT, "pipeline", "web", "quantize_vertex_light.mjs"), t[6], t[7]])
        final = os.path.join(TMP, "scene.glb")
        gt("meshopt", t[7], final, "--level", "high")
        print("scene.glb %.1f MB" % (os.path.getsize(final) / 2 ** 20))
    # GitHub refuses files over 100 MB and hosts like Vercel skip Git LFS: ship the scene in plain-git pieces
    split_dir = os.path.join(PUB, "scene")  # noqa
    shutil.rmtree(split_dir, ignore_errors=True)
    os.makedirs(split_dir)
    if os.path.exists(os.path.join(PUB, "scene.glb")):
        os.remove(os.path.join(PUB, "scene.glb"))
    data = open(final, "rb").read()
    parts = []
    for i in range(0, len(data), PART):
        name = "scene/scene_%d.bin" % (i // PART)
        open(os.path.join(PUB, name), "wb").write(data[i:i + PART])
        parts.append(PUB_NAME + "/" + name)
    lm_manifest = json.load(open(lm_path))
    lm_manifest["parts"] = {PUB_NAME + "/scene.glb": parts}
    json.dump(lm_manifest, open(lm_path, "w"), indent=1)
    if not LITE:  # cameras / floor lights are shared
        for f in ("cameras.json", "lights.json"):
            shutil.copy(os.path.join(SRC, f), os.path.join(PUB, f))
# download sizes for an honest preloader: every file the viewer fetches before showing the scene
lm_manifest = json.load(open(lm_path))
files = {u: None for u in lm_manifest.get("parts", {}).get(PUB_NAME + "/scene.glb", [PUB_NAME + "/scene.glb"])}
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
