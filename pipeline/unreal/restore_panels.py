"""Put the real perforated bronze panels (49 meshes with 12.5 mm holes, build_room.py without NIK_UE_FLAT_PANELS) back
into Unreal (in the open editor; after export_ue.py): re-import the meshes, give them the ordinary M20309 brass MI.
The flat version (perf_panels.py, M_Nik_Perf) is kept as an option for weak machines."""
import os
import sys

import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.environ.get("NIK_PIPELINE", ""))
import importlib
import nik_ue  # noqa: E402
importlib.reload(nik_ue)
from nik_ue import GAME, SCENE, UE_DIR, mi_name  # noqa: E402

AT = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary
panels = [o for o in SCENE["objects"] if o["materials"] and all(
    SCENE["materials"][m].get("origName") == "Material #2147483647" for m in o["materials"])]
mid = next(k for k, v in SCENE["materials"].items() if v.get("origName") == "Material #2147483647")
mi = unreal.load_asset(GAME + "/Materials/Instances/" + mi_name(mid, SCENE["materials"][mid]))


def opts():
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
    return ui


tasks = []
for o in panels:
    t = unreal.AssetImportTask()
    t.filename = os.path.join(UE_DIR, o["fbx"])
    t.destination_path, t.destination_name = GAME + "/Meshes", o["name"]
    t.automated, t.replace_existing, t.save = True, True, False
    t.options = opts()
    tasks.append(t)
for i in range(0, len(tasks), 8):
    AT.import_asset_tasks(tasks[i:i + 8])
tris = 0
for o in panels:
    sm = unreal.load_asset(GAME + "/Meshes/" + o["name"])
    for k in range(len(sm.get_editor_property("static_materials"))):
        sm.set_material(k, mi)
    EAL.save_loaded_asset(sm, False)
    tris += o["faces"]
unreal.EditorLoadingAndSavingUtils.save_current_level()
print("panels restored: %d meshes, %d faces" % (len(panels), tris))
