"""Garden v2 (in the open editor): a mown lawn with stripes, a clipped hedge ring 5 m out, boxwood balls. Cheap by design:
  - lawn: one plane + a world-space material (grass texture at two scales, macro patches, mowing stripes): no foliage
  - hedge: ONE Nanite opaque mesh (garden_mesh.py: rounded profile, real lumps) with a layered-leaf texture: no alpha,
    no instances; collision from four invisible boxes
  - boxwood balls: the same leaf material on Nanite spheres
Inputs: build/ue/garden/{Hedge,Ball}.fbx + tex/*.png (garden_mesh.py, garden_textures.py). Re-runnable (tag "garden2").
"""
import math
import os
import random

import unreal

ROOT = "C:/Users/hdog/Downloads/Telegram Desktop/NOBEL ISLAND KITCHEN (2)/NOBEL ISLAND KITCHEN/build/ue/garden"
G = "/Game/Nobel/Garden"
AT = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
MP = unreal.MaterialProperty
VT = unreal.MaterialSamplerType
rng = random.Random(21)
X0, X1, Y0, Y1 = -880.0, 2380.0, -1150.0, 1150.0  # hedge centre line (garden_mesh.py)
FLOOR = (-380.0, 1880.0, -650.0, 650.0)


def log(*a):
    unreal.log("NIK garden2 " + " ".join(str(x) for x in a))


for a in list(EAS.get_all_level_actors()):
    if unreal.Name("garden2") in a.tags:
        EAS.destroy_actor(a)


# ------------------------------------------------------------------ textures
def tex(name, fname, srgb, normal=False, virtual=False, masks=False):
    t = unreal.AssetImportTask()
    t.filename, t.destination_path, t.destination_name = "%s/tex/%s" % (ROOT, fname), G, name
    t.automated, t.replace_existing, t.save = True, True, True
    AT.import_asset_tasks([t])
    x = unreal.load_asset(G + "/" + name)
    x.set_editor_property("virtual_texture_streaming", virtual)
    x.set_editor_property("srgb", srgb)
    x.set_editor_property("flip_green_channel", normal)  # generated as OpenGL, Unreal wants DirectX
    x.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP if normal else
                          (unreal.TextureCompressionSettings.TC_MASKS if masks else unreal.TextureCompressionSettings.TC_DEFAULT))
    x.set_editor_property("filter", unreal.TextureFilter.TF_DEFAULT)
    EAL.save_loaded_asset(x, False)
    return x


LAWN_BC = tex("T_Lawn_BC", "lawn_bc.png", True)
LAWN_N = tex("T_Lawn_N", "lawn_n.png", False, normal=True)
MACRO = tex("T_Lawn_Macro", "macro.png", False, masks=True)
HEDGE_BC = tex("T_Hedge_BC", "hedge_bc.png", True, virtual=True)  # M_Nik samples virtual textures
HEDGE_N = tex("T_Hedge_N", "hedge_n.png", False, normal=True, virtual=True)


# ------------------------------------------------------------------ lawn master material
def node(m, cls, x, y, **props):
    e = MEL.create_material_expression(m, cls, x, y)
    for k, v in props.items():
        e.set_editor_property(k, v)
    return e


def link(a, aout, b, bin_):
    if not MEL.connect_material_expressions(a, aout, b, bin_):
        log("WARN link failed", a.get_name(), aout, "->", b.get_name(), bin_)


def load_or_create(name, folder, cls, factory):
    return unreal.load_asset(folder + "/" + name) or AT.create_asset(name, folder, cls, factory)


M = load_or_create("M_Nik_Lawn", G, unreal.Material, unreal.MaterialFactoryNew())
MEL.delete_all_material_expressions(M)
wp = node(M, unreal.MaterialExpressionWorldPosition, -1700, 0)
xy = node(M, unreal.MaterialExpressionComponentMask, -1500, 0, r=True, g=True, b=False, a=False)
link(wp, "", xy, "")
uv1 = node(M, unreal.MaterialExpressionDivide, -1300, 0, const_b=150.0)  # the texture covers 1.5 m
link(xy, "", uv1, "A")
uv2 = node(M, unreal.MaterialExpressionMultiply, -1300, 150, const_b=0.41)
link(uv1, "", uv2, "A")
uvm = node(M, unreal.MaterialExpressionDivide, -1300, 300, const_b=3500.0)  # macro patches ~35 m
link(xy, "", uvm, "A")


def smp(cls, tex_, stype, uv, x, y, name=None):
    props = dict(texture=tex_, sampler_type=stype)
    if name:
        props["parameter_name"] = name
    s = node(M, cls, x, y, **props)
    link(uv, "", s, "UVs")
    return s


cA = smp(unreal.MaterialExpressionTextureSampleParameter2D, LAWN_BC, VT.SAMPLERTYPE_COLOR, uv1, -1000, -250, "LawnBC")
cB = smp(unreal.MaterialExpressionTextureSample, LAWN_BC, VT.SAMPLERTYPE_COLOR, uv2, -1000, -50)
nA = smp(unreal.MaterialExpressionTextureSampleParameter2D, LAWN_N, VT.SAMPLERTYPE_NORMAL, uv1, -1000, 200, "LawnN")
nB = smp(unreal.MaterialExpressionTextureSample, LAWN_N, VT.SAMPLERTYPE_NORMAL, uv2, -1000, 400)
mc = smp(unreal.MaterialExpressionTextureSampleParameter2D, MACRO, VT.SAMPLERTYPE_MASKS, uvm, -1000, 650, "Macro")
mix_c = node(M, unreal.MaterialExpressionLinearInterpolate, -700, -150, const_alpha=0.35)
link(cA, "RGB", mix_c, "A")
link(cB, "RGB", mix_c, "B")
patch = node(M, unreal.MaterialExpressionLinearInterpolate, -700, 600)
a_ = node(M, unreal.MaterialExpressionConstant3Vector, -950, 780, constant=unreal.LinearColor(0.80, 0.92, 0.68, 1))
b_ = node(M, unreal.MaterialExpressionConstant3Vector, -950, 880, constant=unreal.LinearColor(1.12, 1.05, 0.86, 1))
link(a_, "", patch, "A")
link(b_, "", patch, "B")
link(mc, "R", patch, "Alpha")
# mowing stripes: 2.4 m wide, alternating lighter / darker (the blades lean the other way)
sx = node(M, unreal.MaterialExpressionComponentMask, -1500, 500, r=True, g=False, b=False, a=False)
link(wp, "", sx, "")
dv = node(M, unreal.MaterialExpressionDivide, -1300, 500, const_b=480.0)
link(sx, "", dv, "A")
fr = node(M, unreal.MaterialExpressionFrac, -1150, 500)
link(dv, "", fr, "")
t2 = node(M, unreal.MaterialExpressionMultiply, -1000, 500, const_b=2.0)
link(fr, "", t2, "A")
t1 = node(M, unreal.MaterialExpressionSubtract, -850, 500, const_b=1.0)
link(t2, "", t1, "A")
ab = node(M, unreal.MaterialExpressionAbs, -700, 500)
link(t1, "", ab, "")
ss = node(M, unreal.MaterialExpressionSmoothStep, -550, 500, const_min=0.38, const_max=0.62)
link(ab, "", ss, "Value")
stripe = node(M, unreal.MaterialExpressionLinearInterpolate, -400, 500, const_a=0.80, const_b=1.12)
link(ss, "", stripe, "Alpha")
col = node(M, unreal.MaterialExpressionMultiply, -300, -50)
link(mix_c, "", col, "A")
link(patch, "", col, "B")
col2 = node(M, unreal.MaterialExpressionMultiply, -150, 0)
link(col, "", col2, "A")
link(stripe, "", col2, "B")
bright = node(M, unreal.MaterialExpressionScalarParameter, -150, 120, parameter_name="Brightness", default_value=0.62)  # strong sun: a lawn albedo of ~0.1 reads neon green at 1.0
col3 = node(M, unreal.MaterialExpressionMultiply, 0, 0)
link(col2, "", col3, "A")
link(bright, "", col3, "B")
MEL.connect_material_property(col3, "", MP.MP_BASE_COLOR)
nmix = node(M, unreal.MaterialExpressionLinearInterpolate, -700, 300, const_alpha=0.35)
link(nA, "RGB", nmix, "A")
link(nB, "RGB", nmix, "B")
flat = node(M, unreal.MaterialExpressionConstant3Vector, -700, 450, constant=unreal.LinearColor(0, 0, 1, 1))
nstr = node(M, unreal.MaterialExpressionLinearInterpolate, -500, 330)
link(flat, "", nstr, "A")
link(nmix, "", nstr, "B")
link(node(M, unreal.MaterialExpressionScalarParameter, -700, 560, parameter_name="NormalStrength", default_value=0.9), "", nstr, "Alpha")
MEL.connect_material_property(nstr, "", MP.MP_NORMAL)
MEL.connect_material_property(node(M, unreal.MaterialExpressionConstant, 0, 150, r=0.9), "", MP.MP_ROUGHNESS)
MEL.connect_material_property(node(M, unreal.MaterialExpressionConstant, 0, 230, r=0.32), "", MP.MP_SPECULAR)
log("lawn master:", MEL.recompile_material(M))
EAL.save_loaded_asset(M, False)

lawn_mi = load_or_create("MI_Lawn2", G, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
MEL.set_material_instance_parent(lawn_mi, M)
MEL.update_material_instance(lawn_mi)
EAL.save_loaded_asset(lawn_mi, False)

# ------------------------------------------------------------------ hedge / boxwood material (M_Nik, leaf texture)
nik = unreal.load_asset("/Game/Nobel/Materials/M_Nik")
leaf = load_or_create("MI_Leaves", G, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
MEL.set_material_instance_parent(leaf, nik)
for k in ("UseBaseTex", "UseNormalTex"):
    MEL.set_material_instance_static_switch_parameter_value(leaf, k, True)
MEL.set_material_instance_texture_parameter_value(leaf, "BaseColorTex", HEDGE_BC)
MEL.set_material_instance_texture_parameter_value(leaf, "NormalTex", HEDGE_N)
for k, v in (("TileU", 1.0), ("TileV", 1.0), ("Roughness", 0.9), ("Specular", 0.22), ("NormalStrength", 1.3)):
    MEL.set_material_instance_scalar_parameter_value(leaf, k, v)
MEL.set_material_instance_vector_parameter_value(leaf, "BaseTint", unreal.LinearColor(0.42, 0.52, 0.38, 1.0))  # deep, muted green
MEL.update_material_instance(leaf)
EAL.save_loaded_asset(leaf, False)
log("MI instr: lawn", MEL.get_statistics(lawn_mi).num_pixel_shader_instructions, "leaves", MEL.get_statistics(leaf).num_pixel_shader_instructions)

# ------------------------------------------------------------------ meshes
unreal.SystemLibrary.execute_console_command(None, "Interchange.FeatureFlags.Import.FBX False")


def import_mesh(name):
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
    t = unreal.AssetImportTask()
    t.filename, t.destination_path, t.destination_name = "%s/%s.fbx" % (ROOT, name), G, "SM_" + name
    t.automated, t.replace_existing, t.save = True, True, False
    t.options = ui
    AT.import_asset_tasks([t])
    m = unreal.load_asset(G + "/SM_" + name)
    m.set_material(0, leaf)
    EAL.save_loaded_asset(m, False)
    b = m.get_bounding_box()
    log(name, "bounds", [round(v) for v in b.min.to_tuple()], [round(v) for v in b.max.to_tuple()])
    return m


hedge_mesh, ball_mesh = import_mesh("Hedge"), import_mesh("Ball")


def tag(a, label):
    a.set_actor_label(label)
    a.set_folder_path("Garden")
    a.tags = [unreal.Name("garden2")]
    return a


tag(EAS.spawn_actor_from_object(hedge_mesh, unreal.Vector(0, 0, 0)), "Hedge_Ring")
# the walker must not pass through it: four invisible boxes (a Nanite mesh with 450 k triangles is no collision shape)
cube = unreal.load_asset("/Engine/BasicShapes/Cube")
for i, (cx, cy, lx, ly) in enumerate((((X0 + X1) / 2, Y0, X1 - X0 + 100, 90.0), ((X0 + X1) / 2, Y1, X1 - X0 + 100, 90.0),
                                      (X0, (Y0 + Y1) / 2, 90.0, Y1 - Y0 + 100), (X1, (Y0 + Y1) / 2, 90.0, Y1 - Y0 + 100))):
    a = tag(EAS.spawn_actor_from_object(cube, unreal.Vector(cx, cy, 115.0)), "Hedge_Collision_%d" % i)
    a.set_actor_scale3d(unreal.Vector(lx / 100, ly / 100, 2.3))
    c = a.get_component_by_class(unreal.StaticMeshComponent)
    c.set_editor_property("visible", False)
    c.set_editor_property("cast_shadow", False)
    c.set_collision_profile_name("BlockAll")

# boxwood balls on both long sides of the building, away from the trees
trees = [(a.get_actor_location().x, a.get_actor_location().y) for a in EAS.get_all_level_actors()
         if a.get_actor_label().startswith("Tree_")]
n_ball = 0
for side in (-1, 1):
    x = -250.0
    while x < 1850.0:
        y = side * (FLOOR[3] + 190 + rng.uniform(-25, 25))
        if all(math.hypot(x - tx, y - ty) > 320 for tx, ty in trees):
            a = tag(EAS.spawn_actor_from_object(ball_mesh, unreal.Vector(x + rng.uniform(-15, 15), y, -3)), "Boxwood_%d" % n_ball)
            s = rng.uniform(0.62, 1.0)
            a.set_actor_scale3d(unreal.Vector(s, s, s * rng.uniform(0.92, 1.05)))
            a.set_actor_rotation(unreal.Rotator(0, 0, rng.uniform(0, 360)), False)
            a.get_component_by_class(unreal.StaticMeshComponent).set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
            n_ball += 1
        x += 290.0 + rng.uniform(-30, 30)

# ------------------------------------------------------------------ ground planes get the lawn
for a in EAS.get_all_level_actors():
    if a.get_actor_label() in ("Lawn", "Meadow"):
        a.get_component_by_class(unreal.StaticMeshComponent).set_material(0, lawn_mi)
unreal.EditorLoadingAndSavingUtils.save_current_level()
log("done: hedge ring + %d boxwood balls" % n_ball)
