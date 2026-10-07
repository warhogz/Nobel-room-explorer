import * as THREE from 'three'

/**
 * Procedural reflection environments (PMREM), one per mood:
 *  - light: bright ivory gallery (big overhead softbox, pale walls, window strip)
 *  - dark:  warm bronze room with downlights
 * Panels are unlit emissive quads around the origin, like drei's Lightformers.
 */
type Panel = { form: 'rect' | 'circle'; color: string; intensity: number; scale: [number, number]; position: [number, number, number]; lookAt?: [number, number, number] }

const DARK: { background: string; panels: Panel[] } = {
  background: '#1c1713',
  panels: [
    { form: 'rect', color: '#fff3e2', intensity: 2.2, scale: [4, 3], position: [0, 3.2, 0] },
    ...[-1.2, 0, 1.2].flatMap((x) => [-1, 1].map((z) => ({ form: 'circle' as const, color: '#ffd9a8', intensity: 6, scale: [0.35, 0.35] as [number, number], position: [x, 3, z] as [number, number, number] }))),
    { form: 'rect', color: '#c49a72', intensity: 0.55, scale: [10, 3], position: [0, 1.5, -4] },
    { form: 'rect', color: '#c49a72', intensity: 0.55, scale: [10, 3], position: [0, 1.5, 4] },
    { form: 'rect', color: '#b88d66', intensity: 0.45, scale: [10, 3], position: [-4, 1.5, 0] },
    { form: 'rect', color: '#fff4e4', intensity: 1.6, scale: [3, 4], position: [5, 2, 0] },
    { form: 'rect', color: '#ecd9be', intensity: 0.6, scale: [8, 8], position: [0, -0.01, 0] },
  ],
}

const LIGHT: { background: string; panels: Panel[] } = {
  background: '#d8cfc3',
  panels: [
    { form: 'rect', color: '#fffaf2', intensity: 3.2, scale: [6, 5], position: [0, 3.4, 0] },
    ...[-1.2, 0, 1.2].flatMap((x) => [-1, 1].map((z) => ({ form: 'circle' as const, color: '#ffe6c4', intensity: 5, scale: [0.35, 0.35] as [number, number], position: [x, 3, z] as [number, number, number] }))),
    { form: 'rect', color: '#f3ebe0', intensity: 1.15, scale: [12, 4], position: [0, 1.6, -5] },
    { form: 'rect', color: '#f3ebe0', intensity: 1.15, scale: [12, 4], position: [0, 1.6, 5] },
    { form: 'rect', color: '#efe5d8', intensity: 1.0, scale: [12, 4], position: [-5, 1.6, 0] },
    { form: 'rect', color: '#ffffff', intensity: 2.6, scale: [4, 3], position: [5, 1.8, 0] },
    { form: 'rect', color: '#f1e4d1', intensity: 1.0, scale: [10, 10], position: [0, -0.01, 0] },
  ],
}

function buildScene(def: { background: string; panels: Panel[] }) {
  const scene = new THREE.Scene()
  scene.background = new THREE.Color(def.background)
  const rect = new THREE.PlaneGeometry(1, 1)
  const circle = new THREE.CircleGeometry(0.5, 32)
  for (const p of def.panels) {
    const m = new THREE.MeshBasicMaterial({ color: new THREE.Color(p.color).multiplyScalar(p.intensity), side: THREE.DoubleSide, toneMapped: false })
    const mesh = new THREE.Mesh(p.form === 'rect' ? rect : circle, m)
    mesh.scale.set(p.scale[0], p.scale[1], 1)
    mesh.position.set(...p.position)
    const [x, y, z] = p.position
    if (y > 2.5) mesh.lookAt(x, 0, z) // ceiling panels face down
    else if (y < 0) mesh.lookAt(x, 1, z) // floor bounce faces up
    else mesh.lookAt(0, y, 0) // walls face the island
    scene.add(mesh)
  }
  return scene
}

export function buildEnvironments(gl: THREE.WebGLRenderer) {
  const pmrem = new THREE.PMREMGenerator(gl)
  const make = (def: typeof DARK) => {
    const scene = buildScene(def)
    const rt = pmrem.fromScene(scene, 0.02, 0.1, 100)
    scene.traverse((o) => {
      if (o instanceof THREE.Mesh) o.material.dispose()
    })
    return rt.texture
  }
  const out = { dark: make(DARK), light: make(LIGHT) }
  pmrem.dispose()
  return out
}

/** day: real interior HDRI (Poly Haven "Lebombo", CC0) prefiltered for reflections */
export function buildDayEnvironment(gl: THREE.WebGLRenderer, hdr: THREE.Texture) {
  const pmrem = new THREE.PMREMGenerator(gl)
  const rt = pmrem.fromEquirectangular(hdr)
  pmrem.dispose()
  return rt.texture
}

/** night backdrop: very dark warm gradient, slightly lifted towards the ground (equirectangular, used as scene.background) */
export function makeNightBackdrop() {
  const c = document.createElement('canvas')
  c.width = 4
  c.height = 256
  const g = c.getContext('2d')!
  const grad = g.createLinearGradient(0, 0, 0, 256)
  // smooth, monotone falloff (no horizon band: the dissolving floor must meet one continuous tone)
  grad.addColorStop(0, '#030202')
  grad.addColorStop(0.45, '#0a0705')
  grad.addColorStop(1, '#0d0907')
  g.fillStyle = grad
  g.fillRect(0, 0, 4, 256)
  const t = new THREE.CanvasTexture(c)
  t.colorSpace = THREE.SRGBColorSpace
  t.mapping = THREE.EquirectangularReflectionMapping
  return t
}
