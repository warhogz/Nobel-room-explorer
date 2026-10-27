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
  /** phones: no transmission pass (a second render of the whole room): the glass is a clear tinted shell that mirrors the probes */
  cheap = false,
) {
  gl.transmissionResolutionScale = 0.5
  let rods: THREE.Mesh | null = null
  root.traverse((o) => {
    if (!(o instanceof THREE.Mesh) || Array.isArray(o.material)) return // glass already split into glass + rods
    const src = o.material as THREE.MeshStandardMaterial
    if (src.userData?.nikChandelier) return // already set up (StrictMode double render)
    const nik = src.userData?.nik ? JSON.parse(src.userData.nik) : {}
    if (src.name.includes('2147483537')) {
      rods = o
      return
    }
    let mat: THREE.MeshStandardMaterial
    if (cheap && (nik.glass || (src as THREE.MeshPhysicalMaterial).transmission > 0)) {
      mat = new THREE.MeshStandardMaterial({
        color: new THREE.Color(1, 0.96, 0.9),
        metalness: 0.1,
        roughness: 0.04,
        transparent: true,
        opacity: 0.32,
        depthWrite: false,
        envMapIntensity: 2.4,
        side: THREE.FrontSide,
      })
    } else if (nik.glass || (src as THREE.MeshPhysicalMaterial).transmission > 0) {
      mat = new THREE.MeshPhysicalMaterial({
        color: new THREE.Color(1, 0.99, 0.97),
        metalness: 0,
        roughness: 0.03,
        transmission: 1,
        thickness: 0.05,
        // Corona: Fresnel IOR 2.7 - the glass mirrors a lot of the warm room (F0 ~0.16 at the three.js maximum)
        ior: 2.2,
        // clear crystal, only the thickest folds turn faintly warm; the gold comes from the leaves
        attenuationColor: new THREE.Color(1.0, 0.9, 0.76),
        attenuationDistance: 1.0,
        specularIntensity: 1,
        specularColor: new THREE.Color(1.0, 0.9, 0.75),
        envMapIntensity: 2.6,
        side: THREE.DoubleSide,
      })
    } else {
      // amber-gold leaves: polished warm metal
      mat = new THREE.MeshStandardMaterial({ color: new THREE.Color(1.0, 0.74, 0.32), metalness: 1, roughness: 0.12, envMapIntensity: 2.8 })
    }
    mat.userData.nikChandelier = true
    useProbes(mat)
    o.material = mat
    o.raycast = () => {}
    if (mat.transparent || mat instanceof THREE.MeshPhysicalMaterial) splitGlassRods(o, mat)
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
 * The glass mesh also holds dozens of long, few-mm crystal rods. Lit like the sculpture they flash as white strokes
 * across the room (glaring on phones): each connected piece taller than 15 cm and under 2.5 cm across goes to a second
 * draw group with a faint, nearly matte glass.
 */
function splitGlassRods(o: THREE.Mesh, glass: THREE.Material) {
  const g = o.geometry
  const idx = g.index
  if (!idx || g.groups.length) return
  const pos = g.attributes.position
  // weld by position (split normals / UVs leave duplicate vertices), then union-find over triangles
  const key = new Map<string, number>()
  const weld = new Int32Array(pos.count)
  for (let i = 0; i < pos.count; i++) {
    const k = `${Math.round(pos.getX(i) * 1e4)},${Math.round(pos.getY(i) * 1e4)},${Math.round(pos.getZ(i) * 1e4)}`
    let w = key.get(k)
    if (w === undefined) key.set(k, (w = key.size))
    weld[i] = w
  }
  const parent = new Int32Array(key.size).map((_, i) => i)
  const find = (a: number) => {
    while (parent[a] !== a) a = parent[a] = parent[parent[a]]
    return a
  }
  const ia = idx.array
  for (let t = 0; t < ia.length; t += 3) {
    const a = find(weld[ia[t]])
    parent[find(weld[ia[t + 1]])] = a
    parent[find(weld[ia[t + 2]])] = a
  }
  const box = new Map<number, number[]>() // root -> [minX, minY, minZ, maxX, maxY, maxZ]
  for (let i = 0; i < pos.count; i++) {
    const r = find(weld[i])
    const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i)
    const b = box.get(r)
    if (!b) box.set(r, [x, y, z, x, y, z])
    else {
      b[0] = Math.min(b[0], x); b[1] = Math.min(b[1], y); b[2] = Math.min(b[2], z)
      b[3] = Math.max(b[3], x); b[4] = Math.max(b[4], y); b[5] = Math.max(b[5], z)
    }
  }
  // sizes in world metres (the chandelier root may be scaled)
  o.updateWorldMatrix(true, false)
  const s = new THREE.Vector3().setFromMatrixScale(o.matrixWorld)
  const rod = (r: number) => {
    const b = box.get(r)!
    const w = Math.max((b[3] - b[0]) * s.x, (b[5] - b[2]) * s.z)
    return (b[4] - b[1]) * s.y > 0.15 && w < 0.025
  }
  const keep: number[] = []
  const rods: number[] = []
  for (let t = 0; t < ia.length; t += 3) (rod(find(weld[ia[t]])) ? rods : keep).push(ia[t], ia[t + 1], ia[t + 2])
  if (!rods.length) return
  g.setIndex([...keep, ...rods])
  g.addGroup(0, keep.length, 0)
  g.addGroup(keep.length, rods.length, 1)
  const faint = new THREE.MeshBasicMaterial({ color: new THREE.Color(0.05, 0.04, 0.03), transparent: true, opacity: 0.35, depthWrite: false })
  faint.userData.nikChandelier = true
  o.material = [glass, faint]
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
  // A 1 px line is far wider than a 1.5 mm wire beyond arm's length (worse on phones, where the frame is upscaled):
  // fade it by the share of the pixel the wire really covers, so the hangers read as a faint glint, not white strokes.
  const mat = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    uniforms: { color: { value: new THREE.Color(0.1, 0.07, 0.04) }, k: { value: 1 } },  // scene-linear, warm brass
    vertexShader: /* glsl */ `
      uniform float k;
      varying float vA;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_Position = projectionMatrix * mv;
        vA = clamp(k / max(-mv.z, 0.01), 0.03, 0.45);
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 color;
      varying float vA;
      void main() {
        gl_FragColor = vec4(color, vA);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  })
  const lines = new THREE.LineSegments(geo, mat)
  const px = new THREE.Vector2()
  lines.onBeforeRender = (gl, _s, camera) => {
    // wire width (m) x pixels per metre at 1 m depth
    mat.uniforms.k.value = 0.0015 * gl.getDrawingBufferSize(px).y * 0.5 * camera.projectionMatrix.elements[5]
  }
  lines.name = 'Chandelier_hangers'
  lines.raycast = () => {}
  return lines
}
