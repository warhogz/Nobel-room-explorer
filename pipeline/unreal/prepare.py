"""Before the live run (commandlet, editor closed): textures, materials and IES profiles (build_assets.py on import)
and the empty level the editor opens at startup.

UnrealEditor-Cmd.exe NobelKitchen.uproject -run=pythonscript -script=<this file> -unattended
"""
import os
import sys

import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_assets  # noqa: F401,E402
from nik_ue import GAME  # noqa: E402

LEVEL = GAME + "/Maps/L_Kitchen"
if not unreal.EditorAssetLibrary.does_asset_exist(LEVEL):
    world = unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
    unreal.log("NIK level created: %s" % unreal.EditorLoadingAndSavingUtils.save_map(world, LEVEL))
unreal.log("NIK prepare done")
