import { useFrame, useThree, type ThreeEvent } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import { suspend } from 'suspend-react'
import * as THREE from 'three'
import { acceleratedRaycast, MeshBVH } from 'three-mesh-bvh'
import { MeshoptDecoder } from 'three/examples/jsm/libs/meshopt_decoder.module.js'
import { GLTFLoader, type GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { KTX2Loader } from 'three/examples/jsm/loaders/KTX2Loader.js'
import { expectFiles, fetchBuffer, fetchParts, fileDone, reportBytes, useLoad } from '../loading'
import { MIX_DEFAULTS, useStore, type FaucetFinish } from '../store'
import { setupChandelier } from './Chandelier'
import { buildWalkCollider } from './Walk'
import { makeSkyBackdrop } from './envs'
import { GROUPS, LightmapMixer, loadLightmapTexture, type GroupId, type LightmapManifest, type LiveMix } from './lightmix'
import { anchors, approach, lampsLive, live } from './live'
import { PlanarReflection } from './PlanarReflection'
import { PROBE_PARS, probeUniforms, RoomProbes } from './probe'

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

/** KTX2 with byte progress for the preloader */
function loadKTX2(loader: KTX2Loader, rel: string) {
  return loader.loadAsync(BASE + rel, (e) => reportBytes(rel, e.loaded, e.total || undefined)).then((t) => {
    fileDone(rel)
    return t
  })
}

async function loadAssets(gl: THREE.WebGLRenderer, manifest: LightmapManifest): Promise<Assets> {
  const loader = getKTX2(gl)
  const textures: Assets['textures'] = {}
  const perLight: Assets['perLight'] = {}
  const jobs: Promise<unknown>[] = []
  for (const [obj, info] of Object.entries(manifest.objects)) {
    textures[obj] = {}
    perLight[obj] = {}
    for (const g of GROUPS) {
      const src = info.groups[g]
      if (src)
        jobs.push(
          loadLightmapTexture(() => loadKTX2(loader, src.url), info.mipmaps).then((tex) => (textures[obj][g] = { tex, scale: src.scale })),
        )
      const pl = info.perLight?.[g]
      if (pl) {
        jobs.push(
          Promise.all(pl.urls.map((u) => loadLightmapTexture(() => loadKTX2(loader, u)))).then(
            (texs) => (perLight[obj][g] = { textures: texs, scale: pl.scale, count: pl.count }),
          ),
        )
      }
    }
  }
  const extra: Record<string, THREE.Texture> = {}
  for (const [name, url] of Object.entries(manifest.textures ?? {})) {
    jobs.push(
      loadKTX2(loader, url).then((t) => {
        t.colorSpace = name === 'perf_mask' ? THREE.NoColorSpace : THREE.SRGBColorSpace
        t.flipY = false
        t.wrapS = t.wrapT = THREE.RepeatWrapping
        extra[name] = t
      }),
    )
  }
  await Promise.all(jobs)
  return { manifest, textures, perLight, extra }
}

interface Loaded {
  gltf: GLTF
  chandelier: GLTF | null
  assets: Assets
}

/** everything the first frame needs, fetched in parallel with byte-accurate progress */
async function loadAll(gl: THREE.WebGLRenderer): Promise<Loaded> {
  const manifest: LightmapManifest = await (await fetch(`${BASE}assets/lightmaps.json`)).json()
  expectFiles(manifest.bytes ?? {})
  const gltfLoader = new GLTFLoader().setKTX2Loader(getKTX2(gl)).setMeshoptDecoder(MeshoptDecoder)
  const glb = (rel: string) => {
    const parts = manifest.parts?.[rel]
    return (parts ? fetchParts(BASE, parts) : fetchBuffer(BASE, rel)).then((buf) =>
      gltfLoader.parseAsync(buf, `${BASE}assets/`),
    )
  }
  const [gltf, chandelier, assets] = await Promise.all([
    glb('assets/scene.glb'),
    glb('assets/chandelier.glb').catch((e) => {
      console.warn('chandelier not loaded', e)
      fileDone('assets/chandelier.glb')
      return null
    }),
    loadAssets(gl, manifest),
  ])
  return { gltf, chandelier, assets }
}

// ------------------------------------------------------------------------------------------------ shading
const sssUniform = { value: 0.55 }

/** live LightMix weights shared by every room material (lightmap atlases and per-vertex lightmaps) */
export const roomUniforms = {
  nikWK: { value: new THREE.Vector3(1, 1, 1) },
  nikWE: { value: new THREE.Vector3(1, 1, 1) },
  nikRange: { value: 16 },
  nikVxSK: { value: 1 },
  nikVxSE: { value: 1 },
  /** specular occlusion from the baked light: reflections fade where the room is dark */
  nikSORef: { value: 0.6 },
  nikSOAmt: { value: 0.6 },
}

/**
 * Planar reflection of the honed travertine (mirror pass at half resolution, blurred), Fresnel x gloss.
 */
export const floorUniforms = {
  nikReflSharp: { value: null as THREE.Texture | null },
  nikReflBlur: { value: null as THREE.Texture | null },
  nikReflMatrix: { value: new THREE.Matrix4() },
  nikReflStrength: { value: 1.2 },
}

type LightKind = 'mixer' | 'direct' | 'vertex' | 'none'
interface PatchOpts {
  kind: LightKind
  ostrov?: THREE.Texture
  envLm?: { tex: THREE.Texture; sK: number; sE: number }
  floor?: boolean
  perforated?: THREE.Texture
}

/**
 * One shader patch for every room material:
 *  - irradiance from the baked light (mixed lightmap / two RGBM atlases mixed live / per-vertex RGBM) instead of IBL
 *  - reflections from the box-projected room probes, faded by the baked light (specular occlusion)
 *  - extras: onyx inner glow + SSS, floor planar reflection, perforated bronze holes
 */
function patchRoom(mat: THREE.MeshStandardMaterial, o: PatchOpts) {
  mat.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, roomUniforms, probeUniforms)
    sh.uniforms.nikSss = sssUniform
    if (o.ostrov) sh.uniforms.nikOstrov = { value: o.ostrov }
    if (o.envLm) {
      sh.uniforms.nikLmE = { value: o.envLm.tex }
      sh.uniforms.nikSK = { value: o.envLm.sK }
      sh.uniforms.nikSE = { value: o.envLm.sE }
    }
    if (o.floor) Object.assign(sh.uniforms, floorUniforms)
    if (o.perforated) sh.uniforms.nikPerf = { value: o.perforated }

    // ---- vertex: world position (probes, floor mirror), per-vertex light
    let vHead = 'varying vec3 vNikWP;\n'
    let vBody = 'vNikWP = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;\n'
    if (o.kind === 'vertex') {
      vHead += 'attribute vec4 nikK;\nattribute vec4 nikE;\nuniform vec3 nikWK;\nuniform vec3 nikWE;\nuniform float nikRange;\nuniform float nikVxSK;\nuniform float nikVxSE;\nvarying vec3 vNikIrr;\n'
      vBody += 'vNikIrr = nikK.rgb * nikK.a * nikRange / nikVxSK * nikWK + nikE.rgb * nikE.a * nikRange / nikVxSE * nikWE;\n'
    }
    if (o.floor) {
      vHead += 'uniform mat4 nikReflMatrix;\nvarying vec4 vNikRefl;\n'
      vBody += 'vNikRefl = nikReflMatrix * vec4( vNikWP, 1.0 );\n'
    }
    sh.vertexShader = sh.vertexShader
      .replace('void main() {', vHead + 'void main() {')
      .replace('#include <project_vertex>', '#include <project_vertex>\n' + vBody)

    // ---- fragment
    let fHead = 'uniform float nikSss;\nuniform float nikSORef;\nuniform float nikSOAmt;\n'
    if (o.kind === 'vertex') fHead += 'varying vec3 vNikIrr;\n'
    if (o.envLm) fHead += 'uniform sampler2D nikLmE;\nuniform float nikSK;\nuniform float nikSE;\nuniform vec3 nikWK;\nuniform vec3 nikWE;\nuniform float nikRange;\n'
    if (o.ostrov) fHead += 'uniform sampler2D nikOstrov;\n'
    if (o.floor) fHead += 'varying vec4 vNikRefl;\nuniform sampler2D nikReflSharp;\nuniform sampler2D nikReflBlur;\nuniform float nikReflStrength;\n'
    if (o.perforated) fHead += 'uniform sampler2D nikPerf;\n'
    sh.fragmentShader = sh.fragmentShader.replace('void main() {', fHead + 'void main() {')

    // box-projected probes instead of the plain env lookups
    sh.fragmentShader = sh.fragmentShader.replace(
      '#include <envmap_physical_pars_fragment>',
      THREE.ShaderChunk.envmap_physical_pars_fragment
        .replace('#ifdef USE_ENVMAP', '#ifdef USE_ENVMAP\n' + PROBE_PARS)
        .replace(
          'vec4 envMapColor = textureCubeUV( envMap, envMapRotation * worldNormal, 1.0 );',
          'vec4 envMapColor = nikProbe( worldNormal, 1.0 );',
        )
        .replace(
          'vec4 envMapColor = textureCubeUV( envMap, envMapRotation * reflectVec, roughness );',
          'vec4 envMapColor = nikProbe( reflectVec, roughness );',
        ),
    )

    // irradiance source (nikIrrSO keeps it for the specular occlusion below)
    let maps = 'vec3 nikIrrSO = vec3( nikSORef );\n' + THREE.ShaderChunk.lights_fragment_maps
    if (o.kind !== 'none') maps = maps.replace('iblIrradiance += getIBLIrradiance( geometryNormal );', '')
    if (o.envLm) {
      maps = maps.replace(
        'vec3 lightMapIrradiance = lightMapTexel.rgb * lightMapIntensity;',
        `vec4 nikE4 = texture2D( nikLmE, vLightMapUv );
         vec3 lightMapIrradiance = ( lightMapTexel.rgb * lightMapTexel.a * nikRange / nikSK * nikWK
           + nikE4.rgb * nikE4.a * nikRange / nikSE * nikWE ) * lightMapIntensity;`,
      )
    }
    if (o.kind === 'mixer' || o.kind === 'direct')
      maps = maps.replace('irradiance += lightMapIrradiance;', 'irradiance += lightMapIrradiance;\nnikIrrSO = lightMapIrradiance;')
    if (o.kind === 'vertex') maps = maps.replace('#ifdef USE_LIGHTMAP', 'irradiance += vNikIrr * PI;\nnikIrrSO = vNikIrr * PI;\n#ifdef USE_LIGHTMAP')
    // specular occlusion: reflections of the (bright) probe are toned down where the baked light is dark
    if (o.kind !== 'none') {
      maps = maps.replace(
        'radiance += iblRadiance;',
        `float nikL = dot( nikIrrSO, vec3( 0.2126, 0.7152, 0.0722 ) );
         radiance += iblRadiance * mix( 1.0, clamp( sqrt( nikL / nikSORef ), 0.08, 1.0 ), nikSOAmt );`,
      )
    }
    sh.fragmentShader = sh.fragmentShader.replace('#include <lights_fragment_maps>', maps)

    if (o.ostrov) {
      sh.fragmentShader = sh.fragmentShader.replace(
        '#include <emissivemap_fragment>',
        THREE.ShaderChunk.emissivemap_fragment.replace(
          'totalEmissiveRadiance *= emissiveColor.rgb;',
          // inner glow + subsurface scattering: light hitting the stone spreads softly inside it
          'totalEmissiveRadiance *= emissiveColor.rgb * ( texture2D( nikOstrov, vLightMapUv ).rgb + textureLod( lightMap, vLightMapUv, 3.5 ).rgb * nikSss );',
        ),
      )
    }
    if (o.perforated) {
      // holes: dark cavities (same tile as the bevel normal map)
      sh.fragmentShader = sh.fragmentShader
        .replace(
          '#include <roughnessmap_fragment>',
          '#include <roughnessmap_fragment>\nfloat nikHole = texture2D( nikPerf, vNormalMapUv ).r;\nroughnessFactor = mix( 0.9, roughnessFactor, nikHole );',
        )
        .replace('#include <metalnessmap_fragment>', '#include <metalnessmap_fragment>\nmetalnessFactor *= nikHole;\ndiffuseColor.rgb *= mix( 0.02, 1.0, nikHole );')
    }
    if (o.floor) {
      sh.fragmentShader = sh.fragmentShader.replace(
        '#include <opaque_fragment>',
        `vec2 nikRuv = vNikRefl.xy / vNikRefl.w + normal.xy * 0.012;
         float nikNdV = clamp( dot( normal, normalize( vViewPosition ) ), 0.0, 1.0 );
         float nikFr = 0.04 + 0.96 * pow( 1.0 - nikNdV, 5.0 );
         float nikGloss = clamp( 1.0 - roughnessFactor, 0.0, 1.0 );
         vec3 nikRefl = mix( texture2D( nikReflBlur, nikRuv ).rgb, texture2D( nikReflSharp, nikRuv ).rgb, nikGloss * nikGloss * 0.55 );
         outgoingLight += nikRefl * nikFr * nikReflStrength * ( 0.3 + 0.7 * nikGloss );
         #include <opaque_fragment>`,
      )
    }
  }
  const key = ['nik', o.kind, o.envLm ? 'e' : '', o.ostrov ? 'o' : '', o.floor ? 'f' : '', o.perforated ? 'p' : ''].join('-')
  mat.customProgramCacheKey = () => key
}

/** polished onyx / lacquered walnut: physical material with a clear coat over the PBR base */
const COATS: Record<string, { clearcoat: number; clearcoatRoughness: number }> = {
  'Material #-2147483589': { clearcoat: 1.0, clearcoatRoughness: 0.07 },
  'Material #76111117': { clearcoat: 0.45, clearcoatRoughness: 0.28 },
}
/** per-material corrections of the Corona conversion (orig. Max material name) */
const TWEAKS: Record<string, Partial<{ ior: number; roughness: number; dropRoughnessMap: boolean; env: number; tint: [number, number, number] }>> = {
  // bronze (perforated walls, kitchen box, ceiling): the Corona reflection colour tints the grey brushed-metal map
  'Material #2147483647': { tint: [1.0, 0.68, 0.46] },
  'Material #-2147483422': { tint: [1.0, 0.68, 0.46] },
  'Material #-2147483644': { tint: [1.0, 0.72, 0.5] },
  // honed travertine: the reflection map is missing from the archive -> Corona IOR 3 alone reads as a wet mirror
  travertine7567567: { ior: 1.5, roughness: 0.5, dropRoughnessMap: true },
  travertine: { ior: 1.5, roughness: 0.5, dropRoughnessMap: true },
  // photo backdrops of the view outside the windows: a print, not a mirror
  'Material #-2147483574': { roughness: 1, env: 0 },
  // sofa cushions (accent fabric): their gloss map is missing from the archive
  'Material #-214748313700675': { roughness: 0.85, env: 0.3 },
}
const RELIEF: Record<string, number> = { 'Material #-2147483589': 1.7, travertine7567567: 1.6, 'Material #76111117': 1.3 }

interface Nik {
  orig?: string
  translucency?: { colorTex?: string }
  perforated?: boolean
  glass?: boolean
  emissive?: number
  metal?: boolean
  surface?: 'fabric' | 'leather'
}
function nikOf(m: THREE.Material): Nik {
  try {
    return m.userData?.nik ? JSON.parse(m.userData.nik) : {}
  } catch {
    return {}
  }
}

function toPhysical(src: THREE.MeshStandardMaterial, nik: Nik) {
  const coat = COATS[nik.orig ?? '']
  if (!coat) return src.clone()
  const m = new THREE.MeshPhysicalMaterial()
  THREE.MeshStandardMaterial.prototype.copy.call(m, src)
  m.clearcoat = coat.clearcoat
  m.clearcoatRoughness = coat.clearcoatRoughness
  return m
}

/** window panes and the glass sculpture: thin, clear, mostly reflection (no refraction pass) */
/**
 * Exterior windows and glass doors: like the renders, an over-exposed daylight glow by day (and nothing of the
 * cropped villa outside shows through); dark glass reflecting the interior in the evening (see useFrame).
 */
const WINDOW_GLASS = new Set(['glass clear', 'Glass'])
function toWindow(src: THREE.MeshStandardMaterial) {
  const m = new THREE.MeshPhysicalMaterial({
    color: new THREE.Color(0.02, 0.02, 0.022),
    emissive: new THREE.Color(1.0, 0.97, 0.92),
    emissiveIntensity: 3,
    metalness: 0,
    roughness: 0.04,
    transparent: true,
    opacity: 0.96,
    envMapIntensity: 1.2,
    side: THREE.DoubleSide,
  })
  m.name = src.name
  return m
}

function toGlass(src: THREE.MeshStandardMaterial) {
  const m = new THREE.MeshPhysicalMaterial({
    color: src.color.clone().lerp(new THREE.Color(1, 1, 1), 0.5),
    metalness: 0,
    roughness: Math.min(0.08, src.roughness),
    transparent: true,
    opacity: 0.18,
    depthWrite: false,
    envMapIntensity: 1.4,
    side: THREE.DoubleSide,
  })
  m.name = src.name
  return m
}

interface Setup {
  mixers: LightmapMixer[]
  faucet: THREE.Mesh | null
  floors: THREE.Object3D[]
  glass: THREE.Object3D[]
  /** emissive lenses of the floor uplights (dimmed with the circuit) */
  lenses: { mat: THREE.MeshStandardMaterial; base: number }[]
  windows: THREE.MeshPhysicalMaterial[]
}
const POL_LENS = 'Material #-2147483616'
const setups = new WeakMap<THREE.Object3D, Setup>()

/** scene parts other modules need (camera collision, first-person walking) */
export const world = {
  /** architecture: walls, ceilings, floors, glass - the orbit camera never passes them */
  colliders: [] as THREE.Mesh[],
  /** everything the walker bumps into: architecture + island, table, dense furniture */
  walkSources: [] as THREE.Mesh[],
}
let maxAniso = 8

function setupScene(root: THREE.Object3D, assets: Assets): Setup {
  const cached = setups.get(root)
  if (cached) return cached
  const mixers: LightmapMixer[] = []
  const range = assets.manifest.rgbmRange
  roomUniforms.nikRange.value = range
  const vx = assets.manifest.vertex
  if (vx) {
    roomUniforms.nikVxSK.value = vx.scales.kitchen ?? 1
    roomUniforms.nikVxSE.value = vx.scales.env ?? 1
  }
  const vxNames = new Set(vx?.objects ?? [])
  let faucet: THREE.Mesh | null = null
  const floors: THREE.Object3D[] = []
  const glass: THREE.Object3D[] = []
  const lenses: Setup['lenses'] = []
  const windows: THREE.MeshPhysicalMaterial[] = []

  const prep = (m: THREE.Mesh, kind: LightKind, extra: Omit<PatchOpts, 'kind'> = {}, lightMap?: THREE.Texture) => {
    const src = (m.userData.nikSrc ??= m.material) as THREE.MeshStandardMaterial
    const nik = nikOf(src)
    if (nik.glass) {
      const win = WINDOW_GLASS.has(nik.orig ?? '')
      m.material = win ? toWindow(src) : toGlass(src)
      if (win) windows.push(m.material as THREE.MeshPhysicalMaterial)
      glass.push(m)
      return
    }
    const mat = toPhysical(src, nik)
    mat.vertexColors = false
    const tw = TWEAKS[nik.orig ?? '']
    if (tw) {
      if (tw.roughness !== undefined) mat.roughness = tw.roughness
      if (tw.dropRoughnessMap) mat.roughnessMap = null
      if (tw.ior !== undefined && mat instanceof THREE.MeshPhysicalMaterial) mat.ior = tw.ior
    }
    if (lightMap) {
      mat.lightMap = lightMap
      mat.lightMapIntensity = Math.PI
    }
    const perforated = nik.perforated ? assets.extra.perf_mask : undefined
    patchRoom(mat, { kind, perforated, ...extra })
    for (const t of [mat.map, mat.normalMap, mat.roughnessMap, mat.metalnessMap, mat.emissiveMap]) if (t) t.anisotropy = maxAniso
    if (mat.normalMap) mat.normalScale.multiplyScalar(RELIEF[nik.orig ?? ''] ?? (nik.surface === 'fabric' ? 0.7 : 1.0))
    // how much each kind of surface mirrors the room: metals live on reflections, textiles barely reflect
    mat.envMapIntensity = nik.metal ? 1.5 : nik.surface === 'fabric' ? 0.3 : nik.surface === 'leather' ? 0.7 : 0.9
    if (nik.surface === 'fabric') mat.roughness = Math.max(mat.roughness, 0.88)
    // roughness exactly 0 on a dielectric without a map = a Corona gloss map that did not survive the export
    if (!nik.metal && !mat.roughnessMap && mat.roughness < 0.02 && !COATS[nik.orig ?? '']) mat.roughness = 0.3
    if (tw?.roughness !== undefined) mat.roughness = tw.roughness
    if (tw?.env !== undefined) mat.envMapIntensity = tw.env
    if (tw?.tint) mat.color.multiply(new THREE.Color(...tw.tint))
    if (nik.surface === 'leather') {
      // the leather gloss maps read as patent leather under real-time IBL: soft satin instead
      mat.roughnessMap = null
      mat.roughness = 0.55
    }
    m.material = mat
    if (nik.orig === POL_LENS) lenses.push({ mat, base: mat.emissiveIntensity })
  }

  root.traverse((o) => {
    if (o.name === 'Faucets' && o instanceof THREE.Mesh) faucet = o
    if (o.name.startsWith('Floor')) floors.push(o)
  })
  const done = new Set<THREE.Object3D>()
  root.traverse((o) => {
    if (done.has(o)) return
    const info = assets.manifest.objects[o.name]
    if (info) {
      o.traverse((c) => done.add(c))
      const lm = assets.textures[o.name]
      const pl = assets.perLight[o.name]?.pol
      const isIsland = o.name === 'Island'
      const isFloor = o.name.startsWith('Floor')
      const big = info.size >= 4096 || !!info.mipmaps
      if (big && lm.kitchen && lm.env) {
        // big atlases: the two RGBM groups are mixed in the material (no 4K float render target)
        const k = lm.kitchen.tex
        k.channel = 1
        o.traverse((m) => {
          if (m instanceof THREE.Mesh) prep(m, 'direct', { envLm: { tex: lm.env!.tex, sK: lm.kitchen!.scale, sE: lm.env!.scale }, floor: isFloor }, k)
        })
        return
      }
      const groups = GROUPS.filter((g) => lm[g] && !(isIsland && g === 'ostrov'))
      const mixer = new LightmapMixer(
        info.size,
        groups.slice(0, 3).map((g) => ({ group: g, tex: lm[g]!.tex, scale: lm[g]!.scale })),
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
        const nik = nikOf(src)
        const glow = isIsland && nik.translucency
        if (glow) {
          // emissive = translucency map x inner light (+ SSS); without an ostrov bake only the SSS term remains
          src.emissive = new THREE.Color(1, 1, 1)
          src.emissiveIntensity = 1
          src.emissiveMap = assets.extra[nik.orig ?? ''] ?? null
        }
        const black = new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1)
        black.needsUpdate = true
        prep(m, 'mixer', { ostrov: glow ? (ostrovMixer?.target.texture ?? black) : undefined, floor: isFloor }, mixer.target.texture)
      })
      return
    }
    if (vxNames.has(o.name)) {
      o.traverse((c) => done.add(c))
      o.traverse((m) => {
        if (!(m instanceof THREE.Mesh)) return
        const g = m.geometry as THREE.BufferGeometry
        // custom attributes _NIKK / _NIKE = RGBM kitchen / daylight irradiance
        const k = g.getAttribute('_nikk')
        const e = g.getAttribute('_nike')
        if (k) g.setAttribute('nikK', k)
        if (e) g.setAttribute('nikE', e)
        prep(m, 'vertex')
      })
      return
    }
    if (o instanceof THREE.Mesh && !done.has(o)) {
      done.add(o)
      prep(o, 'none')
    }
  })
  if (faucet) {
    const f = faucet as THREE.Mesh
    f.material = (f.material as THREE.MeshStandardMaterial).clone()
    anchors.faucet = new THREE.Box3().setFromObject(f).getCenter(new THREE.Vector3())
  }
  // what is solid: architecture stops the orbit camera; the walker also bumps into the island and furniture.
  // Only meshes that are ever ray-cast get a BVH; the dense furniture is skipped by pointer rays altogether.
  world.colliders.length = world.walkSources.length = 0
  root.updateMatrixWorld(true)
  for (const top of root.children) {
    const n = top.name
    const arch = /^(LM_Atlas|Floor|Static|Ground)/.test(n)
    const hero = /^(Island|Table|Planters|Faucets)$/.test(n)
    const dense = /^VX_/.test(n)
    top.traverse((m) => {
      if (!(m instanceof THREE.Mesh)) return
      if (arch) world.colliders.push(m)
      if (arch || hero || dense) world.walkSources.push(m)
      if (arch || hero) {
        m.geometry.boundsTree = new MeshBVH(m.geometry)
        m.raycast = acceleratedRaycast
      } else {
        m.raycast = () => {}
      }
    })
  }
  const setup = { mixers, faucet, floors, glass, lenses, windows }
  setups.set(root, setup)
  return setup
}

/** faucet finishes (linear colours) */
const FINISH_PARAMS: Record<FaucetFinish, { color: THREE.Color; metalness: number; roughness: number; env: number }> = {
  black: { color: new THREE.Color(0.028, 0.026, 0.024), metalness: 0.6, roughness: 0.42, env: 1.0 },
  brass: { color: new THREE.Color(0.95, 0.72, 0.36), metalness: 1.0, roughness: 0.22, env: 1.4 },
  beige: { color: new THREE.Color(0.7, 0.6, 0.47), metalness: 0, roughness: 0.48, env: 1.4 },
}
const HOVER_TINT = new THREE.Color(0.05, 0.035, 0.02)
/** objects left out of the reflection-probe captures (glass, the chandelier) */
export const probeHide: THREE.Object3D[] = []
/** daylight vs evening backdrop seen through the windows */
export const moodLook = { daySky: 7.0, nightSky: 0.05 }

function makeLive(): LiveMix {
  return {
    groups: { kitchen: new THREE.Vector3(), ostrov: new THREE.Vector3(), pol: new THREE.Vector3(), env: new THREE.Vector3() },
    lights: { pol: [] },
  }
}

export function Kitchen() {
  const gl = useThree((s) => s.gl)
  const scene = useThree((s) => s.scene)
  const { gltf, chandelier, assets } = suspend(() => loadAll(gl), ['nik-scene'])
  maxAniso = gl.capabilities.getMaxAnisotropy()
  const { mixers, faucet, floors, glass, lenses, windows } = useMemo(() => {
    if (chandelier) {
      setupChandelier(chandelier.scene, gl)
      if (!probeHide.includes(chandelier.scene)) probeHide.push(chandelier.scene)
    }
    return setupScene(gltf.scene, assets)
  }, [gltf, chandelier, assets, gl])
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera
  const setFrameloop = useThree((s) => s.setFrameloop)
  const raycaster = useThree((s) => s.raycaster)
  raycaster.firstHitOnly = true
  const size = useThree((s) => s.size)
  const dpr = useThree((s) => s.viewport.dpr)
  const sky = useMemo(() => makeSkyBackdrop(), [])
  const reflection = useMemo(() => new PlanarReflection(0.5), [])
  const probes = useMemo(() => new RoomProbes(gl), [gl])
  useEffect(
    () => () => {
      reflection.dispose()
      probes.dispose()
    },
    [reflection, probes],
  )
  const liveMix = useRef<LiveMix>(null!)
  if (!liveMix.current) liveMix.current = makeLive()
  const first = useRef(true)
  const faucetHover = useRef(false)
  const probeAge = useRef(0)
  const probeDirty = useRef(true)
  /** extra captures after a change: reflections of reflections settle in a few bounces */
  const probeBounces = useRef(4)
  const warmFrames = useRef(0)
  const walkBuilt = useRef(false)

  // honest preloader: compile every shader program before the first frame (parallel where supported), then let
  // the light mix + reflection probes settle; only then is the scene revealed
  useEffect(() => {
    let alive = true
    const load = useLoad.getState()
    load.setStage('compile')
    setFrameloop('never')
    scene.environment = probes.prime()
    probeUniforms.nikEnvB.value = probes.env[1]!.texture
    // materials render into the composer's linear HDR target, compile them for that output
    const rt = new THREE.WebGLRenderTarget(4, 4, { type: THREE.HalfFloatType })
    gl.setRenderTarget(rt)
    gl.compileAsync(scene, camera)
      .catch((e) => console.warn('precompile', e))
      .finally(() => {
        gl.setRenderTarget(null)
        rt.dispose()
        if (!alive) return
        load.setStage('warmup')
        setFrameloop('always')
        // first-person collision mesh (BVH in a worker) is part of "ready": walking works from the first second
        buildWalkCollider()
          .catch((e) => console.warn('walk collider', e))
          .finally(() => (walkBuilt.current = true))
      })
    return () => {
      alive = false
    }
  }, [gl, scene, camera, probes, setFrameloop])

  useFrame((_, dt) => {
    const s = useStore.getState()
    if (useLoad.getState().stage === 'warmup') {
      warmFrames.current++
      // probes settled (bounces done) and the frame time is back to normal
      if (warmFrames.current > 12 && probeBounces.current <= 0 && !probeDirty.current && walkBuilt.current && dt < 0.1)
        useLoad.getState().setStage('ready')
    }
    const lm = liveMix.current
    let changed = first.current
    // daylight (sun + sky) follows the day/night switch
    live.light = first.current ? (s.day ? 1 : 0) : approach(live.light, s.day ? 1 : 0, dt, 2.2)
    for (const g of GROUPS) {
      const m = s.mix[g]
      const k = (m.enabled ? m.intensity : 0) * (g === 'env' ? live.light : 1)
      const v = lm.groups[g]
      const tx = m.color[0] * k
      const ty = m.color[1] * k
      const tz = m.color[2] * k
      const nx = first.current ? tx : g === 'env' ? tx : approach(v.x, tx, dt, 4.5)
      const ny = first.current ? ty : g === 'env' ? ty : approach(v.y, ty, dt, 4.5)
      const nz = first.current ? tz : g === 'env' ? tz : approach(v.z, tz, dt, 4.5)
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
    roomUniforms.nikWK.value.copy(lm.groups.kitchen)
    roomUniforms.nikWE.value.copy(lm.groups.env)
    first.current = false
    lampsLive.values = lamps
    lampsLive.group = lm.groups.pol.x / Math.max(1e-6, MIX_DEFAULTS.pol.color[0] * MIX_DEFAULTS.pol.intensity)
    const lensOn = lamps.length ? lamps.reduce((a, b) => a + b, 0) / lamps.length : 1
    for (const l of lenses) l.mat.emissiveIntensity = l.base * lensOn * lampsLive.group
    // windows: daylight glow fading to dark reflective glass
    for (const w of windows) w.emissiveIntensity = 0.015 + 2.6 * live.light * live.light

    // sky through the windows: bright daylight, deep blue evening
    scene.background = sky
    scene.backgroundBlurriness = 0
    scene.backgroundIntensity = moodLook.nightSky + (moodLook.daySky - moodLook.nightSky) * live.light * live.light

    // reflection probes follow the light (throttled while it is changing, once more when it settles)
    probeAge.current++
    if (changed) {
      probeDirty.current = true
      probeBounces.current = 3
    }
    if ((probeDirty.current || probeBounces.current > 0) && (probeAge.current > 6 || !scene.environment)) {
      scene.environment = probes.update(gl, scene, [...glass, ...probeHide])
      probeAge.current = 0
      if (!changed) probeBounces.current--
      probeDirty.current = changed
    }
    scene.environmentIntensity = s.envIntensity

    // mirror pass for the honed travertine floor (rendered before the main pass)
    reflection.setSize(size.width * dpr, size.height * dpr)
    camera.updateMatrixWorld()
    reflection.update(gl, scene, camera, floors)
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
    Object.assign(window, {
      __nik: { gl, scene, mixers, assets, THREE, store: useStore, reflection, floorUniforms, roomUniforms, moodLook, sssUniform, probes, probeUniforms },
    })
    Promise.all([import('../dev/solveCamera'), import('../dev/cameraSpecs')]).then(([m, c]) =>
      Object.assign(window, { __solveCamera: (spec: never) => m.solveCamera(scene, spec), __cameraSpecs: c.cameraSpecs }),
    )
  }, [gl, scene, mixers, assets, reflection, probes])

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
    if (!e.object.name.startsWith('Floor')) return
    e.stopPropagation()
    window.dispatchEvent(new CustomEvent('nik-move-to', { detail: e.point.toArray() }))
  }

  return (
    <>
      <primitive object={gltf.scene} onPointerMove={onMove} onPointerOut={onOut} onClick={onClick} onDoubleClick={onDoubleClick} />
      {chandelier && <primitive object={chandelier.scene} />}
    </>
  )
}
