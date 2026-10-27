"""Assets the C++ experience (Source/NobelKitchen/NikExperience) drives (in the open editor):

/Game/Nobel/FX/MPC_Nik          RevealRadius (cm from the camera, 1e6 = all visible), RevealEdge (cm), InteriorGlow
/Game/Nobel/FX/M_Reveal         post process: the scene appears inside a sphere growing from the camera, gold rim
M_Nik emissive x MPC_Nik.InteriorGlow (lamps, onyx, LED strips follow the time of day)
Chandelier_Glow point lights inside the glass sculpture (tag "chandelier_glow"; the C++ fades them by night)
"""
import unreal

AT = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
FX = "/Game/Nobel/FX"

# ------------------------------------------------------------------ parameter collection
mpc = unreal.load_asset(FX + "/MPC_Nik") or AT.create_asset("MPC_Nik", FX, unreal.MaterialParameterCollection,
                                                             unreal.MaterialParameterCollectionFactoryNew())
def scalar_param(name, value):
    p = unreal.CollectionScalarParameter()
    p.set_editor_property("parameter_name", name)
    p.set_editor_property("default_value", value)
    return p


# only once: re-creating the parameters gives them new ids and every material using them stops compiling
if not mpc.get_editor_property("scalar_parameters"):
    mpc.set_editor_property("scalar_parameters", [scalar_param("RevealRadius", 1.0e6), scalar_param("RevealEdge", 250.0),
                                                  scalar_param("InteriorGlow", 1.0)])
EAL.save_loaded_asset(mpc, False)


def node(m, cls, x, y, **props):
    e = MEL.create_material_expression(m, cls, x, y)
    for k, v in props.items():
        e.set_editor_property(k, v)
    return e


def link(a, aout, b, bin_):
    if not MEL.connect_material_expressions(a, aout, b, bin_):
        print("WARN link failed", a.get_name(), aout, b.get_name(), bin_)


def mpc_param(m, name, x, y):
    return node(m, unreal.MaterialExpressionCollectionParameter, x, y, collection=mpc, parameter_name=name)


# ------------------------------------------------------------------ logo (build/ue/intro/Logo.png, rasterised from Logo.svg)
LOGO = "C:/Users/hdog/Downloads/Telegram Desktop/NOBEL ISLAND KITCHEN (2)/NOBEL ISLAND KITCHEN/build/ue/intro/Logo.png"
t = unreal.AssetImportTask()
t.filename, t.destination_path, t.destination_name, t.automated, t.replace_existing, t.save = LOGO, FX, "T_Logo", True, True, True
AT.import_asset_tasks([t])
logo = unreal.load_asset(FX + "/T_Logo")
logo.set_editor_property("lod_group", unreal.TextureGroup.TEXTUREGROUP_UI)
logo.set_editor_property("mip_gen_settings", unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)
EAL.save_loaded_asset(logo, False)

# ------------------------------------------------------------------ reveal post process
path = FX + "/M_Reveal"
if EAL.does_asset_exist(path):
    m = unreal.load_asset(path)
    MEL.delete_all_material_expressions(m)
else:
    m = AT.create_asset("M_Reveal", FX, unreal.Material, unreal.MaterialFactoryNew())
m.set_editor_property("material_domain", unreal.MaterialDomain.MD_POST_PROCESS)
m.set_editor_property("blendable_location", unreal.BlendableLocation.BL_SCENE_COLOR_AFTER_TONEMAPPING)
scene = node(m, unreal.MaterialExpressionSceneTexture, -900, 0, scene_texture_id=unreal.SceneTextureId.PPI_POST_PROCESS_INPUT0)
depth = node(m, unreal.MaterialExpressionSceneDepth, -900, 300)
radius = mpc_param(m, "RevealRadius", -900, 450)
edge = mpc_param(m, "RevealEdge", -900, 550)
# hidden = smoothstep(R - edge, R, depth): 0 inside the sphere, 1 beyond it
lo = node(m, unreal.MaterialExpressionSubtract, -650, 450)
link(radius, "", lo, "A")
link(edge, "", lo, "B")
ss = node(m, unreal.MaterialExpressionSmoothStep, -450, 350)
link(lo, "", ss, "Min")
link(radius, "", ss, "Max")
link(depth, "", ss, "Value")
# off switch: gate = saturate((1e8 - R) * 1e-7) - 1 while revealing, 0 once the radius is "everything" (the sky's
# depth is ~infinite: without the gate it stayed black in the windows)
sub = node(m, unreal.MaterialExpressionSubtract, -650, 800, const_a=1.0e8)
link(mpc_param(m, "RevealRadius", -900, 800), "", sub, "B")
k7 = node(m, unreal.MaterialExpressionMultiply, -500, 800, const_b=1.0e-7)
link(sub, "", k7, "A")
gate = node(m, unreal.MaterialExpressionSaturate, -400, 800)
link(k7, "", gate, "")
mask = node(m, unreal.MaterialExpressionMultiply, -300, 350)
link(ss, "", mask, "A")
link(gate, "", mask, "B")
ss = mask
# gold rim: a band that peaks in the middle of the edge
band = node(m, unreal.MaterialExpressionMultiply, -250, 500)
om = node(m, unreal.MaterialExpressionOneMinus, -350, 600)
link(ss, "", om, "")
link(ss, "", band, "A")
link(om, "", band, "B")
gold = node(m, unreal.MaterialExpressionConstant3Vector, -250, 700, constant=unreal.LinearColor(1.0, 0.72, 0.35, 1))
rim = node(m, unreal.MaterialExpressionMultiply, -50, 600)
k4 = node(m, unreal.MaterialExpressionMultiply, -150, 500)
link(band, "", k4, "A")
k4.set_editor_property("const_b", 4.0)
link(k4, "", rim, "A")
link(gold, "", rim, "B")
black = node(m, unreal.MaterialExpressionConstant3Vector, -250, 200, constant=unreal.LinearColor(0, 0, 0, 1))
rgb = node(m, unreal.MaterialExpressionComponentMask, -650, 0, r=True, g=True, b=True, a=False)
link(scene, "Color", rgb, "")
lerp = node(m, unreal.MaterialExpressionLinearInterpolate, -50, 150)
link(rgb, "", lerp, "A")
link(black, "", lerp, "B")
link(ss, "", lerp, "Alpha")
out = node(m, unreal.MaterialExpressionAdd, 150, 250)
link(lerp, "", out, "A")
link(rim, "", out, "B")
MEL.connect_material_property(out, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
print("M_Reveal:", MEL.recompile_material(m))
EAL.save_loaded_asset(m, False)

pp = [a for a in EAS.get_all_level_actors() if isinstance(a, unreal.PostProcessVolume)][0]
s = pp.settings
wb = s.get_editor_property("weighted_blendables")
arr = [b for b in wb.array if b.object != m] + [unreal.WeightedBlendable(weight=1.0, object=m)]
wb.array = arr
s.set_editor_property("weighted_blendables", wb)
pp.settings = s

# ------------------------------------------------------------------ M_Nik emissive x InteriorGlow
nik = unreal.load_asset("/Game/Nobel/Materials/M_Nik")
attrs = [e for e in unreal.ObjectIterator(unreal.MaterialExpressionMakeMaterialAttributes) if e.get_outer() == nik]
glow = [e for e in unreal.ObjectIterator(unreal.MaterialExpressionCollectionParameter) if e.get_outer() == nik]
if attrs and not glow:
    # the node currently feeding EmissiveColor is the Add of (emissive colour, glow map)
    adds = [e for e in unreal.ObjectIterator(unreal.MaterialExpressionAdd) if e.get_outer() == nik]
    src = adds[-1]
    g = mpc_param(nik, "InteriorGlow", -700, 950)
    mul = node(nik, unreal.MaterialExpressionMultiply, -500, 850)
    link(src, "", mul, "A")
    link(g, "", mul, "B")
    link(mul, "", attrs[0], "EmissiveColor")
    print("M_Nik:", MEL.recompile_material(nik))
    EAL.save_loaded_asset(nik, False)

# ------------------------------------------------------------------ chandelier glow lights
for a in EAS.get_all_level_actors():
    if unreal.Name("chandelier_glow") in a.tags:
        EAS.destroy_actor(a)
ch = [a for a in EAS.get_all_level_actors() if a.get_actor_label().startswith("Chandelier_")]
lo_b, hi_b = None, None
for a in ch:
    o, e = a.get_actor_bounds(False)
    lo = o - e
    hi = o + e
    lo_b = lo if lo_b is None else unreal.Vector(min(lo_b.x, lo.x), min(lo_b.y, lo.y), min(lo_b.z, lo.z))
    hi_b = hi if hi_b is None else unreal.Vector(max(hi_b.x, hi.x), max(hi_b.y, hi.y), max(hi_b.z, hi.z))
n = 0
if lo_b:
    # warm points along the sculpture's long axis, a little under it (the glass and gold catch them)
    long_x = (hi_b.x - lo_b.x) >= (hi_b.y - lo_b.y)
    steps = 7
    for i in range(steps):
        t = (i + 0.5) / steps
        x = lo_b.x + (hi_b.x - lo_b.x) * (t if long_x else 0.5)
        y = lo_b.y + (hi_b.y - lo_b.y) * (0.5 if long_x else t)
        z = lo_b.z + (hi_b.z - lo_b.z) * 0.35
        a = EAS.spawn_actor_from_class(unreal.PointLight, unreal.Vector(x, y, z))
        a.set_actor_label("Chandelier_Glow_%d" % i)
        a.set_folder_path("Lights/chandelier")
        a.tags = [unreal.Name("chandelier_glow")]
        c = a.get_component_by_class(unreal.PointLightComponent)
        c.set_mobility(unreal.ComponentMobility.MOVABLE)
        c.set_editor_property("intensity_units", unreal.LightUnits.CANDELAS)
        c.set_editor_property("intensity", 0.0)  # NikExperience fades them in at dusk / night
        c.set_editor_property("use_temperature", True)
        c.set_editor_property("temperature", 2700.0)
        c.set_editor_property("source_radius", 25.0)
        c.set_editor_property("attenuation_radius", 900.0)
        c.set_editor_property("cast_shadows", False)
        n += 1
unreal.EditorLoadingAndSavingUtils.save_current_level()
print("experience assets ready; chandelier glow lights:", n, "bounds", lo_b, hi_b)
