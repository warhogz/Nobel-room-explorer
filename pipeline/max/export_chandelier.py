# Exports the glass/bronze chandelier sculpture (hidden in Option 9, but in every client render) on its own.
# Env: NIK_MAX, NIK_EXPORT, NIK_MTLS (JSON list of material names), NIK_ORIGIN_M, NIK_BOX.
# Writes chandelier.fbx, chandelier_manifest.json, chandelier_refs.json, export.log.
import json
import os
import sys
import time
import traceback

from pymxs import runtime as rt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mxs_dump  # noqa: E402

MAXF = os.environ["NIK_MAX"]
OUT = os.environ["NIK_EXPORT"]
MTLS = set(json.loads(os.environ["NIK_MTLS"]))
OX, OY = [float(v) for v in os.environ.get("NIK_ORIGIN_M", "-99.7140121459961,19.368379592895508").split(",")]
BOX = [float(v) for v in os.environ.get("NIK_BOX", "-3.5,18.5,-6.2,6.2").split(",")]
os.makedirs(OUT, exist_ok=True)
LOG = open(os.path.join(OUT, "export.log"), "w", encoding="utf-8")
T0 = time.time()


def log(*a):
    LOG.write("[%7.1fs] " % (time.time() - T0) + " ".join(str(x) for x in a) + "\n")
    LOG.flush()


def handle(v):
    return int(rt.getHandleByAnim(v))


try:
    rt.resetMaxFile(rt.Name("noPrompt"))
    rt.loadMaxFile(MAXF, useFileUnits=True, quiet=True)
    mpu = 0.3048 * float(rt.units.SystemScale) if str(rt.units.SystemType) == "feet" else 1.0
    log("loaded", rt.objects.count)
    for h in [o for o in rt.helpers if rt.isGroupHead(o)]:
        if rt.isValidNode(h):
            rt.explodeGroup(h)
    keep = []
    for o in list(rt.geometry):
        m = o.material
        if m is None or str(m.name) not in MTLS:
            continue
        a, b = o.min, o.max
        if b.x * mpu - OX < BOX[0] or a.x * mpu - OX > BOX[1] or b.y * mpu - OY < BOX[2] or a.y * mpu - OY > BOX[3]:
            continue
        keep.append(o)
    ks = set(handle(o) for o in keep)
    rt.delete([o for o in rt.objects if handle(o) not in ks])
    for o in keep:
        o.isHidden = False
        for i in range(o.modifiers.count, 0, -1):
            md = o.modifiers[i - 1]
            if str(rt.classOf(md)) in ("TurboSmooth", "meshsmooth", "OpenSubdiv"):
                try:
                    md.iterations = min(int(md.iterations), 1)
                    md.useRenderIterations = False
                except Exception:
                    pass
    log("kept", len(keep))
    names = {}
    tops = {}
    for o in keep:
        m = o.material
        h = handle(m)
        if h not in names:
            names[h] = {"name": str(m.name), "class": str(rt.classOf(m))}
            m.name = "M%d" % h
            tops["M%d" % h] = mxs_dump.conv(m)
    seen = set()
    manifest = []
    for o in keep:
        n = str(o.name)
        if n in seen:
            o.name = "%s_%d" % (n, int(o.inode.handle))
        seen.add(str(o.name))
        rt.convertToPoly(o)
        manifest.append({"name": str(o.name), "material": "M%d" % handle(o.material), "faces": int(rt.polyop.getNumFaces(o))})
    log("faces", sum(m["faces"] for m in manifest))
    json.dump({"top": tops, "refs": mxs_dump.REFS}, open(os.path.join(OUT, "room_refs.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    rt.FBXExporterSetParam("ResetExport")
    for k, v in (("Animation", False), ("Cameras", False), ("Lights", False), ("EmbedTextures", False),
                 ("ASCII", False), ("FileVersion", "FBX202000"), ("ConvertUnit", "m"), ("UpAxis", "Y"),
                 ("SmoothingGroups", True), ("Preserveinstances", False), ("Triangulate", False)):
        rt.FBXExporterSetParam(k, v)
    ok = rt.exportFile(os.path.join(OUT, "chandelier.fbx"), rt.Name("noPrompt"), using=rt.FBXEXP)
    json.dump({"origin_m": [OX, OY], "box": BOX, "materials": {("M%d" % h): v for h, v in names.items()},
               "objects": manifest}, open(os.path.join(OUT, "room_manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    log("exported", ok, "done")
except Exception:
    log("FAILED\n" + traceback.format_exc())
LOG.close()
