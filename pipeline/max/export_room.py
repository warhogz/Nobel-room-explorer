# Crops the full villa to the kitchen + double-height hall and exports it for Blender (3dsmaxbatch / pymxs).
# Env: NIK_MAX (scene), NIK_EXPORT (output dir), NIK_ORIGIN_M ("x,y" metres, web origin = island centre),
#      NIK_BOX ("x0,x1,y0,y1" metres relative to the origin).
# Writes room.fbx, room_manifest.json, room_crop.max (fast reload for later iterations), export.log.
#
# - only visible, renderable geometry whose bbox touches the box (+ renderable splines, converted to mesh)
# - TurboSmooth / MeshSmooth limited to 1 iteration (purchased furniture is subdivided 2-3x for stills)
# - Hair and Fur removed (the rug becomes its base mesh)
# - every material (and sub-material) renamed "M<anim handle>", so names are unique and map 1:1 to refs.json
# - duplicate node names get "_<handle>" appended
# - material graphs dumped in the same session (anim handles are per session): room_refs.json
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
OX, OY = [float(v) for v in os.environ.get("NIK_ORIGIN_M", "-99.7140121459961,19.368379592895508").split(",")]
BOX = [float(v) for v in os.environ.get("NIK_BOX", "-3.5,18.5,-6.2,6.2").split(",")]
os.makedirs(OUT, exist_ok=True)
LOG = open(os.path.join(OUT, "export.log"), "w", encoding="utf-8")
T0 = time.time()


def log(*a):
    LOG.write("[%7.1fs] " % (time.time() - T0) + " ".join(str(x) for x in a) + "\n")
    LOG.flush()


def handle(v):
    try:
        return int(rt.getHandleByAnim(v))
    except Exception:
        return None


def cls(v):
    return str(rt.classOf(v))


def det(m):
    a, b, c = m.row1, m.row2, m.row3
    return a.x * (b.y * c.z - b.z * c.y) - a.y * (b.x * c.z - b.z * c.x) + a.z * (b.x * c.y - b.y * c.x)


try:
    rt.resetMaxFile(rt.Name("noPrompt"))
    rt.loadMaxFile(MAXF, useFileUnits=True, quiet=True)
    log("loaded", rt.objects.count, "objects; units", rt.units.SystemType)
    m_per_unit = {"inches": 0.0254, "feet": 0.3048, "millimeters": 0.001, "centimeters": 0.01, "meters": 1.0}[
        str(rt.units.SystemType)] * float(rt.units.SystemScale)

    def in_box(o):
        try:
            a, b = o.min, o.max
        except Exception:
            return False
        x0, x1 = a.x * m_per_unit - OX, b.x * m_per_unit - OX
        y0, y1 = a.y * m_per_unit - OY, b.y * m_per_unit - OY
        return not (x1 < BOX[0] or x0 > BOX[1] or y1 < BOX[2] or y0 > BOX[3])

    def visible(o):
        try:
            if o.isHidden or not o.renderable:
                return False
            L = o.layer
            return bool(L.on) and not bool(L.isHidden)
        except Exception:
            return False

    # open groups first: deleting a group head would take its members with it
    heads = [o for o in rt.helpers if rt.isGroupHead(o)]
    for h in heads:
        if rt.isValidNode(h):
            rt.explodeGroup(h)
    log("exploded groups:", len(heads))

    keep, splines = [], []
    for o in list(rt.objects):
        sc = str(rt.superClassOf(o))
        if sc == "GeometryClass" and cls(o) != "Targetobject" and visible(o) and in_box(o):
            keep.append(o)
        elif sc == "shape" and visible(o) and in_box(o):
            try:
                if o.render_renderable:
                    splines.append(o)
            except Exception:
                pass
    keep_set = set(handle(o) for o in keep + splines)
    drop = [o for o in rt.objects if handle(o) not in keep_set]
    log("keep geometry:", len(keep), "renderable splines:", len(splines), "delete:", len(drop))
    try:
        rt.delete(drop)
    except Exception:
        for o in drop:
            if rt.isValidNode(o):
                rt.delete(o)
    for s in splines:
        try:
            rt.convertToMesh(s)
            keep.append(s)
        except Exception as e:
            log("spline convert failed", s.name, e)

    # modifiers: cap subdivision, drop fur
    capped = removed = 0
    for o in keep:
        for i in range(o.modifiers.count, 0, -1):
            md = o.modifiers[i - 1]
            c = cls(md)
            if c in ("TurboSmooth", "meshsmooth", "OpenSubdiv", "TurboSmooth_Pro"):
                try:
                    if int(md.iterations) > 1:
                        md.iterations = 1
                        capped += 1
                    md.useRenderIterations = False
                except Exception as e:
                    log("cap failed", o.name, c, e)
            elif c in ("HairMod", "Hair_and_Fur", "HairAndFur"):
                rt.deleteModifier(o, md)
                removed += 1
    log("subdivision capped:", capped, "fur removed:", removed)

    # unique material names (sub-materials too) -> "M<handle>"
    mat_names = {}

    def rename_mtl(m, depth=0):
        if m is None or depth > 8:
            return
        h = handle(m)
        if h is None or h in mat_names:
            return
        mat_names[h] = {"name": str(m.name), "class": cls(m)}
        m.name = "M%d" % h
        for k in range(int(rt.getNumSubMtls(m))):
            rename_mtl(rt.getSubMtl(m, k + 1), depth + 1)

    for o in keep:
        rename_mtl(o.material)
    log("materials renamed:", len(mat_names))
    tops = {}
    for o in keep:
        if o.material is not None:
            tops["M%d" % handle(o.material)] = mxs_dump.conv(o.material)
    json.dump({"top": tops, "refs": mxs_dump.REFS}, open(os.path.join(OUT, "room_refs.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    log("material graphs dumped:", len(mxs_dump.REFS), "refs")

    # unique node names
    seen, renamed = set(), 0
    for o in keep:
        n = str(o.name)
        if n in seen:
            o.name = "%s_%d" % (n, int(o.inode.handle))
            renamed += 1
        seen.add(str(o.name))
    log("nodes renamed (duplicates):", renamed)

    crop = os.path.join(OUT, "room_crop.max")
    rt.saveMaxFile(crop, quiet=True)
    log("saved", crop, os.path.getsize(crop) // (1 << 20), "MB")

    manifest = []
    total = 0
    for o in keep:
        info = {"name": str(o.name), "class": cls(o), "mods": [cls(m) for m in o.modifiers],
                "mirrored": det(o.transform) < 0, "material": ("M%d" % handle(o.material)) if o.material else None}
        try:
            rt.convertToPoly(o)
            info["faces"] = int(rt.polyop.getNumFaces(o))
            info["mapChannels"] = [i for i in range(0, int(rt.polyop.getNumMaps(o))) if rt.polyop.getMapSupport(o, i)]
        except Exception as e:
            info["convertError"] = str(e)[:200]
        total += info.get("faces", 0)
        info["bboxMin_m"] = [round(float(v) * m_per_unit, 4) for v in (o.min.x, o.min.y, o.min.z)]
        info["bboxMax_m"] = [round(float(v) * m_per_unit, 4) for v in (o.max.x, o.max.y, o.max.z)]
        manifest.append(info)
    log("collapsed", len(manifest), "objects, faces", total)

    rt.FBXExporterSetParam("ResetExport")
    for k, v in (("Animation", False), ("Cameras", False), ("Lights", False), ("EmbedTextures", False),
                 ("ASCII", False), ("FileVersion", "FBX202000"), ("ConvertUnit", "m"), ("UpAxis", "Y"),
                 ("SmoothingGroups", True), ("Preserveinstances", False), ("TangentSpaceExport", False),
                 ("Triangulate", False), ("GenerateLog", False), ("ShowWarnings", False), ("ScaleFactor", 1.0)):
        rt.FBXExporterSetParam(k, v)
    fbx = os.path.join(OUT, "room.fbx")
    ok = rt.exportFile(fbx, rt.Name("noPrompt"), using=rt.FBXEXP)
    log("exportFile ok=", ok, "size MB=", os.path.getsize(fbx) // (1 << 20) if os.path.exists(fbx) else None)
    json.dump({"source": MAXF, "metersPerUnit": m_per_unit, "origin_m": [OX, OY], "box": BOX,
               "materials": {("M%d" % h): v for h, v in mat_names.items()}, "objects": manifest},
              open(os.path.join(OUT, "room_manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log("done")
except Exception:
    log("FAILED\n" + traceback.format_exc())
LOG.close()
