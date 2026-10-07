"""Corona material graph (from dump_scene.py JSON) -> PBR material descriptions + processed textures.

usage: compile_materials.py <dump_dir> <tex_src_dir> <out_dir>
writes <out_dir>/materials.json and <out_dir>/tex/*.png

Approximations (documented on purpose):
- Color Correction chains are baked into the texture (saturation, hue, gain/gamma/pivot/lift, brightness/contrast),
  evaluated in linear space like 3ds Max does with input gamma 2.2.
- Composite -> first enabled layer only; Mix/Falloff -> map1; CoronaMix -> bottom; CoronaAO/Noise -> ignored.
- Bump from a plain bitmap is converted to a tangent-space normal map; CoronaNormal maps are used as-is.
- Legacy material with fresnel IOR >= 4 is treated as metal (base colour = reflect colour).
"""
import hashlib
import json
import math
import ntpath
import os
import sys

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

DUMP, TEXSRC, OUT = sys.argv[1:4]
TEXOUT = os.path.join(OUT, "tex")
os.makedirs(TEXOUT, exist_ok=True)
R = json.load(open(os.path.join(DUMP, "refs.json"), encoding="utf-8"))
OBJS = json.load(open(os.path.join(DUMP, "objects.json"), encoding="utf-8"))
MAX_GAMMA = 2.2
HERO_SIZE, DEFAULT_SIZE, SMALL_SIZE = 4096, 2048, 1024
warnings = []


def warn(msg):
    if msg not in warnings:
        warnings.append(msg)
        print("WARN", msg)


def ref(v):
    return R[v["$ref"]] if isinstance(v, dict) and "$ref" in v else None


def col_lin(c):
    if not c:
        return [0.0, 0.0, 0.0]
    return [round((x / 255.0) ** MAX_GAMMA, 5) for x in c["rgb"]]


# ---------------------------------------------------------------- texture graph resolution
def uv_of_bitmap(e):
    p = e["props"]
    if e["class"] == "CoronaBitmap":
        s = p.get("uvwScale") or [1, 1, 1]
        o = p.get("uvwOffset") or [0, 0, 0]
        return {"scale": [s[0], s[1]], "offset": [o[0], o[1]], "rot": p.get("wAngle", 0.0) or 0.0,
                "channel": p.get("uvwChannel", 1), "realWorld": bool(p.get("realWorldScale"))}
    c = ref(p.get("coords"))
    if not c:
        return {"scale": [1, 1], "offset": [0, 0], "rot": 0.0, "channel": 1, "realWorld": False}
    q = c["props"]
    return {"scale": [q.get("U_Tiling", 1.0), q.get("V_Tiling", 1.0)], "offset": [q.get("U_Offset", 0.0),
            q.get("V_Offset", 0.0)], "rot": q.get("W_Angle", 0.0) or 0.0, "channel": q.get("mapChannel", 1),
            "realWorld": bool(q.get("realWorldScale"))}


def cc_op(p):
    op = {"t": "cc", "rewire": p.get("rewireMode", 0), "hue": p.get("hueShift", 0.0), "sat": p.get("saturation", 0.0),
          "mode": p.get("lightnessMode", 0), "bright": p.get("brightness", 0.0), "contrast": p.get("contrast", 0.0),
          "gain": p.get("gainRGB", 100.0), "gamma": p.get("gammaRGB", 1.0), "pivot": p.get("pivotRGB", 1.0),
          "lift": p.get("liftRGB", 0.0)}
    if any(p.get(k) for k in ("enableR", "enableG", "enableB")):
        warn("per-channel colour correction ignored")
    return op


def resolve(v, ops=(), depth=0):
    """Returns {'file','ops','uv','level'} | {'color': lin} | {'normal': {...}} | None"""
    e = ref(v)
    if e is None or depth > 20:
        return None
    c, p = e["class"], e["props"]
    if c in ("Bitmaptexture", "CoronaBitmap"):
        fn = p.get("filename") or ""
        lvl = 1.0
        out = ref(p.get("output"))
        if out:
            lvl = (out["props"].get("RGB_Level", 1.0) or 1.0) * (out["props"].get("Output_Amount", 1.0) or 1.0)
        return {"file": ntpath.basename(fn), "ops": list(ops), "uv": uv_of_bitmap(e), "level": lvl}
    if c in ("Color_Correction", "CoronaColorCorrect"):
        if c == "CoronaColorCorrect":
            warn("CoronaColorCorrect treated as pass-through")
            return resolve(p.get("texmap") or p.get("inputTexmap"), ops, depth + 1)
        return resolve(p.get("map"), [cc_op(p)] + list(ops), depth + 1)
    if c == "CompositeTexturemap":
        maps, en = p.get("mapList") or [], p.get("mapEnabled") or []
        for i, m in enumerate(maps):
            if m and (i >= len(en) or en[i]):
                if len(maps) > 1:
                    warn("Composite '%s': using only layer %d" % (e.get("name"), i))
                return resolve(m, ops, depth + 1)
        return None
    if c in ("Mix", "Falloff"):
        return resolve(p.get("map1"), ops, depth + 1) or ({"color": col_lin(p.get("color1"))} if p.get("color1") else None)
    if c == "CoronaMix":
        return resolve(p.get("texmapBottom"), ops, depth + 1) or resolve(p.get("texmapTop"), ops, depth + 1)
    if c == "CoronaColor":
        return {"color": [x * (p.get("multiplier", 1.0) or 1.0) for x in col_lin(p.get("color"))]}
    if c == "CoronaNormal":
        inner = resolve(p.get("normalMap"), (), depth + 1)
        if inner and "file" in inner:
            return {"normal": inner, "mult": p.get("multiplier", 1.0), "flipR": p.get("flipred"),
                    "flipG": p.get("flipgreen"), "swap": p.get("swapRedGreen")}
        return None
    warn("unsupported texmap %s (%s) ignored" % (c, e.get("name")))
    return None


# ---------------------------------------------------------------- texture processing
def srgb_encode(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def lum(x):
    return x[..., 0:1] * 0.2126 + x[..., 1:2] * 0.7152 + x[..., 2:3] * 0.0722


def apply_cc(x, op):
    if op["rewire"] == 1:
        x = np.repeat(lum(x), 3, axis=-1)
    elif op["rewire"] == 2:
        x = 1.0 - x
    if op["hue"]:
        a = math.radians(op["hue"])
        k = 1 / math.sqrt(3)
        cs, sn = math.cos(a), math.sin(a)
        m = np.array([[cs + (1 - cs) / 3, (1 - cs) / 3 - k * sn, (1 - cs) / 3 + k * sn],
                      [(1 - cs) / 3 + k * sn, cs + (1 - cs) / 3, (1 - cs) / 3 - k * sn],
                      [(1 - cs) / 3 - k * sn, (1 - cs) / 3 + k * sn, cs + (1 - cs) / 3]], np.float32)
        x = np.clip(x @ m.T, 0, None)
    if op["sat"]:
        L = lum(x)
        x = np.clip(L + (x - L) * (1 + op["sat"] / 100.0), 0, None)
    if op["mode"] == 1:
        x = x * (op["gain"] / 100.0)
        piv = op["pivot"] or 1.0
        x = piv * np.power(np.clip(x / piv, 0, None), 1.0 / max(op["gamma"], 1e-3))
        x = x + op["lift"]
    else:
        if op["contrast"]:
            x = (x - 0.5) * (1 + op["contrast"] / 100.0) + 0.5
        if op["bright"]:
            x = x + op["bright"] / 100.0
    return np.clip(x, 0, None)


_cache = {}


def load_lin(fname, size_limit):
    path = os.path.join(TEXSRC, fname)
    if not os.path.exists(path):
        return None
    key = (fname, size_limit)
    if key in _cache:
        return _cache[key]
    im = Image.open(path)
    im.draft("RGB", (size_limit, size_limit))
    im = im.convert("RGB")
    # power-of-two sizes (block compression / mipmaps), each side capped at size_limit
    w, h = im.size
    pot = lambda v: min(size_limit, 1 << max(2, round(math.log2(v))))
    if (pot(w), pot(h)) != (w, h):
        im = im.resize((pot(w), pot(h)), Image.LANCZOS)
    a = np.asarray(im, np.float32) / 255.0
    _cache[key] = a
    return a


def rotate_for_uv(a, uv):
    rot = (uv.get("rot") or 0.0) % 360
    if rot in (90.0, 180.0, 270.0):
        a = np.rot90(a, k=int(rot // 90))  # counter-clockwise, like Max W angle
        uv = dict(uv, rot=0.0)
    return a, uv


def tex_name(stem, spec, extra=""):
    h = hashlib.md5(json.dumps([spec, extra], sort_keys=True).encode()).hexdigest()[:8]
    return "%s_%s.png" % (stem, h)


def emit_color(spec, stem, size, alpha=None):
    """baked colour texture (sRGB PNG). returns (filename, uv) or (None, None) if missing"""
    name = tex_name(stem, spec, alpha and alpha.get("file"))
    a = load_lin(spec["file"], size)
    if a is None:
        warn("missing texture %s" % spec["file"])
        return None, None
    x = np.power(a, MAX_GAMMA)
    for op in spec["ops"]:
        x = apply_cc(x, op)
    x = x * spec.get("level", 1.0)
    x, uv = rotate_for_uv(x, spec["uv"])
    rgb = (srgb_encode(x) * 255 + 0.5).astype(np.uint8)
    if alpha:
        al = load_alpha(alpha, rgb.shape[1], rgb.shape[0])
        img = Image.fromarray(np.dstack([rgb, al]), "RGBA")
    else:
        img = Image.fromarray(rgb, "RGB")
    path = os.path.join(TEXOUT, name)
    if not os.path.exists(path):
        img.save(path, optimize=False)
    return name, uv


def eval_data(spec, size):
    a = load_lin(spec["file"], size)
    if a is None:
        warn("missing texture %s" % spec["file"])
        return None, spec["uv"]
    x = np.power(a, MAX_GAMMA)
    for op in spec["ops"]:
        x = apply_cc(x, op)
    x = lum(x)[..., 0] * spec.get("level", 1.0)
    return rotate_for_uv(x, spec["uv"])


def load_alpha(spec, w, h):
    x, _ = eval_data(spec, max(w, h))
    if x is None:
        return np.full((h, w), 255, np.uint8)
    img = Image.fromarray((np.clip(x, 0, 1) * 255 + 0.5).astype(np.uint8), "L").resize((w, h), Image.LANCZOS)
    return np.asarray(img)


def emit_scalar(spec, stem, size, fn):
    """grayscale data texture after mapping fn(values)"""
    x, uv = eval_data(spec, size)
    if x is None:
        return None, None
    name = tex_name(stem, spec, fn.__name__)
    path = os.path.join(TEXOUT, name)
    if not os.path.exists(path):
        Image.fromarray((np.clip(fn(x), 0, 1) * 255 + 0.5).astype(np.uint8), "L").save(path)
    return name, uv


def emit_normal_from_height(spec, stem, size, amount):
    x, uv = eval_data(spec, size)
    if x is None:
        return None, None
    name = tex_name(stem, spec, "n%.3f" % amount)
    path = os.path.join(TEXOUT, name)
    if not os.path.exists(path):
        # strength scaled by resolution so that the look does not depend on texture size
        k = amount * 6.0 * (x.shape[1] / 1024.0)
        dx = (np.roll(x, -1, 1) - np.roll(x, 1, 1)) * 0.5 * k
        dy = (np.roll(x, -1, 0) - np.roll(x, 1, 0)) * 0.5 * k
        n = np.dstack([-dx, dy, np.ones_like(x)])  # +Y up (OpenGL / glTF convention, image row 0 = top)
        n /= np.linalg.norm(n, axis=-1, keepdims=True)
        Image.fromarray(((n * 0.5 + 0.5) * 255 + 0.5).astype(np.uint8), "RGB").save(path)
    return name, uv


def emit_normal_map(nspec, stem, size):
    inner = nspec["normal"]
    a = load_lin(inner["file"], size)
    if a is None:
        warn("missing texture %s" % inner["file"])
        return None, None
    name = tex_name(stem, nspec)
    path = os.path.join(TEXOUT, name)
    if not os.path.exists(path):
        x = a.copy()
        if nspec.get("swap"):
            x[..., [0, 1]] = x[..., [1, 0]]
        if nspec.get("flipR"):
            x[..., 0] = 1 - x[..., 0]
        if nspec.get("flipG"):
            x[..., 1] = 1 - x[..., 1]
        x, _ = rotate_for_uv(x, inner["uv"])
        Image.fromarray((x * 255 + 0.5).astype(np.uint8), "RGB").save(path)
    return name, rotate_for_uv(np.zeros((1, 1)), inner["uv"])[1]


# ---------------------------------------------------------------- materials
def slug(s):
    return "".join(ch if ch.isalnum() else "_" for ch in s).strip("_")[:40] or "mtl"


def compile_physical(e, size):
    p = e["props"]
    stem = slug(e.get("name", "mtl"))
    m = {"name": e.get("name"), "source": e["class"]}
    # base colour (+ opacity in alpha)
    base = resolve(p.get("baseTexmap")) if p.get("baseTexmapOn", True) else None
    op = resolve(p.get("opacityTexmap")) if p.get("opacityTexmapOn", True) else None
    level = p.get("baseLevel", 1.0)
    m["baseColor"] = [c * level for c in col_lin(p.get("baseColor"))]
    if base and "file" in base:
        amt = (p.get("baseMapAmount", 100.0) or 0) / 100.0
        if amt < 0.999:
            warn("%s: base map amount %.0f%% baked as 100%%" % (m["name"], amt * 100))
        m["baseColorTex"], m["uv"] = emit_color(base, stem + "_base", size,
                                               alpha=op if op and "file" in op else None)
        m["baseColor"] = [level] * 3
    elif base and "color" in base:
        m["baseColor"] = [c * level for c in base["color"]]
    if op and "file" in op:
        m["alphaMode"] = "MASK"
        m["alphaCutoff"] = 0.5
        m["doubleSided"] = True
        if not m.get("baseColorTex"):
            warn("%s: opacity map without base map" % m["name"])
    # roughness
    gl_mode = p.get("roughnessMode", 0) == 1
    r0 = p.get("baseRoughness", 0.5)
    rt = resolve(p.get("baseRoughnessTexmap")) if p.get("baseRoughnessTexmapOn", True) else None
    amt = (p.get("baseRoughnessMapAmount", 100.0) or 0) / 100.0

    def rough_fn(x, r0=r0, amt=amt, gl_mode=gl_mode):
        v = (1 - amt) * r0 + amt * x
        return 1 - v if gl_mode else v

    if rt and "file" in rt:
        m["roughnessTex"], _ = emit_scalar(rt, stem + "_rough", DEFAULT_SIZE, rough_fn)
        m["roughness"] = 1.0
    else:
        m["roughness"] = round(1 - r0 if gl_mode else r0, 4)
    m["metallic"] = 1.0 if p.get("metalnessMode", 0) == 1 else 0.0
    m["ior"] = p.get("baseIor", 1.5)
    # bump / normal
    bt = resolve(p.get("baseBumpTexmap")) if p.get("baseBumpTexmapOn", True) else None
    bamt = p.get("baseBumpMapAmount", 1.0) or 0.0
    if bt and "normal" in bt:
        m["normalTex"], _ = emit_normal_map(bt, stem + "_nrm", DEFAULT_SIZE)
        m["normalScale"] = round(bamt * (bt.get("mult") or 1.0), 4)
    elif bt and "file" in bt and bamt:
        m["normalTex"], _ = emit_normal_from_height(bt, stem + "_nrm", size, bamt)
        m["normalScale"] = 1.0
    # translucency
    tf = p.get("translucencyFraction", 0.0) or 0.0
    if tf > 0:
        tc = resolve(p.get("translucencyColorTexmap")) if p.get("translucencyColorTexmapOn", True) else None
        t = {"fraction": tf, "color": col_lin(p.get("translucencyColor"))}
        if tc and "file" in tc:
            t["colorTex"], _ = emit_color(tc, stem + "_transl", size)
        m["translucency"] = t
    if (p.get("refractionAmount", 0) or 0) > 0:
        m["transmission"] = p.get("refractionAmount")
        m["thin"] = bool(p.get("useThinMode"))
    if (p.get("selfIllumLevel", 0) or 0) > 0:
        m["emissive"] = [c * p["selfIllumLevel"] for c in col_lin(p.get("selfIllumColor"))]
    return m


def compile_legacy(e, size):
    p = e["props"]
    stem = slug(e.get("name", "mtl"))
    m = {"name": e.get("name"), "source": e["class"]}
    fior = p.get("fresnelIor", 1.52) or 1.52
    metal = fior >= 4.0 and (p.get("levelDiffuse", 1.0) or 0) < 0.05
    gloss = p.get("reflectGlossiness", 1.0)
    gt = resolve(p.get("texmapReflectGlossiness")) if p.get("texmapOnReflectGlossiness", True) else None
    gamt = (p.get("mapamountReflectGlossiness", 100.0) or 0) / 100.0
    if metal:
        m["baseColor"] = [c * (p.get("levelReflect", 1.0) or 0) for c in col_lin(p.get("colorReflect"))]
        m["metallic"] = 1.0
    else:
        d = resolve(p.get("texmapDiffuse")) if p.get("texmapOnDiffuse", True) else None
        lvl = p.get("levelDiffuse", 1.0)
        m["baseColor"] = [c * lvl for c in col_lin(p.get("colorDiffuse"))]
        if d and "file" in d:
            m["baseColorTex"], m["uv"] = emit_color(d, stem + "_base", size)
            m["baseColor"] = [lvl] * 3
        elif d and "color" in d:
            m["baseColor"] = [c * lvl for c in d["color"]]
        m["metallic"] = 0.0
        m["ior"] = fior
        m["specular"] = p.get("levelReflect", 1.0)
    if gt and "file" in gt and not metal:
        def rough_fn(x, g=gloss, a=gamt):
            return 1 - ((1 - a) * g + a * x)
        m["roughnessTex"], _ = emit_scalar(gt, stem + "_rough", DEFAULT_SIZE, rough_fn)
        m["roughness"] = 1.0
    else:
        m["roughness"] = round(1 - gloss, 4)
    bt = resolve(p.get("texmapBump")) if p.get("texmapOnBump", True) else None
    bamt = (p.get("mapamountBump", 100.0) or 0) / 100.0 if "mapamountBump" in p else 1.0
    if bt and "normal" in bt:
        m["normalTex"], _ = emit_normal_map(bt, stem + "_nrm", DEFAULT_SIZE)
        m["normalScale"] = round(bamt * (bt.get("mult") or 1.0), 4)
    elif bt and "file" in bt and bamt:
        m["normalTex"], _ = emit_normal_from_height(bt, stem + "_nrm", size, bamt)
        m["normalScale"] = 1.0
    if (p.get("levelTranslucency", 0) or 0) > 0:
        m["translucency"] = {"fraction": p["levelTranslucency"], "color": col_lin(p.get("colorTranslucency"))}
    if (p.get("levelSelfIllum", 0) or 0) > 0:
        m["emissive"] = [c * p["levelSelfIllum"] for c in col_lin(p.get("colorSelfIllum"))]
    return m


def compile_mtl(k, out, size):
    e = R[k]
    name = e.get("name")
    if e["class"] == "Multimaterial":
        for sm in e["props"].get("materialList") or []:
            if sm and "$ref" in sm:
                compile_mtl(sm["$ref"], out, size)
        return
    if name in out:
        return
    if e["class"] == "_CoronaPhysicalMtl" or e["class"] == "CoronaPhysicalMtl":
        out[name] = compile_physical(e, size)
    elif e["class"] == "CoronaLegacyMtl":
        out[name] = compile_legacy(e, size)
    else:
        warn("unsupported material class %s (%s): grey fallback" % (e["class"], name))
        out[name] = {"name": name, "source": e["class"], "baseColor": [0.5, 0.5, 0.5], "roughness": 0.5,
                     "metallic": 0.0}


HERO = set(json.loads(os.environ.get("NIK_HERO_MTLS", "[]")))
mats = {}
for o in OBJS:
    m = o.get("mtl")
    if m and m.get("id"):
        top = R[m["id"]]
        size = HERO_SIZE if (top.get("name") in HERO) else DEFAULT_SIZE
        # hero applies to sub-materials as well
        if top["class"] == "Multimaterial":
            for sm in top["props"].get("materialList") or []:
                if sm and "$ref" in sm:
                    compile_mtl(sm["$ref"], mats, HERO_SIZE if R[sm["$ref"]].get("name") in HERO else DEFAULT_SIZE)
        else:
            compile_mtl(m["id"], mats, size)

json.dump({"materials": mats, "warnings": warnings}, open(os.path.join(OUT, "materials.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("materials:", len(mats), "textures:", len(os.listdir(TEXOUT)))
