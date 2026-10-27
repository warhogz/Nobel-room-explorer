"""Unreal assets of the room: textures (virtual, source resolution), master materials, one material instance per Corona
material, Nanite static meshes, IES light profiles.

UnrealEditor-Cmd.exe NobelKitchen.uproject -run=pythonscript -script=<this file> -unattended
(or live in the editor: run_live.py imports this module and drives mesh_steps() one chunk per tick)
  in : build/ue/scene.json + meshes/*.fbx (export_ue.py), build/materials_ue/tex
  out: /Game/Nobel/{Textures, Materials, Meshes, IES}
Re-runs skip assets that exist (NIK_FORCE=1 rebuilds everything, NIK_FORCE_MATERIALS=1 only the materials).
"""
import os
import struct
import sys
import time
import zlib

import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nik_ue import (COATS, GAME, LAMP_GLOW_NITS, NICHE_GLOW_NITS, ONYX_GLOW_COLOR, ONYX_GLOW_NITS, KITCHEN_X, PHOT, RELIEF, SCENE,  # noqa: E402
                    TWEAKS, UE_DIR, f0_specular, mi_name, slug, tex_asset)

T0 = time.time()
FORCE = os.environ.get("NIK_FORCE") == "1"
FORCE_MATS = FORCE or os.environ.get("NIK_FORCE_MATERIALS") == "1"
AT = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
TEXDIR = SCENE["textures"]


def log(*a):
    unreal.log("NIK [%6.0fs] %s" % (time.time() - T0, " ".join(str(x) for x in a)))


def exists(path):
    return EAL.does_asset_exist(path)


def import_tasks(tasks, chunk=40):
    """generator: one chunk per step (the live editor run redraws in between)"""
    for i in range(0, len(tasks), chunk):
        AT.import_asset_tasks(tasks[i:i + chunk])
        log("imported %d/%d" % (min(len(tasks), i + chunk), len(tasks)))
        yield tasks[i:i + chunk]


def task(filename, dest, name, options=None):
    t = unreal.AssetImportTask()
    t.filename = filename
    t.destination_path = dest
    t.destination_name = name
    t.automated = True
    t.replace_existing = True
    t.save = False
    if options is not None:
        t.options = options
    return t


# ------------------------------------------------------------------ textures
def png(path, w, h, rgba):
    raw = b"".join(b"\x00" + bytes(rgba) * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


DEF = os.path.join(UE_DIR, "defaults")
os.makedirs(DEF, exist_ok=True)
png(os.path.join(DEF, "nik_white.png"), 256, 256, (255, 255, 255, 255))
png(os.path.join(DEF, "nik_white_linear.png"), 256, 256, (255, 255, 255, 255))
png(os.path.join(DEF, "nik_flat_normal.png"), 256, 256, (128, 128, 255, 255))

# role of every texture file: base colour / glow = sRGB, roughness = linear, normal = normal map
roles = {}
for mid, spec in SCENE["materials"].items():
    for key, role in (("baseColorTex", "color"), ("roughnessTex", "linear"), ("normalTex", "normal")):
        if spec.get(key):
            roles.setdefault(spec[key], set()).add(role)
    tr = spec.get("translucency") or {}
    if tr.get("colorTex"):
        roles.setdefault(tr["colorTex"], set()).add("color")
for f, r in roles.items():
    if len(r) > 1:
        log("WARN texture used as", r, f)
files = {f: (TEXDIR, next(iter(r))) for f, r in roles.items()}
files["nik_white.png"] = (DEF, "color")
# a linear sampler's default texture must be linear too, or every instance that switches the sampler on fails to compile
files["nik_white_linear.png"] = (DEF, "linear")
files["nik_flat_normal.png"] = (DEF, "normal")
TEX = GAME + "/Textures"
todo = [task(os.path.join(d, f), TEX, tex_asset(f)) for f, (d, _) in files.items()
        if FORCE or not exists(TEX + "/" + tex_asset(f))]
log("textures:", len(files), "to import:", len(todo))
for _ in import_tasks(todo, 20):
    pass
for f, (_, role) in files.items():
    t = unreal.load_asset(TEX + "/" + tex_asset(f))
    if t is None:
        log("WARN missing texture asset", f)
        continue
    # every map virtual: one sampler type per master parameter, 8K-16K maps stream by tiles
    want = {
        "virtual_texture_streaming": True,
        "srgb": role == "color",
        "compression_settings": unreal.TextureCompressionSettings.TC_NORMALMAP if role == "normal"
        else unreal.TextureCompressionSettings.TC_DEFAULT,
        # Blender / Corona maps are OpenGL (+Y), Unreal is DirectX
        "flip_green_channel": role == "normal",
        "lod_group": unreal.TextureGroup.TEXTUREGROUP_WORLD_NORMAL_MAP if role == "normal"
        else unreal.TextureGroup.TEXTUREGROUP_WORLD,
    }
    changed = False
    for k, v in want.items():
        if t.get_editor_property(k) != v:
            t.set_editor_property(k, v)
            changed = True
    if changed:  # a re-save rebuilds the (up to 16K) virtual texture
        EAL.save_loaded_asset(t, False)
log("textures ready")
WHITE = unreal.load_asset(TEX + "/" + tex_asset("nik_white.png"))
FLAT = unreal.load_asset(TEX + "/" + tex_asset("nik_flat_normal.png"))
WHITE_LIN = unreal.load_asset(TEX + "/" + tex_asset("nik_white_linear.png"))


def T(f):
    return unreal.load_asset(TEX + "/" + tex_asset(f)) if f else None


# ------------------------------------------------------------------ master materials
MAT = GAME + "/Materials"
MP = unreal.MaterialProperty
VT = unreal.MaterialSamplerType


def new_material(name):
    path = MAT + "/" + name
    if exists(path):
        m = unreal.load_asset(path)
        if not FORCE_MATS:
            return m, False
        # rebuilt in place: the instances and meshes keep pointing at the same asset
        MEL.delete_all_material_expressions(m)
        return m, True
    return AT.create_asset(name, MAT, unreal.Material, unreal.MaterialFactoryNew()), True


def node(m, cls, x, y, **props):
    e = MEL.create_material_expression(m, cls, x, y)
    for k, v in props.items():
        e.set_editor_property(k, v)
    return e


def link(a, aout, b, bin_):
    if not MEL.connect_material_expressions(a, aout, b, bin_):
        log("WARN link failed", a.get_name(), aout, "->", b.get_name(), bin_)


def scalar(m, name, v, x, y):
    return node(m, unreal.MaterialExpressionScalarParameter, x, y, parameter_name=name, default_value=v)


def vector(m, name, v, x, y):
    return node(m, unreal.MaterialExpressionVectorParameter, x, y, parameter_name=name,
                default_value=unreal.LinearColor(v[0], v[1], v[2], 1.0))


def switch(m, name, a, aout, b, bout, x, y):
    s = node(m, unreal.MaterialExpressionStaticSwitchParameter, x, y, parameter_name=name, default_value=False)
    link(a, aout, s, "True")
    link(b, bout, s, "False")
    return s


def mul(m, a, aout, b, bout, x, y):
    e = node(m, unreal.MaterialExpressionMultiply, x, y)
    link(a, aout, e, "A")
    link(b, bout, e, "B")
    return e


def build_master():
    """M_Nik: Corona standard / physical material. Shading model, blend mode and two-sidedness come from the instance
    (base property overrides): Default Lit, Clear Coat (onyx, walnut), Cloth (fabrics), Masked (cut-outs)."""
    m, new = new_material("M_Nik")
    if not new:
        return m
    # every output goes through one Make Material Attributes node (Python cannot reach the CustomData pins directly)
    attrs = node(m, unreal.MaterialExpressionMakeMaterialAttributes, -300, 300)
    # UV = TexCoord0 * (TileU, TileV)  (Max UVW tiling / real-world size; 90-degree rotations are baked in the maps)
    tc = node(m, unreal.MaterialExpressionTextureCoordinate, -2200, 0, coordinate_index=0)
    tu = scalar(m, "TileU", 1.0, -2400, 150)
    tv = scalar(m, "TileV", 1.0, -2400, 250)
    ap = node(m, unreal.MaterialExpressionAppendVector, -2200, 200)
    link(tu, "", ap, "A")
    link(tv, "", ap, "B")
    uv = mul(m, tc, "", ap, "", -2000, 100)

    def sampler(name, tex, stype, x, y):
        s = node(m, unreal.MaterialExpressionTextureSampleParameter2D, x, y, parameter_name=name, texture=tex,
                 sampler_type=stype)
        link(uv, "", s, "UVs")
        return s

    # base colour
    bt = sampler("BaseColorTex", WHITE, VT.SAMPLERTYPE_VIRTUAL_COLOR, -1700, -600)
    tint = vector(m, "BaseTint", (1, 1, 1), -1700, -400)
    bcol = vector(m, "BaseColor", (0.8, 0.8, 0.8), -1300, -300)
    btm = mul(m, bt, "RGB", tint, "", -1300, -500)
    base = switch(m, "UseBaseTex", btm, "", bcol, "", -1000, -450)
    link(base, "", attrs, "BaseColor")
    # cut-outs: base map alpha
    am = switch(m, "UseAlphaMask", bt, "A", node(m, unreal.MaterialExpressionConstant, -1300, -150, r=1.0), "",
                -1000, -200)
    link(am, "", attrs, "OpacityMask")
    # roughness = (map or value) * RoughMul, >= RoughMin
    rt = sampler("RoughnessTex", WHITE_LIN, VT.SAMPLERTYPE_VIRTUAL_LINEAR_COLOR, -1700, 0)
    rv = scalar(m, "Roughness", 0.5, -1300, 150)
    rs = switch(m, "UseRoughnessTex", rt, "R", rv, "", -1100, 50)
    rm = mul(m, rs, "", scalar(m, "RoughMul", 1.0, -1100, 200), "", -900, 80)
    rmax = node(m, unreal.MaterialExpressionMax, -700, 80)
    link(rm, "", rmax, "A")
    link(scalar(m, "RoughMin", 0.0, -900, 220), "", rmax, "B")
    link(rmax, "", attrs, "Roughness")
    link(scalar(m, "Metallic", 0.0, -900, -60), "", attrs, "Metallic")
    link(scalar(m, "Specular", 0.5, -900, 0), "", attrs, "Specular")
    # normal: lerp(flat, map, strength) (strength > 1 = stronger relief)
    nt = sampler("NormalTex", FLAT, VT.SAMPLERTYPE_VIRTUAL_NORMAL, -1700, 400)
    flat = node(m, unreal.MaterialExpressionConstant3Vector, -1500, 300, constant=unreal.LinearColor(0, 0, 1, 1))
    nl = node(m, unreal.MaterialExpressionLinearInterpolate, -1200, 380)
    link(flat, "", nl, "A")
    link(nt, "RGB", nl, "B")
    link(scalar(m, "NormalStrength", 1.0, -1500, 550), "", nl, "Alpha")
    ns = switch(m, "UseNormalTex", nl, "", flat, "", -900, 400)
    link(ns, "", attrs, "Normal")
    # emissive = EmissiveColor * EmissiveScale  +  GlowTex * GlowColor * GlowScale (backlit onyx, lamp shades)
    em = mul(m, vector(m, "EmissiveColor", (0, 0, 0), -1300, 700), "", scalar(m, "EmissiveScale", PHOT, -1300, 850), "",
             -1100, 750)
    gt = sampler("GlowTex", WHITE, VT.SAMPLERTYPE_VIRTUAL_COLOR, -1700, 950)
    gm = mul(m, gt, "RGB", vector(m, "GlowColor", (1, 1, 1), -1500, 1150), "", -1300, 1000)
    gs = mul(m, gm, "", scalar(m, "GlowScale", 0.0, -1300, 1150), "", -1100, 1000)
    gsw = switch(m, "UseGlow", gs, "", node(m, unreal.MaterialExpressionConstant, -1100, 1150, r=0.0), "", -900, 1000)
    add = node(m, unreal.MaterialExpressionAdd, -700, 800)
    link(em, "", add, "A")
    link(gsw, "", add, "B")
    link(add, "", attrs, "EmissiveColor")
    # clear coat / cloth (CustomData0 = cloth amount, SubsurfaceColor = fuzz colour)
    link(scalar(m, "ClearCoat", 0.0, -900, 1300), "", attrs, "ClearCoat")
    link(scalar(m, "ClearCoatRoughness", 0.1, -900, 1400), "", attrs, "ClearCoatRoughness")
    link(vector(m, "FuzzColor", (0.55, 0.5, 0.45), -900, 1500), "", attrs, "SubsurfaceColor")
    m.set_editor_property("use_material_attributes", True)
    MEL.connect_material_property(attrs, "", MP.MP_MATERIAL_ATTRIBUTES)
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_OPAQUE)
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_DEFAULT_LIT)
    m.set_editor_property("used_with_nanite", True)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m, False)
    log("master M_Nik built")
    return m


def build_glass():
    """M_Nik_Glass: thin translucent (window panes, glassware, the chandelier glass) - transmittance tint + Fresnel"""
    m, new = new_material("M_Nik_Glass")
    if not new:
        return m
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_THIN_TRANSLUCENT)
    m.set_editor_property("translucency_lighting_mode", unreal.TranslucencyLightingMode.TLM_SURFACE_PER_PIXEL_LIGHTING)
    m.set_editor_property("two_sided", True)
    MEL.connect_material_property(vector(m, "BaseColor", (0, 0, 0), -600, -200), "", MP.MP_BASE_COLOR)
    MEL.connect_material_property(scalar(m, "Roughness", 0.02, -600, 0), "", MP.MP_ROUGHNESS)
    MEL.connect_material_property(scalar(m, "Specular", 0.5, -600, 100), "", MP.MP_SPECULAR)
    MEL.connect_material_property(scalar(m, "Metallic", 0.0, -600, 200), "", MP.MP_METALLIC)
    MEL.connect_material_property(scalar(m, "Opacity", 0.1, -600, 300), "", MP.MP_OPACITY)
    # delete_all_material_expressions leaves this custom output behind, and a second one breaks the compile
    for e in [e for e in unreal.ObjectIterator(unreal.MaterialExpressionThinTranslucentMaterialOutput)
              if e.get_outer() == m]:
        MEL.delete_material_expression(m, e)
    out = node(m, unreal.MaterialExpressionThinTranslucentMaterialOutput, -200, 500)
    tr = vector(m, "Transmittance", (0.95, 0.95, 0.95), -600, 500)
    if not MEL.connect_material_expressions(tr, "", out, "Transmittance Color"):
        link(tr, "", out, "TransmittanceColor")
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m, False)
    log("master M_Nik_Glass built")
    return m


M_NIK = build_master()
M_GLASS = build_glass()


# ------------------------------------------------------------------ material instances
def make_mi(name, parent):
    path = MAT + "/Instances/" + name
    if exists(path):
        mi = unreal.load_asset(path)
        if not FORCE_MATS:
            return mi, False
        # reset in place (the meshes reference it)
        MEL.clear_all_material_instance_parameters(mi)
        mi.set_editor_property("base_property_overrides", unreal.MaterialInstanceBasePropertyOverrides())
    else:
        mi = AT.create_asset(name, MAT + "/Instances", unreal.MaterialInstanceConstant,
                             unreal.MaterialInstanceConstantFactoryNew())
    MEL.set_material_instance_parent(mi, parent)
    return mi, True


def lc(c):
    return unreal.LinearColor(float(c[0]), float(c[1]), float(c[2]), 1.0)


def overrides(mi, blend=None, two_sided=None, shading=None, clip=None):
    o = mi.get_editor_property("base_property_overrides")
    if blend is not None:
        o.set_editor_property("override_blend_mode", True)
        o.set_editor_property("blend_mode", blend)
    if two_sided is not None:
        o.set_editor_property("override_two_sided", True)
        o.set_editor_property("two_sided", two_sided)
    if shading is not None:
        o.set_editor_property("override_shading_model", True)
        o.set_editor_property("shading_model", shading)
    if clip is not None:
        o.set_editor_property("override_opacity_mask_clip_value", True)
        o.set_editor_property("opacity_mask_clip_value", clip)
    mi.set_editor_property("base_property_overrides", o)


def glass_mi(mid, spec):
    mi, new = make_mi(mi_name(mid, spec), M_GLASS)
    if not new:
        return mi
    tr = min(1.0, spec.get("transmission") or 1.0)
    bc = spec.get("baseColor", [1, 1, 1])
    # Corona refraction colour -> transmittance; partly refractive glass is partly opaque tinted glass
    tint = [0.92 + 0.08 * c for c in bc] if max(bc) > 0.05 else [0.95, 0.95, 0.95]
    MEL.set_material_instance_vector_parameter_value(mi, "Transmittance", lc(tint))
    MEL.set_material_instance_scalar_parameter_value(mi, "Opacity", 0.05 + 0.6 * (1.0 - tr))
    MEL.set_material_instance_vector_parameter_value(mi, "BaseColor", lc([c * (1.0 - tr) for c in bc]))
    MEL.set_material_instance_scalar_parameter_value(mi, "Roughness", min(0.1, spec.get("roughness", 0.0)))
    MEL.set_material_instance_scalar_parameter_value(mi, "Specular", f0_specular(spec, {}))
    MEL.update_material_instance(mi)
    return mi


def standard_mi(mid, spec, variant=None):
    """variant: None | 'backlit' (the island onyx) | 'niche' (the kitchen shelf niche)"""
    orig = spec.get("origName") or ""
    tw = TWEAKS.get(orig, {})
    spec = dict(spec, **tw.get("maps", {}))  # maps borrowed from another material
    coat = COATS.get(orig)
    fl = spec.get("flags") or {}
    surface = spec.get("surface") or fl.get("surface")
    name = mi_name(mid, spec) + ("_" + variant.capitalize() if variant else "")
    mi, new = make_mi(name, M_NIK)
    if not new:
        return mi
    S = lambda k, v: MEL.set_material_instance_scalar_parameter_value(mi, k, float(v))
    V = lambda k, v: MEL.set_material_instance_vector_parameter_value(mi, k, lc(v))
    X = lambda k, v: MEL.set_material_instance_texture_parameter_value(mi, k, v)
    W = lambda k, v: MEL.set_material_instance_static_switch_parameter_value(mi, k, bool(v))
    uv = spec.get("uv") or {}
    sx, sy = uv.get("scale") or [1, 1]
    if uv.get("realWorld"):
        sx, sy = (1.0 / sx if sx else 1.0), (1.0 / sy if sy else 1.0)
    d = tw.get("detail", 1)
    S("TileU", sx * d)
    S("TileV", sy * d)
    color = tw.get("color") or spec.get("baseColor", [0.8, 0.8, 0.8])
    base_tex = T(spec.get("baseColorTex")) if not tw.get("dropMap") and not tw.get("color") else None
    tint = list(tw.get("tint", [1, 1, 1]))
    if variant == "niche":
        tint = [t * 0.5 for t in tint]
    if base_tex:
        W("UseBaseTex", True)
        X("BaseColorTex", base_tex)
        V("BaseTint", tint)
    else:
        V("BaseColor", [c * t for c, t in zip(color, tint)])
    if spec.get("alphaMode") == "MASK" and base_tex:
        W("UseAlphaMask", True)
        overrides(mi, blend=unreal.BlendMode.BLEND_MASKED, clip=spec.get("alphaCutoff", 0.5))
    metal = tw.get("metallic", spec.get("metallic", 0.0))
    S("Metallic", metal)
    S("Specular", f0_specular(spec, tw))
    rough = spec.get("roughness", 0.5)
    rtex = T(spec.get("roughnessTex")) if not tw.get("dropRoughnessMap") and surface != "leather" else None
    if rtex:
        W("UseRoughnessTex", True)
        X("RoughnessTex", rtex)
    if surface == "leather":
        rough = 0.55
    if surface == "fabric":
        rough = max(rough, 0.88)
    # roughness 0 on a dielectric without a map = a Corona gloss map that did not survive the export
    if metal < 0.5 and not rtex and rough < 0.02 and not coat and not fl.get("emissive"):
        rough = 0.3
    if tw.get("roughness") is not None:
        rough = tw["roughness"]
    S("Roughness", rough)
    S("RoughMul", tw.get("roughMul", 1.0))
    if coat and coat.get("minRoughness"):
        S("RoughMin", coat["minRoughness"])
    if spec.get("normalTex"):
        W("UseNormalTex", True)
        X("NormalTex", T(spec["normalTex"]))
        S("NormalStrength", spec.get("normalScale", 1.0) * RELIEF.get(orig, 0.7 if surface == "fabric" else 1.0))
    em = spec.get("emissive")
    if em and max(em) > 0:
        V("EmissiveColor", em)
    glow_tex = None
    if variant in ("backlit", "niche"):
        glow_tex = T((spec.get("translucency") or {}).get("colorTex"))
        S("GlowScale", ONYX_GLOW_NITS if variant == "backlit" else NICHE_GLOW_NITS)
        V("GlowColor", ONYX_GLOW_COLOR)  # warm LED behind the stone: amber in the renders, not white
    elif tw.get("glow"):
        glow_tex = base_tex or WHITE
        V("GlowColor", tw["glow"])
        S("GlowScale", LAMP_GLOW_NITS)
    if glow_tex:
        W("UseGlow", True)
        X("GlowTex", glow_tex)
    shading = None
    if coat:
        shading = unreal.MaterialShadingModel.MSM_CLEAR_COAT
        S("ClearCoat", coat["clearcoat"])
        S("ClearCoatRoughness", coat["clearcoatRoughness"])
    elif surface == "fabric" or spec.get("sheen"):
        shading = unreal.MaterialShadingModel.MSM_CLOTH
        S("ClearCoat", spec.get("sheen", 0.6))  # CustomData0 = cloth amount
    overrides(mi, two_sided=True if spec.get("doubleSided") else None, shading=shading)
    MEL.update_material_instance(mi)
    return mi


MIS = {}
glass_ids = set()
for mid, spec in SCENE["materials"].items():
    fl = spec.get("flags") or {}
    if spec.get("transmission") or fl.get("glass"):
        MIS[mid] = glass_mi(mid, spec)
        glass_ids.add(mid)
    else:
        MIS[mid] = standard_mi(mid, spec)
ONYX_IDS = {mid for mid, s in SCENE["materials"].items() if s.get("translucency")}
VARIANTS = {}
for mid in ONYX_IDS:
    VARIANTS[(mid, "backlit")] = standard_mi(mid, SCENE["materials"][mid], "backlit")
    VARIANTS[(mid, "niche")] = standard_mi(mid, SCENE["materials"][mid], "niche")
EAL.save_directory(MAT, only_if_is_dirty=True, recursive=True)
log("material instances:", len(MIS), "glass", len(glass_ids), "onyx variants", len(VARIANTS))

# ------------------------------------------------------------------ meshes
MESH = GAME + "/Meshes"
unreal.SystemLibrary.execute_console_command(None, "Interchange.FeatureFlags.Import.FBX False")


def fbx_options(nanite):
    ui = unreal.FbxImportUI()
    ui.import_materials = False
    ui.import_textures = False
    ui.import_animations = False
    ui.import_as_skeletal = False
    ui.mesh_type_to_import = unreal.FBXImportType.FBXIT_STATIC_MESH
    sm = ui.static_mesh_import_data
    sm.combine_meshes = True
    sm.generate_lightmap_u_vs = False
    sm.auto_generate_collision = False
    sm.build_nanite = nanite
    sm.normal_import_method = unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS
    sm.remove_degenerates = False  # keep thin slivers of the Max geometry
    return ui


def is_glass(o):
    return all(m in glass_ids for m in o["materials"]) and o["materials"]


def assign(o):
    """material instances on the mesh asset (actors inherit them) + complex collision for walking"""
    sm = unreal.load_asset(MESH + "/" + o["name"])
    if sm is None:
        log("WARN mesh missing", o["name"])
        return None
    cx = (o["boundsMin"][0] + o["boundsMax"][0]) / 2 + o["location"][0]
    slots = sm.get_editor_property("static_materials")
    by_slot = {str(s.material_slot_name): k for k, s in enumerate(slots)}
    for k, mid in enumerate(o["materials"]):
        idx = by_slot.get(mid, k)
        mi = MIS.get(mid)
        if mid in ONYX_IDS:
            if o["name"] == "SM_Island":
                mi = VARIANTS[(mid, "backlit")]
            elif cx < KITCHEN_X:
                mi = VARIANTS[(mid, "niche")]
        if mi is not None and idx < len(slots):
            sm.set_material(idx, mi)
    bs = sm.get_editor_property("body_setup")
    if bs is not None:
        bs.set_editor_property("collision_trace_flag", unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)
    EAL.save_loaded_asset(sm, False)
    return sm


# IES profiles (the level needs them before the meshes)
IES = GAME + "/IES"
ies_files = sorted({l["ies"] for l in SCENE["lights"] if l.get("ies")})
for _ in import_tasks([task(f, IES, "IES_" + slug(os.path.splitext(os.path.basename(f))[0])) for f in ies_files
                       if FORCE or not exists(IES + "/IES_" + slug(os.path.splitext(os.path.basename(f))[0]))]):
    pass


def mesh_steps(on_chunk=None):
    """generator: imports the meshes chunk by chunk; on_chunk(objects) gets every chunk once its meshes are ready"""
    by_name = {o["name"]: o for o in SCENE["objects"]}
    todo, ready = [], []
    for o in SCENE["objects"]:
        if FORCE or not exists(MESH + "/" + o["name"]):
            todo.append(task(os.path.join(UE_DIR, o["fbx"]), MESH, o["name"], fbx_options(not is_glass(o))))
        else:
            ready.append(o)
    log("meshes:", len(SCENE["objects"]), "to import:", len(todo))
    # architecture and the hero set first, then furniture, glass last: the room takes shape early in the live run
    rank = {None: 0, "lightmap": 0, "vertex": 1, "none": 2}
    todo.sort(key=lambda t: (rank.get(by_name[t.destination_name]["bake"], 1),
                             -by_name[t.destination_name]["faces"]))
    for i in range(0, len(ready), 50):
        chunk = [o for o in ready[i:i + 50] if assign(o)]
        if on_chunk:
            on_chunk(chunk)
        yield
    for done in import_tasks(todo, 10):
        chunk = [by_name[t.destination_name] for t in done]
        chunk = [o for o in chunk if assign(o)]
        if on_chunk:
            on_chunk(chunk)
        yield
    EAL.save_directory(GAME, only_if_is_dirty=True, recursive=True)
    log("done: textures", len(files), "materials", len(MIS), "meshes", len(SCENE["objects"]), "ies", len(ies_files))


if __name__ == "__main__":
    for _ in mesh_steps():
        pass
