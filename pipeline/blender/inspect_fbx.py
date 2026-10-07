# blender -b --factory-startup -P inspect_fbx.py -- <scene.fbx>
import sys

import bmesh
import bpy

fbx = sys.argv[sys.argv.index("--") + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=fbx)
for o in sorted(bpy.context.scene.objects, key=lambda o: o.name):
    line = "%-32s %-6s loc=%s rot=%s scale=%s" % (o.name[:32], o.type, tuple(round(v, 3) for v in o.location),
                                                 tuple(round(v, 3) for v in o.rotation_euler),
                                                 tuple(round(v, 3) for v in o.scale))
    if o.type == "MESH":
        me = o.data
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.transform(o.matrix_world)
        vol = bm.calc_volume(signed=True)
        bm.free()
        dims = tuple(round(v, 3) for v in o.dimensions)
        line += " dims=%s faces=%d uv=%s mats=%s vol=%.4f" % (dims, len(me.polygons), [u.name for u in me.uv_layers],
                                                            [m.name if m else None for m in me.materials], vol)
    print(line)
