"""Performance pass (in the open editor) after garden v2 dropped the game to ~15 fps.

- the hedge shells and the 24 poplars go (non-Nanite alpha-tested foliage over a huge shadow area: VSM marking
  overflow, overdraw); the lawn plane and the olive trees stay
- no front-layer translucency reflections (the 1.8 M-triangle glass chandelier), coarser volumetric fog grid,
  Lumen one step down, a little sharpening against the TSR softness
(M_Reveal's off switch past the intro is built in experience_assets.py)
"""
import unreal

EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
MEL = unreal.MaterialEditingLibrary
CVARS = {
    "r.Lumen.TranslucencyReflections.FrontLayer.Enable": "0",
    "r.VolumetricFog.GridPixelSize": "16",
    "r.VolumetricFog.GridSizeZ": "64",
    "r.Tonemapper.Sharpen": "0.6",
}
for k, v in CVARS.items():
    unreal.SystemLibrary.execute_console_command(None, "%s %s" % (k, v))

gone = 0
for a in EAS.get_all_level_actors():
    lbl = a.get_actor_label()
    if unreal.Name("garden") in a.tags and (lbl.startswith("Hedge") or lbl == "Poplars"):
        EAS.destroy_actor(a)
        gone += 1

pp = [a for a in EAS.get_all_level_actors() if isinstance(a, unreal.PostProcessVolume)][0]
s = pp.settings
for k, v in (("lumen_final_gather_quality", 1.0), ("lumen_scene_detail", 1.0), ("lumen_reflection_quality", 1.0)):
    s.set_editor_property("override_" + k, True)
    s.set_editor_property(k, v)
pp.settings = s

unreal.EditorLoadingAndSavingUtils.save_current_level()
print("perf pass: removed %d garden actors" % gone)
