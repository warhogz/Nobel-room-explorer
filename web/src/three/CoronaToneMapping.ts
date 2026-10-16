import { Effect } from 'postprocessing'
import * as THREE from 'three'

/**
 * Re-implementation of the Corona 14 tone-mapping stack stored in Island_Israel.max
 * (processing order = bottom of the Corona UI stack first):
 *   Exposure 2.253 EV -> White balance 6300 K -> Tint 0 -> Contrast 2.0 -> Saturation 0 -> (ACES off)
 *   -> Vignette 1.0 -> [sRGB] Curves [linear] -> Filmic (highlights 0.004, rich shadows 0.9) -> Reinhard (HC 43.4)
 * Corona does not publish the exact operator formulas; the shapes below are approximations whose free
 * coefficients (contrastK, vignetteK, shadowsK) are calibrated against the client renders.
 */
export interface CoronaTMParams {
  exposureEV: number
  /** offset between our baked light units and Corona's (calibrated against render 030) */
  calibrationEV: number
  /** viewer-facing exposure slider */
  userEV: number
  whiteBalanceK: number
  contrast: number
  contrastK: number
  saturation: number
  vignette: number
  vignetteK: number
  richShadows: number
  shadowsK: number
  highlightCompression: number
  curve: [number, number][]
}

export const CORONA_DEFAULTS: CoronaTMParams = {
  exposureEV: 2.253,
  calibrationEV: 0.2,
  userEV: 0,
  whiteBalanceK: 6300,
  contrast: 2.0,
  contrastK: 0.12,
  saturation: -0.18, // the converted light tints read more saturated than Corona's
  vignette: 1.0,
  vignetteK: 0.35,
  richShadows: 0.9,
  shadowsK: 0.03,
  highlightCompression: 43.421,
  curve: [
    [0, 0],
    [0.125, 0.1094],
    [0.6836, 0.6836],
    [1, 1],
  ],
}

const FRAG = /* glsl */ `
uniform float exposure;
uniform vec3 wb;
uniform float contrastExp;
uniform float saturation;
uniform float vignette;
uniform sampler2D curveLut;
uniform float shadowsK;
uniform float hc2;
// background space (display-linear) and its light/dark blend
uniform float lightMode;
uniform float grain;
uniform float dayExposure;

float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
vec3 toSrgb(vec3 c) { return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c)); }
vec3 toLin(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c)); }

vec3 tonemap(vec3 c) {
  c = max(c, 0.0) * exposure * wb;
  float L = luma(c);
  if (L > 1e-6) { c *= (0.18 * pow(L / 0.18, contrastExp)) / L; }
  L = luma(c);
  c = max(mix(vec3(L), c, 1.0 + saturation), 0.0);
  vec3 s = toSrgb(min(c, 1.0));
  vec3 over = max(c - 1.0, 0.0);
  s = vec3(texture2D(curveLut, vec2(s.r, 0.5)).r, texture2D(curveLut, vec2(s.g, 0.5)).r, texture2D(curveLut, vec2(s.b, 0.5)).r);
  c = toLin(s) + over;
  c *= c / (c + shadowsK);
  L = luma(c);
  if (L > 1e-6) { float Lc = L * (1.0 + L / hc2) / (1.0 + L); c *= Lc / L; }
  return c;
}

void mainImage(const in vec4 inputColor, const in vec2 uv, out vec4 outputColor) {
  // the backdrop (HDRI by day, dark gradient by night) is part of the scene now: tone map everything
  vec3 c = tonemap(inputColor.rgb * mix(1.0, dayExposure, lightMode));
  vec2 d = (uv - 0.5) * 2.0;
  c *= max(0.0, 1.0 - vignette * dot(d, d) * 0.5);
  // fine animated film grain in display space (also dithers the gradients); a bit stronger in the shadows
  vec2 gp = gl_FragCoord.xy + vec2(fract(time * 7.13) * 431.0, fract(time * 3.71) * 197.0);
  float n = fract(sin(dot(gp, vec2(12.9898, 78.233))) * 43758.5453);
  vec3 sc = toSrgb(c);
  float gAmt = grain * (1.15 - 0.5 * dot(sc, vec3(0.333)));
  c = toLin(clamp(sc + (n - 0.5) * gAmt, 0.0, 1.0));
  outputColor = vec4(c, 1.0);
}
`

export function kelvinToLinearRGB(T: number): [number, number, number] {
  const t = Math.min(25000, Math.max(1667, T))
  const x =
    t <= 4000
      ? -0.2661239e9 / t ** 3 - 0.2343589e6 / t ** 2 + 0.8776956e3 / t + 0.17991
      : -3.0258469e9 / t ** 3 + 2.1070379e6 / t ** 2 + 0.2226347e3 / t + 0.24039
  const y =
    t <= 2222
      ? -1.1063814 * x ** 3 - 1.3481102 * x ** 2 + 2.18555832 * x - 0.20219683
      : t <= 4000
        ? -0.9549476 * x ** 3 - 1.37418593 * x ** 2 + 2.09137015 * x - 0.16748867
        : 3.081758 * x ** 3 - 5.8733867 * x ** 2 + 3.75112997 * x - 0.37001483
  const X = x / y
  const Z = (1 - x - y) / y
  const r = 3.2406 * X - 1.5372 - 0.4986 * Z
  const g = -0.9689 * X + 1.8758 + 0.0415 * Z
  const b = 0.0557 * X - 0.204 + 1.057 * Z
  return [Math.max(r, 0), Math.max(g, 0), Math.max(b, 0)]
}

function whiteBalance(T: number): THREE.Vector3 {
  const ref = kelvinToLinearRGB(6504)
  const t = kelvinToLinearRGB(T)
  const m = new THREE.Vector3(ref[0] / t[0], ref[1] / t[1], ref[2] / t[2])
  const l = 0.2126 * m.x + 0.7152 * m.y + 0.0722 * m.z
  return m.multiplyScalar(1 / l)
}

/** monotone cubic (Fritsch–Carlson) curve -> 256 px float LUT */
function curveLut(points: [number, number][]): THREE.DataTexture {
  const n = points.length
  const xs = points.map((p) => p[0])
  const ys = points.map((p) => p[1])
  const dx = xs.slice(1).map((x, i) => x - xs[i])
  const sl = ys.slice(1).map((y, i) => (y - ys[i]) / dx[i])
  const m = new Array(n).fill(0)
  m[0] = sl[0]
  m[n - 1] = sl[n - 2]
  for (let i = 1; i < n - 1; i++) m[i] = sl[i - 1] * sl[i] <= 0 ? 0 : (sl[i - 1] + sl[i]) / 2
  for (let i = 0; i < n - 1; i++) {
    if (sl[i] === 0) {
      m[i] = m[i + 1] = 0
      continue
    }
    const a = m[i] / sl[i]
    const b = m[i + 1] / sl[i]
    const h = Math.hypot(a, b)
    if (h > 3) {
      m[i] = (3 * a * sl[i]) / h
      m[i + 1] = (3 * b * sl[i]) / h
    }
  }
  const N = 256
  const data = new Float32Array(N * 4)
  for (let k = 0; k < N; k++) {
    const x = k / (N - 1)
    let i = 0
    while (i < n - 2 && x > xs[i + 1]) i++
    const h = dx[i]
    const t = (x - xs[i]) / h
    const t2 = t * t
    const t3 = t2 * t
    const v =
      (2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * h * m[i] + (-2 * t3 + 3 * t2) * ys[i + 1] + (t3 - t2) * h * m[i + 1]
    data[k * 4] = data[k * 4 + 1] = data[k * 4 + 2] = Math.min(1, Math.max(0, v))
    data[k * 4 + 3] = 1
  }
  const tex = new THREE.DataTexture(data, N, 1, THREE.RGBAFormat, THREE.FloatType)
  tex.minFilter = tex.magFilter = THREE.LinearFilter
  tex.wrapS = tex.wrapT = THREE.ClampToEdgeWrapping
  tex.needsUpdate = true
  return tex
}


export class CoronaToneMappingEffect extends Effect {
  constructor(p: CoronaTMParams = CORONA_DEFAULTS) {
    super('CoronaToneMapping', FRAG, {
      uniforms: new Map<string, THREE.Uniform>([
        ['exposure', new THREE.Uniform(1)],
        ['wb', new THREE.Uniform(new THREE.Vector3(1, 1, 1))],
        ['contrastExp', new THREE.Uniform(1)],
        ['saturation', new THREE.Uniform(0)],
        ['vignette', new THREE.Uniform(0)],
        ['curveLut', new THREE.Uniform(curveLut(p.curve))],
        ['shadowsK', new THREE.Uniform(0)],
        ['hc2', new THREE.Uniform(1)],
        ['lightMode', new THREE.Uniform(1)],
        ['grain', new THREE.Uniform(0.028)],
        // daylight grade: a touch darker than the warm night so the HDRI day reads natural, not blown out
        ['dayExposure', new THREE.Uniform(Math.pow(2, -0.45))],
      ]),
    })
    this.setParams(p)
  }

  /** 0 = dark room, 1 = bright gallery space */
  setLight(v: number) {
    this.uniforms.get('lightMode')!.value = v
  }

  setParams(p: CoronaTMParams) {
    const u = this.uniforms
    u.get('exposure')!.value = Math.pow(2, p.exposureEV + p.calibrationEV + p.userEV)
    u.get('wb')!.value = whiteBalance(p.whiteBalanceK)
    u.get('contrastExp')!.value = 1 + (p.contrast - 1) * p.contrastK
    u.get('saturation')!.value = p.saturation
    u.get('vignette')!.value = p.vignette * p.vignetteK
    u.get('shadowsK')!.value = p.richShadows * p.shadowsK
    u.get('hc2')!.value = p.highlightCompression * p.highlightCompression
  }
}
