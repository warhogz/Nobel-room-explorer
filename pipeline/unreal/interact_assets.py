"""Assets for the walk-through interactions (in the open editor). Re-runnable.
  - M_Water: the stream from the island faucet (glassy, streaked, moving down); NikExperience spawns and scales it
  - invisible walls just outside the glass: the visitor stays inside the house (tag "bounds")
"""
import unreal

FX = "/Game/Nobel/FX"
AT = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
MP = unreal.MaterialProperty


def log(*a):
    unreal.log("NIK interact " + " ".join(str(x) for x in a))


def node(m, cls, x, y, **props):
    e = MEL.create_material_expression(m, cls, x, y)
    for k, v in props.items():
        e.set_editor_property(k, v)
    return e


def link(a, aout, b, bin_):
    if not MEL.connect_material_expressions(a, aout, b, bin_):
        log("WARN link failed", a.get_name(), aout, "->", b.get_name(), bin_)


# ------------------------------------------------------------------ water
# NikExperience holds a hard reference to M_Water: rebuilding the graph of the loaded material crashes the editor
# (DeleteAllMaterialExpressions on a rooted object) -> only built once; delete the asset to rebuild it
M = unreal.load_asset(FX + "/M_Water")
if M is None:
    M = AT.create_asset("M_Water", FX, unreal.Material, unreal.MaterialFactoryNew())
    MEL.delete_all_material_expressions(M)
    M.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    M.set_editor_property("translucency_lighting_mode", unreal.TranslucencyLightingMode.TLM_SURFACE_PER_PIXEL_LIGHTING)
    M.set_editor_property("two_sided", True)
    # streaks: world z scrolling down fast, a little noise across -> reads as running water
    wp = node(M, unreal.MaterialExpressionWorldPosition, -1200, 0)
    t = node(M, unreal.MaterialExpressionTime, -1200, 200)
    spd = node(M, unreal.MaterialExpressionMultiply, -1000, 200, const_b=120.0)
    link(t, "", spd, "A")
    pos = node(M, unreal.MaterialExpressionAdd, -800, 100)
    link(wp, "", pos, "A")
    mv = node(M, unreal.MaterialExpressionAppendVector, -1000, 350)
    link(node(M, unreal.MaterialExpressionConstant2Vector, -1200, 350, r=0.0, g=0.0), "", mv, "A")
    link(spd, "", mv, "B")
    link(mv, "", pos, "B")
    sc = node(M, unreal.MaterialExpressionMultiply, -650, 100, const_b=0.0)
    link(pos, "", sc, "A")
    link(node(M, unreal.MaterialExpressionConstant3Vector, -800, 250, constant=unreal.LinearColor(0.9, 0.9, 0.12, 1)), "", sc, "B")
    nz = node(M, unreal.MaterialExpressionNoise, -450, 100, scale=1.0, levels=2, output_min=0.0, output_max=1.0, quality=1)
    link(sc, "", nz, "")
    op = node(M, unreal.MaterialExpressionLinearInterpolate, -200, 100, const_a=0.38, const_b=0.8)
    link(nz, "", op, "Alpha")
    fres = node(M, unreal.MaterialExpressionFresnel, -450, 300, exponent=2.5)
    op2 = node(M, unreal.MaterialExpressionAdd, -50, 150)
    link(op, "", op2, "A")
    link(fres, "", op2, "B")
    sat = node(M, unreal.MaterialExpressionSaturate, 100, 150)
    link(op2, "", sat, "")
    MEL.connect_material_property(sat, "", MP.MP_OPACITY)
    MEL.connect_material_property(node(M, unreal.MaterialExpressionConstant3Vector, 100, -150,
                                       constant=unreal.LinearColor(0.75, 0.85, 0.95, 1)), "", MP.MP_BASE_COLOR)
    MEL.connect_material_property(node(M, unreal.MaterialExpressionConstant, 100, -50, r=0.04), "", MP.MP_ROUGHNESS)
    MEL.connect_material_property(node(M, unreal.MaterialExpressionConstant, 100, 0, r=1.0), "", MP.MP_SPECULAR)
    MEL.connect_material_property(node(M, unreal.MaterialExpressionConstant, 100, 50, r=0.0), "", MP.MP_METALLIC)
    log("water compile", MEL.recompile_material(M))
    EAL.save_loaded_asset(M, False)

# ------------------------------------------------------------------ stay inside: walls along the glass line
for a in list(EAS.get_all_level_actors()):
    if unreal.Name("bounds") in a.tags:
        EAS.destroy_actor(a)
X0, X1, Y0, Y1, H = -410.0, 1755.0, -305.0, 585.0, 600.0  # just outside south glass (-282), north (560), east (1733)
cube = unreal.load_asset("/Engine/BasicShapes/Cube")
for i, (cx, cy, lx, ly) in enumerate((((X0 + X1) / 2, Y0, X1 - X0 + 40, 20.0), ((X0 + X1) / 2, Y1, X1 - X0 + 40, 20.0),
                                      (X0, (Y0 + Y1) / 2, 20.0, Y1 - Y0 + 40), (X1, (Y0 + Y1) / 2, 20.0, Y1 - Y0 + 40))):
    a = EAS.spawn_actor_from_object(cube, unreal.Vector(cx, cy, H / 2 - 20))
    a.set_actor_scale3d(unreal.Vector(lx / 100, ly / 100, H / 100))
    a.set_actor_label("Bounds_%d" % i)
    a.set_folder_path("Experience")
    a.tags = [unreal.Name("bounds")]
    c = a.get_component_by_class(unreal.StaticMeshComponent)
    c.set_editor_property("visible", False)
    c.set_editor_property("cast_shadow", False)
    c.set_editor_property("affect_distance_field_lighting", False)
    c.set_collision_profile_name("BlockAll")
unreal.EditorLoadingAndSavingUtils.save_current_level()
log("done")
