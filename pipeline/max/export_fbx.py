# Cleans the loaded scene and exports FBX for Blender (runs inside 3ds Max via 3dsmaxbatch).
# Env: NIK_MAX (scene), NIK_EXPORT (output dir). Writes scene.fbx + export_manifest.json.
import json
import os
import traceback

from pymxs import runtime as rt

MAXF = os.environ["NIK_MAX"]
OUT = os.environ["NIK_EXPORT"]
os.makedirs(OUT, exist_ok=True)
LOG = open(os.path.join(OUT, "export.log"), "w", encoding="utf-8")


def log(*a):
    LOG.write(" ".join(str(x) for x in a) + "\n")
    LOG.flush()


def det(m):
    a, b, c = m.row1, m.row2, m.row3
    return (a.x * (b.y * c.z - b.z * c.y) - a.y * (b.x * c.z - b.z * c.x) + a.z * (b.x * c.y - b.y * c.x))


def p3m(v):
    return [float(v.x), float(v.y), float(v.z)]


def mtl_info(m):
    if m is None:
        return None
    d = {"name": str(m.name), "class": str(rt.classOf(m))}
    if str(rt.classOf(m)) == "Multimaterial":
        subs = []
        for i, sm in enumerate(m.materialList):
            subs.append({"id": int(m.materialIDList[i]),
                         "name": str(sm.name) if sm is not None else None,
                         "class": str(rt.classOf(sm)) if sm is not None else None})
        d["sub"] = subs
    return d


try:
    rt.resetMaxFile(rt.Name("noPrompt"))
    rt.loadMaxFile(MAXF, useFileUnits=True, quiet=True)
    log("loaded", rt.objects.count, "objects; units", rt.units.SystemType)
    # meters per system unit
    scale_to_m = {"inches": 0.0254, "feet": 0.3048, "miles": 1609.344, "millimeters": 0.001,
                  "centimeters": 0.01, "meters": 1.0, "kilometers": 1000.0}[str(rt.units.SystemType)] \
        * float(rt.units.SystemScale)

    heads = [o for o in rt.helpers if rt.isGroupHead(o)]
    for h in heads:
        if rt.isValidNode(h):
            rt.explodeGroup(h)
    log("exploded groups:", len(heads), "remaining helpers:", rt.helpers.count)

    manifest = []
    for o in list(rt.geometry):
        info = {"srcName": str(o.name), "mods": [str(rt.classOf(m)) for m in o.modifiers],
                "mirrored": det(o.transform) < 0, "material": mtl_info(o.material)}
        # Only collapse the modifier stack. ResetXForm is NOT used: on the mirrored island (det<0) it moved the
        # shell by 0.36 m and mirrored it in X. Node transforms (incl. negative scale) go to FBX as they are and
        # Blender bakes them on import (transform_apply handles negative determinants).
        rt.convertToPoly(o)
        info["faces"] = int(rt.polyop.getNumFaces(o))
        info["mapChannels"] = [i for i in range(0, int(rt.polyop.getNumMaps(o))) if rt.polyop.getMapSupport(o, i)]
        info["bboxMin_m"] = [round(x * scale_to_m, 5) for x in p3m(o.min)]
        info["bboxMax_m"] = [round(x * scale_to_m, 5) for x in p3m(o.max)]
        manifest.append(info)
    log("processed geometry:", len(manifest))

    rt.FBXExporterSetParam("ResetExport")
    for k, v in (("Animation", False), ("Cameras", False), ("Lights", False), ("EmbedTextures", False),
                 ("ASCII", False), ("FileVersion", "FBX202000"), ("ConvertUnit", "m"), ("UpAxis", "Y"),
                 ("SmoothingGroups", True), ("Preserveinstances", False), ("TangentSpaceExport", False),
                 ("Triangulate", False), ("GenerateLog", False), ("ShowWarnings", False), ("ScaleFactor", 1.0)):
        rt.FBXExporterSetParam(k, v)
    fbx = os.path.join(OUT, "scene.fbx")
    ok = rt.exportFile(fbx, rt.Name("noPrompt"), using=rt.FBXEXP)
    log("exportFile ok=", ok, "size=", os.path.getsize(fbx) if os.path.exists(fbx) else None)
    json.dump({"source": MAXF, "systemUnits": str(rt.units.SystemType), "metersPerUnit": scale_to_m,
               "objects": manifest}, open(os.path.join(OUT, "export_manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
except Exception:
    log("FAILED\n" + traceback.format_exc())
LOG.close()
