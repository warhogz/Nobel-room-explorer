/**
 * Dev-only: fits a two-point-perspective preset camera (level, lens shift) to measurements taken on a client
 * render, using the real mesh vertices. Run from the console with ?dev:  await __solveCamera(spec)
 * Measurements are in render pixels; silhouettes are matched by their extremes.
 */
import * as THREE from 'three'

type V3 = [number, number, number]
export interface SolveSpec {
  resolution: [number, number]
  silhouettes: { mesh: string; filter?: (p: V3) => boolean; umin?: number; umax?: number; vmin?: number; vmax?: number }[]
  points: { at: V3; uv: [number, number] }[]
  init: { x: number; y: number; z: number; yaw: number; lens: number; shift: number }
}

function collect(scene: THREE.Object3D, name: string, step: number): V3[] {
  const out: V3[] = []
  const v = new THREE.Vector3()
  scene.getObjectByName(name)?.traverse((m) => {
    if (!(m instanceof THREE.Mesh)) return
    m.updateWorldMatrix(true, false)
    const p = m.geometry.attributes.position
    for (let i = 0; i < p.count; i += step) {
      v.fromBufferAttribute(p, i).applyMatrix4(m.matrixWorld)
      out.push([v.x, v.y, v.z])
    }
  })
  return out
}

function nelderMead(f: (x: number[]) => number, x0: number[], scale: number[], iters = 4000) {
  const n = x0.length
  let pts = [x0, ...x0.map((_, i) => x0.map((v, j) => (i === j ? v + scale[j] : v)))]
  let vals = pts.map(f)
  for (let k = 0; k < iters; k++) {
    const idx = vals.map((_, i) => i).sort((a, b) => vals[a] - vals[b])
    pts = idx.map((i) => pts[i])
    vals = idx.map((i) => vals[i])
    const c = Array(n).fill(0)
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) c[j] += pts[i][j] / n
    const w = pts[n]
    const xr = c.map((v, j) => v + (v - w[j]))
    const fr = f(xr)
    if (fr < vals[0]) {
      const xe = c.map((v, j) => v + 2 * (v - w[j]))
      const fe = f(xe)
      ;[pts[n], vals[n]] = fe < fr ? [xe, fe] : [xr, fr]
    } else if (fr < vals[n - 1]) {
      ;[pts[n], vals[n]] = [xr, fr]
    } else {
      const xc = c.map((v, j) => v + 0.5 * (w[j] - v))
      const fc = f(xc)
      if (fc < vals[n]) {
        ;[pts[n], vals[n]] = [xc, fc]
      } else {
        pts = pts.map((p) => p.map((v, j) => pts[0][j] + 0.5 * (v - pts[0][j])))
        vals = pts.map(f)
      }
    }
  }
  return { x: pts[0], f: vals[0] }
}

export function solveCamera(scene: THREE.Object3D, spec: SolveSpec) {
  const [W, H] = spec.resolution
  const L = Math.max(W, H)
  const sil = spec.silhouettes.map((s) => ({ ...s, pts: collect(scene, s.mesh, s.mesh === "Island" ? 23 : 3).filter(s.filter ?? (() => true)) }))
  const project = (x: number[], P: V3): [number, number] | null => {
    const [cx, cy, cz, a, lens, shift] = x
    const F = (lens / 36) * L
    const dx = P[0] - cx
    const dy = P[1] - cy
    const dz = P[2] - cz
    const xc = dx * Math.cos(a) + dz * Math.sin(a)
    const zc = dx * Math.sin(a) - dz * Math.cos(a)
    if (zc < 0.05) return null
    return [W / 2 + (F * xc) / zc, H / 2 - (F * dy) / zc + shift * L]
  }
  const loss = (x: number[]) => {
    let e = 0
    for (const s of sil) {
      let umin = Infinity, umax = -Infinity, vmin = Infinity, vmax = -Infinity
      for (const p of s.pts) {
        const q = project(x, p)
        if (!q) return 1e12
        umin = Math.min(umin, q[0]); umax = Math.max(umax, q[0]); vmin = Math.min(vmin, q[1]); vmax = Math.max(vmax, q[1])
      }
      if (s.umin !== undefined) e += (umin - s.umin) ** 2
      if (s.umax !== undefined) e += (umax - s.umax) ** 2
      if (s.vmin !== undefined) e += (vmin - s.vmin) ** 2
      if (s.vmax !== undefined) e += (vmax - s.vmax) ** 2
    }
    for (const p of spec.points) {
      const q = project(x, p.at)
      if (!q) return 1e12
      e += (q[0] - p.uv[0]) ** 2 + (q[1] - p.uv[1]) ** 2
    }
    return e
  }
  const i = spec.init
  let best = nelderMead(loss, [i.x, i.y, i.z, i.yaw, i.lens, i.shift], [0.3, 0.1, 0.3, 0.05, 2, 0.02], 1500)
  for (let r = 0; r < 2; r++) best = nelderMead(loss, best.x, [0.1, 0.05, 0.1, 0.02, 0.5, 0.005], 700)
  const [cx, cy, cz, a, lens, shift] = best.x
  const fwd = [Math.sin(a), 0, -Math.cos(a)]
  const nTerms = sil.reduce((n, s) => n + ['umin', 'umax', 'vmin', 'vmax'].filter((k) => (s as never)[k] !== undefined).length, 0) + spec.points.length * 2
  return {
    rmsPx: Math.sqrt(best.f / nTerms),
    preset: {
      position: [cx, cy, cz],
      target: [cx + fwd[0] * 4, cy, cz + fwd[2] * 4],
      lens,
      sensor: 36,
      shiftY: shift,
      resolution: spec.resolution,
    },
    blender: { pos: [cx, -cz, cy], look: [cx + fwd[0] * 4, -(cz + fwd[2] * 4)], lens, shift },
  }
}
