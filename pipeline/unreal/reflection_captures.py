"""Reflection captures for the light quality tier (laptops, integrated graphics: no Lumen). Lumen ignores them, so the
other tiers are unchanged; without them the metal and stone would mirror only the sky light. A grid of sphere captures
at eye height over the kitchen and the hall floors (x -380..1880 cm, y -650..650). Re-runnable (replaces its own).
"""
import unreal

EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in EAS.get_all_level_actors():
    if isinstance(a, unreal.SphereReflectionCapture) and a.get_actor_label().startswith("NIK_Refl"):
        EAS.destroy_actor(a)
n = 0
for x in (-180, 220, 620, 1020, 1420, 1780):
    for y in (-380, 0, 380):
        a = EAS.spawn_actor_from_class(unreal.SphereReflectionCapture, unreal.Vector(x, y, 150))
        a.set_actor_label("NIK_Refl_%d_%d" % (x, y))
        a.set_folder_path("Experience/Reflections")
        a.capture_component.set_editor_property("influence_radius", 560.0)
        n += 1
unreal.EditorLevelLibrary.build_reflection_captures() if hasattr(unreal.EditorLevelLibrary, "build_reflection_captures") else None
unreal.EditorLoadingAndSavingUtils.save_current_level()
unreal.log("NIK reflection captures %d" % n)
