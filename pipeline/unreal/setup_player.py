"""First-person walker for the room level (in the open editor; Python remote execution or the Output Log).

The character is the UE 5.8 First Person template's (copied into the project: Content/FirstPerson, Characters, Input,
LevelPrototyping from Templates/TP_FirstPersonBP and TemplateResources/High), retuned for walking through an interior:
  - 1.5 m/s with a body's inertia (the template runs at 6 m/s and stops dead)
  - FOV 75 (90 distorts the architecture), arms hidden
  - natural head bob: the camera rides on the head of the hidden first-person mesh; the template stabilises that head
    with its warp rig (ABP_FP_Copy), so the mesh plays the plain walk cycle (ABP_Unarmed) instead: ~1 cm at walking pace
Dust motes: NS_DustMote copied from the template's Horror variant (Content/Variant_Horror/Blueprints/Light/Assets).
"""
import unreal

bp = unreal.load_asset("/Game/FirstPerson/Blueprints/BP_FirstPersonCharacter")
sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
L = unreal.SubobjectDataBlueprintFunctionLibrary
# head animation of the camera mesh: the template's stabilised first-person rig (no bob; the user found the walk-cycle
# bob too strong) - "/Game/Characters/Mannequins/Anims/Unarmed/ABP_Unarmed" gives ~1 cm of natural head bob
walk = unreal.BlueprintEditorLibrary.generated_class(unreal.load_asset("/Game/FirstPerson/Anims/ABP_FP_Copy"))
ALWAYS = unreal.VisibilityBasedAnimTickOption.ALWAYS_TICK_POSE_AND_REFRESH_BONES
for h in sds.k2_gather_subobject_data_for_blueprint(bp):
    o = L.get_object(L.get_data(h))
    if isinstance(o, unreal.CharacterMovementComponent):
        for k, v in (("max_walk_speed", 150.0), ("max_acceleration", 420.0), ("braking_deceleration_walking", 220.0),
                     ("ground_friction", 2.0), ("braking_friction_factor", 1.0), ("max_step_height", 25.0),
                     ("jump_z_velocity", 300.0)):
            o.set_editor_property(k, v)
    elif isinstance(o, unreal.CameraComponent):
        o.set_editor_property("field_of_view", 75.0)
    elif isinstance(o, unreal.SkeletalMeshComponent):
        o.set_editor_property("visibility_based_anim_tick_option", ALWAYS)  # hidden meshes must still animate
        if o.get_name().startswith("FirstPersonMesh"):
            o.set_editor_property("visible", False)
            o.set_editor_property("anim_class", walk)
        else:
            o.set_editor_property("cast_shadow", True)
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
unreal.EditorAssetLibrary.save_loaded_asset(bp, False)

world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
world.get_world_settings().set_editor_property("default_game_mode", unreal.BlueprintEditorLibrary.generated_class(
    unreal.load_asset("/Game/FirstPerson/Blueprints/BP_FirstPersonGameMode")))
unreal.EditorLoadingAndSavingUtils.save_current_level()
print("player ready")
