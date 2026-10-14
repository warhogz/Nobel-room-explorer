"""Denoises baked lightmaps with Intel OIDN (Blender compositor Denoise node, HDR).

blender -b --factory-startup -P denoise_lightmaps.py -- <bake_dir>
  every <bake_dir>/*.exr is denoised in place; the raw bake is kept in <bake_dir>/raw/
Bakes have no albedo/normal passes, so the plain HDR filter is used; seams are safe (16 px dilated margins).
"""
import glob
import os
import shutil
import sys
import time

import bpy

DIR = sys.argv[sys.argv.index("--") + 1]
RAW = os.path.join(DIR, "raw")
os.makedirs(RAW, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.render.resolution_percentage = 100
sc.render.use_compositing = True
sc.render.image_settings.file_format = "OPEN_EXR"
sc.render.image_settings.color_depth = "32"
sc.render.image_settings.exr_codec = "ZIP"
sc.view_settings.view_transform = "Standard"
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
ng = bpy.data.node_groups.new("denoise", "CompositorNodeTree")
sc.compositing_node_group = ng
ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
n_img = ng.nodes.new("CompositorNodeImage")
n_den = ng.nodes.new("CompositorNodeDenoise")
for k, v in (("HDR", True),):
    if k in n_den.inputs:
        n_den.inputs[k].default_value = v
out = ng.nodes.new("NodeGroupOutput")
ng.links.new(n_img.outputs["Image"], n_den.inputs["Image"])
ng.links.new(n_den.outputs["Image"], out.inputs[0])

for path in sorted(glob.glob(os.path.join(DIR, "*.exr"))):
    raw = os.path.join(RAW, os.path.basename(path))
    if not os.path.exists(raw):
        shutil.copy2(path, raw)
    t = time.time()
    img = bpy.data.images.load(raw)
    img.colorspace_settings.name = "Non-Color"
    n_img.image = img
    sc.render.resolution_x, sc.render.resolution_y = img.size
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    bpy.data.images.remove(img)
    print("DENOISED %-34s %.1fs" % (os.path.basename(path), time.time() - t), flush=True)
print("done")
