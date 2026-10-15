# Re-exports the objects whose node transform FBX cannot carry (non-uniform scale under rotation = shear: the
# Marvelous Designer pillows, a few scaled props) with their transform baked into the mesh (Reset XForm).
# 3dsmaxbatch on build/export_room/room_crop.max (materials there already carry the M<handle> names of room.fbx).
# Env: NIK_MAX (room_crop.max), NIK_EXPORT (output dir). Writes xform_fix.fbx + xform_fix.json (object names).
import json
import os
import time
import traceback

from pymxs import runtime as rt

OUT = os.environ["NIK_EXPORT"]
LOG = open(os.path.join(OUT, "xform_fix.log"), "w", encoding="utf-8")
T0 = time.time()


def log(*a):
    LOG.write("[%6.1fs] " % (time.time() - T0) + " ".join(str(x) for x in a) + "\n")
    LOG.flush()


def det(m):
    a, b, c = m.row1, m.row2, m.row3
    return a.x * (b.y * c.z - b.z * c.y) - a.y * (b.x * c.z - b.z * c.x) + a.z * (b.x * c.y - b.y * c.x)


def sheared(o):
    """non-uniform scale anywhere in the world transform or the object offset, combined with a rotation"""
    for m in (o.transform, o.objectTransform):
        r = [m.row1, m.row2, m.row3]
        s = [(v.x * v.x + v.y * v.y + v.z * v.z) ** 0.5 for v in r]
        if max(s) / max(min(s), 1e-9) > 1.01:
            # axis-aligned scale is fine; scale + rotation is where FBX loses the shape
            off = sum(abs(r[i].x * (i != 0) + r[i].y * (i != 1) + r[i].z * (i != 2)) for i in range(3))
            if off > 1e-3 * max(s):
                return True
        # skew: rows not orthogonal
        for i in range(3):
            for j in range(i + 1, 3):
                d = r[i].x * r[j].x + r[i].y * r[j].y + r[i].z * r[j].z
                if abs(d) > 1e-3 * s[i] * s[j]:
                    return True
    return False


try:
    rt.resetMaxFile(rt.Name("noPrompt"))
    rt.loadMaxFile(os.environ["NIK_MAX"], useFileUnits=True, quiet=True)
    log("loaded", rt.objects.count)
    fix = []
    for o in list(rt.geometry):
        try:
            if sheared(o):
                fix.append(o)
        except Exception as e:
            log("check failed", o.name, e)
    log("sheared:", len(fix), [str(o.name) for o in fix][:60])
    names = []
    for o in fix:
        try:
            mirrored = det(o.transform) < 0
            rt.resetXForm(o)
            if mirrored:
                # Reset XForm keeps the negative scale in the mesh: the faces come out inside-out
                md = rt.Normalmodifier()
                md.flip = True
                rt.addModifier(o, md)
            rt.convertToPoly(o)
            names.append(str(o.name))
        except Exception as e:
            log("reset failed", o.name, e)
    rt.select([o for o in fix if str(o.name) in names])
    rt.FBXExporterSetParam("ResetExport")
    for k, v in (("Animation", False), ("Cameras", False), ("Lights", False), ("EmbedTextures", False),
                 ("ASCII", False), ("FileVersion", "FBX202000"), ("ConvertUnit", "m"), ("UpAxis", "Y"),
                 ("SmoothingGroups", True), ("Preserveinstances", False), ("TangentSpaceExport", False),
                 ("Triangulate", False), ("GenerateLog", False), ("ShowWarnings", False), ("ScaleFactor", 1.0)):
        rt.FBXExporterSetParam(k, v)
    fbx = os.path.join(OUT, "xform_fix.fbx")
    ok = rt.exportFile(fbx, rt.Name("noPrompt"), selectedOnly=True, using=rt.FBXEXP)
    json.dump(names, open(os.path.join(OUT, "xform_fix.json"), "w", encoding="utf-8"), ensure_ascii=False)
    log("exported", ok, len(names))
except Exception:
    log("FAILED\n" + traceback.format_exc())
LOG.close()
