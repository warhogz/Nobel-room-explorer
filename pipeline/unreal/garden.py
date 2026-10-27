"""Manicured garden around the room (in the open editor), from the Fab "Environment_Set" pack:
an even, dense lawn, a clipped 2 m hedge on the 5 m line and a row of poplars behind it as a wall of leaves.
Replaces the first courtyard's Poly Haven grass and shrubs (courtyard.py); its lawn plane, meadow, olive trees and
fog stay. Re-runnable: everything it makes is tagged "garden".
"""
import math
import random

import unreal

EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
SDS = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
SDL = unreal.SubobjectDataBlueprintFunctionLibrary
F = "/Game/Environment_Set/Environment/Foliage/Models/"
LT = "/Game/Environment_Set/Environment/Landscape/Textures/"
rng = random.Random(11)

FLOOR = (-380.0, 1880.0, -650.0, 650.0)  # the room's floor (cm)
OUT = 500.0  # hedge line, 5 m out
X0, X1, Y0, Y1 = FLOOR[0] - OUT, FLOOR[1] + OUT, FLOOR[2] - OUT, FLOOR[3] + OUT
GROUND_Z = -3.0
HEDGE_H, HEDGE_T = 200.0, 90.0  # clipped hedge: height, thickness
GRASS_PER_M2 = 140

for a in EAS.get_all_level_actors():
    if unreal.Name("garden") in a.tags or a.get_actor_label() in ("Lawn_Grass", "Hedge"):
        EAS.destroy_actor(a)


def tag(a, label):
    a.set_actor_label(label)
    a.set_folder_path("Garden")
    a.tags = [unreal.Name("garden")]
    return a


def mesh(name, nanite=False):
    m = unreal.load_asset(F + name)
    if nanite and not m.get_editor_property("nanite_settings").enabled:
        ns = m.get_editor_property("nanite_settings")
        ns.enabled = True
        m.set_editor_property("nanite_settings", ns)  # thousands of grass instances: Nanite instead of LODs
        EAL.save_loaded_asset(m, False)
    return m


def ism_actor(label, meshes, shadows=True):
    a = tag(EAS.spawn_actor_from_class(unreal.Actor, unreal.Vector(0, 0, 0)), label)
    root = SDS.k2_gather_subobject_data_for_instance(a)[0]
    if not SDL.get_object(SDL.get_data(root)):
        root, _ = SDS.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=root, new_class=unreal.SceneComponent))
    comps = []
    for m in meshes:
        h, _ = SDS.add_new_subobject(unreal.AddNewSubobjectParams(
            parent_handle=root, new_class=unreal.HierarchicalInstancedStaticMeshComponent))
        c = SDL.get_object(SDL.get_data(h))
        c.set_static_mesh(m)
        c.set_editor_property("mobility", unreal.ComponentMobility.STATIC)
        c.set_editor_property("cast_shadow", shadows)
        c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
        comps.append(c)
    return a, comps


def add(comp, loc, rot, s):
    comp.add_instance(unreal.Transform(loc, rot, unreal.Vector(s, s, s)), world_space=True)


def in_room(x, y, pad):
    return FLOOR[0] - pad < x < FLOOR[1] + pad and FLOOR[2] - pad < y < FLOOR[3] + pad


# ------------------------------------------------------------------ lawn ground: the pack's grass texture
def vt(t, srgb, normal=False):
    t.set_editor_property("virtual_texture_streaming", True)  # M_Nik samples virtual textures
    t.set_editor_property("srgb", srgb)
    if normal:
        t.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
    EAL.save_loaded_asset(t, False)
    return t


grass_bc = vt(unreal.load_asset(LT + "T_ground_forest_grass_01_0_BC_H"), True)
grass_n = vt(unreal.load_asset(LT + "T_ground_forest_grass_01_N"), False, normal=True)
for name, tint in (("MI_Lawn", (0.42, 0.78, 0.28)), ("MI_Meadow", (0.45, 0.72, 0.3))):
    mi = unreal.load_asset("/Game/Nobel/Courtyard/" + name)
    MEL.set_material_instance_texture_parameter_value(mi, "BaseColorTex", grass_bc)
    MEL.set_material_instance_texture_parameter_value(mi, "NormalTex", grass_n)
    MEL.set_material_instance_static_switch_parameter_value(mi, "UseRoughnessTex", False)
    MEL.set_material_instance_scalar_parameter_value(mi, "Roughness", 0.85)
    MEL.set_material_instance_vector_parameter_value(mi, "BaseTint", unreal.LinearColor(*tint, 1.0))
    MEL.update_material_instance(mi)
    EAL.save_loaded_asset(mi, False)

# ------------------------------------------------------------------ the lawn: dense, short, even
grass = [mesh("SM_grass_bush_simple_0%d" % i, nanite=True) for i in range(1, 6)]
_, gc = ism_actor("Lawn_Grass", grass, shadows=False)
area = ((X1 - X0 - 2 * HEDGE_T) * (Y1 - Y0 - 2 * HEDGE_T) - (FLOOR[1] - FLOOR[0]) * (FLOOR[3] - FLOOR[2])) / 1e4
n = 0
while n < int(area * GRASS_PER_M2):
    x = rng.uniform(X0 + HEDGE_T / 2, X1 - HEDGE_T / 2)
    y = rng.uniform(Y0 + HEDGE_T / 2, Y1 - HEDGE_T / 2)
    if in_room(x, y, 3):
        continue
    k = rng.randrange(len(grass))
    # mown: every clump cut to ~6 cm (the pack's clumps are 30 cm), slight lean
    add(gc[k], unreal.Vector(x, y, GROUND_Z), unreal.Rotator(rng.uniform(-6, 6), rng.uniform(-6, 6), rng.uniform(0, 360)),
        rng.uniform(0.13, 0.17))
    n += 1

# ------------------------------------------------------------------ clipped hedge: dark core + leafy skin
core_mi_path = "/Game/Nobel/Courtyard/MI_HedgeCore"
core_mi = unreal.load_asset(core_mi_path) or unreal.AssetToolsHelpers.get_asset_tools().create_asset(
    "MI_HedgeCore", "/Game/Nobel/Courtyard", unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
MEL.set_material_instance_parent(core_mi, unreal.load_asset("/Game/Nobel/Materials/M_Nik"))
MEL.set_material_instance_vector_parameter_value(core_mi, "BaseColor", unreal.LinearColor(0.02, 0.045, 0.015, 1))
MEL.set_material_instance_scalar_parameter_value(core_mi, "Roughness", 0.9)
MEL.set_material_instance_scalar_parameter_value(core_mi, "Specular", 0.2)
MEL.update_material_instance(core_mi)
EAL.save_loaded_asset(core_mi, False)
cube = unreal.load_asset("/Engine/BasicShapes/Cube")  # 100 cm, centred


def leaf_tex(name, normal=False):
    """copies of the pack's poplar leaf maps as virtual textures (the poplars keep the originals)"""
    dst = "/Game/Nobel/Courtyard/" + name.replace("T_Poplar", "T_Hedge")
    if not EAL.does_asset_exist(dst):
        EAL.duplicate_asset("/Game/Environment_Set/Environment/Foliage/Textures/" + name, dst)
    return vt(unreal.load_asset(dst), not normal, normal)


LEAF_BC, LEAF_N = leaf_tex("T_Poplar_leaves_BC"), leaf_tex("T_Poplar_leaves_N", normal=True)


def skin_mi(name, tile_u, tile_v):
    """clipped-hedge skin: the leaf atlas tiled over a box, alpha-tested, two-sided"""
    path = "/Game/Nobel/Courtyard/" + name
    mi = unreal.load_asset(path) or unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        name, "/Game/Nobel/Courtyard", unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    MEL.set_material_instance_parent(mi, unreal.load_asset("/Game/Nobel/Materials/M_Nik"))
    for k in ("UseBaseTex", "UseAlphaMask", "UseNormalTex"):
        MEL.set_material_instance_static_switch_parameter_value(mi, k, True)
    MEL.set_material_instance_texture_parameter_value(mi, "BaseColorTex", LEAF_BC)
    MEL.set_material_instance_texture_parameter_value(mi, "NormalTex", LEAF_N)
    MEL.set_material_instance_vector_parameter_value(mi, "BaseTint", unreal.LinearColor(0.75, 0.95, 0.6, 1))
    MEL.set_material_instance_scalar_parameter_value(mi, "TileU", tile_u)
    MEL.set_material_instance_scalar_parameter_value(mi, "TileV", tile_v)
    MEL.set_material_instance_scalar_parameter_value(mi, "Roughness", 0.7)
    MEL.set_material_instance_scalar_parameter_value(mi, "Specular", 0.35)
    o = mi.get_editor_property("base_property_overrides")
    o.set_editor_property("override_blend_mode", True); o.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
    o.set_editor_property("override_two_sided", True); o.set_editor_property("two_sided", True)
    o.set_editor_property("override_opacity_mask_clip_value", True); o.set_editor_property("opacity_mask_clip_value", 0.45)
    mi.set_editor_property("base_property_overrides", o)
    MEL.update_material_instance(mi)
    EAL.save_loaded_asset(mi, False)
    return mi


sides = ((X0, Y0, X1, Y0), (X1, Y0, X1, Y1), (X1, Y1, X0, Y1), (X0, Y1, X0, Y0))
n_leaf = 0
for i, (ax, ay, bx, by) in enumerate(sides):
    length = math.hypot(bx - ax, by - ay) + HEDGE_T
    dx, dy = (bx - ax) / (length - HEDGE_T), (by - ay) / (length - HEDGE_T)
    cx, cy = (ax + bx) / 2, (ay + by) / 2
    yaw = math.degrees(math.atan2(dy, dx))
    core = tag(EAS.spawn_actor_from_object(cube, unreal.Vector(cx, cy, GROUND_Z + HEDGE_H / 2 - 4)), "Hedge_Core_%d" % i)
    core.set_actor_rotation(unreal.Rotator(0, 0, yaw), False)
    core.set_actor_scale3d(unreal.Vector(length / 100, (HEDGE_T - 12) / 100, (HEDGE_H - 8) / 100))
    core.static_mesh_component.set_material(0, core_mi)
    # three leaf shells, each a little larger and tiled differently: a dense, clipped surface with depth
    for k, (grow, tk) in enumerate(((4, 1.0), (8, 1.13), (12, 1.29))):
        sk = tag(EAS.spawn_actor_from_object(cube, unreal.Vector(cx, cy, GROUND_Z + HEDGE_H / 2 - 4 + grow / 4)),
                 "Hedge_Skin_%d_%d" % (i, k))
        sk.set_actor_rotation(unreal.Rotator(0, 0, yaw), False)
        sk.set_actor_scale3d(unreal.Vector((length + grow) / 100, (HEDGE_T - 12 + grow) / 100, (HEDGE_H - 8 + grow / 2) / 100))
        # leaf atlas ~45 cm per repeat along the hedge and up its face
        sk.static_mesh_component.set_material(0, skin_mi("MI_HedgeSkin_%d_%d" % (i, k), length / 45 * tk, HEDGE_H / 45 * tk))
        sk.static_mesh_component.set_editor_property("cast_shadow", k == 2)
        n_leaf += 1

# ------------------------------------------------------------------ poplars behind the hedge: a wall of leaves
poplars = [mesh("SM_Poplar_01_Standalone"), mesh("SM_Poplar_03_Medium")]
_, pc = ism_actor("Poplars", poplars)
n_pop = 0
for (ax, ay, bx, by) in sides:
    length = math.hypot(bx - ax, by - ay)
    dx, dy = (bx - ax) / length, (by - ay) / length
    nx, ny = dy, -dx
    t = 0.0
    while t <= length:
        x = ax + dx * t + nx * 330 + rng.uniform(-40, 40)
        y = ay + dy * t + ny * 330 + rng.uniform(-40, 40)
        k = n_pop % 2
        add(pc[k], unreal.Vector(x, y, GROUND_Z - 5), unreal.Rotator(0, 0, rng.uniform(0, 360)), rng.uniform(0.85, 1.05))
        n_pop += 1
        t += 480.0

unreal.EditorLoadingAndSavingUtils.save_current_level()
print("garden: lawn %.0f m2, %d grass clumps, hedge %d leaf shells, %d poplars" % (area, n, n_leaf, n_pop))
