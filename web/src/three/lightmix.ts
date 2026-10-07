import * as THREE from 'three'
import type { KTX2Loader } from 'three/examples/jsm/loaders/KTX2Loader.js'

export type GroupId = 'kitchen' | 'ostrov' | 'pol' | 'env'
export const GROUPS: GroupId[] = ['kitchen', 'ostrov', 'pol', 'env']

export interface PerLightInfo {
  count: number
  scale: number
  encoding: 'sqrt'
  urls: string[]
}

export interface LightmapManifest {
  rgbmRange: number
  objects: Record<
    string,
    {
      size: number
      groups: Partial<Record<GroupId, { url: string; scale: number }>>
      perLight?: Partial<Record<GroupId, PerLightInfo>>
    }
  >
  textures?: Record<string, string>
}

export interface GroupMix {
  color: [number, number, number]
  intensity: number
  enabled: boolean
}

/** Animated (displayed) light state: per group colour * intensity, per-light 0..1 */
export interface LiveMix {
  groups: Record<GroupId, THREE.Vector3>
  lights: Partial<Record<GroupId, number[]>>
}

const VERT = /* glsl */ `
varying vec2 vUv;
void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }
`
const FRAG = /* glsl */ `
precision highp float;
uniform sampler2D t0; uniform sampler2D t1; uniform sampler2D t2;
uniform vec3 w0; uniform vec3 w1; uniform vec3 w2;
uniform float s0; uniform float s1; uniform float s2;
uniform float range;
// per-light group: up to 8 lights packed 4 per texture (sqrt-encoded luminance, shared scale)
uniform sampler2D p0; uniform sampler2D p1;
uniform vec4 pw0; uniform vec4 pw1;
uniform vec3 pColor; uniform float pScale;
varying vec2 vUv;
vec3 dec(vec4 c, float s) { return c.rgb * c.a * range / s; }
void main() {
  vec3 c = dec(texture2D(t0, vUv), s0) * w0 + dec(texture2D(t1, vUv), s1) * w1 + dec(texture2D(t2, vUv), s2) * w2;
  vec4 a = texture2D(p0, vUv); vec4 b = texture2D(p1, vUv);
  c += (dot(a * a, pw0) + dot(b * b, pw1)) * pScale * pColor;
  gl_FragColor = vec4(c, 1.0);
}
`

const black = new THREE.DataTexture(new Uint8Array([0, 0, 0, 0]), 1, 1)
black.needsUpdate = true

export interface MixerSource {
  group: GroupId
  tex: THREE.Texture
  scale: number
}
export interface MixerPerLight {
  group: GroupId
  textures: THREE.Texture[]
  scale: number
  count: number
}

/**
 * Sums baked lightmap groups (RGBM, weight = LightMix colour * intensity) plus one optional per-light group
 * (each light weighted on its own) into a single HDR lightmap texture.
 */
export class LightmapMixer {
  readonly target: THREE.WebGLRenderTarget
  private readonly mat: THREE.ShaderMaterial
  private readonly scene = new THREE.Scene()
  private readonly cam = new THREE.Camera()
  readonly groups: GroupId[]
  readonly perLight?: MixerPerLight

  constructor(size: number, sources: MixerSource[], range: number, perLight?: MixerPerLight) {
    if (sources.length > 3) throw new Error('LightmapMixer: at most 3 RGBM groups')
    this.groups = sources.map((s) => s.group)
    this.perLight = perLight
    this.target = new THREE.WebGLRenderTarget(size, size, {
      type: THREE.HalfFloatType,
      format: THREE.RGBAFormat,
      generateMipmaps: true,
      minFilter: THREE.LinearMipmapLinearFilter,
      magFilter: THREE.LinearFilter,
      depthBuffer: false,
      colorSpace: THREE.NoColorSpace,
    })
    this.target.texture.channel = 1
    const u: Record<string, THREE.IUniform> = {
      range: { value: range },
      p0: { value: perLight?.textures[0] ?? black },
      p1: { value: perLight?.textures[1] ?? black },
      pw0: { value: new THREE.Vector4() },
      pw1: { value: new THREE.Vector4() },
      pColor: { value: new THREE.Vector3() },
      pScale: { value: perLight?.scale ?? 0 },
    }
    for (let i = 0; i < 3; i++) {
      const s = sources[i]
      u['t' + i] = { value: s ? s.tex : black }
      u['s' + i] = { value: s ? s.scale : 1 }
      u['w' + i] = { value: new THREE.Vector3() }
    }
    this.mat = new THREE.ShaderMaterial({ vertexShader: VERT, fragmentShader: FRAG, uniforms: u, depthTest: false, depthWrite: false })
    const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.mat)
    quad.frustumCulled = false
    this.scene.add(quad)
  }

  render(gl: THREE.WebGLRenderer, live: LiveMix) {
    const u = this.mat.uniforms
    this.groups.forEach((g, i) => (u['w' + i].value as THREE.Vector3).copy(live.groups[g]))
    if (this.perLight) {
      const w = live.lights[this.perLight.group] ?? []
      ;(u.pw0.value as THREE.Vector4).set(w[0] ?? 0, w[1] ?? 0, w[2] ?? 0, w[3] ?? 0)
      ;(u.pw1.value as THREE.Vector4).set(w[4] ?? 0, w[5] ?? 0, w[6] ?? 0, w[7] ?? 0)
      ;(u.pColor.value as THREE.Vector3).copy(live.groups[this.perLight.group])
    }
    const prev = gl.getRenderTarget()
    gl.setRenderTarget(this.target)
    gl.render(this.scene, this.cam)
    gl.setRenderTarget(prev)
  }

  dispose() {
    this.target.dispose()
    this.mat.dispose()
  }
}

export async function loadLightmapTexture(loader: KTX2Loader, url: string) {
  const tex = await loader.loadAsync(url)
  tex.colorSpace = THREE.NoColorSpace
  tex.minFilter = THREE.LinearFilter
  tex.magFilter = THREE.LinearFilter
  tex.generateMipmaps = false
  tex.flipY = false
  return tex
}
