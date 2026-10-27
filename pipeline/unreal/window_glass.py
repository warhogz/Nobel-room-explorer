"""Cheap window glass (in the open editor). The big panes were Thin Translucent with per-pixel lighting: ~10 ms a frame
at 60 % resolution under 100+ lamps. Panes now use M_WindowGlass: unlit translucent, the reflection is the sky light's own
capture along the reflection vector (follows the time of day), weighted by Fresnel (4 % head-on, a mirror at grazing).
Small glass (tableware, chandelier, shelves) keeps the full material. Re-runnable.
"""
import unreal

G = "/Game/Nobel/Materials"
AT = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
MP = unreal.MaterialProperty
PANES = {"SM_Rectangle2106791298", "SM_Rectangle2106791308", "SM_Rectangle2106791309", "SM_Object2121419066",
         "SM_Object2121419067", "SM_Object2121419068", "SM_Object2121419069", "SM_Object2121419070", "SM_Object2121419071",
         "SM_Object2121419072", "SM_Object2121419073"}


def node(m, cls, x, y, **props):
    e = MEL.create_material_expression(m, cls, x, y)
    for k, v in props.items():
        e.set_editor_property(k, v)
    return e


M = unreal.load_asset(G + "/M_WindowGlass")
if M is None:
    M = AT.create_asset("M_WindowGlass", G, unreal.Material, unreal.MaterialFactoryNew())
else:
    MEL.delete_all_material_expressions(M)
M.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
M.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
M.set_editor_property("two_sided", True)
rv = node(M, unreal.MaterialExpressionReflectionVectorWS, -700, 0)
sky = node(M, unreal.MaterialExpressionSkyLightEnvMapSample, -450, 0)
MEL.connect_material_expressions(rv, "", sky, "Direction")
gain = node(M, unreal.MaterialExpressionMultiply, -200, 0, const_b=1.0)
MEL.connect_material_expressions(sky, "", gain, "A")
MEL.connect_material_expressions(node(M, unreal.MaterialExpressionScalarParameter, -450, 150, parameter_name="Reflection", default_value=0.1), "", gain, "B")
MEL.connect_material_property(gain, "", MP.MP_EMISSIVE_COLOR)
fr = node(M, unreal.MaterialExpressionFresnel, -450, 300, exponent=5.0, base_reflect_fraction=0.04)
MEL.connect_material_property(fr, "", MP.MP_OPACITY)
unreal.log("NIK glass " + str(MEL.recompile_material(M)))
EAL.save_loaded_asset(M, False)

n = 0
for a in EAS.get_all_level_actors():
    if not isinstance(a, unreal.StaticMeshActor):
        continue
    c = a.static_mesh_component
    if c.static_mesh and c.static_mesh.get_name() in PANES:
        for i in range(c.get_num_materials()):
            m = c.get_material(i)
            if m and "Glass" in m.get_base_material().get_name():
                c.set_material(i, M)
                n += 1
unreal.EditorLoadingAndSavingUtils.save_current_level()
unreal.log("NIK glass panes %d" % n)
