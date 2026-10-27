"""Courtyard around the cropped room (in the open editor): lawn, a hedge wall 5 m out, a few trees, light shafts.

Assets: CC0 Poly Haven models imported to /Game/Nobel/Courtyard (grass_medium_01, grass_bermuda_01, shrub_02,
island_tree_01/02, texture leafy_grass), downloaded to build/ue/polyhaven. Rebuilds everything tagged "courtyard".
"""
import math
import random

import unreal

EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
SDS = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
SDL = unreal.SubobjectDataBlueprintFunctionLibrary
C = "/Game/Nobel/Courtyard"
rng = random.Random(7)

# the room's floor (cm): the lawn reaches 5 m beyond it, the hedge stands on that line
FLOOR = (-380.0, 1880.0, -650.0, 650.0)
OUT = 500.0
X0, X1, Y0, Y1 = FLOOR[0] - OUT, FLOOR[1] + OUT, FLOOR[2] - OUT, FLOOR[3] + OUT
GROUND_Z = -3.0  # just under the travertine (the floors cover the lawn inside)

for a in EAS.get_all_level_actors():
    if unreal.Name("courtyard") in a.tags:
        EAS.destroy_actor(a)


def mesh(path):
    m = unreal.load_asset(path)
    if m is None:
        raise RuntimeError("missing " + path)
    return m


def tag(a, label, folder="Courtyard"):
    a.set_actor_label(label)
    a.set_folder_path(folder)
    a.tags = [unreal.Name("courtyard")]
    return a


# ------------------------------------------------------------------ lawn material (leafy_grass, 2 m repeat)
def tex(name, srgb, normal=False):
    t = unreal.load_asset("%s/leafy_grass/%s" % (C, name))
    t.set_editor_property("virtual_texture_streaming", True)  # M_Nik samples virtual textures
    t.set_editor_property("srgb", srgb)
    if normal:
        t.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
        t.set_editor_property("flip_green_channel", True)  # Poly Haven nor_gl = OpenGL
    EAL.save_loaded_asset(t, False)
    return t


def lawn_mi(name, tile_u, tile_v, tint):
    path = C + "/" + name
    mi = unreal.load_asset(path) or unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        name, C, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    MEL.set_material_instance_parent(mi, unreal.load_asset("/Game/Nobel/Materials/M_Nik"))
    for k, v in (("UseBaseTex", True), ("UseRoughnessTex", True), ("UseNormalTex", True)):
        MEL.set_material_instance_static_switch_parameter_value(mi, k, v)
    MEL.set_material_instance_texture_parameter_value(mi, "BaseColorTex", BASE)
    MEL.set_material_instance_texture_parameter_value(mi, "RoughnessTex", ROUGH)
    MEL.set_material_instance_texture_parameter_value(mi, "NormalTex", NRM)
    MEL.set_material_instance_scalar_parameter_value(mi, "TileU", tile_u)
    MEL.set_material_instance_scalar_parameter_value(mi, "TileV", tile_v)
    MEL.set_material_instance_vector_parameter_value(mi, "BaseTint", unreal.LinearColor(*tint, 1.0))
    MEL.set_material_instance_scalar_parameter_value(mi, "Specular", 0.35)
    MEL.update_material_instance(mi)
    EAL.save_loaded_asset(mi, False)
    return mi


BASE = tex("leafy_grass_diff_4k", True)
ROUGH = tex("leafy_grass_rough_4k", False)
NRM = tex("leafy_grass_nor_gl_4k", False, normal=True)
PLANE = mesh("/Engine/BasicShapes/Plane")  # 100 x 100 cm, UV 0..1

w, h = X1 - X0, Y1 - Y0
lawn = tag(EAS.spawn_actor_from_object(PLANE, unreal.Vector((X0 + X1) / 2, (Y0 + Y1) / 2, GROUND_Z)), "Lawn")
lawn.set_actor_scale3d(unreal.Vector(w / 100, h / 100, 1))
lawn.static_mesh_component.set_material(0, lawn_mi("MI_Lawn", w / 200, h / 200, (0.95, 1.0, 0.9)))
# beyond the hedge: meadow to the horizon (no dark planet ground in the high windows)
far = tag(EAS.spawn_actor_from_object(PLANE, unreal.Vector((X0 + X1) / 2, 0, GROUND_Z - 5)), "Meadow")
far.set_actor_scale3d(unreal.Vector(600, 600, 1))
far.static_mesh_component.set_material(0, lawn_mi("MI_Meadow", 150, 150, (0.85, 0.9, 0.75)))


# ------------------------------------------------------------------ instanced foliage
def ism_actor(label, meshes):
    """one actor, one hierarchical ISM component per mesh variant"""
    a = tag(EAS.spawn_actor_from_class(unreal.Actor, unreal.Vector(0, 0, 0)), label)
    root = SDS.k2_gather_subobject_data_for_instance(a)[0]
    if not SDL.get_object(SDL.get_data(root)):
        root_handle, _ = SDS.add_new_subobject(unreal.AddNewSubobjectParams(
            parent_handle=root, new_class=unreal.SceneComponent))
        root = root_handle
    comps = []
    for m in meshes:
        hnd, fail = SDS.add_new_subobject(unreal.AddNewSubobjectParams(
            parent_handle=root, new_class=unreal.HierarchicalInstancedStaticMeshComponent))
        c = SDL.get_object(SDL.get_data(hnd))
        c.set_static_mesh(m)
        c.set_editor_property("mobility", unreal.ComponentMobility.STATIC)
        comps.append(c)
    return a, comps


def centre(m):
    """mesh bounds centre on the ground (the Poly Haven variants keep their layout offsets)"""
    b = m.get_bounding_box()
    return unreal.Vector((b.min.x + b.max.x) / 2, (b.min.y + b.max.y) / 2, b.min.z)


def put(comp, m, x, y, z, yaw, s):
    c = centre(m)
    r = math.radians(yaw)
    # rotate/scale the mesh around its own footprint centre, then place that centre at (x, y, z)
    ox = (c.x * math.cos(r) - c.y * math.sin(r)) * s
    oy = (c.x * math.sin(r) + c.y * math.cos(r)) * s
    t = unreal.Transform(unreal.Vector(x - ox, y - oy, z - c.z * s), unreal.Rotator(0, 0, yaw), unreal.Vector(s, s, s))
    comp.add_instance(t, world_space=True)


def inside_floor(x, y, pad=0.0):
    return FLOOR[0] - pad < x < FLOOR[1] + pad and FLOOR[2] - pad < y < FLOOR[3] + pad


# lawn: grass clumps over the whole courtyard (dense, random size / yaw)
gm = "%s/grass_medium_01/grass_medium_01_2k/StaticMeshes/grass_medium_01_%s_LOD0"
grass_meshes = [mesh(gm % (C, v)) for v in ("large_a", "large_b", "large_c", "mid_a", "mid_b", "mid_c", "small_a", "small_b",
                                       "tall_a", "tall_b", "tall_c")]
_, gcomps = ism_actor("Lawn_Grass", grass_meshes)
area_m2 = ((X1 - X0) * (Y1 - Y0) - (FLOOR[1] - FLOOR[0]) * (FLOOR[3] - FLOOR[2])) / 1e4
n_grass = int(area_m2 * 16)
placed = 0
while placed < n_grass:
    x, y = rng.uniform(X0 + 60, X1 - 60), rng.uniform(Y0 + 60, Y1 - 60)
    if inside_floor(x, y, 5):
        continue
    k = rng.randrange(len(grass_meshes))
    put(gcomps[k], grass_meshes[k], x, y, GROUND_Z, rng.uniform(0, 360), rng.uniform(0.8, 1.4))
    placed += 1

# hedge: two staggered rows of big shrubs on the 5 m line, ~2.6 m high
sm = "%s/shrub_02/shrub_02_2k/StaticMeshes/shrub_02_%s"
shrubs = [mesh(sm % (C, v)) for v in "abcd"]
_, scomps = ism_actor("Hedge", shrubs)
n_shrub = 0
for (ax, ay, bx, by) in ((X0, Y0, X1, Y0), (X1, Y0, X1, Y1), (X1, Y1, X0, Y1), (X0, Y1, X0, Y0)):
    length = math.hypot(bx - ax, by - ay)
    nx, ny = (by - ay) / length, -(bx - ax) / length  # outward normal
    for row, off in ((0, 0.0), (1, 55.0)):
        steps = int(length / 75)
        for i in range(steps + 1):
            t = (i + 0.5 * row) / steps
            x = ax + (bx - ax) * t + nx * off + rng.uniform(-12, 12)
            y = ay + (by - ay) * t + ny * off + rng.uniform(-12, 12)
            k = rng.randrange(4)
            put(scomps[k], shrubs[k], x, y, GROUND_Z, rng.uniform(0, 360), rng.uniform(1.55, 1.95))
            n_shrub += 1

# trees where the windows look out: south (glass doors), north facade, the hall's end window
trees = [("island_tree_01", 900, Y0 + 260, 20, 1.15), ("island_tree_02", X1 - 250, -380, 140, 1.25),
         ("island_tree_01", 450, Y1 - 270, 250, 1.0), ("island_tree_02", 1500, Y1 - 240, 70, 1.1)]
for name, x, y, yaw, s in trees:
    m = mesh("%s/%s/%s_2k/StaticMeshes/%s_2k" % (C, name, name, name))
    a = tag(EAS.spawn_actor_from_object(m, unreal.Vector(0, 0, 0)), "Tree_" + name)
    c = centre(m)
    a.set_actor_scale3d(unreal.Vector(s, s, s))
    a.set_actor_rotation(unreal.Rotator(0, 0, yaw), False)
    r = math.radians(yaw)
    a.set_actor_location(unreal.Vector(x - (c.x * math.cos(r) - c.y * math.sin(r)) * s,
                                       y - (c.x * math.sin(r) + c.y * math.cos(r)) * s, GROUND_Z - c.z * s), False, False)

# ------------------------------------------------------------------ light shafts: volumetric fog lit by the sun
fog = tag(EAS.spawn_actor_from_class(unreal.ExponentialHeightFog, unreal.Vector(0, 0, 0)), "Fog_LightShafts", "Lights/env")
fc = fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
fc.set_editor_property("fog_density", 0.004)
fc.set_editor_property("fog_height_falloff", 0.35)
fc.set_editor_property("enable_volumetric_fog", True)
fc.set_editor_property("volumetric_fog_scattering_distribution", 0.6)  # forward scattering: beams toward the sun
fc.set_editor_property("volumetric_fog_extinction_scale", 1.4)
fc.set_editor_property("fog_inscattering_luminance", unreal.LinearColor(0.0, 0.0, 0.0, 1.0))
for a in EAS.get_all_level_actors():
    if isinstance(a, unreal.DirectionalLight):
        a.get_component_by_class(unreal.DirectionalLightComponent).set_editor_property("volumetric_scattering_intensity", 2.0)
    elif isinstance(a, (unreal.PointLight, unreal.RectLight, unreal.SpotLight)):
        lc = a.get_component_by_class(unreal.LocalLightComponent)
        lc.set_editor_property("volumetric_scattering_intensity", 0.0)  # 250 lamps in fog: cost and haze

unreal.EditorLoadingAndSavingUtils.save_current_level()
print("courtyard: lawn %.0f m2, grass %d, shrubs %d, trees %d" % (area_m2, placed, n_shrub, len(trees)))
