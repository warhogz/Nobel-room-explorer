"""Garden v4 on top of garden3.py (in the open editor): a living forest floor and air.
  - M_Ground on the hills: meadow grass, moss, leaf litter and dirt (Environment_Set ground scans), height-blended in
    world space with patch masks; the meadow turns into forest floor under the trees
  - Nanite boulders with scree, loose stones, ferns / forest plants / grasses in patches, roots, fallen logs
    (placements from blender/garden3_mesh.py, garden3.json "ground")
  - air: volumetric fog close by (sun shafts through the windows and the trees), and height fog that thickens with
    distance and glows towards the sun, so the forest fades layer by layer
Re-runnable (tag garden4).
"""
import json

import unreal

SRC = "C:/Users/hdog/Downloads/Telegram Desktop/NOBEL ISLAND KITCHEN (2)/NOBEL ISLAND KITCHEN/build/ue/garden3"
G = "/Game/Nobel/Garden3"
ENV = "/Game/Environment_Set/Environment/"
AT = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
MP = unreal.MaterialProperty
ST = unreal.MaterialSamplerType
V = unreal.Vector
data = json.load(open(SRC + "/garden3.json"))


def log(*a):
    unreal.log("NIK garden4 " + " ".join(str(x) for x in a))


for a in list(EAS.get_all_level_actors()):
    if "garden4" in [str(t) for t in a.tags]:
        EAS.destroy_actor(a)


def node(m, cls, x, y, **props):
    e = MEL.create_material_expression(m, cls, x, y)
    for k, v in props.items():
        e.set_editor_property(k, v)
    return e


def link(a, aout, b, bin_):
    if not MEL.connect_material_expressions(a, aout, b, bin_):
        log("WARN link failed", a.get_name(), aout, "->", b.get_name(), bin_)


# ------------------------------------------------------------------ ground material
M = unreal.load_asset(G + "/M_Ground")
if M is None:
    M = AT.create_asset("M_Ground", G, unreal.Material, unreal.MaterialFactoryNew())
else:
    MEL.delete_all_material_expressions(M)
M.set_editor_property("used_with_nanite", True)
wp = node(M, unreal.MaterialExpressionWorldPosition, -2400, 0)
xy = node(M, unreal.MaterialExpressionComponentMask, -2200, 0, r=True, g=True, b=False, a=False)
link(wp, "", xy, "")
LT = ENV + "Landscape/Textures/T_ground_"
LAYERS = [("forest_grass_02", 300.0), ("moss_01", 230.0), ("forest_leaves_01_0", 260.0), ("dirt_02", 250.0)]
y0 = -900
cols, nrms = [], []
for i, (tex, tile) in enumerate(LAYERS):
    uv = node(M, unreal.MaterialExpressionDivide, -1900, y0 + i * 320, const_b=tile)
    link(xy, "", uv, "A")
    bc = node(M, unreal.MaterialExpressionTextureSample, -1650, y0 + i * 320,
              texture=unreal.load_asset(LT + tex + "_BC_H"), sampler_type=ST.SAMPLERTYPE_COLOR)
    link(uv, "", bc, "UVs")
    nt = unreal.load_asset(LT + tex.replace("_01_0", "_01") + "_N")
    nm = node(M, unreal.MaterialExpressionTextureSample, -1650, y0 + i * 320 + 160, texture=nt, sampler_type=ST.SAMPLERTYPE_NORMAL)
    link(uv, "", nm, "UVs")
    cols.append(bc)
    nrms.append(nm)
MAC = unreal.load_asset("/Game/Nobel/Garden/T_Lawn_Macro")
masks = []
for i, (scale, off) in enumerate(((2600.0, 0.0), (1100.0, 0.37), (5200.0, 0.71))):
    uv = node(M, unreal.MaterialExpressionDivide, -1900, 500 + i * 200, const_b=scale)
    link(xy, "", uv, "A")
    ad = node(M, unreal.MaterialExpressionAdd, -1750, 500 + i * 200, const_b=off)
    link(uv, "", ad, "A")
    s = node(M, unreal.MaterialExpressionTextureSample, -1600, 500 + i * 200, texture=MAC, sampler_type=ST.SAMPLERTYPE_MASKS)
    link(ad, "", s, "UVs")
    masks.append(s)
dist = node(M, unreal.MaterialExpressionDistance, -1600, 1150)
link(xy, "", dist, "A")
link(node(M, unreal.MaterialExpressionConstant2Vector, -1800, 1200, r=750.0, g=0.0), "", dist, "B")

WEIGHTS = """
float hG = cG.a, hM = cM.a, hL = cL.a, hD = cD.a;
// forest floor beyond ~28 m (the boundary wanders with the big mask), moss and dirt in patches
float forest = saturate((Dist + (m0 - 0.5) * 1800.0 - 2600.0) / 1500.0);
float moss = saturate((m1 - 0.52) * 5.0);
float dirt = saturate((m2 - 0.62) * 6.0) * (0.35 + 0.65 * forest);
// height blend: the higher texel of two layers wins near the transition
float3 w = float3(moss, forest, dirt);
float a1 = saturate((w.x - 0.5) * 4.0 + (hM - hG) * 3.0 + 0.5);
float a2 = saturate((w.y - 0.5) * 4.0 + (hL - lerp(hG, hM, a1)) * 3.0 + 0.5);
float a3 = saturate((w.z - 0.5) * 4.0 + (hD - 0.5) * 3.0 + 0.5);
float4 W;
W.x = (1 - a1) * (1 - a2) * (1 - a3);
W.y = a1 * (1 - a2) * (1 - a3);
W.z = a2 * (1 - a3);
W.w = a3;
"""


def mixer(name, inputs, body, x, y, out=unreal.CustomMaterialOutputType.CMOT_FLOAT3):
    c = node(M, unreal.MaterialExpressionCustom, x, y)
    c.set_editor_property("output_type", out)
    c.set_editor_property("description", name)
    c.set_editor_property("code", body)
    ins = []
    for n in inputs:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", n)
        ins.append(ci)
    c.set_editor_property("inputs", ins)
    return c


common = ["cG", "cM", "cL", "cD", "m0", "m1", "m2", "Dist"]
col = mixer("GroundColor", common, WEIGHTS + """
float3 c = cG.rgb * float3(0.86, 0.9, 0.7) * W.x + cM.rgb * W.y + cL.rgb * W.z + cD.rgb * W.w;
// large-scale tone drift: no two metres of field are the same colour
return c * lerp(0.82, 1.1, m0);
""", -900, -200)
nrm = mixer("GroundNormal", common + ["nG", "nM", "nL", "nD"], WEIGHTS + """
return normalize(nG * W.x + nM * W.y + nL * W.z + nD * W.w + float3(0, 0, 0.001));
""", -900, 300)
rough = mixer("GroundRough", common, WEIGHTS + """
return 0.92 * W.x + 0.8 * W.y + 0.85 * W.z + 0.95 * W.w;
""", -900, 700, unreal.CustomMaterialOutputType.CMOT_FLOAT1)
for c in (col, nrm, rough):
    for src, n in zip(cols, ("cG", "cM", "cL", "cD")):
        link(src, "RGBA", c, n)
    for src, n in zip(masks, ("m0", "m1", "m2")):
        link(src, "R", c, n)
    link(dist, "", c, "Dist")
for src, n in zip(nrms, ("nG", "nM", "nL", "nD")):
    link(src, "RGB", nrm, n)
MEL.connect_material_property(col, "", MP.MP_BASE_COLOR)
MEL.connect_material_property(nrm, "", MP.MP_NORMAL)
MEL.connect_material_property(rough, "", MP.MP_ROUGHNESS)
MEL.connect_material_property(node(M, unreal.MaterialExpressionConstant, -600, 900, r=0.3), "", MP.MP_SPECULAR)
log("ground", MEL.recompile_material(M))
EAL.save_loaded_asset(M, False)
for a in EAS.get_all_level_actors():
    if a.get_actor_label() == "Hills":
        a.get_component_by_class(unreal.StaticMeshComponent).set_material(0, M)

# ------------------------------------------------------------------ rocks become Nanite (opaque, ideal for it)
for k in list(data["ground"]):
    if "Rock" in k:
        m = unreal.load_asset(ENV + "Rocks/Models/" + k)
        ns = m.get_editor_property("nanite_settings")
        if not ns.enabled:
            ns.enabled = True
            m.set_editor_property("nanite_settings", ns)
            EAL.save_loaded_asset(m, False)

# ------------------------------------------------------------------ scatter
NikScatter = unreal.load_class(None, "/Script/NobelKitchen.NikScatter")
n = 0
for kind, pts in data["ground"].items():
    if not pts:
        continue
    folder = "Rocks/Models/" if "Rock" in kind else "Foliage/Models/"
    m = unreal.load_asset(ENV + folder + kind)
    if m is None:
        log("WARN missing", kind)
        continue
    rock = "Rock" in kind or "trunk" in kind
    small = "Small_Rock" in kind
    a = EAS.spawn_actor_from_class(NikScatter, V(0, 0, 0))
    a.set_actor_label("Floor_" + kind[3:30])
    a.set_folder_path("Garden/Floor")
    a.tags = [unreal.Name("garden4")]
    a.set_editor_property("mesh", m)
    a.set_editor_property("instances", [unreal.Transform(V(x, y, z), unreal.Rotator(0, 0, yaw), V(s, s, s))
                                        for x, y, z, yaw, s in pts])
    # optimisation: plants and pebbles vanish past where the fog has them anyway; only big pieces cast shadows
    a.set_editor_property("cast_shadow", rock and not small)
    a.set_editor_property("cull_distance", 6000.0 if not rock else (8000.0 if small else 0.0))
    a.set_editor_property("lumen", rock and not small)
    a.rebuild()
    n += len(pts)
log("floor instances", n)

# ------------------------------------------------------------------ air
for f in [a for a in EAS.get_all_level_actors() if isinstance(a, unreal.ExponentialHeightFog)]:
    c = f.component
    c.set_editor_property("volumetric_fog_distance", 3500.0)       # shafts inside and over the garden
    c.set_editor_property("volumetric_fog_extinction_scale", 0.03)  # keeps the inside as it was (the density is ~40x)
    c.set_editor_property("start_distance", 2200.0)
    c.set_editor_property("fog_height_falloff", 0.06)
    c.set_editor_property("fog_inscattering_luminance", unreal.LinearColor(2600.0, 3000.0, 3500.0, 1.0))
    c.set_editor_property("directional_inscattering_luminance", unreal.LinearColor(9000.0, 7000.0, 4300.0, 1.0))
    c.set_editor_property("directional_inscattering_start_distance", 2500.0)
    c.set_editor_property("directional_inscattering_exponent", 5.0)
    c.set_editor_property("fog_max_opacity", 0.97)
# the time of day presets carry the fog density: far forest layers fade, the room keeps its light shafts
x = [a for a in EAS.get_all_level_actors() if a.get_class().get_name() == "NikExperience"][0]
P = list(x.get_editor_property("presets"))
for i, v in enumerate((0.1, 0.07, 0.12, 0.08)):
    p = P[i]
    p.set_editor_property("fog_density", v)
    P[i] = p
x.set_editor_property("presets", P)
for a in EAS.get_all_level_actors():
    if a.get_actor_label() == "Lawn3D":
        a.set_editor_property("lumen", False)
        a.rebuild()
unreal.EditorLoadingAndSavingUtils.save_current_level()
log("done")
