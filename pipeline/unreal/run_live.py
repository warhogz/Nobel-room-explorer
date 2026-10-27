"""Build the room inside the open editor, so it can be watched: level with lights / sky / cameras first, then the
assets (textures, materials) and the meshes chunk by chunk, each chunk spawned into the level as soon as it is imported.

UnrealEditor.exe NobelKitchen.uproject -ExecutePythonScript="<this file>"
"""
import os
import sys
import traceback

import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_level  # noqa: E402

state = {"phase": "wait", "ticks": 0, "gen": None, "handle": None, "spawned": 0}


def stop():
    # the editor crashed right after an unregister from inside the callback: the callback just goes idle instead
    state["phase"] = "idle"


def on_chunk(objs):
    state["spawned"] += build_level.spawn_meshes(objs)
    unreal.log("NIK live: %d mesh actors in the level" % state["spawned"])


def tick(dt):
    # saving packages / importing pumps Slate, which calls this callback again from inside the running step
    if state.get("busy"):
        return
    state["busy"] = True
    try:
        state["ticks"] += 1
        if state["phase"] == "idle":
            return
        if state["phase"] == "wait":
            if state["ticks"] > 120:  # let the editor finish opening
                import build_assets  # textures, materials, IES (already made by prepare.py: quick)
                state["gen"] = build_assets.mesh_steps(on_chunk)
                state["phase"] = "level"
        elif state["phase"] == "level":
            build_level.start()
            state["phase"] = "meshes"
        elif state["phase"] == "meshes":
            try:
                next(state["gen"])
            except StopIteration:
                build_level.look_through("10")
                build_level.finish()
                unreal.log("NIK live: done")
                stop()
    except Exception:
        unreal.log_error("NIK live failed:\n" + traceback.format_exc())
        stop()
    finally:
        state["busy"] = False


state["handle"] = unreal.register_slate_post_tick_callback(tick)
