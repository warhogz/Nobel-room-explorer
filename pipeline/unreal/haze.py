"""Garden haze (in the open editor): the courtyard dissolves in a soft lit mist, the room does not.

A translucent shell just outside the glass (five inward-facing planes) carries the fog. Its material integrates
exponential height fog along the view ray, but only over the part of the ray *behind* the shell (scene depth - shell
depth), so the interior, its lights, Lumen and the light shafts are untouched; the lawn by the glass stays clear and the
hedge / trees fade. Lit (volumetric non-directional) -> it follows the sun and the sky through the time of day.
Re-runnable (tag "haze").
"""
import unreal

G = "/Game/Nobel/Garden"
AT = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
MP = unreal.MaterialProperty

# the shell: just outside the windows (south glass y -282, north y 560, east x 1733), up over the roof
X0, X1, Y0, Y1, Z0, Z1 = -430.0, 1765.0, -330.0, 600.0, -100.0, 1150.0
DENSITY, FALLOFF, MAX_OPACITY = 0.0026, 900.0, 0.94  # 1/cm at the ground, cm per e-fold of height
MAX_LEN = 1800.0  # the mist lies over the courtyard only: no more than 18 m of it along a ray (keeps the sky)


def log(*a):
    unreal.log("NIK haze " + " ".join(str(x) for x in a))


def node(m, cls, x, y, **props):
    e = MEL.create_material_expression(m, cls, x, y)
    for k, v in props.items():
        e.set_editor_property(k, v)
    return e


def link(a, aout, b, bin_):
    if not MEL.connect_material_expressions(a, aout, b, bin_):
        log("WARN link failed", a.get_name(), aout, "->", b.get_name(), bin_)


M = unreal.load_asset(G + "/M_Haze") or AT.create_asset("M_Haze", G, unreal.Material, unreal.MaterialFactoryNew())
MEL.delete_all_material_expressions(M)
M.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
M.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_DEFAULT_LIT)
M.set_editor_property("translucency_lighting_mode", unreal.TranslucencyLightingMode.TLM_VOLUMETRIC_NON_DIRECTIONAL)
M.set_editor_property("two_sided", False)
for p in ("apply_fogging", "apply_cloud_fogging"):
    try:
        M.set_editor_property(p, False)
    except Exception:
        pass

wp = node(M, unreal.MaterialExpressionWorldPosition, -1200, 0)
z1 = node(M, unreal.MaterialExpressionComponentMask, -1000, 0, r=False, g=False, b=True, a=False)
link(wp, "", z1, "")
cam = node(M, unreal.MaterialExpressionCameraVectorWS, -1200, 150)
sd = node(M, unreal.MaterialExpressionSceneDepth, -1200, 300)
pd = node(M, unreal.MaterialExpressionPixelDepth, -1200, 400)
dens = node(M, unreal.MaterialExpressionScalarParameter, -1200, 500, parameter_name="Density", default_value=DENSITY)
fall = node(M, unreal.MaterialExpressionScalarParameter, -1200, 600, parameter_name="Falloff", default_value=FALLOFF)
maxo = node(M, unreal.MaterialExpressionScalarParameter, -1200, 700, parameter_name="MaxOpacity", default_value=MAX_OPACITY)

cu = node(M, unreal.MaterialExpressionCustom, -700, 300)
cu.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT1)
cu.set_editor_property("description", "HazeBehindShell")
cu.set_editor_property("code", """
float3 Dir = -normalize(CamVec);
float CosA = max(dot(Dir, View.ViewForward), 1e-3);
float Len = min(max(SceneD - PixelD, 0.0) / CosA, MaxLen);  // ray length behind the shell
float H = max(Falloff, 1.0);
float Base = exp(-max(Z1, 0.0) / H);
float K = Dir.z / H;
float KL = clamp(K * Len, -30.0, 60.0);
float I = abs(KL) < 1e-4 ? Len * Base : Base * (1.0 - exp(-KL)) / K;
float Up = saturate(1.0 - max(Dir.z, 0.0) * 1.6);  // the sky above stays blue
return MaxOp * Up * (1.0 - exp(-Density * max(I, 0.0)));
""")
ins = []
maxl = node(M, unreal.MaterialExpressionScalarParameter, -1200, 800, parameter_name="MaxLen", default_value=MAX_LEN)
for n in ("CamVec", "SceneD", "PixelD", "Z1", "Density", "Falloff", "MaxOp", "MaxLen"):
    ci = unreal.CustomInput()
    ci.set_editor_property("input_name", n)
    ins.append(ci)
cu.set_editor_property("inputs", ins)
for src, n in ((cam, "CamVec"), (sd, "SceneD"), (pd, "PixelD"), (z1, "Z1"), (dens, "Density"), (fall, "Falloff"), (maxo, "MaxOp"), (maxl, "MaxLen")):
    link(src, "", cu, n)
MEL.connect_material_property(cu, "", MP.MP_OPACITY)
col = node(M, unreal.MaterialExpressionVectorParameter, -400, -100, parameter_name="Color",
           default_value=unreal.LinearColor(0.78, 0.82, 0.86, 1.0))
MEL.connect_material_property(col, "", MP.MP_BASE_COLOR)
MEL.connect_material_property(node(M, unreal.MaterialExpressionConstant, -400, 50, r=1.0), "", MP.MP_ROUGHNESS)
MEL.connect_material_property(node(M, unreal.MaterialExpressionConstant, -400, 120, r=0.0), "", MP.MP_SPECULAR)
log("compile", MEL.recompile_material(M))
EAL.save_loaded_asset(M, False)

# ------------------------------------------------------------------ the shell
for a in list(EAS.get_all_level_actors()):
    if unreal.Name("haze") in a.tags:
        EAS.destroy_actor(a)
plane = unreal.load_asset("/Engine/BasicShapes/Plane")
V = unreal.Vector
faces = [  # centre, inward normal, in-plane x axis, size (x, y) cm
    (V((X0 + X1) / 2, Y0, (Z0 + Z1) / 2), V(0, 1, 0), V(1, 0, 0), (X1 - X0, Z1 - Z0)),
    (V((X0 + X1) / 2, Y1, (Z0 + Z1) / 2), V(0, -1, 0), V(1, 0, 0), (X1 - X0, Z1 - Z0)),
    (V(X0, (Y0 + Y1) / 2, (Z0 + Z1) / 2), V(1, 0, 0), V(0, 1, 0), (Y1 - Y0, Z1 - Z0)),
    (V(X1, (Y0 + Y1) / 2, (Z0 + Z1) / 2), V(-1, 0, 0), V(0, 1, 0), (Y1 - Y0, Z1 - Z0)),
    (V((X0 + X1) / 2, (Y0 + Y1) / 2, Z1), V(0, 0, -1), V(1, 0, 0), (X1 - X0, Y1 - Y0)),
]
for i, (c, n, ax, (sx, sy)) in enumerate(faces):
    a = EAS.spawn_actor_from_object(plane, c)
    a.set_actor_rotation(unreal.MathLibrary.make_rot_from_zx(n, ax), False)
    up = a.get_actor_up_vector()
    if up.dot(n) < 0.5:
        log("WARN face", i, "normal", up)
    # the plane's local y may map to either in-plane axis: scale both to cover
    a.set_actor_scale3d(V(sx / 100.0, sy / 100.0, 1.0))
    a.set_actor_label("Haze_%d" % i)
    a.set_folder_path("Garden")
    a.tags = [unreal.Name("haze")]
    smc = a.get_component_by_class(unreal.StaticMeshComponent)
    smc.set_material(0, M)
    smc.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    smc.set_editor_property("cast_shadow", False)
    smc.set_editor_property("translucency_sort_priority", -100)  # under the light shafts and the glass
    smc.set_editor_property("affect_distance_field_lighting", False)
    smc.set_editor_property("affect_dynamic_indirect_lighting", False)
unreal.EditorLoadingAndSavingUtils.save_current_level()
log("done", len(faces), "faces")
