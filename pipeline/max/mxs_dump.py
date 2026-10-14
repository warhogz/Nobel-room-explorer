# Generic ReferenceTarget -> JSON dumper shared by the Max batch scripts (pymxs).
# REFS maps anim handle (as string) -> {"class","super","name","props"}; values reference each other with {"$ref": h}.
from pymxs import runtime as rt

MAX_DEPTH = 14
MAX_STR = 4000
SKIP_PROPS = {"bitmap"}  # BitmapTexture.bitmap loads the image file


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


