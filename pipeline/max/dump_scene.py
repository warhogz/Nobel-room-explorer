# Dump of the loaded 3ds Max scene to JSON (runs inside 3ds Max via 3dsmaxbatch / pymxs).
# Output dir: env NIK_OUT, else ../../build/dump relative to this file.
import json
import os
import time
import traceback

from pymxs import runtime as rt

OUT = os.environ.get("NIK_OUT") or os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "build", "dump"))
os.makedirs(OUT, exist_ok=True)
LOG = open(os.path.join(OUT, "progress.log"), "w", encoding="utf-8")
T0 = time.time()

MAX_DEPTH = 14
MAX_STR = 4000
SKIP_PROPS = {"bitmap"}  # BitmapTexture.bitmap loads the image file


def log(msg):
    LOG.write("[%7.1fs] %s\n" % (time.time() - T0, msg))
    LOG.flush()


def cls(v):
    try:
        return str(rt.classOf(v))
    except Exception:
        return type(v).__name__


def sup(v):
    try:
        return str(rt.superClassOf(v))
    except Exception:
        return None


def pname(n):
    s = str(n)
    return s[1:] if s.startswith("#") else s


def p3(v):
    return [round(float(v.x), 4), round(float(v.y), 4), round(float(v.z), 4)]


def m3(m):
    return [p3(m.row1), p3(m.row2), p3(m.row3), p3(m.row4)]


# ---- generic ReferenceTarget dump (materials, maps, renderer, operators, ...) ----
REFS = {}


def anim_handle(v):
    try:
        h = rt.getHandleByAnim(v)
        return int(h) if h is not None else None
    except Exception:
        return None


def dump_ref(v, depth):
    h = anim_handle(v)
    if h is None:
        return str(v)[:MAX_STR]
    key = str(h)
    if key in REFS:
        return {"$ref": key}
    entry = {"class": cls(v), "super": sup(v)}
    try:
        entry["name"] = str(v.name)
    except Exception:
        pass
    REFS[key] = entry
    props = {}
    try:
        names = list(rt.getPropNames(v))
    except Exception:
        names = []
    for n in names:
        k = pname(n)
        if k in SKIP_PROPS:
            continue
        try:
            val = rt.getProperty(v, n)
        except Exception as e:
            props[k] = "<err %s>" % str(e)[:80]
            continue
        props[k] = conv(val, depth + 1)
    entry["props"] = props
    return {"$ref": key}


def conv(v, depth=0):
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, str):
        return v[:MAX_STR]
    c = cls(v)
    try:
        if c == "Point3":
            return p3(v)
        if c == "Point2":
            return [float(v.x), float(v.y)]
        if c == "Point4":
            return [float(v.x), float(v.y), float(v.z), float(v.w)]
        if c == "Color":
            return {"rgb": [round(float(v.r), 3), round(float(v.g), 3), round(float(v.b), 3)], "a": float(v.a)}
        if c == "Quat":
            return [float(v.x), float(v.y), float(v.z), float(v.w)]
        if c == "Matrix3":
            return m3(v)
        if c == "Name":
            return pname(v)
        if c in ("Array", "ArrayParameter"):
            return [conv(x, depth + 1) for x in v]
        if c in ("BitArray", "Interval", "Time"):
            return str(v)[:MAX_STR]
    except Exception:
        pass
    try:
        if rt.isValidNode(v):
            return {"$node": str(v.name)}
    except Exception:
        pass
    if depth < MAX_DEPTH and anim_handle(v) is not None:
        return dump_ref(v, depth)
    return str(v)[:MAX_STR]


def node_props(o):
    props = {}
    for n in list(rt.getPropNames(o)):
        k = pname(n)
        try:
            props[k] = conv(rt.getProperty(o, n), 1)
        except Exception as e:
            props[k] = "<err %s>" % str(e)[:80]
    return props


def write(name, data):
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    log("wrote %s (%d KB)" % (name, os.path.getsize(path) // 1024))


def section(fn):
    try:
        fn()
    except Exception:
        log("SECTION %s FAILED:\n%s" % (fn.__name__, traceback.format_exc()))


# ---------------------------------------------------------------------------
def s_info():
    info = {
        "maxFile": os.path.join(str(rt.maxFilePath), str(rt.maxFileName)),
        "maxVersion": [conv(x) for x in rt.maxVersion()],
        "units": {"systemType": str(rt.units.SystemType), "systemScale": float(rt.units.SystemScale),
                  "displayType": str(rt.units.DisplayType)},
        "renderer": cls(rt.renderers.current),
        "renderSize": [int(rt.renderWidth), int(rt.renderHeight)],
        "rendOutputFilename": str(rt.rendOutputFilename),
        "counts": {"objects": int(rt.objects.count), "geometry": int(rt.geometry.count),
                   "shapes": int(rt.shapes.count), "lights": int(rt.lights.count),
                   "cameras": int(rt.cameras.count), "helpers": int(rt.helpers.count)},
        "animationRange": str(rt.animationRange),
        "sliderTime": str(rt.sliderTime),
    }
    try:
        info["xrefFiles"] = int(rt.xrefs.getXRefFileCount())
    except Exception:
        pass
    layers = []
    for i in range(int(rt.LayerManager.count)):
        L = rt.LayerManager.getLayer(i)
        layers.append({"name": str(L.name), "on": bool(L.on), "isHidden": bool(L.isHidden),
                       "isFrozen": bool(L.isFrozen), "renderable": bool(L.renderable)})
    info["layers"] = layers
    states = []
    try:
        for i in range(1, int(rt.sceneStateMgr.GetCount()) + 1):
            states.append(str(rt.sceneStateMgr.GetSceneState(i)))
    except Exception as e:
        states.append("<err %s>" % e)
    info["sceneStates"] = states
    views = []
    bm = rt.batchRenderMgr
    for i in range(1, int(bm.numViews) + 1):
        v = bm.GetView(i)
        d = {}
        for k in ("name", "enabled", "outputFilename", "width", "height", "pixelAspect", "overridePreset",
                  "presetFile", "sceneStateName", "startFrame", "endFrame"):
            try:
                d[k] = conv(rt.getProperty(v, k))
            except Exception:
                pass
        try:
            d["camera"] = str(v.camera.name) if v.camera else None
        except Exception:
            pass
        views.append(d)
    info["batchViews"] = views
    write("scene_info.json", info)


def s_objects():
    objs = []
    n = 0
    for o in rt.objects:
        n += 1
        if n % 500 == 0:
            log("objects %d" % n)
        d = {"name": str(o.name), "class": cls(o), "super": sup(o)}
        try:
            d["handle"] = int(o.inode.handle)
            d["layer"] = str(o.layer.name)
            d["parent"] = str(o.parent.name) if o.parent else None
            d["hidden"] = bool(o.isHidden)
            d["renderable"] = bool(o.renderable)
            d["groupHead"] = bool(rt.isGroupHead(o))
            d["groupMember"] = bool(rt.isGroupMember(o))
            d["base"] = anim_handle(o.baseObject)
            d["baseClass"] = cls(o.baseObject)
            d["mods"] = [cls(m) for m in o.modifiers]
            d["pos"] = p3(o.pos)
            d["min"] = p3(o.min)
            d["max"] = p3(o.max)
            d["scale"] = p3(o.scale)
        except Exception as e:
            d["err"] = str(e)[:200]
        if d["super"] == "GeometryClass":
            try:
                pc = rt.getPolygonCount(o)
                d["faces"], d["verts"] = int(pc[0]), int(pc[1])
            except Exception:
                pass
        try:
            m = o.material
            if m is not None:
                ref = conv(m)
                d["mtl"] = {"name": str(m.name), "class": cls(m),
                            "id": ref.get("$ref") if isinstance(ref, dict) else None}
        except Exception as e:
            d["mtlErr"] = str(e)[:200]
        objs.append(d)
    write("objects.json", objs)


def s_cameras():
    cams = []
    for o in rt.cameras:
        if sup(o) != "camera":
            continue
        d = {"name": str(o.name), "class": cls(o), "layer": str(o.layer.name), "hidden": bool(o.isHidden),
             "transform": m3(o.transform), "pos": p3(o.pos)}
        try:
            if o.target:
                d["target"] = {"name": str(o.target.name), "pos": p3(o.target.pos)}
        except Exception:
            pass
        d["props"] = node_props(o)
        cams.append(d)
    write("cameras.json", cams)


def s_lights():
    out = []
    for o in rt.lights:
        if sup(o) != "light":
            continue
        d = {"name": str(o.name), "class": cls(o), "layer": str(o.layer.name), "hidden": bool(o.isHidden),
             "parent": str(o.parent.name) if o.parent else None,
             "transform": m3(o.transform), "pos": p3(o.pos)}
        try:
            if o.target:
                d["target"] = {"name": str(o.target.name), "pos": p3(o.target.pos)}
        except Exception:
            pass
        d["props"] = node_props(o)
        out.append(d)
    write("lights.json", out)


def s_render():
    r = {"renderer": conv(rt.renderers.current)}
    r["useEnvironmentMap"] = bool(rt.useEnvironmentMap)
    r["environmentMap"] = conv(rt.environmentMap)
    r["backgroundColor"] = conv(rt.backgroundColor)
    els = []
    rem = rt.maxOps.GetCurRenderElementMgr()
    for i in range(int(rem.NumRenderElements())):
        els.append(conv(rem.GetRenderElement(i)))
    r["renderElements"] = els
    effects = []
    try:
        for i in range(1, int(rt.numAtmospherics) + 1):
            effects.append(conv(rt.getAtmospheric(i)))
    except Exception:
        pass
    r["atmospherics"] = effects
    write("render.json", r)


def s_materials():
    # all scene materials (incl. ones not assigned to objects, e.g. in sceneMaterials)
    top = []
    for m in rt.sceneMaterials:
        top.append(conv(m))
    write("materials_top.json", top)


log("start, file=%s%s" % (rt.maxFilePath, rt.maxFileName))
for fn in (s_info, s_cameras, s_lights, s_render, s_objects, s_materials):
    log("section %s" % fn.__name__)
    section(fn)
write("refs.json", REFS)
log("done, refs=%d" % len(REFS))
LOG.close()
