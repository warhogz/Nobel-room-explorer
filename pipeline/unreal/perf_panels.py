"""Flat perforated bronze panels + light chandelier glass in Unreal (in the open editor; run after export_ue.py).

The 49 wall panels used to be real geometry with 12.5 mm holes (2.84 M triangles): sub-pixel holes shimmer at any distance
and every Nanite cluster pays for them. Now each panel is a flat polygon (UV 1 = one hole tile) and M_Nik_Perf darkens the
holes with a mip-filtered mask: stable at every distance, with the bevel from a normal map.
Also re-imports the decimated glass of the chandelier (1.8 M -> 0.45 M non-Nanite triangles).
Re-runnable.
"""
import os
import sys

import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else
                os.environ.get("NIK_PIPELINE", ""))
import nik_ue  # noqa: E402
from nik_ue import GAME, SCENE, TWEAKS, UE_DIR, mi_name, tex_asset  # noqa: E402

AT = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
MP = unreal.MaterialProperty
VT = unreal.MaterialSamplerType
MAT = GAME + "/Materials"
perf_spec = SCENE["materials"]["Perforated_Bronze"]
PERF = perf_spec["perforated"]


def log(*a):
    unreal.log("NIK perf " + " ".join(str(x) for x in a))


# ------------------------------------------------------------------ textures: hole mask + bevel normal (small, regular)
def import_tex(path, name, srgb, normal=False):
    t = unreal.AssetImportTask()
    t.filename, t.destination_path, t.destination_name = path, GAME + "/Textures", name
    t.automated, t.replace_existing, t.save = True, True, True
    AT.import_asset_tasks([t])
    tex = unreal.load_asset(GAME + "/Textures/" + name)
    tex.set_editor_property("virtual_texture_streaming", False)
    tex.set_editor_property("srgb", srgb)
    if normal:
        tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
        tex.set_editor_property("flip_green_channel", True)  # Blender writes OpenGL (+Y) normals
    else:
        tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_MASKS)
    tex.set_editor_property("filter", unreal.TextureFilter.TF_TRILINEAR)
    EAL.save_loaded_asset(tex, False)
    return tex


MASK = import_tex(PERF["mask"], "T_Perf_Mask", False)
NRM = import_tex(PERF["normal"], "T_Perf_Normal", False, normal=True)


# ------------------------------------------------------------------ master material
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


def mul(m, a, aout, b, bout, x, y):
    e = node(m, unreal.MaterialExpressionMultiply, x, y)
    link(a, aout, e, "A")
    link(b, bout, e, "B")
    return e


path = MAT + "/M_Nik_Perf"
M = unreal.load_asset(path)  # (does_asset_exist is False for an asset created but not yet saved)
if M is None:
    M = AT.create_asset("M_Nik_Perf", MAT, unreal.Material, unreal.MaterialFactoryNew())
else:
    MEL.delete_all_material_expressions(M)
tc = node(M, unreal.MaterialExpressionTextureCoordinate, -1500, 0, coordinate_index=0)
ap = node(M, unreal.MaterialExpressionAppendVector, -1500, 200)
link(scalar(M, "TileU", 0.02, -1700, 150), "", ap, "A")
link(scalar(M, "TileV", 0.02, -1700, 250), "", ap, "B")
uvb = mul(M, tc, "", ap, "", -1300, 100)  # the bronze repeats every ~0.6 m, the holes every tile


def sampler(name, tex, stype, uv, x, y):
    s = node(M, unreal.MaterialExpressionTextureSampleParameter2D, x, y, parameter_name=name, texture=tex, sampler_type=stype)
    link(uv, "", s, "UVs")
    return s


WHITE = unreal.load_asset(GAME + "/Textures/" + tex_asset("nik_white.png"))
WHITE_LIN = unreal.load_asset(GAME + "/Textures/" + tex_asset("nik_white_linear.png"))
bt = sampler("BaseColorTex", WHITE, VT.SAMPLERTYPE_VIRTUAL_COLOR, uvb, -1000, -500)
rt = sampler("RoughnessTex", WHITE_LIN, VT.SAMPLERTYPE_VIRTUAL_LINEAR_COLOR, uvb, -1000, -100)
mk = sampler("MaskTex", MASK, VT.SAMPLERTYPE_MASKS, tc, -1000, 300)
nm = sampler("NormalTex", NRM, VT.SAMPLERTYPE_NORMAL, tc, -1000, 650)
tint = node(M, unreal.MaterialExpressionVectorParameter, -1000, -650, parameter_name="BaseTint",
            default_value=unreal.LinearColor(1, 1, 1, 1))
hole = node(M, unreal.MaterialExpressionLinearInterpolate, -700, 250, const_b=1.0)
link(scalar(M, "HoleDark", 0.06, -950, 450), "", hole, "A")
link(mk, "R", hole, "Alpha")
bc = mul(M, mul(M, bt, "RGB", tint, "", -750, -500), "", hole, "", -500, -300)
MEL.connect_material_property(bc, "", MP.MP_BASE_COLOR)
rr = mul(M, rt, "R", scalar(M, "RoughMul", 1.0, -750, 0), "", -500, -50)
rmix = node(M, unreal.MaterialExpressionLinearInterpolate, -300, -50)  # flat satin roughness <-> the map, by RoughContrast
link(scalar(M, "RoughMin", 0.42, -500, 120), "", rmix, "A")
link(rr, "", rmix, "B")
link(scalar(M, "RoughContrast", 0.0, -500, 200), "", rmix, "Alpha")
MEL.connect_material_property(rmix, "", MP.MP_ROUGHNESS)
MEL.connect_material_property(scalar(M, "Metallic", 1.0, -500, -150), "", MP.MP_METALLIC)
MEL.connect_material_property(scalar(M, "Specular", 0.5, -500, 220), "", MP.MP_SPECULAR)
flat = node(M, unreal.MaterialExpressionConstant3Vector, -700, 600, constant=unreal.LinearColor(0, 0, 1, 1))
nl = node(M, unreal.MaterialExpressionLinearInterpolate, -450, 650)
link(flat, "", nl, "A")
link(nm, "RGB", nl, "B")
link(scalar(M, "NormalStrength", 1.0, -700, 760), "", nl, "Alpha")
MEL.connect_material_property(nl, "", MP.MP_NORMAL)
M.set_editor_property("used_with_nanite", True)
log("master errors:", MEL.recompile_material(M))
EAL.save_loaded_asset(M, False)

# ------------------------------------------------------------------ instance
mi_path = MAT + "/Instances/MI_Perforated_Bronze"
mi = unreal.load_asset(mi_path) or AT.create_asset("MI_Perforated_Bronze", MAT + "/Instances", unreal.MaterialInstanceConstant,
                                                    unreal.MaterialInstanceConstantFactoryNew())
MEL.set_material_instance_parent(mi, M)
tw = TWEAKS.get(perf_spec.get("origName"), {})
S = lambda k, v: MEL.set_material_instance_scalar_parameter_value(mi, k, float(v))
tu, tv = PERF["tile_m"]
S("TileU", tu / 0.6)
S("TileV", tv / 0.6)
S("Metallic", tw.get("metallic", perf_spec.get("metallic", 1.0)))
S("RoughMul", tw.get("roughMul", 1.0))
S("RoughMin", tw.get("roughness", 0.22))  # RoughContrast 0 = the flat satin roughness (the map only added ribs)
S("RoughContrast", 0.0)
MEL.set_material_instance_vector_parameter_value(mi, "BaseTint", unreal.LinearColor(*tw.get("tint", (1, 1, 1)), 1.0))
MEL.set_material_instance_texture_parameter_value(mi, "BaseColorTex", unreal.load_asset(GAME + "/Textures/" + tex_asset(perf_spec["baseColorTex"])))
MEL.set_material_instance_texture_parameter_value(mi, "RoughnessTex", unreal.load_asset(GAME + "/Textures/" + tex_asset(perf_spec["roughnessTex"])))
MEL.update_material_instance(mi)
EAL.save_loaded_asset(mi, False)
log("instance instructions", MEL.get_statistics(mi).num_pixel_shader_instructions)


# ------------------------------------------------------------------ re-import the changed meshes
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
    sm.remove_degenerates = False
    return ui


glass_ids = {k for k, v in SCENE["materials"].items() if v.get("transmission") or (v.get("flags") or {}).get("glass")}
todo = [o for o in SCENE["objects"] if "Perforated_Bronze" in o["materials"] or o["name"] == "SM_Chandelier_Material_2147483535"]
tasks = []
for o in todo:
    t = unreal.AssetImportTask()
    t.filename = os.path.join(UE_DIR, o["fbx"])
    t.destination_path, t.destination_name = GAME + "/Meshes", o["name"]
    t.automated, t.replace_existing, t.save = True, True, False
    t.options = fbx_options(not all(m in glass_ids for m in o["materials"]))
    tasks.append(t)
for i in range(0, len(tasks), 10):
    AT.import_asset_tasks(tasks[i:i + 10])
for o in todo:
    sm = unreal.load_asset(GAME + "/Meshes/" + o["name"])
    slots = sm.get_editor_property("static_materials")
    for k, mid in enumerate(o["materials"]):
        inst = mi if mid == "Perforated_Bronze" else unreal.load_asset(
            MAT + "/Instances/" + mi_name(mid, SCENE["materials"][mid]))
        sm.set_material(k, inst)
    bs = sm.get_editor_property("body_setup")
    if bs is not None:
        bs.set_editor_property("collision_trace_flag", unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)
    EAL.save_loaded_asset(sm, False)
log("re-imported", len(todo), "meshes")

# ------------------------------------------------------------------ glass casts no shadow (VSM renders non-Nanite meshes slowly)
n = 0
for o in SCENE["objects"]:
    if o["materials"] and all(m in glass_ids for m in o["materials"]):
        for a in EAS.get_all_level_actors():
            if a.get_actor_label() == o["name"][3:]:
                a.get_component_by_class(unreal.StaticMeshComponent).set_editor_property("cast_shadow", False)
                n += 1
unreal.EditorLoadingAndSavingUtils.save_current_level()
log("glass actors without shadow:", n)
