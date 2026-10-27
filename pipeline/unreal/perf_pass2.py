"""Second performance / crispness pass (in the open editor): texture filtering and pools, glass casts no shadow.

Same cvars as in DefaultEngine.ini (applied live here). Glass meshes (windows, glassware, the chandelier) are non-Nanite:
in a virtual shadow map each one is rendered again per page - and a window pane or a glass casts no useful shadow.
"""
import os
import sys

import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.environ.get("NIK_PIPELINE", ""))
from nik_ue import SCENE  # noqa: E402

for c in ("r.VT.AnisotropicFiltering 1", "r.MaxAnisotropy 16", "r.Streaming.PoolSize 3500", "r.VT.PoolSizeScale 3",
          "r.ScreenPercentage.Default.Desktop.Mode 0", "r.ScreenPercentage.Default 85"):
    unreal.SystemLibrary.execute_console_command(None, c)
glass = {k for k, v in SCENE["materials"].items() if v.get("transmission") or (v.get("flags") or {}).get("glass")}
want = {o["name"][3:] for o in SCENE["objects"] if o["materials"] and all(m in glass for m in o["materials"])}
n = 0
for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
    if a.get_actor_label() in want:
        a.get_component_by_class(unreal.StaticMeshComponent).set_editor_property("cast_shadow", False)
        n += 1
unreal.EditorLoadingAndSavingUtils.save_current_level()
print("glass actors without shadows: %d of %d" % (n, len(want)))
