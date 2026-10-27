"""Real-time mode without ray tracing (in the open editor): software Lumen, no MegaLights, cheap local lights.

- Lumen GI / reflections from distance fields + screen traces (no hardware ray tracing)
- MegaLights off: shadows (virtual shadow maps) only on the brightest SHADOW_LIGHTS lights - the small LED strips and
  uplights cast no visible shadow anyway; attenuation radius from each light's intensity (was 30 m for every light)
The project config gets the same cvars (Config/DefaultEngine.ini [ConsoleVariables]); ray tracing support stays
compiled in, so the path tracer can still be switched on for stills (r.RayTracing.Enable 1).
"""
import math

import unreal

# a shadowed point light is 6 cube faces of virtual shadow map over the 16 M-triangle scene: 32 of them were 30 ms of
# a 61 ms frame. Full shadows on the 6 strongest, screen-space contact shadows (nearly free) on the next ones.
SHADOW_LIGHTS = 6
CONTACT_LIGHTS = 40
# 142 of the 249 Corona lamps are LED tape / uplights of 3-30 cd: ~1 % of the light of the room together, but each one
# costs a full deferred light (rect lights are the most expensive kind). Their glow is the emissive surfaces' job.
MIN_CANDELA = 100.0
CVARS = {
    "r.RayTracing.Enable": "0",
    "r.Lumen.HardwareRayTracing": "0",
    "r.MegaLights.Allowed": "0",
    "r.Lumen.Reflections.ScreenTraces": "1",
    "r.Lumen.TraceMeshSDFs": "1",
    "r.Shadow.Virtual.Enable": "1",
    "r.Forward.MaxCulledLightsPerCell": "64",
    "r.LightGridPixelSize": "32",
    "r.Shadow.Virtual.ResolutionLodBiasLocal": "1.5",
}
for k, v in CVARS.items():
    unreal.SystemLibrary.execute_console_command(None, "%s %s" % (k, v))

EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
lights = []
for a in EAS.get_all_level_actors():
    if isinstance(a, (unreal.PointLight, unreal.RectLight, unreal.SpotLight)) and unreal.Name("chandelier_glow") not in a.tags:
        lights.append((a.get_component_by_class(unreal.LocalLightComponent), a))
lights.sort(key=lambda t: -t[0].intensity)
for i, (c, a) in enumerate(lights):
    c.set_editor_property("cast_shadows", i < SHADOW_LIGHTS)
    c.set_editor_property("contact_shadow_length", 0.04 if i < CONTACT_LIGHTS else 0.0)
    # radius grows with sqrt(intensity), 1.5 m .. 12 m: 250 lights in one room overflow the light grid otherwise
    c.set_editor_property("attenuation_radius", max(150.0, min(1200.0, 35.0 * math.sqrt(max(c.intensity, 1.0)))))
    c.set_editor_property("allow_mega_lights", False)
    c.set_visibility(c.intensity >= MIN_CANDELA)

pp = [a for a in EAS.get_all_level_actors() if isinstance(a, unreal.PostProcessVolume)][0]
s = pp.settings
for k, v in (("lumen_final_gather_quality", 1.5), ("lumen_scene_lighting_quality", 1.0), ("lumen_scene_detail", 1.5),
             ("lumen_reflection_quality", 1.0), ("lumen_max_trace_distance", 8000.0)):
    s.set_editor_property("override_" + k, True)
    s.set_editor_property(k, v)
pp.settings = s
unreal.EditorLoadingAndSavingUtils.save_current_level()
print("no-RT mode: %d lights (%d visible), %d with shadows, %d with contact shadows" % (
    len(lights), sum(1 for c, _ in lights if c.intensity >= MIN_CANDELA), min(SHADOW_LIGHTS, len(lights)),
    min(CONTACT_LIGHTS, len(lights))))
