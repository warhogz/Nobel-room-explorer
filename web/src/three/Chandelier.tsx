import * as THREE from 'three'

/**
 * The glass sculpture chandelier: clear glass refracts the room behind it (transmission pass), the amber-gold
 * leaves are polished metal reflecting the room probes, hung on hairline rods from the ceiling. Decorative only:
 * never ray-cast.
 */
export function setupChandelier(
  root: THREE.Object3D,
  gl: THREE.WebGLRenderer,
  ceilings: THREE.Object3D[],
  /** room probe lookup (box-projected, kitchen or hall probe by position): without it the hall pieces mirror the kitchen */
  useProbes: (m: THREE.MeshStandardMaterial) => void,
) {
  gl.transmissionResolutionScale = 0.5
  let rods: THREE.Mesh | null = null
  root.traverse((o) => {
    if (!(o instanceof THREE.Mesh)) return
    const src = o.material as THREE.MeshStandardMaterial
    if (src.userData?.nikChandelier) return // already set up (StrictMode double render)
    const nik = src.userData?.nik ? JSON.parse(src.userData.nik) : {}
    if (src.name.includes('2147483537')) {
      rods = o
      return
    }
    let mat: THREE.MeshStandardMaterial
    if (nik.glass || (src as THREE.MeshPhysicalMaterial).transmission > 0) {
      mat = new THREE.MeshPhysicalMaterial({
        color: new THREE.Color(1, 0.99, 0.97),
        metalness: 0,
        roughness: 0.03,
        transmission: 1,
        thickness: 0.05,
        // Corona: Fresnel IOR 2.7 - the glass mirrors a lot of the warm room (F0 ~0.16 at the three.js maximum)
        ior: 2.2,
        // thick folds glow amber, thin edges stay clear (the renders' honey-gold glass)
        attenuationColor: new THREE.Color(1.0, 0.72, 0.4),
        attenuationDistance: 0.3,
        specularIntensity: 1,
        specularColor: new THREE.Color(1.0, 0.9, 0.75),
        envMapIntensity: 2.6,
        side: THREE.DoubleSide,
      })
    } else {
      // amber-gold leaves: polished warm metal
      mat = new THREE.MeshStandardMaterial({ color: new THREE.Color(1.0, 0.6, 0.25), metalness: 1, roughness: 0.1, envMapIntensity: 2.4 })
    }
    mat.userData.nikChandelier = true
    useProbes(mat)
    o.material = mat
    o.raycast = () => {}
  })
  if (rods && !root.getObjectByName('Chandelier_hangers')) {
    root.updateWorldMatrix(true, false)
    const lines = hangers(rods, ceilings)
    // built in world space
    lines.matrixAutoUpdate = false
    lines.matrix.copy(root.matrixWorld).invert()
    root.add(lines)
  }
}

/**
 * The source rods are short stubs (the export lost most of each hanger). Stubs on one vertical line are merged
 * and extended up to the ceiling above them; drawn as hairlines, which is what 1-2 mm wires are on screen.
 */
function hangers(rods: THREE.Mesh, ceilings: THREE.Object3D[]) {
  rods.updateWorldMatrix(true, false)
  rods.visible = false
  const g = rods.geometry
  const pos = g.getAttribute('position') as THREE.BufferAttribute
  const idx = g.index
  // connected components (stubs) by shared positions
  const key = (i: number) => `${Math.round(pos.getX(i) * 1e4)},${Math.round(pos.getY(i) * 1e4)},${Math.round(pos.getZ(i) * 1e4)}`
  const parent = new Map<string, string>()
  const find = (a: string): string => {
    let r = a
    while (parent.get(r) !== r) r = parent.get(r)!
    parent.set(a, r)
    return r
  }
  const keys: string[] = []
  for (let i = 0; i < pos.count; i++) {
    const k = key(i)
    keys.push(k)
    if (!parent.has(k)) parent.set(k, k)
  }
  const tri = idx ? idx.count : pos.count
  for (let t = 0; t < tri; t += 3) {
    const v = (j: number) => keys[idx ? idx.getX(t + j) : t + j]
    const a = find(v(0))
    parent.set(find(v(1)), a)
    parent.set(find(v(2)), a)
  }
  const p = new THREE.Vector3()
  const stubs = new Map<string, THREE.Box3>()
  for (let i = 0; i < pos.count; i++) {
    const r = find(keys[i])
    let b = stubs.get(r)
    if (!b) stubs.set(r, (b = new THREE.Box3()))
    b.expandByPoint(p.fromBufferAttribute(pos, i).applyMatrix4(rods.matrixWorld))
  }
  // stubs within 3 cm (horizontally) hang on the same wire
  const wires: { x: number; z: number; lo: number; hi: number; n: number }[] = []
  for (const b of stubs.values()) {
    const c = b.getCenter(p)
    const w = wires.find((w) => Math.hypot(w.x - c.x, w.z - c.z) < 0.03)
    if (w) {
      w.lo = Math.min(w.lo, b.min.y)
      w.hi = Math.max(w.hi, b.max.y)
    } else wires.push({ x: c.x, z: c.z, lo: b.min.y, hi: b.max.y, n: 1 })
  }
  const ray = new THREE.Raycaster()
  ray.firstHitOnly = true
  const up = new THREE.Vector3(0, 1, 0)
  const verts: number[] = []
  for (const w of wires) {
    ray.set(new THREE.Vector3(w.x, w.hi, w.z), up)
    ray.far = 8
    const hit = ray.intersectObjects(ceilings, false)[0]
    verts.push(w.x, w.lo, w.z, w.x, hit ? hit.point.y : w.hi, w.z)
  }
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3))
  const lines = new THREE.LineSegments(
    geo,
    // scene-linear (tone mapping exposes it ~4.8x): a fine warm-gold glint
    new THREE.LineBasicMaterial({ color: new THREE.Color(0.16, 0.11, 0.06), transparent: true, opacity: 0.7 }),
  )
  lines.name = 'Chandelier_hangers'
  lines.raycast = () => {}
  return lines
}
