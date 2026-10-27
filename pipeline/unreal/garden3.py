"""Garden v3 (in the open editor; after blender/garden3_mesh.py). Everything is real geometry:
  - clipped hedge: 200 cm modules of folded leaves (Nanite, opaque, two-sided foliage shading, per-leaf colour)
  - boxwood balls, a 3D mown lawn (instanced blade clumps over the lawn texture)
  - the land beyond: a meadow ring, rolling hills to the horizon, specimen trees and a forest (Environment_Set trees,
    instanced with their LODs; far trees cast no shadow)
  - air: height fog that starts 25 m out (the room and the garden stay clear, the forest and the hills recede)
Replaces garden v2 (tag garden2), the haze shell (tag haze) and the flat Meadow plane. Re-runnable (tag garden3).
"""
import json
import math
import random

import unreal

SRC = "C:/Users/hdog/Downloads/Telegram Desktop/NOBEL ISLAND KITCHEN (2)/NOBEL ISLAND KITCHEN/build/ue/garden3"
G = "/Game/Nobel/Garden3"
FOL = "/Game/Environment_Set/Environment/Foliage/Models/"
AT = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
MP = unreal.MaterialProperty
V = unreal.Vector
rng = random.Random(3)
data = json.load(open(SRC + "/garden3.json"))
X0, X1, Y0, Y1 = data["hedge"]["rect"]
T, MOD = data["hedge"]["thick"], data["hedge"]["module"]
CX = (X0 + X1) / 2


def log(*a):
    unreal.log("NIK garden3 " + " ".join(str(x) for x in a))


# ------------------------------------------------------------------ clear the old garden
old = 0
for a in list(EAS.get_all_level_actors()):
    tags = [str(t) for t in a.tags]
    if any(t in tags for t in ("garden2", "haze", "garden3")) or a.get_actor_label() == "Meadow":
        EAS.destroy_actor(a)
        old += 1
log("removed", old)


# ------------------------------------------------------------------ materials
def node(m, cls, x, y, **props):
    e = MEL.create_material_expression(m, cls, x, y)
    for k, v in props.items():
        e.set_editor_property(k, v)
    return e


def link(a, aout, b, bin_):
    if not MEL.connect_material_expressions(a, aout, b, bin_):
        log("WARN link failed", a.get_name(), aout, "->", b.get_name(), bin_)


def new_material(name):
    m = unreal.load_asset(G + "/" + name)
    if m is None:
        m = AT.create_asset(name, G, unreal.Material, unreal.MaterialFactoryNew())
    else:
        MEL.delete_all_material_expressions(m)
    return m


def foliage(name, rough, spec, sss, tint):
    m = new_material(name)
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_TWO_SIDED_FOLIAGE)
    m.set_editor_property("two_sided", True)
    m.set_editor_property("used_with_nanite", True)
    m.set_editor_property("used_with_instanced_static_meshes", True)
    vc = node(m, unreal.MaterialExpressionVertexColor, -700, 0)
    t = node(m, unreal.MaterialExpressionVectorParameter, -700, 200, parameter_name="Tint", default_value=unreal.LinearColor(*tint, 1))
    bc = node(m, unreal.MaterialExpressionMultiply, -450, 0)
    link(vc, "", bc, "A")
    link(t, "", bc, "B")
    MEL.connect_material_property(bc, "", MP.MP_BASE_COLOR)
    ss = node(m, unreal.MaterialExpressionMultiply, -250, 250)
    link(bc, "", ss, "A")
    link(node(m, unreal.MaterialExpressionConstant3Vector, -450, 300, constant=unreal.LinearColor(*sss, 1)), "", ss, "B")
    MEL.connect_material_property(ss, "", MP.MP_SUBSURFACE_COLOR)
    MEL.connect_material_property(node(m, unreal.MaterialExpressionScalarParameter, -250, 100, parameter_name="Roughness", default_value=rough), "", MP.MP_ROUGHNESS)
    MEL.connect_material_property(node(m, unreal.MaterialExpressionScalarParameter, -250, 170, parameter_name="Specular", default_value=spec), "", MP.MP_SPECULAR)
    log(name, MEL.recompile_material(m))
    EAL.save_loaded_asset(m, False)
    return m


M_LEAF = foliage("M_Leaf3D", 0.5, 0.42, (0.75, 0.95, 0.4), (0.66, 0.72, 0.6))  # deep, not lime  # glossy laurel / boxwood leaves
M_GRASS = foliage("M_Grass3D", 0.75, 0.3, (0.6, 0.8, 0.35), (0.72, 0.76, 0.62))

# the meadow and hills: the lawn textures at field scale, dry and green patches, no mowing stripes
M = new_material("M_Meadow")
M.set_editor_property("used_with_nanite", True)
wp = node(M, unreal.MaterialExpressionWorldPosition, -1700, 0)
xy = node(M, unreal.MaterialExpressionComponentMask, -1500, 0, r=True, g=True, b=False, a=False)
link(wp, "", xy, "")
uv1 = node(M, unreal.MaterialExpressionDivide, -1300, 0, const_b=260.0)
link(xy, "", uv1, "A")
uv2 = node(M, unreal.MaterialExpressionDivide, -1300, 150, const_b=1130.0)
link(xy, "", uv2, "A")
uvm = node(M, unreal.MaterialExpressionDivide, -1300, 300, const_b=5200.0)
link(xy, "", uvm, "A")
LBC = unreal.load_asset("/Game/Nobel/Garden/T_Lawn_BC")
LN = unreal.load_asset("/Game/Nobel/Garden/T_Lawn_N")
MAC = unreal.load_asset("/Game/Nobel/Garden/T_Lawn_Macro")
ST = unreal.MaterialSamplerType


def smp(tex, st, uv, x, y):
    s = node(M, unreal.MaterialExpressionTextureSample, x, y, texture=tex, sampler_type=st)
    link(uv, "", s, "UVs")
    return s


ca, cb = smp(LBC, ST.SAMPLERTYPE_COLOR, uv1, -1000, -250), smp(LBC, ST.SAMPLERTYPE_COLOR, uv2, -1000, -50)
na = smp(LN, ST.SAMPLERTYPE_NORMAL, uv1, -1000, 250)
mc = smp(MAC, ST.SAMPLERTYPE_MASKS, uvm, -1000, 500)
mix = node(M, unreal.MaterialExpressionLinearInterpolate, -700, -150, const_alpha=0.5)
link(ca, "RGB", mix, "A")
link(cb, "RGB", mix, "B")
patch = node(M, unreal.MaterialExpressionLinearInterpolate, -700, 450)
link(node(M, unreal.MaterialExpressionConstant3Vector, -950, 650, constant=unreal.LinearColor(0.55, 0.6, 0.42, 1)), "", patch, "A")
link(node(M, unreal.MaterialExpressionConstant3Vector, -950, 750, constant=unreal.LinearColor(0.92, 0.84, 0.58, 1)), "", patch, "B")
link(mc, "R", patch, "Alpha")
col = node(M, unreal.MaterialExpressionMultiply, -400, 0)
link(mix, "", col, "A")
link(patch, "", col, "B")
col2 = node(M, unreal.MaterialExpressionMultiply, -200, 0)
link(col, "", col2, "A")
link(node(M, unreal.MaterialExpressionScalarParameter, -400, 150, parameter_name="Brightness", default_value=0.4), "", col2, "B")
# under the forest (beyond ~25 m from the house) the field turns into darker forest floor
dist = node(M, unreal.MaterialExpressionDistance, -400, 380)
link(xy, "", dist, "A")
link(node(M, unreal.MaterialExpressionConstant2Vector, -600, 420, r=750.0, g=0.0), "", dist, "B")
ff = node(M, unreal.MaterialExpressionSmoothStep, -250, 380, const_min=2600.0, const_max=4200.0)
link(dist, "", ff, "Value")
floor = node(M, unreal.MaterialExpressionMultiply, -250, 500)
link(col2, "", floor, "A")
link(node(M, unreal.MaterialExpressionConstant3Vector, -450, 560, constant=unreal.LinearColor(0.55, 0.5, 0.36, 1)), "", floor, "B")
ground = node(M, unreal.MaterialExpressionLinearInterpolate, -50, 200)
link(col2, "", ground, "A")
link(floor, "", ground, "B")
link(ff, "", ground, "Alpha")
MEL.connect_material_property(ground, "", MP.MP_BASE_COLOR)
fl = node(M, unreal.MaterialExpressionLinearInterpolate, -500, 300, const_alpha=0.6)
link(node(M, unreal.MaterialExpressionConstant3Vector, -700, 350, constant=unreal.LinearColor(0, 0, 1, 1)), "", fl, "A")
link(na, "RGB", fl, "B")
MEL.connect_material_property(fl, "", MP.MP_NORMAL)
MEL.connect_material_property(node(M, unreal.MaterialExpressionConstant, -200, 200, r=0.95), "", MP.MP_ROUGHNESS)
MEL.connect_material_property(node(M, unreal.MaterialExpressionConstant, -200, 260, r=0.25), "", MP.MP_SPECULAR)
log("meadow", MEL.recompile_material(M))
EAL.save_loaded_asset(M, False)

# ------------------------------------------------------------------ meshes
unreal.SystemLibrary.execute_console_command(None, "Interchange.FeatureFlags.Import.FBX False")


def import_mesh(name, mat):
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
    sm.build_nanite = True
    sm.normal_import_method = unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS
    sm.remove_degenerates = False
    sm.vertex_color_import_option = unreal.VertexColorImportOption.REPLACE
    t = unreal.AssetImportTask()
    t.filename, t.destination_path, t.destination_name = "%s/%s.fbx" % (SRC, name), G, "SM_" + name
    t.automated, t.replace_existing, t.save = True, True, False
    t.options = ui
    AT.import_asset_tasks([t])
    m = unreal.load_asset(G + "/SM_" + name)
    m.set_material(0, mat)
    EAL.save_loaded_asset(m, False)
    return m


hedges = [import_mesh(n, M_LEAF) for n in ("HedgeA", "HedgeB", "HedgeC")]
ball = import_mesh("Ball", M_LEAF)
grass = import_mesh("Grass", M_GRASS)
hills = import_mesh("Hills", M)
log("imported")

NikScatter = unreal.load_class(None, "/Script/NobelKitchen.NikScatter")


def scatter(label, mesh, transforms, shadow=True, cull=0.0, collide=False):
    a = EAS.spawn_actor_from_class(NikScatter, V(0, 0, 0))
    a.set_actor_label(label)
    a.set_folder_path("Garden")
    a.tags = [unreal.Name("garden3")]
    a.set_editor_property("mesh", mesh)
    a.set_editor_property("instances", transforms)
    a.set_editor_property("cast_shadow", shadow)
    a.set_editor_property("cull_distance", cull)
    a.set_editor_property("collide", collide)
    a.rebuild()
    return a


def xf(x, y, z, yaw=0.0, s=(1.0, 1.0, 1.0)):
    return unreal.Transform(V(x, y, z), unreal.Rotator(0, 0, yaw), V(*s))


# hedge: the long sides run past the corners by half a thickness, the short sides fit between them
mods = [[], [], []]


def run(ax, ay, bx, by):
    L = math.hypot(bx - ax, by - ay)
    n = max(1, round(L / MOD))
    s = L / (n * MOD)
    yaw = math.degrees(math.atan2(by - ay, bx - ax))
    ux, uy = (bx - ax) / L, (by - ay) / L
    for k in range(n):
        x, y = ax + ux * k * MOD * s, ay + uy * k * MOD * s
        mods[rng.randrange(3)].append(xf(x, y, -2.0, yaw, (s, 1.0, rng.uniform(0.985, 1.015))))


run(X0 - T / 2, Y0, X1 + T / 2, Y0)
run(X0 - T / 2, Y1, X1 + T / 2, Y1)
run(X0, Y0 + T / 2, X0, Y1 - T / 2)
run(X1, Y0 + T / 2, X1, Y1 - T / 2)
for k, m in enumerate(hedges):
    scatter("Hedge3_%s" % "ABC"[k], m, mods[k])

# boxwood balls: pairs flanking the terrace beds, and a row along the lawn
balls = []
for y in (-1, 1):
    for x in (-250.0, 60.0, 370.0, 1130.0, 1440.0, 1750.0):
        s = rng.uniform(0.8, 1.05)
        balls.append(xf(x + rng.uniform(-10, 10), y * (650 + 200 + rng.uniform(-8, 8)), -3.0, rng.uniform(0, 360), (s, s, s)))
for x in (X0 + 160, X1 - 160):
    for y in (-420.0, 0.0, 420.0):
        s = rng.uniform(0.85, 1.1)
        balls.append(xf(x, y, -3.0, rng.uniform(0, 360), (s, s, s)))
scatter("Boxwood3", ball, balls)

# 3D lawn: blade clumps on a jittered grid, between the planted beds and the hedge, around the trees and balls
trees = [(a.get_actor_location().x, a.get_actor_location().y) for a in EAS.get_all_level_actors()
         if a.get_actor_label().startswith("Tree_")]
bx = [(t.translation.x, t.translation.y) for t in balls]
clumps, step = [], 11.0
x = X0 + T / 2 + 4
while x < X1 - T / 2 - 4:
    y = Y0 + T / 2 + 4
    while y < Y1 - T / 2 - 4:
        px, py = x + rng.uniform(-4.5, 4.5), y + rng.uniform(-4.5, 4.5)
        in_beds = -380 - 125 < px < 1880 + 125 and -650 - 125 < py < 650 + 125
        if not in_beds and all((px - a) ** 2 + (py - b) ** 2 > 45 ** 2 for a, b in bx) and \
                all((px - a) ** 2 + (py - b) ** 2 > 40 ** 2 for a, b in trees):
            s = rng.uniform(0.8, 1.2)
            clumps.append(xf(px, py, -3.0, rng.uniform(0, 360), (s, s, rng.uniform(0.85, 1.15))))
        y += step
    x += step
scatter("Lawn3D", grass, clumps, shadow=False)
log("lawn clumps", len(clumps))

# land
a = EAS.spawn_actor_from_object(hills, V(0, 0, 0))
a.set_actor_label("Hills")
a.set_folder_path("Garden")
a.tags = [unreal.Name("garden3")]

# trees: shadows only for the near ones (the forest far off needs none, and VSM pays per caster)
n_tree = 0
for mesh_name, pts in data["trees"].items():
    m = unreal.load_asset(FOL + mesh_name)
    if not m or not pts:
        continue
    near, far = [], []
    for x, y, z, yaw, s in pts:
        d = math.hypot(max(abs(x - CX) - (X1 - X0) / 2, 0), max(abs(y) - Y1, 0))
        (near if d < 4500 else far).append(xf(x, y, z, yaw, (s, s, s)))
    if near:
        scatter("Trees_%s_near" % mesh_name[3:], m, near, shadow=True)
    if far:
        scatter("Trees_%s_far" % mesh_name[3:], m, far, shadow=False)
    n_tree += len(pts)
log("trees", n_tree)

# ------------------------------------------------------------------ air
for f in [a for a in EAS.get_all_level_actors() if isinstance(a, unreal.ExponentialHeightFog)]:
    c = f.component
    c.set_editor_property("start_distance", 2500.0)
    c.set_editor_property("fog_height_falloff", 0.12)
    c.set_editor_property("fog_inscattering_luminance", unreal.LinearColor(0.42, 0.52, 0.66, 1.0))
for s in [a for a in EAS.get_all_level_actors() if isinstance(a, unreal.SkyAtmosphere)]:
    try:
        s.get_component_by_class(unreal.SkyAtmosphereComponent).set_editor_property("aerial_pespective_view_distance_scale", 3.0)
    except Exception as e:
        log("WARN aerial", e)
# the mown lawn under the blades: calmer, less saturated
lawn = unreal.load_asset("/Game/Nobel/Garden/MI_Lawn2")
MEL.set_material_instance_scalar_parameter_value(lawn, "Brightness", 0.46)
MEL.update_material_instance(lawn)
EAL.save_loaded_asset(lawn, False)
unreal.EditorLoadingAndSavingUtils.save_current_level()
log("done")
