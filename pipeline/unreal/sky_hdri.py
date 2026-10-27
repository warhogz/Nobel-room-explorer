"""Daylight from an HDRI (in the open editor): the HDRI lights the scene (sky light cubemap), one crisp sun.

The four Corona suns (two of them 34 degrees wide: a giant soft panel that floods every surface) and the procedural
SkyAtmosphere are replaced. The sun's direction follows the sun in the HDRI; intensities are parameters at the top.
HDRI: build/hdri/<name>.hdr (Poly Haven CC0). Re-runnable (everything it makes is tagged "daylight").
What the windows show is a clean physical sky (SkyAtmosphere lit by the sun): the HDRI's photographed ground and
hills, projected on a 500 m sphere, read wrong outside. NIK_HDRI_VISIBLE=1 shows the HDRI sphere instead.
"""
import math
import os

import unreal

HDRI = os.environ.get("NIK_HDRI", "C:/Users/hdog/Downloads/Telegram Desktop/NOBEL ISLAND KITCHEN (2)/NOBEL ISLAND KITCHEN/build/hdri/lebombo_2k.hdr")
SUN_LUX = float(os.environ.get("NIK_SUN_LUX", "15000"))     # crisp sun (was 4 Corona suns, ~39 000 lux together)
SKY_NITS = float(os.environ.get("NIK_SKY_NITS", "4000"))    # HDRI value 1.0 -> nits on the sky sphere
SUN_ELEVATION = float(os.environ.get("NIK_SUN_ELEV", "18"))  # the HDRI's sun (lebombo: 18 deg)
# light travel direction (yaw, deg): from the south-west through the south glass doors and clerestory into the hall
SUN_YAW = float(os.environ.get("NIK_SUN_YAW", "70"))
# HDRI longitude of its sun (u = 0.521 on lebombo) -> sphere yaw so that the HDRI sun sits behind the directional light
HDRI_SUN_U = float(os.environ.get("NIK_HDRI_SUN_U", "0.521"))
HDRI_VISIBLE = os.environ.get("NIK_HDRI_VISIBLE") == "1"

EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
AT = unreal.AssetToolsHelpers.get_asset_tools()
D = "/Game/Nobel/Sky"

for a in EAS.get_all_level_actors():
    if unreal.Name("daylight") in a.tags or isinstance(a, (unreal.SkyAtmosphere, unreal.DirectionalLight)):
        EAS.destroy_actor(a)

# ------------------------------------------------------------------ HDRI cubemap
name = "HDRI_" + os.path.splitext(os.path.basename(HDRI))[0]
if not EAL.does_asset_exist(D + "/" + name):
    t = unreal.AssetImportTask()
    t.filename, t.destination_path, t.destination_name = HDRI, D, name
    t.automated, t.save = True, True
    AT.import_asset_tasks([t])
cube = unreal.load_asset(D + "/" + name)
print("hdri", cube.get_class().get_name())

# ------------------------------------------------------------------ sky material: unlit, IsSky, cube lookup in the sphere's space
mpath = D + "/M_HDRISky"
if EAL.does_asset_exist(mpath):
    EAL.delete_asset(mpath)
m = AT.create_asset("M_HDRISky", D, unreal.Material, unreal.MaterialFactoryNew())
m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
m.set_editor_property("two_sided", True)
m.set_editor_property("is_sky", True)
cam = MEL.create_material_expression(m, unreal.MaterialExpressionCameraVectorWS, -900, 0)
neg = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -700, 0)
MEL.connect_material_expressions(cam, "", neg, "A")
neg.set_editor_property("const_b", -1.0)  # view direction = -camera vector
tr = MEL.create_material_expression(m, unreal.MaterialExpressionTransform, -500, 0)
tr.set_editor_property("transform_source_type", unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_WORLD)
tr.set_editor_property("transform_type", unreal.MaterialVectorCoordTransform.TRANSFORM_LOCAL)
MEL.connect_material_expressions(neg, "", tr, "")
smp = MEL.create_material_expression(m, unreal.MaterialExpressionTextureSampleParameterCube, -300, 0)
smp.set_editor_property("parameter_name", "HDRI")
smp.set_editor_property("texture", cube)
MEL.connect_material_expressions(tr, "", smp, "UVs")
k = MEL.create_material_expression(m, unreal.MaterialExpressionScalarParameter, -300, 250)
k.set_editor_property("parameter_name", "Intensity")
k.set_editor_property("default_value", SKY_NITS)
mul = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -100, 0)
MEL.connect_material_expressions(smp, "RGB", mul, "A")
MEL.connect_material_expressions(k, "", mul, "B")
MEL.connect_material_property(mul, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
print("sky material errors:", MEL.recompile_material(m))
EAL.save_loaded_asset(m, False)

# ------------------------------------------------------------------ sky sphere (500 m), rotated so the HDRI sun is behind the light
src_yaw = SUN_YAW + 180.0  # where the light comes from
sphere = EAS.spawn_actor_from_object(unreal.load_asset("/Engine/BasicShapes/Sphere"), unreal.Vector(0, 0, 0))
sphere.set_actor_label("HDRI_SkySphere")
sphere.set_folder_path("Lights/env")
sphere.tags = [unreal.Name("daylight")]
sphere.set_actor_scale3d(unreal.Vector(10000, 10000, 10000))
# long-lat u = 0.5 looks down local +X; the HDRI sun at u is (u - 0.5) * 360 deg from it
sphere.set_actor_rotation(unreal.Rotator(0, 0, src_yaw - (HDRI_SUN_U - 0.5) * 360.0), False)
smc = sphere.static_mesh_component
smc.set_material(0, m)
smc.set_editor_property("cast_shadow", False)
smc.set_editor_property("affect_distance_field_lighting", False)
smc.set_editor_property("affect_dynamic_indirect_lighting", False)
# a 5 km solid sphere around the level: with any collision the walker spawns inside it and is pushed out 5 km away
smc.set_collision_profile_name("NoCollision")
smc.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
smc.set_editor_property("generate_overlap_events", False)

# ------------------------------------------------------------------ one sun
sun = EAS.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 3000),
                                 unreal.Rotator(0, -SUN_ELEVATION, SUN_YAW))
sun.set_actor_label("Sun")
sun.set_folder_path("Lights/env")
sun.tags = [unreal.Name("daylight")]
sc = sun.get_component_by_class(unreal.DirectionalLightComponent)
sc.set_mobility(unreal.ComponentMobility.MOVABLE)
sc.set_editor_property("intensity", SUN_LUX)
sc.set_editor_property("light_source_angle", 0.53)  # the real sun: crisp window shadows
sc.set_editor_property("use_temperature", True)
sc.set_editor_property("temperature", float(os.environ.get("NIK_SUN_K", "4600")))  # 4600 K = low warm sun
sc.set_editor_property("volumetric_scattering_intensity", 1.5)
sc.set_editor_property("atmosphere_sun_light", False)

# ------------------------------------------------------------------ sky light + visible sky
sphere_yaw = sphere.get_actor_rotation().yaw
if not HDRI_VISIBLE:
    EAS.destroy_actor(sphere)
    atm = EAS.spawn_actor_from_class(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0))
    atm.set_actor_label("SkyAtmosphere")
    atm.set_folder_path("Lights/env")
    atm.tags = [unreal.Name("daylight")]
    sc.set_editor_property("atmosphere_sun_light", True)
for a in EAS.get_all_level_actors():
    if isinstance(a, unreal.SkyLight):
        c = a.get_component_by_class(unreal.SkyLightComponent)
        c.set_editor_property("lower_hemisphere_is_black", False)
        if HDRI_VISIBLE:
            c.set_editor_property("real_time_capture", True)  # captures the IsSky sphere
            c.set_editor_property("source_type", unreal.SkyLightSourceType.SLS_CAPTURED_SCENE)
            c.set_editor_property("intensity", 1.0)
        else:
            # the HDRI lights the room directly, rotated like the sphere so its sun side matches the Sun
            c.set_editor_property("real_time_capture", False)
            c.set_editor_property("source_type", unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP)
            c.set_editor_property("cubemap", cube)
            c.set_editor_property("source_cubemap_angle", sphere_yaw)
            c.set_editor_property("intensity", SKY_NITS)
            c.recapture_sky()
unreal.EditorLoadingAndSavingUtils.save_current_level()
print("daylight: sun %.0f lux from yaw %.0f / elev %.0f, sky %.0f nits/unit, hdri %s" % (
    SUN_LUX, src_yaw, SUN_ELEVATION, SKY_NITS, "visible" if HDRI_VISIBLE else "lighting only"))
