import { Bvh, useGLTF } from '@react-three/drei'
import { useFrame, useThree, type ThreeEvent } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import { suspend } from 'suspend-react'
import * as THREE from 'three'
import { HDRLoader } from 'three/examples/jsm/loaders/HDRLoader.js'
import { KTX2Loader } from 'three/examples/jsm/loaders/KTX2Loader.js'
import { MIX_DEFAULTS, useStore, type FaucetFinish } from '../store'
import { GROUPS, LightmapMixer, loadLightmapTexture, type GroupId, type LightmapManifest, type LiveMix } from './lightmix'
import { buildDayEnvironment, buildEnvironments, makeNightBackdrop } from './envs'
import { anchors, approach, lampsLive, live } from './live'
import { PlanarReflection } from './PlanarReflection'

const BASE = import.meta.env.BASE_URL

let ktx2: KTX2Loader | null = null
export function getKTX2(gl: THREE.WebGLRenderer) {
  if (!ktx2) ktx2 = new KTX2Loader().setTranscoderPath(`${BASE}basis/`).detectSupport(gl)
  return ktx2
}

interface Assets {
  manifest: LightmapManifest
  textures: Record<string, Partial<Record<GroupId, { tex: THREE.Texture; scale: number }>>>
  perLight: Record<string, Partial<Record<GroupId, { textures: THREE.Texture[]; scale: number; count: number }>>>
  extra: Record<string, THREE.Texture>
}

async function loadAssets(gl: THREE.WebGLRenderer): Promise<Assets> {
  const loader = getKTX2(gl)
  const manifest: LightmapManifest = await (await fetch(`${BASE}assets/lightmaps.json`)).json()
  const textures: Assets['textures'] = {}
  const perLight: Assets['perLight'] = {}
  const jobs: Promise<unknown>[] = []
  for (const [obj, info] of Object.entries(manifest.objects)) {
    textures[obj] = {}
    perLight[obj] = {}
    for (const g of GROUPS) {
      const src = info.groups[g]
      if (src) jobs.push(loadLightmapTexture(loader, BASE + src.url).then((tex) => (textures[obj][g] = { tex, scale: src.scale })))
      const pl = info.perLight?.[g]
      if (pl) {
        jobs.push(
          Promise.all(pl.urls.map((u) => loadLightmapTexture(loader, BASE + u))).then(
            (texs) => (perLight[obj][g] = { textures: texs, scale: pl.scale, count: pl.count }),
          ),
        )
      }
    }
  }
  const extra: Record<string, THREE.Texture> = {}
  for (const [name, url] of Object.entries(manifest.textures ?? {})) {
    jobs.push(
      loader.loadAsync(BASE + url).then((t) => {
        t.colorSpace = THREE.SRGBColorSpace
        t.flipY = false
        extra[name] = t
      }),
    )
  }
  await Promise.all(jobs)
  return { manifest, textures, perLight, extra }
}

const sssUniform = { value: 0.55 }

/** lightmapped surfaces: lightmap replaces IBL diffuse (env keeps only reflections) */
function patchLightmapped(mat: THREE.MeshStandardMaterial, ostrov?: THREE.Texture) {
  mat.onBeforeCompile = (sh) => {
    sh.uniforms.nikOstrov = { value: ostrov ?? null }
    sh.uniforms.nikSss = sssUniform
    sh.fragmentShader = sh.fragmentShader.replace(
      '#include <lights_fragment_maps>',
      THREE.ShaderChunk.lights_fragment_maps.replace('iblIrradiance += getIBLIrradiance( geometryNormal );', ''),
    )
    if (ostrov) {
      // onyx glow: translucency colour map (emissiveMap) x light arriving from inside the island (baked)
      sh.fragmentShader = sh.fragmentShader
        .replace('void main() {', 'uniform sampler2D nikOstrov;\nuniform float nikSss;\nvoid main() {')
        .replace(
          '#include <emissivemap_fragment>',
          THREE.ShaderChunk.emissivemap_fragment.replace(
            'totalEmissiveRadiance *= emissiveColor.rgb;',
            // inner glow + subsurface scattering: light hitting the stone spreads softly inside it (blurred
            // front irradiance from a low mip of the lightmap), revealed by the translucent veins
            'totalEmissiveRadiance *= emissiveColor.rgb * ( texture2D( nikOstrov, vLightMapUv ).rgb + textureLod( lightMap, vLightMapUv, 3.5 ).rgb * nikSss );',
          ),
        )
    }
  }
  mat.customProgramCacheKey = () => (ostrov ? 'nik-lm-ostrov' : 'nik-lm')
}

/**
 * Placeholder floor: honed travertine with a blurred planar reflection (Fresnel, roughness-aware), and a
 * coverage mask in alpha (the post effect composites the background): opaque plateau around the island,
 * then a soft gaussian tail, forced to zero before the square edge of the plane.
 */
export const floorUniforms = {
  nikLight: { value: 1 },
  nikReflSharp: { value: null as THREE.Texture | null },
  nikReflBlur: { value: null as THREE.Texture | null },
  nikReflMatrix: { value: new THREE.Matrix4() },
  nikReflStrength: { value: 10.0 },
}
function patchFloor(mat: THREE.MeshStandardMaterial) {
  const prev = mat.onBeforeCompile
  mat.onBeforeCompile = (sh, r) => {
    prev.call(mat, sh, r)
    Object.assign(sh.uniforms, floorUniforms)
    sh.vertexShader = sh.vertexShader
      .replace('void main() {', 'uniform mat4 nikReflMatrix;\nvarying vec2 vNikXZ;\nvarying vec4 vNikRefl;\nvoid main() {')
      .replace(
        '#include <project_vertex>',
        '#include <project_vertex>\nvec4 nikW = modelMatrix * vec4(transformed, 1.0);\nvNikXZ = nikW.xz;\nvNikRefl = nikReflMatrix * nikW;',
      )
    sh.fragmentShader = sh.fragmentShader
      .replace(
        'void main() {',
        'varying vec2 vNikXZ;\nvarying vec4 vNikRefl;\nuniform float nikLight;\nuniform sampler2D nikReflSharp;\nuniform sampler2D nikReflBlur;\nuniform float nikReflStrength;\nvoid main() {',
      )
      .replace(
        '#include <opaque_fragment>',
        `// planar reflection (mirror rendered in linear HDR), slightly distorted by the stone's normal map
         vec2 nikRuv = vNikRefl.xy / vNikRefl.w + normal.xy * 0.012;
         float nikNdV = clamp(dot(normal, normalize(vViewPosition)), 0.0, 1.0);
         float nikFr = 0.04 + 0.96 * pow(1.0 - nikNdV, 5.0);
         float nikGloss = clamp(1.0 - roughnessFactor, 0.0, 1.0);
         vec3 nikRefl = mix(texture2D(nikReflBlur, nikRuv).rgb, texture2D(nikReflSharp, nikRuv).rgb, nikGloss * nikGloss * 0.55);
         outgoingLight += nikRefl * nikFr * nikReflStrength * (0.3 + 0.7 * nikGloss);
         #include <opaque_fragment>
         float nikR = length(vNikXZ);
         float nikT = max(0.0, nikR - mix(1.1, 2.6, nikLight));
         float nikF = exp(-(nikT * nikT) / mix(1.9, 4.0, nikLight));
         nikF *= 1.0 - smoothstep(5.6, 6.8, max(abs(vNikXZ.x), abs(vNikXZ.y)));
         float nikN = fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715))));
         gl_FragColor.a = clamp(nikF + (nikN - 0.5) / 48.0, 0.0, 1.0);`,
      )
  }
  mat.customProgramCacheKey = () => 'nik-lm-floor'
}

/** polished onyx / lacquered walnut: physical material with a clear coat over the PBR base */
const COATS: Record<string, { clearcoat: number; clearcoatRoughness: number }> = {
  'Material #-2147483589': { clearcoat: 1.0, clearcoatRoughness: 0.07 },
  'Material #76111117': { clearcoat: 0.45, clearcoatRoughness: 0.28 },
}
function toPhysical(src: THREE.MeshStandardMaterial) {
  const coat = COATS[src.name]
  if (!coat) return src.clone()
  const m = new THREE.MeshPhysicalMaterial()
  THREE.MeshStandardMaterial.prototype.copy.call(m, src)
  m.clearcoat = coat.clearcoat
  m.clearcoatRoughness = coat.clearcoatRoughness
  return m
}

interface Setup {
  mixers: LightmapMixer[]
  faucet: THREE.Mesh | null
  floor: THREE.Object3D | null
}
const setups = new WeakMap<THREE.Object3D, Setup>()

const RELIEF: Record<string, number> = { 'Material #-2147483589': 1.7, Floor_Travertine: 1.9, 'Material #76111117': 1.3 }
let maxAniso = 8

function setupScene(root: THREE.Object3D, assets: Assets): Setup {
  const cached = setups.get(root)
  if (cached) return cached
  const mixers: LightmapMixer[] = []
  const range = assets.manifest.rgbmRange
  let faucet: THREE.Mesh | null = null
  let floor: THREE.Object3D | null = null
  root.traverse((o) => {
    if (o.name === 'Faucets' && o instanceof THREE.Mesh) faucet = o
    if (o.name === 'Floor') floor = o
    const info = assets.manifest.objects[o.name]
    if (!info) return
    const lm = assets.textures[o.name]
    const pl = assets.perLight[o.name]?.pol
    const isIsland = o.name === 'Island'
    const groups = GROUPS.filter((g) => lm[g] && !(isIsland && g === 'ostrov'))
    const mixer = new LightmapMixer(
      info.size,
      groups.map((g) => ({ group: g, tex: lm[g]!.tex, scale: lm[g]!.scale })),
      range,
      pl ? { group: 'pol', ...pl } : undefined,
    )
    mixers.push(mixer)
    let ostrovMixer: LightmapMixer | null = null
    if (isIsland && lm.ostrov) {
      ostrovMixer = new LightmapMixer(info.size, [{ group: 'ostrov', tex: lm.ostrov.tex, scale: lm.ostrov.scale }], range)
      mixers.push(ostrovMixer)
    }
    o.traverse((m) => {
      if (!(m instanceof THREE.Mesh)) return
      const src = (m.userData.nikSrc ??= m.material) as THREE.MeshStandardMaterial
      const mat = toPhysical(src)
      mat.lightMap = mixer.target.texture
      mat.lightMapIntensity = Math.PI
      const nik = src.userData?.nik ? JSON.parse(src.userData.nik) : null
      const glow = isIsland && nik?.translucency && ostrovMixer
      if (glow) {
        mat.emissive = new THREE.Color(1, 1, 1)
        mat.emissiveIntensity = 1
        mat.emissiveMap = assets.extra[src.name] ?? null
      }
      patchLightmapped(mat, glow ? ostrovMixer!.target.texture : undefined)
      if (o.name === 'Floor') {
        patchFloor(mat)
        mat.transparent = true // dissolves into the backdrop by alpha
      }
      // texture crispness at grazing angles + a bit more surface relief
      for (const t of [mat.map, mat.normalMap, mat.roughnessMap, mat.metalnessMap, mat.emissiveMap]) if (t) t.anisotropy = maxAniso
      if (mat.normalMap) mat.normalScale.multiplyScalar(RELIEF[src.name] ?? 1.3)
      m.material = mat
    })
  })
  if (faucet) {
    const f = faucet as THREE.Mesh
    f.material = (f.material as THREE.MeshStandardMaterial).clone()
    anchors.faucet = new THREE.Box3().setFromObject(f).getCenter(new THREE.Vector3())
  }
  const setup = { mixers, faucet, floor }
  setups.set(root, setup)
  return setup
}

/** faucet finishes (linear colours) */
const FINISH_PARAMS: Record<FaucetFinish, { color: THREE.Color; metalness: number; roughness: number; env: number }> = {
  black: { color: new THREE.Color(0.028, 0.026, 0.024), metalness: 0.6, roughness: 0.42, env: 1.0 },
  brass: { color: new THREE.Color(0.95, 0.72, 0.36), metalness: 1.0, roughness: 0.22, env: 1.6 },
  beige: { color: new THREE.Color(0.7, 0.6, 0.47), metalness: 0.0, roughness: 0.48, env: 1.8 },
}
const HOVER_TINT = new THREE.Color(0.05, 0.035, 0.02)
/** look of the two moods (HDRI rotation puts the window behind-left of the hero camera) */
export const moodLook = { dayRotation: 1.6, dayBackdrop: 0.08, dayBlur: 0.12, dayEnv: 0.35, nightBackdrop: 0.35, nightEnv: 0.85, nightBounce: 0.22 }

function makeLive(): LiveMix {
  return {
    groups: { kitchen: new THREE.Vector3(), ostrov: new THREE.Vector3(), pol: new THREE.Vector3(), env: new THREE.Vector3() },
    lights: { pol: [] },
  }
}

export function Kitchen() {
  const gl = useThree((s) => s.gl)
  const scene = useThree((s) => s.scene)
  const gltf = useGLTF(`${BASE}assets/scene.glb`, false, true, (loader) => {
    // drei types the loader from three-stdlib; the three KTX2Loader is runtime-compatible
    loader.setKTX2Loader(getKTX2(gl) as never)
  })
  const assets = suspend(() => loadAssets(gl), ['nik-lightmaps'])
  const hdr = suspend(async () => {
    const t = await new HDRLoader().loadAsync(`${BASE}assets/env/lebombo_2k.hdr`)
    t.mapping = THREE.EquirectangularReflectionMapping
    return t
  }, ['nik-hdr'])
  maxAniso = gl.capabilities.getMaxAnisotropy()
  const { mixers, faucet, floor } = useMemo(() => setupScene(gltf.scene, assets), [gltf, assets])
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera
  const size = useThree((s) => s.size)
  const dpr = useThree((s) => s.viewport.dpr)
  const envs = useMemo(
    () => ({ ...buildEnvironments(gl), day: buildDayEnvironment(gl, hdr), nightBg: makeNightBackdrop() }),
    [gl, hdr],
  )
  const reflection = useMemo(() => new PlanarReflection(0.5), [])
  useEffect(() => () => reflection.dispose(), [reflection])
  const liveMix = useRef<LiveMix>(null!)
  if (!liveMix.current) liveMix.current = makeLive()
  const first = useRef(true)
  const faucetHover = useRef(false)

  useFrame((_, dt) => {
    const s = useStore.getState()
    const lm = liveMix.current
    let changed = first.current
    // room bounce is a daylight thing: at night only a little of it stays (light pool around the island)
    const bounce = moodLook.nightBounce + (1 - moodLook.nightBounce) * live.light
    for (const g of GROUPS) {
      const m = s.mix[g]
      const k = (m.enabled ? m.intensity : 0) * (g === 'env' ? bounce : 1)
      const v = lm.groups[g]
      const tx = m.color[0] * k
      const ty = m.color[1] * k
      const tz = m.color[2] * k
      if (first.current) v.set(tx, ty, tz)
      const nx = approach(v.x, tx, dt, 4.5)
      const ny = approach(v.y, ty, dt, 4.5)
      const nz = approach(v.z, tz, dt, 4.5)
      if (Math.abs(nx - v.x) + Math.abs(ny - v.y) + Math.abs(nz - v.z) > 1e-5) changed = true
      v.set(nx, ny, nz)
    }
    const lamps = (lm.lights.pol ??= [])
    s.lamps.forEach((on, i) => {
      const t = on ? 1 : 0
      const cur = lamps[i] ?? t
      const n = first.current ? t : approach(cur, t, dt, 5)
      if (Math.abs(n - cur) > 1e-5 || lamps[i] === undefined) changed = true
      lamps[i] = n
    })
    if (changed) for (const m of mixers) m.render(gl, lm)
    first.current = false
    lampsLive.values = lamps
    lampsLive.group = lm.groups.pol.x / Math.max(1e-6, MIX_DEFAULTS.pol.color[0] * MIX_DEFAULTS.pol.intensity)

    // bright gallery space follows the kitchen light (0 = dark room)
    const kd = MIX_DEFAULTS.kitchen.intensity
    const kTarget = s.mix.kitchen.enabled ? Math.min(1, s.mix.kitchen.intensity / kd) : 0
    live.light = approach(live.light, kTarget, dt, 2.2)
    floorUniforms.nikLight.value = live.light
    // day: real interior HDRI (blurred backdrop + reflections); night: bronze room + dark gradient.
    // The swap happens at the dimmest point of the transition, so it reads as lights going down / up.
    const L = live.light
    const ease = (x: number) => x * x * (3 - 2 * x)
    scene.backgroundRotation.set(0, moodLook.dayRotation, 0)
    scene.environmentRotation.set(0, moodLook.dayRotation, 0)
    if (L >= 0.5) {
      scene.background = hdr
      scene.backgroundBlurriness = moodLook.dayBlur
      scene.backgroundIntensity = moodLook.dayBackdrop * ease(Math.min(1, (L - 0.5) * 2))
      scene.environment = envs.day
      scene.environmentIntensity = s.envIntensity * moodLook.dayEnv
    } else {
      scene.background = envs.nightBg
      scene.backgroundBlurriness = 0
      scene.backgroundIntensity = moodLook.nightBackdrop * ease(Math.min(1, (0.5 - L) * 2))
      scene.environment = envs.dark
      scene.environmentIntensity = s.envIntensity * moodLook.nightEnv
    }

    // mirror pass for the honed travertine floor (rendered before the main pass)
    reflection.setSize(size.width * dpr, size.height * dpr)
    camera.updateMatrixWorld()
    reflection.update(gl, scene, camera, floor ? [floor] : [])
    floorUniforms.nikReflSharp.value = reflection.sharp.texture
    floorUniforms.nikReflBlur.value = reflection.blurred.texture
    floorUniforms.nikReflMatrix.value.copy(reflection.textureMatrix)

    if (faucet) {
      const mat = faucet.material as THREE.MeshStandardMaterial
      const p = FINISH_PARAMS[s.finish]
      const k = 1 - Math.exp(-dt * 5)
      mat.color.lerp(p.color, k)
      mat.metalness += (p.metalness - mat.metalness) * k
      mat.roughness += (p.roughness - mat.roughness) * k
      mat.envMapIntensity += (p.env - mat.envMapIntensity) * k
      mat.emissive.lerp(faucetHover.current && s.focus !== 'faucet' ? HOVER_TINT : new THREE.Color(0, 0, 0), k)
    }
  })

  useEffect(() => {
    if (!useStore.getState().dev) return
    Object.assign(window, { __nik: { gl, scene, mixers, assets, THREE, store: useStore, reflection, floorUniforms, moodLook, sssUniform } })
    Promise.all([import('../dev/solveCamera'), import('../dev/cameraSpecs')]).then(([m, c]) =>
      Object.assign(window, { __solveCamera: (spec: never) => m.solveCamera(scene, spec), __cameraSpecs: c.cameraSpecs }),
    )
  }, [gl, scene, mixers, assets, reflection])

  const setHover = useStore((s) => s.setHover)
  const onMove = (e: ThreeEvent<PointerEvent>) => {
    const isFaucet = e.object.name === 'Faucets'
    if (isFaucet !== faucetHover.current) {
      faucetHover.current = isFaucet
      document.body.style.cursor = isFaucet ? 'pointer' : ''
      setHover(isFaucet && useStore.getState().focus !== 'faucet' ? { label: 'Faucet', hint: 'Click to choose a finish' } : null)
    }
  }
  const onOut = () => {
    if (faucetHover.current) {
      faucetHover.current = false
      document.body.style.cursor = ''
      setHover(null)
    }
  }
  const onClick = (e: ThreeEvent<MouseEvent>) => {
    if (e.delta > 4) return // was a drag (orbit)
    if (e.object.name === 'Faucets') {
      e.stopPropagation()
      setHover(null)
      useStore.getState().setFocus('faucet')
    }
  }
  const onDoubleClick = (e: ThreeEvent<MouseEvent>) => {
    if (e.object.name !== 'Floor') return
    e.stopPropagation()
    window.dispatchEvent(new CustomEvent('nik-move-to', { detail: e.point.toArray() }))
  }

  return (
    <>
      <Bvh firstHitOnly>
        <primitive object={gltf.scene} onPointerMove={onMove} onPointerOut={onOut} onClick={onClick} onDoubleClick={onDoubleClick} />
      </Bvh>
    </>
  )
}
