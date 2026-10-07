# Prints compact material trees (non-default-looking params + maps) for every object material in the dump.
import json
import os
import sys

D = sys.argv[1]
R = json.load(open(os.path.join(D, "refs.json"), encoding="utf-8"))
objs = json.load(open(os.path.join(D, "objects.json"), encoding="utf-8"))

# params worth showing for Corona materials (prefix match)
KEEP = ("color", "level", "rough", "gloss", "ior", "metal", "opacity", "translucency", "trans", "refract", "reflect",
        "base", "bump", "displace", "emission", "selfIllum", "fresnel", "aniso", "sss", "volume", "attenuation",
        "absorption", "scatter", "thin", "clearcoat", "sheen", "filename", "tiling", "offset", "angle", "u_", "v_",
        "map", "mono", "rgb", "output", "coords", "real", "brightness", "contrast", "saturation", "hue", "gamma",
        "mix", "amount", "strength", "multiplier", "intensity", "texmap", "mode", "use", "enable", "names",
        "materialIDList", "twoSided", "uvw", "channel", "blur", "wrap", "mapping", "W_", "U_", "V_")
SKIP_VAL = (None, [], "")
seen = set()


def short(v):
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) < 110 else s[:107] + "..."


def show(k, ind, label=""):
    e = R[k]
    head = "%s%s%s [%s] %s" % ("  " * ind, label, e["class"], k, e.get("name", ""))
    if k in seen:
        print(head + "  (see above)")
        return
    seen.add(k)
    print(head)
    for p, v in e["props"].items():
        refs = []
        vals = v if isinstance(v, list) else [v]
        for i, x in enumerate(vals):
            if isinstance(x, dict) and "$ref" in x:
                refs.append((i, x["$ref"]))
        if refs:
            for i, r in refs:
                cls = R[r]["class"]
                if cls in ("ParamBlock2", "CustAttribContainer", "Bezier Float", "Output", "Placement",
                           "Bezier Color", "Curve Control") or "mental ray" in cls:
                    continue
                show(r, ind + 2, ".%s%s = " % (p, "[%d]" % i if isinstance(v, list) else ""))
            continue
        if v in SKIP_VAL or isinstance(v, str) and v.startswith("<err"):
            continue
        if any(p.lower().startswith(x.lower()) or x.lower() in p.lower() for x in KEEP):
            print("%s  .%s = %s" % ("  " * ind, p, short(v)))


mats = {}
for o in objs:
    m = o.get("mtl")
    if m and m["id"]:
        mats.setdefault(m["id"], []).append(o["name"])
for k, users in mats.items():
    print("=" * 100)
    print("USED BY:", ", ".join(users))
    show(k, 0)
