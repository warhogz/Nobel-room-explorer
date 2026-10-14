import * as THREE from 'three'

/**
 * Reflection probes captured from the baked room itself (cube camera -> PMREM), box-projected in the shader:
 * probe A sits at the island (kitchen box), probe B in the double-height hall. Fragments west of `splitX`
 * use A, the rest B. Re-captured whenever the light mix changes, so reflections follow day/night and the lamps.
 */
export interface ProbeDef {
  position: THREE.Vector3
  boxMin: THREE.Vector3
  boxMax: THREE.Vector3
}

export const PROBES: ProbeDef[] = [
  // kitchen box (web coords: x east, y up, z = -blender y)
  { position: new THREE.Vector3(0.9, 1.45, 0), boxMin: new THREE.Vector3(-2.05, -0.01, -2.25), boxMax: new THREE.Vector3(2.72, 3.85, 2.25) },
  // hall under the gable
  { position: new THREE.Vector3(8.5, 1.8, 0), boxMin: new THREE.Vector3(2.72, -0.01, -2.7), boxMax: new THREE.Vector3(17.5, 7.0, 2.7) },
]

export const probeUniforms = {
  nikEnvB: { value: null as THREE.Texture | null },
  nikProbeA: { value: PROBES[0].position },
  nikBoxMinA: { value: PROBES[0].boxMin },
  nikBoxMaxA: { value: PROBES[0].boxMax },
  nikProbeB: { value: PROBES[1].position },
  nikBoxMinB: { value: PROBES[1].boxMin },
  nikBoxMaxB: { value: PROBES[1].boxMax },
  nikSplitX: { value: 2.72 },
}

export class RoomProbes {
  private readonly cubes: THREE.WebGLCubeRenderTarget[]
  private readonly cams: THREE.CubeCamera[]
  private readonly pmrem: THREE.PMREMGenerator
  readonly env: (THREE.WebGLRenderTarget | null)[] = [null, null]

  constructor(gl: THREE.WebGLRenderer, size = 256) {
    this.pmrem = new THREE.PMREMGenerator(gl)
    this.cubes = PROBES.map(
      () => new THREE.WebGLCubeRenderTarget(size, { type: THREE.HalfFloatType, generateMipmaps: true, minFilter: THREE.LinearMipmapLinearFilter }),
    )
    this.cams = PROBES.map((p, i) => {
      const c = new THREE.CubeCamera(0.05, 80, this.cubes[i])
      c.position.copy(p.position)
      return c
    })
  }

  /** allocate the prefiltered targets up front (shaders compile against the final env map layout) */
  prime() {
    this.cubes.forEach((c, i) => {
      this.env[i] = this.pmrem.fromCubemap(c.texture, this.env[i] ?? undefined)
    })
    return this.env[0]!.texture
  }

  /**
   * capture both probes. The previous capture stays bound as environment, so metal sees metal: repeated
   * captures converge to multi-bounce reflections (bronze walls reflecting the lit room in each other).
   */
  update(gl: THREE.WebGLRenderer, scene: THREE.Scene, hide: THREE.Object3D[] = []) {
    const vis = hide.map((o) => o.visible)
    hide.forEach((o) => (o.visible = false))
    this.cams.forEach((c, i) => {
      c.update(gl, scene)
      this.env[i] = this.pmrem.fromCubemap(this.cubes[i].texture, this.env[i] ?? undefined)
    })
    hide.forEach((o, i) => (o.visible = vis[i]))
    probeUniforms.nikEnvB.value = this.env[1]!.texture
    return this.env[0]!.texture
  }

  dispose() {
    this.cubes.forEach((c) => c.dispose())
    this.env.forEach((e) => e?.dispose())
    this.pmrem.dispose()
  }
}

/** GLSL: box-projected probe lookup replacing the stock IBL fetches (needs varying vNikWP) */
export const PROBE_PARS = /* glsl */ `
uniform sampler2D nikEnvB;
uniform vec3 nikProbeA; uniform vec3 nikBoxMinA; uniform vec3 nikBoxMaxA;
uniform vec3 nikProbeB; uniform vec3 nikBoxMinB; uniform vec3 nikBoxMaxB;
uniform float nikSplitX;
varying vec3 vNikWP;
vec3 nikBoxProject( vec3 dir, vec3 bmin, vec3 bmax, vec3 probe ) {
  vec3 p = clamp( vNikWP, bmin, bmax );
  vec3 rmax = ( bmax - p ) / dir;
  vec3 rmin = ( bmin - p ) / dir;
  vec3 r = max( rmax, rmin );
  float t = min( min( r.x, r.y ), r.z );
  return normalize( p + dir * t - probe );
}
vec4 nikProbe( vec3 worldDir, float roughness ) {
  // rough lobes see the whole room: blend the parallax correction out with roughness
  float k = 1.0 - smoothstep( 0.35, 0.9, roughness );
  if ( vNikWP.x < nikSplitX ) {
    vec3 d = normalize( mix( worldDir, nikBoxProject( worldDir, nikBoxMinA, nikBoxMaxA, nikProbeA ), k ) );
    return textureCubeUV( envMap, envMapRotation * d, roughness );
  }
  vec3 d = normalize( mix( worldDir, nikBoxProject( worldDir, nikBoxMinB, nikBoxMaxB, nikProbeB ), k ) );
  return textureCubeUV( nikEnvB, envMapRotation * d, roughness );
}
`
