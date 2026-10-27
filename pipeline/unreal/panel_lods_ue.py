"""Perforated bronze sheets without moire (in the open editor; after blender/panel_lods.py).

Each real sheet (12.5 mm holes, up to 137 k triangles) keeps its geometry up close; from ~4 m on it switches to a flat
stand-in whose holes are a mip-filtered mask (M_Nik_Perf). Sub-pixel holes are what rippled on the far walls: the mask
averages them into the right brightness instead. The sheets leave Nanite for this (Nanite has no LODs): only the few
sheets near the camera draw their full geometry.
Re-runnable.
"""
import json
import os

import unreal

ROOT = "C:/Users/hdog/Downloads/Telegram Desktop/NOBEL ISLAND KITCHEN (2)/NOBEL ISLAND KITCHEN/build/ue"
GAME = "/Game/Nobel"
DEST = GAME + "/Meshes/PanelLOD"
SWITCH_CM = 400.0
AT = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
SMES = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)


def log(*a):
    unreal.log("NIK panel_lods " + " ".join(str(x) for x in a))


scene = json.load(open(ROOT + "/scene.json", encoding="utf-8"))
perf = {k for k, v in scene["materials"].items() if v.get("origName") == "Material #2147483647"}
panels = [o["name"] for o in scene["objects"] if o["materials"] and set(o["materials"]) <= perf]

# the flat material: the same satin brass as the real sheets (nik_ue.TWEAKS), holes from the mask
mi = unreal.load_asset(GAME + "/Materials/Instances/MI_Perforated_Bronze")
S = lambda k, v: MEL.set_material_instance_scalar_parameter_value(mi, k, float(v))
S("TileU", 0.0125 / 0.6)  # UV 1 = one hole tile; the brass texture repeats every 0.6 m
S("TileV", 0.013 / 0.6)
S("Metallic", 0.6)
S("RoughMin", 0.42)
S("RoughContrast", 0.0)
S("HoleDark", 0.1)
MEL.set_material_instance_vector_parameter_value(mi, "BaseTint", unreal.LinearColor(2.06, 2.3, 2.48, 1.0))
MEL.update_material_instance(mi)
EAL.save_loaded_asset(mi, False)

ui = unreal.FbxImportUI()
ui.import_materials = False
ui.import_textures = False
ui.import_animations = False
ui.import_as_skeletal = False
ui.mesh_type_to_import = unreal.FBXImportType.FBXIT_STATIC_MESH
d = ui.static_mesh_import_data
d.combine_meshes = True
d.generate_lightmap_u_vs = False
d.auto_generate_collision = False
d.build_nanite = False
d.normal_import_method = unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS
d.remove_degenerates = False
unreal.SystemLibrary.execute_console_command(None, "Interchange.FeatureFlags.Import.FBX False")
tasks = []
for name in panels:
    t = unreal.AssetImportTask()
    t.filename = "%s/panel_lods/%s_Flat.fbx" % (ROOT, name)
    t.destination_path, t.destination_name = DEST, name + "_Flat"
    t.automated, t.replace_existing, t.save = True, True, False
    t.options = ui
    tasks.append(t)
AT.import_asset_tasks(tasks)

done = 0
for name in panels:
    flat = unreal.load_asset("%s/%s_Flat" % (DEST, name))
    sm = unreal.load_asset("%s/Meshes/%s" % (GAME, name))
    if not flat or not sm:
        log("WARN missing", name, bool(flat), bool(sm))
        continue
    flat.set_material(0, mi)
    ns = sm.get_editor_property("nanite_settings")
    ns.set_editor_property("enabled", False)
    sm.set_editor_property("nanite_settings", ns)
    if SMES.set_lod_from_static_mesh(sm, 1, flat, 0, False) < 0:
        log("WARN lod failed", name)
        continue
    r = sm.get_bounds().sphere_radius
    near = min(1.0, 2.3 * r / SWITCH_CM)  # screen size of the sheet at SWITCH_CM (FOV 75)
    try:
        SMES.set_lod_screen_sizes(sm, [1.0, near])
    except Exception:
        sm.set_editor_property("auto_compute_lod_screen_size", False)
        models = sm.get_editor_property("source_models")
        for i, sc in enumerate((1.0, near)):
            ss = models[i].get_editor_property("screen_size")
            ss.set_editor_property("default", sc)
            models[i].set_editor_property("screen_size", ss)
        sm.set_editor_property("source_models", models)
    EAL.save_loaded_asset(sm, False)
    EAL.save_loaded_asset(flat, False)
    done += 1
log("done", done, "of", len(panels))
