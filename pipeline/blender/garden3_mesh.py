"""Garden v3 meshes: real leaf geometry (no textures, no alpha) for Nanite.

blender -b --factory-startup -P garden3_mesh.py -- <out dir>
  out: HedgeA/B/C.fbx  a 200 cm module of clipped hedge (160 high, 70 thick, rounded top), ~50 k folded leaves over a
                       dark core; modules are instanced along the hedge line (garden3.py)
       Ball.fbx        a boxwood topiary ball, r 45 cm, small leaves, resting on the ground
       Grass.fbx       a clump of mown lawn blades (the 3D lawn)
       Hills.fbx       the land around the garden: flat meadow ring, then rolling hills to the horizon (400 m)
       hills.json      the height function's parameters + tree placements with their ground heights
  Units: Unreal cm (x, y, z) -> Blender m (x, -y, z) like the room meshes. Colours: per-vertex (sRGB).
"""
import json
import math
import os
import sys

import bpy
import numpy as np

OUT = sys.argv[sys.argv.index("--") + 1]
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(7)
X0, X1, Y0, Y1 = -880.0, 2380.0, -1150.0, 1150.0  # hedge centre line (same as garden v2)
HEDGE_T, HEDGE_H, MOD_L = 70.0, 160.0, 200.0
CX = (X0 + X1) / 2


def unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def srgb_to_lin(c):
    c = np.asarray(c, np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def build(name, verts, faces, colors=None):
    """verts (N,3) Unreal cm, faces (F,k) int, colors (N,3) sRGB 0..1 per vertex"""
    v = np.asarray(verts, np.float64) / 100.0
    v[:, 1] *= -1
    f = np.asarray(faces, np.int64)[:, ::-1]  # the Y mirror flips the winding back
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(v))
    me.vertices.foreach_set("co", v.ravel().astype(np.float32))
    k = f.shape[1]
    me.loops.add(f.size)
    me.loops.foreach_set("vertex_index", f.ravel().astype(np.int32))
    me.polygons.add(len(f))
    me.polygons.foreach_set("loop_start", (np.arange(len(f)) * k).astype(np.int32))
    me.update(calc_edges=True)
    me.validate(clean_customdata=False)
    if colors is not None:
        ca = me.color_attributes.new("Col", "BYTE_COLOR", "POINT")
        col = np.concatenate([srgb_to_lin(colors), np.ones((len(v), 1), np.float32)], 1)
        ca.data.foreach_set("color", col.ravel().astype(np.float32))
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    me.materials.append(bpy.data.materials.new(name))
    return ob


def export(ob, smooth=False):
    for p in ob.data.polygons:
        p.use_smooth = smooth
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.export_scene.fbx(filepath=os.path.join(OUT, ob.name + ".fbx"), use_selection=True, object_types={"MESH"},
                             mesh_smooth_type="FACE", use_tspace=False, add_leaf_bones=False, bake_anim=False,
                             path_mode="STRIP", embed_textures=False, apply_unit_scale=True,
                             apply_scale_options="FBX_SCALE_NONE", axis_forward="-Z", axis_up="Y", colors_type="SRGB")
    print("exported", ob.name, len(ob.data.vertices), "verts", len(ob.data.polygons), "faces", flush=True)


# ------------------------------------------------------------------ leaves
def leaves(p, n, length, width, palette, r):
    """folded leaves at points p with facing n: 5 verts (base, left, tip, right, raised midrib), 4 triangles"""
    m = len(p)
    up = np.array([0.0, 0.0, 1.0])
    # the leaf points along the surface, mostly upward/outward, with a random twist
    a = r.uniform(0, 2 * np.pi, m)
    t0 = unit(np.cross(n, up) + 1e-4)
    b0 = unit(np.cross(n, t0))
    t = unit(t0 * np.cos(a)[:, None] + b0 * np.sin(a)[:, None] + up * 0.6)
    t = unit(t - n * np.einsum("ij,ij->i", t, n)[:, None])
    b = unit(np.cross(n, t))
    L = r.uniform(*length, m)[:, None]
    W = (r.uniform(*width, m)[:, None]) * L
    base = p - t * L * 0.45
    tip = p + t * L * 0.55 - n * L * 0.12  # droops at the tip
    left = p - b * W * 0.5 + t * L * 0.02
    right = p + b * W * 0.5 + t * L * 0.02
    mid = p + n * W * 0.22 + t * L * 0.04  # folded along the midrib
    V = np.stack([base, left, tip, right, mid], 1).reshape(-1, 3)
    i = (np.arange(m) * 5)[:, None]
    F = np.concatenate([i + [0, 1, 4], i + [1, 2, 4], i + [2, 3, 4], i + [3, 0, 4]], 0)
    # winding so the face normal agrees with n (checked on the first leaf)
    e = np.cross(V[1] - V[0], V[4] - V[0])
    if np.dot(e, n[0]) < 0:
        F = F[:, ::-1]
    # colour: one of the palette greens per leaf, a lighter midrib, sun-bleached tips on the outer layer
    pc = np.asarray(palette, np.float32)
    c = pc[r.integers(0, len(pc), m)] * r.uniform(0.82, 1.15, (m, 1)).astype(np.float32)
    C = np.repeat(c[:, None, :], 5, 1)
    C[:, 4] *= 1.25
    C[:, 2] *= 1.08
    return V, F, np.clip(C.reshape(-1, 3), 0, 1)


def box_core(x0, x1, y0, y1, z0, z1, color):
    V = np.array([[x, y, z] for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)], float)
    F = np.array([[0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4], [2, 6, 7, 3], [0, 4, 6, 2], [1, 3, 7, 5]])
    return V, F, np.tile(color, (8, 1))


def tris(F):
    F = np.asarray(F)
    if F.shape[1] == 3:
        return F
    return np.concatenate([F[:, [0, 1, 2]], F[:, [0, 2, 3]]], 0)


def merge(parts):
    V, F, C, off = [], [], [], 0
    for v, f, c in parts:
        V.append(v)
        F.append(tris(f) + off)
        C.append(c)
        off += len(v)
    return np.concatenate(V), np.concatenate(F), np.concatenate(C)


HEDGE_GREENS = [(0.10, 0.20, 0.06), (0.13, 0.24, 0.07), (0.08, 0.17, 0.05), (0.16, 0.27, 0.09), (0.11, 0.22, 0.05)]


def hedge_profile(t, h, rc, step=1.0):
    hw = t / 2
    pts = [(-hw, z) for z in np.arange(0, h - rc, step)]
    for k in np.linspace(0, 1, 24):
        a = k * np.pi / 2
        pts.append((-hw + rc - rc * np.cos(a), h - rc + rc * np.sin(a)))
    pts += [(y, h) for y in np.arange(-hw + rc, hw - rc, step)]
    for k in np.linspace(0, 1, 24):
        a = k * np.pi / 2
        pts.append((hw - rc + rc * np.sin(a), h - rc + rc * np.cos(a)))
    pts += [(hw, z) for z in np.arange(h - rc, 0, -step)]
    pts = np.array(pts)
    tan = np.gradient(pts, axis=0)
    nor = unit(np.stack([tan[:, 1], -tan[:, 0]], 1))
    nor *= np.sign(np.einsum("ij,ij->i", nor, pts - [0, h / 2]))[:, None]
    seg = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
    return pts, nor, seg


def hedge_module(name, seed):
    r = np.random.default_rng(seed)
    prof, pn, seg = hedge_profile(HEDGE_T, HEDGE_H, 14.0)
    area = MOD_L * seg[-1]
    n = int(area * 0.6)
    s = r.uniform(0, seg[-1], n)
    j = np.clip(np.searchsorted(seg, s) - 1, 0, len(seg) - 2)
    u = ((s - seg[j]) / np.maximum(seg[j + 1] - seg[j], 1e-6))[:, None]
    yz = prof[j] * (1 - u) + prof[j + 1] * u
    nyz = unit(pn[j] * (1 - u) + pn[j + 1] * u)
    x = r.uniform(-4, MOD_L + 4, n)
    # soft clipping irregularity: a few cm of low-frequency swell, leaves layered up to 6 cm deep
    swell = 1.6 * np.sin(x / 23 + seed) * np.cos(yz[:, 1] / 19 + 2 * seed) + 0.8 * np.sin(x / 7.3 + yz[:, 1] / 9.1)
    depth = -r.uniform(0, 1, n) ** 1.6 * 6.0 + swell
    p = np.stack([x, yz[:, 0] + nyz[:, 0] * depth, yz[:, 1] + nyz[:, 1] * depth], 1)
    nn = np.stack([np.zeros(n), nyz[:, 0], nyz[:, 1]], 1)
    nn = unit(nn + r.normal(0, 0.55, (n, 3)) + [0, 0, 0.25])
    V1, F1, C1 = leaves(p, nn, (2.8, 4.6), (0.38, 0.5), HEDGE_GREENS, r)
    # darker, smaller leaves near the foot (less light reaches them)
    C1 *= np.repeat(np.clip(0.55 + p[:, 2] / HEDGE_H * 0.6, 0.55, 1.08), 5)[:, None]
    core = box_core(-2, MOD_L + 2, -HEDGE_T / 2 + 6, HEDGE_T / 2 - 6, 0, HEDGE_H - 6, (0.025, 0.035, 0.018))
    V, F, C = merge([(V1, F1, C1), core])
    export(build(name, V, F, C))


for k, nm in enumerate(("HedgeA", "HedgeB", "HedgeC")):
    hedge_module(nm, 11 + k)

# ------------------------------------------------------------------ boxwood ball
r = np.random.default_rng(41)
R = 45.0
n = int(4 * np.pi * R * R * 1.0)
d = unit(r.normal(size=(n, 3)))
d = d[d[:, 2] > -0.75]
rad = R + (-r.uniform(0, 1, len(d)) ** 1.5 * 4.0) + 1.2 * np.sin(d[:, 0] * 5) * np.cos(d[:, 1] * 6)
p = d * rad[:, None] + [0, 0, R * 0.9]
nn = unit(d + r.normal(0, 0.5, d.shape) + [0, 0, 0.2])
V1, F1, C1 = leaves(p, nn, (1.6, 2.6), (0.5, 0.62), [(0.12, 0.24, 0.06), (0.15, 0.28, 0.07), (0.10, 0.20, 0.05)], r)
C1 *= np.repeat(np.clip(0.6 + (p[:, 2] / (2 * R)) * 0.55, 0.6, 1.1), 5)[:, None]
# dark core sphere
lat, lon = np.meshgrid(np.linspace(-np.pi / 2, np.pi / 2, 12), np.linspace(0, 2 * np.pi, 24, endpoint=False), indexing="ij")
cv = np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)], -1).reshape(-1, 3) * (R - 5) + [0, 0, R * 0.9]
cf = []
for i in range(11):
    for jj in range(24):
        a, b_ = i * 24 + jj, i * 24 + (jj + 1) % 24
        cf.append([a, b_, b_ + 24, a + 24])
V, F, C = merge([(V1, F1, C1), (cv, np.array(cf), np.tile((0.025, 0.035, 0.018), (len(cv), 1)))])
export(build("Ball", V, F, C))

# ------------------------------------------------------------------ lawn clump
r = np.random.default_rng(5)
blades = 42
V, F, C = [], [], []
for i in range(blades):
    a, rr = r.uniform(0, 2 * np.pi), 7.5 * np.sqrt(r.uniform())
    base = np.array([rr * np.cos(a), rr * np.sin(a), -0.5])
    h, w = r.uniform(4.5, 8.5), r.uniform(0.28, 0.45)
    lean = r.uniform(0, 2 * np.pi)
    ld = np.array([np.cos(lean), np.sin(lean), 0]) * r.uniform(0.1, 0.45)
    side = np.array([-np.sin(lean + 1.3), np.cos(lean + 1.3), 0])
    mid = base + (np.array([0, 0, 1]) + ld * 0.6) * h * 0.55
    tip = base + (np.array([0, 0, 1]) + ld * 1.6) * h
    k = len(V)
    V += [base - side * w / 2, base + side * w / 2, mid - side * w * 0.35, mid + side * w * 0.35, tip]
    F += [[k, k + 1, k + 3], [k, k + 3, k + 2], [k + 2, k + 3, k + 4]]
    g = r.uniform(0.85, 1.15)
    dry = r.uniform() < 0.08
    top = np.array([0.30, 0.36, 0.12]) if dry else np.array([0.15, 0.30, 0.07]) * g
    bot = np.array([0.05, 0.10, 0.025])
    C += [bot, bot, (bot + top) / 2, (bot + top) / 2, top]
export(build("Grass", np.array(V), np.array(F), np.clip(np.array(C), 0, 1)))


# ------------------------------------------------------------------ land: meadow ring, rolling hills to the horizon
def value_noise(x, y, cell, seed):
    rr = np.random.default_rng(seed)
    g = rr.random((256, 256)).astype(np.float64)
    fx, fy = x / cell, y / cell
    ix, iy = np.floor(fx).astype(int), np.floor(fy).astype(int)
    tx, ty = fx - ix, fy - iy
    tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
    a, b = g[ix % 256, iy % 256], g[(ix + 1) % 256, iy % 256]
    c, d_ = g[ix % 256, (iy + 1) % 256], g[(ix + 1) % 256, (iy + 1) % 256]
    return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d_ * tx) * ty - 0.5


def outside(x, y):
    """distance (cm) outside the hedge's outer face, negative inside"""
    dx = np.maximum(np.abs(x - CX) - ((X1 - X0) / 2 + HEDGE_T / 2), 0)
    dy = np.maximum(np.abs(y) - (Y1 + HEDGE_T / 2), 0)
    inside = (np.abs(x - CX) < (X1 - X0) / 2 + HEDGE_T / 2) & (np.abs(y) < Y1 + HEDGE_T / 2)
    return np.where(inside, -1.0, np.hypot(dx, dy))


def height(x, y):
    d = outside(x, y)
    # a flat meadow for ~25 m, then gentle rises; real hills only far out (they read as depth, not as a wall)
    ramp = np.clip((d - 2500) / 14000, 0, 1)
    ramp = ramp * ramp * (3 - 2 * ramp)
    fbm = (value_noise(x, y, 11000, 1) * 1.0 + value_noise(x, y, 4500, 2) * 0.4 + value_noise(x, y, 1800, 3) * 0.12)
    h = -3 + np.maximum(d - 2500, 0) * 0.012 + ramp * (fbm * 1600 + 200) + np.clip(d / 600, 0, 1) * value_noise(x, y, 700, 4) * 25
    far = np.clip((d - 15000) / 25000, 0, 1)  # the horizon ridge rises behind the forest
    h += far * far * 1800
    return np.where(d < 0, -20.0, h)


def axis(lo, hi, near_lo, near_hi, fine, coarse):
    a = list(np.arange(lo, near_lo, coarse)) + list(np.arange(near_lo, near_hi, fine)) + list(np.arange(near_hi, hi + 1, coarse))
    return np.array(sorted(set(np.round(a, 3))))


xs = axis(CX - 40000, CX + 40000, X0 - 3000, X1 + 3000, 150, 900)
ys = axis(-40000, 40000, Y0 - 3000, Y1 + 3000, 150, 900)
gx, gy = np.meshgrid(xs, ys, indexing="ij")
gz = height(gx, gy)
V = np.stack([gx, gy, gz], -1).reshape(-1, 3)
nx, ny = len(xs), len(ys)
i, j = np.meshgrid(np.arange(nx - 1), np.arange(ny - 1), indexing="ij")
a = (i * ny + j).ravel()
F = np.stack([a, a + ny, a + ny + 1, a + 1], 1)
hills = build("Hills", V, F)
export(hills, smooth=True)

# ------------------------------------------------------------------ trees: specimen trees at the meadow edge, forest beyond
TREES = {
    "edge": ["SM_Poplar_01_Standalone", "SM_Poplar_02_Standalone", "SM_Fir_04_Standalone", "SM_Fir_05_Standalone"],
    "under": ["SM_Fir_02_Small", "SM_Fir_01_Plant", "SM_Poplar_05_Small"],
    "forest": ["SM_Poplar_06_Forest", "SM_Poplar_07_Forest", "SM_Fir_06_Forest", "SM_Fir_07_Forest", "SM_Poplar_03_Medium",
               "SM_Poplar_04_Small", "SM_Fir_03_Medium"],
}
r = np.random.default_rng(99)
place = {k: [] for k in sum(TREES.values(), [])}


def scatter(dmin, dmax, spacing, kinds, smin, smax, keep=1.0):
    pts = []
    for x in np.arange(CX - 40000, CX + 40000, spacing):
        for y in np.arange(-40000, 40000, spacing):
            px, py = x + r.uniform(-0.45, 0.45) * spacing, y + r.uniform(-0.45, 0.45) * spacing
            d = float(outside(np.array(px), np.array(py)))
            if dmin <= d <= dmax and r.uniform() < keep:
                pts.append((px, py))
    for px, py in pts:
        m = kinds[r.integers(0, len(kinds))]
        s = float(r.uniform(smin, smax))
        z = float(height(np.array(px), np.array(py))) - 25 * s
        place[m].append([round(px, 1), round(py, 1), round(z, 1), round(float(r.uniform(0, 360)), 1), round(s, 3)])


scatter(700, 1600, 1100, TREES["edge"], 0.85, 1.1, keep=0.55)        # a loose line of fine trees on the meadow
scatter(1500, 3200, 650, TREES["under"], 0.8, 1.2, keep=0.45)        # young firs and saplings: a soft forest edge
scatter(1900, 16000, 900, TREES["forest"], 0.85, 1.3, keep=0.8)      # the forest

# ------------------------------------------------------------------ the forest floor: boulders, stones, undergrowth, logs
# (kind: list of [x, y, z, yaw, scale]; z already sunk into the ground by the mesh's own share)
ROCKS = {"SM_Big_Rock_01": 120, "SM_Big_Rock_02": 130, "SM_Big_Rock_03": 160, "SM_Middle_Rock_01": 55,
         "SM_Middle_Rock_02": 45, "SM_Middle_Rock_03": 45}
SMALL = ["SM_Small_Rock_01", "SM_Small_Rock_02", "SM_Small_Rock_03", "SM_Small_Rock_04", "SM_Small_Rock_05", "SM_Small_Rock_06"]
MEADOW = ["SM_grass_bush_02", "SM_grass_bush_03", "SM_grass_bush_04", "SM_grass_bush_simple_04", "SM_grass_bush_simple_05",
          "SM_ground_foliage_01_flowery", "SM_forest_heather_01"]
FLOOR = ["SM_fern_01_0", "SM_fern_01_1", "SM_fern_01_2", "SM_ground_foliage_02_0", "SM_ground_foliage_02_1",
         "SM_ground_foliage_02_2_SM_ground_foliage_02_2", "SM_ground_foliage_03_SM_ground_foliage_03",
         "SM_nettle_01_0_SM_nettle_01_0", "SM_grass_bush_01", "SM_forest_heather_01"]
ROOTS = ["SM_crooked_root_01", "SM_crooked_root_021", "SM_crooked_root_031", "SM_crooked_root_04", "SM_crooked_root_05"]
LOGS = ["SM_trunk_01", "SM_trunk_02"]
ground = {k: [] for k in list(ROCKS) + SMALL + MEADOW + FLOOR + ROOTS + LOGS}
r = np.random.default_rng(123)


def put(kind, x, y, s, sink=0.0, yaw=None):
    z = float(height(np.array(x), np.array(y))) - sink * s
    ground[kind].append([round(float(x), 1), round(float(y), 1), round(z, 1),
                         round(float(r.uniform(0, 360) if yaw is None else yaw), 1), round(float(s), 3)])


# boulder groups: at the meadow edge and through the forest, each with a scree of stones around it
n_groups = 0
while n_groups < 46:
    x, y = r.uniform(CX - 9000, CX + 9000), r.uniform(-8000, 8000)
    d = float(outside(np.array(x), np.array(y)))
    if not 250 < d < 7000:
        continue
    n_groups += 1
    for _ in range(r.integers(1, 4)):
        k = list(ROCKS)[r.integers(0, len(ROCKS))]
        s = r.uniform(0.45, 1.0) if k.startswith("SM_Big") else r.uniform(0.6, 1.3)
        put(k, x + r.normal(0, 150), y + r.normal(0, 150), s, ROCKS[k])
    for _ in range(r.integers(5, 14)):
        put(SMALL[r.integers(0, len(SMALL))], x + r.normal(0, 260), y + r.normal(0, 260), r.uniform(0.5, 1.6), 8)
# loose stones in the meadow grass
for _ in range(260):
    x, y = r.uniform(CX - 4500, CX + 4500), r.uniform(-4000, 4000)
    if 80 < float(outside(np.array(x), np.array(y))) < 3500:
        put(SMALL[r.integers(0, len(SMALL))], x, y, r.uniform(0.4, 1.1), 10)
# undergrowth: patchy meadow grasses near the hedge, ferns / forest plants under the trees
step = 85.0
for x in np.arange(CX - 6500, CX + 6500, step):
    for y in np.arange(-6000, 6000, step):
        px, py = x + r.uniform(-0.5, 0.5) * step, y + r.uniform(-0.5, 0.5) * step
        d = float(outside(np.array(px), np.array(py)))
        if d < 40 or d > 5200:
            continue
        patch = float(value_noise(np.array(px), np.array(py), 900, 21)) + 0.5   # 0..1 clumps
        forest = np.clip((d - 1500) / 1200, 0, 1)
        if r.uniform() > (0.25 + 0.75 * patch ** 2) * (0.9 if forest > 0.5 else 0.7):
            continue
        kinds = FLOOR if r.uniform() < forest else MEADOW
        put(kinds[r.integers(0, len(kinds))], px, py, r.uniform(0.75, 1.35), 2)
# roots at the foot of the near forest trees, a few fallen logs
for m, pts in place.items():
    for x, y, z, yaw, s in pts:
        d = float(outside(np.array(x), np.array(y)))
        if d < 4500 and r.uniform() < 0.45:
            put(ROOTS[r.integers(0, len(ROOTS))], x + r.normal(0, 40), y + r.normal(0, 40), s * r.uniform(1.0, 1.6), 10)
for _ in range(14):
    while True:
        x, y = r.uniform(CX - 6000, CX + 6000), r.uniform(-5500, 5500)
        if 1800 < float(outside(np.array(x), np.array(y))) < 5000:
            break
    put(LOGS[r.integers(0, 2)], x, y, r.uniform(0.8, 1.3), 25)
print("ground", sum(len(v) for v in ground.values()), {k: len(v) for k, v in ground.items() if v})
json.dump({"trees": place, "ground": ground, "hedge": {"rect": [X0, X1, Y0, Y1], "thick": HEDGE_T, "height": HEDGE_H, "module": MOD_L}},
          open(os.path.join(OUT, "garden3.json"), "w"), indent=0)
print("trees", {k: len(v) for k, v in place.items()}, "total", sum(len(v) for v in place.values()))
print("done")
