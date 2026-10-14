import * as THREE from 'three'

/**
 * The glass sculpture chandelier: clear glass refracts the room behind it (transmission pass), the amber-gold
 * leaves and the fine hanging rods are polished metal reflecting the room probes. Decorative only: never ray-cast.
 */
export function setupChandelier(root: THREE.Object3D, gl: THREE.WebGLRenderer) {
  gl.transmissionResolutionScale = 0.5
  root.traverse((o) => {
    if (!(o instanceof THREE.Mesh)) return
    const src = o.material as THREE.MeshStandardMaterial
    if (src.userData?.nikChandelier) return // already set up (StrictMode double render)
    const nik = src.userData?.nik ? JSON.parse(src.userData.nik) : {}
    let mat: THREE.MeshStandardMaterial
    if (nik.glass || (src as THREE.MeshPhysicalMaterial).transmission > 0) {
      mat = new THREE.MeshPhysicalMaterial({
        color: new THREE.Color(1, 0.97, 0.93),
        metalness: 0,
        roughness: 0.03,
        transmission: 1,
        thickness: 0.06,
        ior: 1.5,
        attenuationColor: new THREE.Color(1.0, 0.86, 0.66),
        attenuationDistance: 0.35,
        specularIntensity: 1,
        envMapIntensity: 1.6,
        side: THREE.DoubleSide,
      })
    } else {
      // amber-gold leaves and the fine hanging rods: polished warm metal
      const rods = src.name.includes('2147483537')
      mat = new THREE.MeshStandardMaterial({
        color: rods ? new THREE.Color(0.75, 0.52, 0.27) : new THREE.Color(0.95, 0.62, 0.28),
        metalness: 1,
        roughness: rods ? 0.3 : 0.12,
        envMapIntensity: 1.6,
      })
    }
    mat.userData.nikChandelier = true
    o.material = mat
    o.raycast = () => {}
  })
}
