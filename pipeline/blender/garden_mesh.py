"""Clipped hedge ring + boxwood ball for the Unreal garden (real, bumpy Nanite geometry; opaque, no alpha).

blender -b --factory-startup -P garden_mesh.py -- <out dir>
  out: Hedge.fbx   a closed ring of hedge (rounded-rectangle plan, rounded profile, 3-octave lumps), UV in leaf-texture tiles
       Ball.fbx    a boxwood ball, radius 50 cm, sitting on the ground
All in Unreal centimetres, converted like the room meshes (Blender: x, -y, z, metres).

Hedge ring: centre line on the rectangle HEDGE_RECT (cm, Unreal axes), thickness 90 cm, height 230 cm.
"""
import math
import os
import sys

import bpy
import numpy as np

OUT = sys.argv[sys.argv.index("--") + 1]
os.makedirs(OUT, exist_ok=True)
X0, X1, Y0, Y1 = (float(v) for v in os.environ.get("NIK_HEDGE_RECT", "-880,2380,-1150,1150").split(","))
THICK, HEIGHT, RC_PLAN, RC_PROF = 90.0, 230.0, 160.0, 22.0
STEP, TILE_CM = 5.0, 60.0  # grid step along the path / the profile; the leaf texture repeats every 60 cm
rng = np.random.default_rng(3)


def smooth(t):
    return t * t * (3 - 2 * t)


def value_noise(l, v, n_l, n_v, seed):
    """periodic along l (grid n_l cells, wraps), open along v (n_v cells); l, v in cell units, broadcast (a,1)x(1,b)"""
    r = np.random.default_rng(seed)
    g = r.random((n_l, n_v + 2)).astype(np.float32)
    li, vi = np.floor(l).astype(int), np.floor(v).astype(int)
    lf, vf = smooth(l - li), smooth(v - vi)
    a = g[li % n_l, vi]
    b = g[(li + 1) % n_l, vi]
    c = g[li % n_l, vi + 1]
    d = g[(li + 1) % n_l, vi + 1]
    return (a * (1 - lf) + b * lf) * (1 - vf) + (c * (1 - lf) + d * lf) * vf - 0.5


def to_blender(p):
    """Unreal cm (x, y, z) -> Blender m (x, -y, z)"""
    q = np.asarray(p, np.float64) / 100.0
    q[..., 1] *= -1
    return q


def make_object(name, verts_ue, faces, uv, normals_ue_hint):
    v = to_blender(verts_ue)
    me = bpy.data.meshes.new(name)
    # winding: the Y flip mirrors the model; make the first face agree with the outward hint
    f = np.asarray(faces, np.int64)
    p0, p1, p2 = v[f[0, 0]], v[f[0, 1]], v[f[0, 2]]
    if np.dot(np.cross(p1 - p0, p2 - p0), to_blender(normals_ue_hint[f[0, 0]] * 100.0)) < 0:
        f = f[:, ::-1]
    me.from_pydata(v.tolist(), [], f.tolist())
    me.update()
    for p in me.polygons:
        p.use_smooth = True
    li = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", li)
    layer = me.uv_layers.new(name="UVMap")
    layer.data.foreach_set("uv", np.asarray(uv, np.float32)[li].ravel())
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    mat = bpy.data.materials.new(name)
    me.materials.append(mat)
    return ob


def export(ob, path):
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.export_scene.fbx(filepath=path, use_selection=True, object_types={"MESH"}, mesh_smooth_type="FACE",
                             use_tspace=False, add_leaf_bones=False, bake_anim=False, path_mode="STRIP",
                             embed_textures=False, apply_unit_scale=True, apply_scale_options="FBX_SCALE_NONE",
                             axis_forward="-Z", axis_up="Y")


def lumps(L, V, perim, n_prof_len, seed):
    """displacement in cm over (path length L, profile length V): big lumps + leaf-mass bumps + fine grain"""
    out = 0.0
    for cell, amp, s in ((34.0, 3.2, 1), (13.0, 1.7, 2), (5.5, 0.8, 3)):
        n_l = max(4, int(round(perim / cell)))
        n_v = max(4, int(math.ceil(n_prof_len / cell)))
        out = out + amp * 2 * value_noise(L / perim * n_l, V / cell, n_l, n_v, seed * 10 + s)
    return out


# ------------------------------------------------------------------ hedge ring
def rounded_rect(x0, x1, y0, y1, r, step):
    """closed polyline of a rounded rectangle, counter-clockwise, with outward normals"""
    pts, nrm = [], []

    def line(a, b, n):
        a, b = np.array(a, float), np.array(b, float)
        m = max(1, int(np.linalg.norm(b - a) / step))
        for k in range(m):
            pts.append(a + (b - a) * k / m)
            nrm.append(n)

    def arc(c, a0, a1):
        m = max(2, int(r * abs(a1 - a0) / step))
        for k in range(m):
            a = a0 + (a1 - a0) * k / m
            pts.append(np.array([c[0] + r * math.cos(a), c[1] + r * math.sin(a)]))
            nrm.append(np.array([math.cos(a), math.sin(a)]))

    line((x0 + r, y0), (x1 - r, y0), np.array([0.0, -1.0]))
    arc((x1 - r, y0 + r), -math.pi / 2, 0)
    line((x1, y0 + r), (x1, y1 - r), np.array([1.0, 0.0]))
    arc((x1 - r, y1 - r), 0, math.pi / 2)
    line((x1 - r, y1), (x0 + r, y1), np.array([0.0, 1.0]))
    arc((x0 + r, y1 - r), math.pi / 2, math.pi)
    line((x0, y1 - r), (x0, y0 + r), np.array([-1.0, 0.0]))
    arc((x0 + r, y0 + r), math.pi, 3 * math.pi / 2)
    return np.array(pts), np.array(nrm)


def hedge_profile(t, h, rc, step):
    """cross-section (w outward offset, z) from the inner foot over the top to the outer foot, and its outward 2D normals"""
    hw = t / 2
    pts = [(-hw, 0.0)]
    n_in = int((h - rc) / step)
    pts += [(-hw, (h - rc) * k / n_in) for k in range(1, n_in + 1)]
    m = 6
    pts += [(-hw + rc - rc * math.cos(math.pi / 2 * k / m), h - rc + rc * math.sin(math.pi / 2 * k / m)) for k in range(1, m + 1)]
    n_top = int((t - 2 * rc) / step)
    pts += [(-hw + rc + (t - 2 * rc) * k / n_top, h) for k in range(1, n_top + 1)]
    pts += [(hw - rc + rc * math.sin(math.pi / 2 * k / m), h - rc + rc * math.cos(math.pi / 2 * k / m)) for k in range(1, m + 1)]
    pts += [(hw, (h - rc) - (h - rc) * k / n_in) for k in range(1, n_in + 1)]
    pts = np.array(pts)
    tan = np.gradient(pts, axis=0)
    nor = np.stack([tan[:, 1], -tan[:, 0]], 1)  # rotate -90 deg
    nor /= np.linalg.norm(nor, axis=1, keepdims=True)
    mid = np.array([0.0, h / 2])
    flip = np.sign(np.einsum("ij,ij->i", nor, pts - mid))
    nor *= np.where(flip == 0, 1, flip)[:, None]
    return pts, nor


path, pn = rounded_rect(X0, X1, Y0, Y1, RC_PLAN, STEP)
seg = np.linalg.norm(np.diff(np.vstack([path, path[:1]]), axis=0), axis=1)
Lc = np.concatenate([[0], np.cumsum(seg)])  # arclength; last = perimeter
perim = Lc[-1]
prof, pnor = hedge_profile(THICK, HEIGHT, RC_PROF, STEP)
Vc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(prof, axis=0), axis=1))])
Nl, Nv = len(path) + 1, len(prof)  # +1: the seam column is duplicated so the texture can close
idx = np.arange(Nl) % len(path)
L = Lc[:Nl][:, None]
V = Vc[None, :]
base_xy = path[idx][:, None, :] + pn[idx][:, None, :] * prof[None, :, 0:1]            # (Nl, Nv, 2)
nxy = pn[idx][:, None, :] * pnor[None, :, 0:1]                                        # outward normal, horizontal part
nz = np.broadcast_to(pnor[None, :, 1:2], (Nl, Nv, 1))
nrm3 = np.concatenate([nxy, nz], 2)
disp = lumps(L, V, perim, Vc[-1], 1)                                                  # (Nl, Nv) cm
fade = np.clip(prof[None, :, 1] / 14.0, 0, 1)                                         # no displacement at the foot
pos = np.concatenate([base_xy, np.broadcast_to(prof[None, :, 1:2], (Nl, Nv, 1))], 2) + nrm3 * (disp * fade)[..., None]
n_tiles = max(1, int(round(perim / TILE_CM)))
uv = np.stack([np.broadcast_to(L / perim * n_tiles, (Nl, Nv)), np.broadcast_to(V / TILE_CM, (Nl, Nv))], 2)
faces = []
for i in range(Nl - 1):
    for j in range(Nv - 1):
        faces.append((i * Nv + j, (i + 1) * Nv + j, (i + 1) * Nv + j + 1, i * Nv + j + 1))
hedge = make_object("Hedge", pos.reshape(-1, 3), faces, uv.reshape(-1, 2), nrm3.reshape(-1, 3))
print("hedge: perimeter %.0f cm, %d verts, %d quads" % (perim, Nl * Nv, len(faces)))
export(hedge, os.path.join(OUT, "Hedge.fbx"))

# ------------------------------------------------------------------ boxwood ball
R, Nlon, Nlat = 50.0, 72, 40
lon = np.linspace(0, 2 * np.pi, Nlon + 1)[:, None]
lat = np.linspace(-np.pi / 2 * 0.86, np.pi / 2, Nlat)[None, :]  # the lower cap is buried in the ground
nb = np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat) * np.ones_like(lon)], 2)
arc_v = R * (lat - lat[0, 0]) * np.ones_like(lon)
arc_u = lon * R * np.cos(lat)
disp = 0.0
for cell, amp, s in ((26.0, 3.0, 11), (11.0, 1.6, 12), (5.0, 0.8, 13)):
    n_l = max(4, int(round(2 * np.pi * R / cell)))
    n_v = max(4, int(np.ceil(np.pi * R / cell)))
    disp = disp + amp * 2 * value_noise(lon / (2 * np.pi) * n_l * np.ones_like(lat), arc_v / cell, n_l, n_v, 100 + s)
pos = nb * (R + disp)[..., None] + np.array([0, 0, R])
uv = np.stack([lon / (2 * np.pi) * 5 * np.ones_like(lat), arc_v / TILE_CM], 2)
faces = []
for i in range(Nlon):
    for j in range(Nlat - 1):
        faces.append((i * Nlat + j, (i + 1) * Nlat + j, (i + 1) * Nlat + j + 1, i * Nlat + j + 1))
ball = make_object("Ball", pos.reshape(-1, 3), faces, uv.reshape(-1, 2), nb.reshape(-1, 3))
export(ball, os.path.join(OUT, "Ball.fbx"))
print("ball ok")
