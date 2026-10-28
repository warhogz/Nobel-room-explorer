import { useFrame, useThree, type ThreeEvent } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import { suspend } from 'suspend-react'
import * as THREE from 'three'
import { acceleratedRaycast, MeshBVH } from 'three-mesh-bvh'
import { MeshoptDecoder } from 'three/examples/jsm/libs/meshopt_decoder.module.js'
import { GLTFLoader, type GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { KTX2Loader } from 'three/examples/jsm/loaders/KTX2Loader.js'
import { expectFiles, fetchBuffer, fetchParts, fileDone, reportBytes, useLoad } from '../loading'
import { ASSETS, guardFullLoad, LITE, MOBILE } from '../lite'
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
  textures: Record<string, Partial<Record<GroupId, { tex: THREE.Texture; scale: number; log?: [number, number] }>>>
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
          loadLightmapTexture(() => loadKTX2(loader, src.url), info.mipmaps).then((tex) => (textures[obj][g] = { tex, scale: src.scale, log: src.log })),
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
  guardFullLoad(true)
  const manifest: LightmapManifest = await (await fetch(`${BASE}${ASSETS}lightmaps.json`)).json()
  // phones: no glass sculpture (it hangs from the ceiling of the room and costs a transmission pass)
  if (LITE && manifest.bytes) delete manifest.bytes['assets/chandelier.glb']
  expectFiles(manifest.bytes ?? {})
  const gltfLoader = new GLTFLoader().setKTX2Loader(getKTX2(gl)).setMeshoptDecoder(MeshoptDecoder)
  const glb = (rel: string) => {
    const parts = manifest.parts?.[rel]
    return (parts ? fetchParts(BASE, parts) : fetchBuffer(BASE, rel)).then((buf) =>
      gltfLoader.parseAsync(buf, `${BASE}${ASSETS}`),
    )
  }
  const [gltf, chandelier, assets] = await Promise.all([
    glb(`${ASSETS}scene.glb`),
    (LITE ? Promise.resolve(null) : glb('assets/chandelier.glb')).catch((e) => {
      console.warn('chandelier not loaded', e)
      fileDone('assets/chandelier.glb')
      return null
    }),
    loadAssets(gl, manifest),
  ])
  return { gltf, chandelier, assets }
}

// ------------------------------------------------------------------------------------------------ shading
// light scattered inside the onyx: a little only (more washed the veins out into a waxy haze)
const sssUniform = { value: 0.18 }

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
  // the daylight baked onto the travertine came out warmer than in Corona (the hall floor read yellow while the walls
  // matched; measured on Corona camera 28): a cooler tint on the travertine's daylight group only
  nikFloorE: { value: new THREE.Vector3(0.85, 1.18, 1.8) },
}

/**
 * "Island only": everything but the island dissolves in a ring sweeping in towards it (a thin warm line at the
 * cut), the floor shrinks to a disc that fades into a studio backdrop (white by day, black in the evening).
 * Radii in metres around the island centre; driven by Kitchen's frame loop.
 */
export const isoUniforms = {
  nikIsoR: { value: 1e4 },
  nikIsoFloorR: { value: 1e4 },
  nikIsoFade: { value: 0.5 },
  nikIsoBg: { value: new THREE.Color(0, 0, 0) },
  nikIsoEdge: { value: 0 },
}
/** island set: stays in the "island only" mode */
const ISO_KEEP = new Set(['Island', 'Planters', 'Faucets'])
/** seconds for the room to dissolve / grow back */
const ISO_TIME = 2.4
/** studio backdrop by day (scene-linear, before the tone mapping: reads as a soft warm white) */
const ISO_BG_DAY = new THREE.Color(0.66, 0.635, 0.6)

type LightKind = 'mixer' | 'direct' | 'vertex' | 'none'
interface PatchOpts {
  kind: LightKind
  ostrov?: THREE.Texture
  envLm?: { tex: THREE.Texture; sK: number; sE: number }
  floor?: boolean
  /** travertine: its baked daylight gets the cooler floor tint (floorUniforms.nikFloorE) */
  dayTint?: boolean
  perforated?: THREE.Texture
  /** "island only" role: kept, the floor disc, or (default) the room that dissolves */
  iso?: 'keep' | 'floor' | 'room'
  /**
   * a shell with no inside (the island has no carcass, the hand shower is a tube): its inner faces are drawn too,
   * at this fraction of their light - the stone wall in the shade behind a groove, not a hole into the backdrop
   */
  hollow?: number
  /** overall light factor (the herb cups sunk in the worktop: dark wells, like the other openings) */
  shade?: number
}

/**
 * One shader patch for every room material:
 *  - irradiance from the baked light (mixed lightmap / two RGBM atlases mixed live / per-vertex RGBM) instead of IBL
 *  - reflections from the box-projected room probes, faded by the baked light (specular occlusion)
 *  - extras: onyx inner glow + SSS, floor planar reflection, perforated bronze holes
 */
function patchRoom(mat: THREE.MeshStandardMaterial, o: PatchOpts) {
  if (o.hollow !== undefined) mat.side = THREE.DoubleSide
  mat.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, roomUniforms, probeUniforms)
    sh.uniforms.nikSss = sssUniform
    if (o.ostrov) sh.uniforms.nikOstrov = { value: o.ostrov }
    if (o.envLm) {
      sh.uniforms.nikLmE = { value: o.envLm.tex }
      sh.uniforms.nikSK = { value: o.envLm.sK }
      sh.uniforms.nikSE = { value: o.envLm.sE }
    }
    if (o.floor || o.dayTint) Object.assign(sh.uniforms, floorUniforms)
    if (o.perforated) sh.uniforms.nikPerf = { value: o.perforated }
    const iso = o.iso ?? 'room'
    if (iso !== 'keep') Object.assign(sh.uniforms, isoUniforms)

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
    if (iso !== 'keep') {
      vHead += 'varying vec2 vNikIso;\n'
      vBody += 'vNikIso = vNikWP.xz;\n'
    }
    sh.vertexShader = sh.vertexShader
      .replace('void main() {', vHead + 'void main() {')
      .replace('#include <project_vertex>', '#include <project_vertex>\n' + vBody)

    // ---- fragment
    let fHead = 'uniform float nikSss;\nuniform float nikSORef;\nuniform float nikSOAmt;\n'
    if (o.kind === 'vertex') fHead += 'varying vec3 vNikIrr;\n'
    if (o.envLm) fHead += 'uniform sampler2D nikLmE;\nuniform float nikSK;\nuniform float nikSE;\nuniform vec3 nikWK;\nuniform vec3 nikWE;\nuniform float nikRange;\n'
    if (o.ostrov) fHead += 'uniform sampler2D nikOstrov;\n'
    if (o.dayTint) fHead += 'uniform vec3 nikFloorE;\n'
    if (o.floor) fHead += 'varying vec4 vNikRefl;\nuniform sampler2D nikReflSharp;\nuniform sampler2D nikReflBlur;\nuniform float nikReflStrength;\n'
    if (o.perforated) fHead += 'uniform sampler2D nikPerf;\n'
    let isoCut = ''
    if (iso !== 'keep') {
      fHead +=
        'varying vec2 vNikIso;\nuniform float nikIsoR;\nuniform float nikIsoFloorR;\nuniform float nikIsoFade;\nuniform vec3 nikIsoBg;\nuniform float nikIsoEdge;\n'
      isoCut = `float nikIsoD = length( vNikIso );\nif ( nikIsoD > ${iso === 'floor' ? 'nikIsoFloorR' : 'nikIsoR'} ) discard;\n`
    }
    sh.fragmentShader = sh.fragmentShader.replace('void main() {', fHead + 'void main() {\n' + isoCut)

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
    // travertine in the big (hall) atlases, mixed here; the kitchen floor matched Corona already
    if (o.dayTint) maps = maps.replace('/ nikSE * nikWE )', '/ nikSE * nikWE * nikFloorE )')
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
          '#include <roughnessmap_fragment>\nfloat nikHole = texture2D( nikPerf, vNormalMapUv, -1.0 ).r;\nroughnessFactor = mix( 0.9, roughnessFactor, nikHole );',
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
    if (iso === 'floor') {
      // the disc fades into the studio backdrop
      sh.fragmentShader = sh.fragmentShader.replace(
        '#include <opaque_fragment>',
        'outgoingLight = mix( outgoingLight, nikIsoBg, smoothstep( nikIsoFloorR - nikIsoFade, nikIsoFloorR, nikIsoD ) );\n#include <opaque_fragment>',
      )
    } else if (iso === 'room') {
      // a thin warm line where the room is being cut away
      sh.fragmentShader = sh.fragmentShader.replace(
        '#include <opaque_fragment>',
        'outgoingLight += vec3( 1.0, 0.62, 0.3 ) * nikIsoEdge * ( 1.0 - smoothstep( 0.0, 0.05, nikIsoR - nikIsoD ) );\n#include <opaque_fragment>',
      )
    }
    if (o.shade !== undefined) {
      sh.fragmentShader = sh.fragmentShader.replace(
        '#include <opaque_fragment>',
        `outgoingLight *= ${o.shade.toFixed(3)};\n#include <opaque_fragment>`,
      )
    }
    if (o.hollow !== undefined) {
      sh.fragmentShader = sh.fragmentShader.replace(
        '#include <opaque_fragment>',
        `if ( !gl_FrontFacing ) outgoingLight *= ${o.hollow.toFixed(3)};\n#include <opaque_fragment>`,
      )
    }
  }
  const key = ['nik', o.kind, o.envLm ? 'e' : '', o.ostrov ? 'o' : '', o.floor ? 'f' : '', o.dayTint ? 't' : '', o.perforated ? 'p' : '', o.iso ?? 'room', o.hollow ?? '', o.shade ?? ''].join('-')
  mat.customProgramCacheKey = () => key
}

/** polished onyx / lacquered walnut: physical material with a clear coat over the PBR base */
const COATS: Record<string, { clearcoat: number; clearcoatRoughness: number; minRoughness?: number }> = {
  // honed-and-polished onyx: crisp but restrained reflections (a full glass-like coat read as wax)
  'Material #-2147483589': { clearcoat: 0.45, clearcoatRoughness: 0.16, minRoughness: 0.3 },
  'Material #76111117': { clearcoat: 0.45, clearcoatRoughness: 0.28 },
}
/** per-material corrections of the Corona conversion (orig. Max material name) */
const TWEAKS: Record<
  string,
  Partial<{
    ior: number
    roughness: number
    roughMul: number
    dropRoughnessMap: boolean
    env: number
    tint: [number, number, number]
    glow: [number, number, number]
    metalness: number
    /** floor for a pure-black base colour (Corona black leather still shows a dark sheen) */
    minColor: [number, number, number]
    /** base colour (linear) measured from the renders, for procedural Corona colour chains */
    color: [number, number, number]
    /** drop the colour map (a mottled scan that reads as dirt on small curved seats) */
    dropMap: boolean
    /** the grain maps repeat this many times (stretched once over a seat the nubuck grain read 100x too big) */
    detail: number
    spec: number
  }>
> = {
  // pleated floor lamp by the corner sofa: translucent shade + diffuser lit by the bulb inside (follows the lights)
  'Material #4931': { glow: [0.34, 0.2, 0.09] },
  'Material #4880': { glow: [1.0, 0.62, 0.3] },
  'Material #-2147483644': { tint: [1.0, 0.72, 0.5] },
  // honed travertine: the reflection map is missing from the archive -> Corona IOR 3 alone reads as a wet mirror
  travertine7567567: { ior: 1.5, roughness: 0.5, dropRoughnessMap: true },
  travertine: { ior: 1.5, roughness: 0.5, dropRoughnessMap: true },
  // photo backdrops of the view outside the windows: a print, not a mirror
  'Material #-2147483574': { roughness: 1, env: 0 },
  // bar stools: caramel nubuck in the renders (the Corona colour chain is mostly lit warm), soft sheen only
  'Material #2147455760': { dropMap: true, detail: 8, color: [0.4, 0.2, 0.09], roughness: 0.78, env: 0.4 },
  // brass: in Corona the spots light it directly (glossy highlights + light gradients). Real time has only the probe
  // reflections, so part of it takes the baked light (metalness < 1); colours measured against renders 10 / 12
  'Material #2147483647': { tint: [2.06, 2.3, 2.48], metalness: 0.45, env: 1.6 },
  'Material #-2147483422': { tint: [1.71, 1.89, 2.06], metalness: 0.75, env: 2.6, roughMul: 0.8 },
  // upholstery whose Corona colour is a Falloff / Mix / Color Correction chain, measured on render 28: camel
  // suede dining chairs; the tall angled lounge screens ("Leather_net_brown") share the very same colour chain
  'Material #-2147483443': { color: [0.5, 0.25, 0.11], detail: 6, spec: 0.35, roughness: 0.8, env: 0.35 },
  'Material #-2147483646': { color: [0.5, 0.25, 0.11], spec: 0.5, roughness: 0.6, env: 0.6 },
  'Material #-2147483565': { color: [0.06, 0.032, 0.016], spec: 0.7, roughness: 0.42, env: 1.1 },
  // sofa cushions (accent fabric): their gloss map is missing from the archive
  'Material #-214748313700675': { roughness: 0.85, env: 0.3 },
}
const RELIEF: Record<string, number> = {
  'Material #-2147483589': 1.7,
  travertine7567567: 1.6,
  'Material #76111117': 1.3,
  // bar stool nubuck: the converted bump read as blotches
  'Material #2147455760': 0.35,
  // suede: a fine grain, not a leather crease
  'Material #-2147483443': 0.4,
}

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
  if (coat.minRoughness) m.roughness = Math.max(m.roughness, coat.minRoughness)
  return m
}

/** window panes and the glass sculpture: thin, clear, mostly reflection (no refraction pass) */
/**
 * Exterior windows and glass doors: like the renders, an over-exposed daylight glow by day (and nothing of the
 * cropped villa outside shows through); dark glass reflecting the interior in the evening (see useFrame).
 */
const WINDOW_GLASS = new Set(['glass clear', 'Glass'])
const WIN_DAY = new THREE.Color(1.0, 0.97, 0.92)
// evening: a deep-blue dusk behind the panes (pure black read as holes in the high windows), mirroring the warm room
const WIN_DUSK = new THREE.Color(0.35, 0.5, 1.0)
/** openings to the cut-off villa: [plane axis, plane coordinate (just inside the wall), u range along the wall
 *  (z for an x plane, x for a z plane), floor to head] in metres, three space */
const OPENINGS: [axis: 'x' | 'z', at: number, u0: number, u1: number, y0: number, y1: number][] = [
  ['x', -3.77, -5.5, 1.2, -0.05, 2.7], // kitchen end: the three doorways
  ['x', -3.77, 1.6, 5.35, -0.05, 2.7],
  ['x', -3.77, 5.5, 6.5, -0.05, 4.0],
  ['x', 17.02, -5.8, -3.05, -0.05, 4.0], // hall end, beside the stairs
  ['x', 17.32, -2.75, -2.55, 2.4, 3.85], // slits above the hall end wall
  ['x', 17.32, 2.55, 2.75, 2.4, 3.85],
  ['z', 6.47, 14.75, 17.35, -0.05, 2.4], // the stairs
  ['z', 5.52, 3.1, 3.55, -0.05, 0.8], // low gaps under the glass
  ['z', 5.52, 5.9, 6.35, -0.05, 0.8],
]

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
  /** lamp shades lit from inside (dimmed with the interior lights) */
  lampGlows: THREE.MeshStandardMaterial[]
}
const POL_LENS = 'Material #-2147483616'
/** kitchen / hall boundary along x (metres from the island) */
const KITCHEN_X = 2.72
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
  const lampGlows: THREE.MeshStandardMaterial[] = []
  /**
   * Backlit onyx (the island, the kitchen's shelf niche): its own copy of the material, so the onyx dining tables
   * and accessories in the hall, which share the Corona material but have no light inside, do not glow.
   */
  const backlitMats = new Map<string, THREE.MeshStandardMaterial>()
  /** niche: the shelf LEDs are already in its bake - a soft glow only, and the stone a little darker (render 10) */
  const backlit = (src: THREE.MeshStandardMaterial, nik: Nik, niche = false) => {
    const key = src.uuid + (niche ? ':niche' : '')
    let g = backlitMats.get(key)
    if (!g) {
      g = src.clone()
      g.emissive = new THREE.Color(1, 1, 1)
      g.emissiveIntensity = niche ? 0.25 : 1
      g.emissiveMap = assets.extra[nik.orig ?? ''] ?? null
      if (niche) g.color.multiplyScalar(0.5)
      backlitMats.set(key, g)
    }
    return g
  }

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
    patchRoom(mat, { kind, perforated, dayTint: /^travertine/.test(nik.orig ?? ''), ...extra })
    for (const t of [mat.map, mat.normalMap, mat.roughnessMap, mat.metalnessMap, mat.emissiveMap]) if (t) t.anisotropy = maxAniso
    if (mat.normalMap) mat.normalScale.multiplyScalar(RELIEF[nik.orig ?? ''] ?? (nik.surface === 'fabric' ? 0.7 : 1.0))
    // how much each kind of surface mirrors the room: metals live on reflections, textiles barely reflect
    mat.envMapIntensity = nik.metal ? 1.5 : nik.surface === 'fabric' ? 0.3 : nik.surface === 'leather' ? 0.7 : 0.9
    if (nik.surface === 'fabric') mat.roughness = Math.max(mat.roughness, 0.88)
    // roughness exactly 0 on a dielectric without a map = a Corona gloss map that did not survive the export
    if (!nik.metal && !mat.roughnessMap && mat.roughness < 0.02 && !COATS[nik.orig ?? '']) mat.roughness = 0.3
    if (tw?.roughness !== undefined) mat.roughness = tw.roughness
    if (tw?.env !== undefined) mat.envMapIntensity = tw.env
    if (tw?.dropMap) mat.map = null
    if (tw?.detail) {
      for (const t of [mat.map, mat.normalMap, mat.roughnessMap]) {
        if (!t) continue
        t.wrapS = t.wrapT = THREE.RepeatWrapping
        t.repeat.set(tw.detail, tw.detail)
        t.needsUpdate = true
      }
    }
    if (tw?.color) mat.color.setRGB(...tw.color)
    if (tw?.tint) mat.color.multiply(new THREE.Color(...tw.tint))
    if (tw?.metalness !== undefined) mat.metalness = tw.metalness
    if (tw?.roughMul !== undefined) mat.roughness *= tw.roughMul
    if (tw?.minColor) {
      mat.color.setRGB(Math.max(mat.color.r, tw.minColor[0]), Math.max(mat.color.g, tw.minColor[1]), Math.max(mat.color.b, tw.minColor[2]))
    }
    if (tw?.spec !== undefined && mat instanceof THREE.MeshPhysicalMaterial) mat.specularIntensity = tw.spec
    if (nik.surface === 'leather') {
      // the leather gloss maps read as patent leather under real-time IBL: soft satin instead
      mat.roughnessMap = null
      mat.roughness = tw?.roughness ?? 0.55
    }
    if (tw?.glow) {
      mat.emissive.setRGB(...tw.glow)
      mat.emissiveMap = mat.map
      lampGlows.push(mat)
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
      const iso = isFloor ? 'floor' : ISO_KEEP.has(o.name) ? 'keep' : 'room'
      if (big && lm.kitchen && lm.env) {
        // big atlases: the two RGBM groups are mixed in the material (no 4K float render target)
        const k = lm.kitchen.tex
        k.channel = 1
        o.traverse((m) => {
          if (!(m instanceof THREE.Mesh)) return
          const src = m.material as THREE.MeshStandardMaterial
          const nik = nikOf(src)
          if (nik.translucency && !m.userData.nikSrc) {
            // the backlit onyx shelf niche at the back of the kitchen
            m.updateWorldMatrix(true, false)
            const c = new THREE.Box3().setFromObject(m).getCenter(new THREE.Vector3())
            if (c.x < KITCHEN_X) m.userData.nikSrc = backlit(src, nik, true)
          }
          prep(m, 'direct', { envLm: { tex: lm.env!.tex, sK: lm.kitchen!.scale, sE: lm.env!.scale }, floor: isFloor, iso }, k)
        })
        return
      }
      const groups = GROUPS.filter((g) => lm[g] && !(isIsland && g === 'ostrov'))
      const mixer = new LightmapMixer(
        info.size,
        groups.slice(0, 3).map((g) => ({ group: g, tex: lm[g]!.tex, scale: lm[g]!.scale, log: lm[g]!.log })),
        range,
        pl ? { group: 'pol', ...pl } : undefined,
      )
      mixers.push(mixer)
      let ostrovMixer: LightmapMixer | null = null
      if (isIsland && lm.ostrov) {
        ostrovMixer = new LightmapMixer(info.size, [{ group: 'ostrov', tex: lm.ostrov.tex, scale: lm.ostrov.scale, log: lm.ostrov.log }], range)
        mixers.push(ostrovMixer)
      }
      o.traverse((m) => {
        if (!(m instanceof THREE.Mesh)) return
        const src = (m.userData.nikSrc ??= m.material) as THREE.MeshStandardMaterial
        const nik = nikOf(src)
        const glow = isIsland && nik.translucency
        // emissive = translucency map x inner light (+ SSS); without an ostrov bake only the SSS term remains
        if (glow) m.userData.nikSrc = backlit(src, nik)
        const black = new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1)
        black.needsUpdate = true
        prep(m, 'mixer', { ostrov: glow ? (ostrovMixer?.target.texture ?? black) : undefined, floor: isFloor, iso, hollow: isIsland ? 0.025 : undefined, shade: o.name === 'Planters' ? 0.12 : undefined }, mixer.target.texture)
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
      if (o.name === 'Ground') {
        // under the floor (the tiles are cut around columns and steps in the Max file): grout-toned stone, a little
        // lower so nothing lying at floor level flickers against it
        o.position.y -= 0.03
        const g = new THREE.MeshStandardMaterial({ color: new THREE.Color(0.3, 0.25, 0.19), roughness: 0.85, metalness: 0 })
        g.userData.nik = JSON.stringify({ orig: 'Ground' })
        o.userData.nikSrc = g
      }
      // multi-material objects are groups of meshes: the role comes from the top-level object
      let top: THREE.Object3D = o
      while (top.parent && top.parent !== root) top = top.parent
      // the hand shower's grille slots look into its hollow body: dark inside, not the counter behind
      prep(o, 'none', { iso: top.name === 'Ground' ? 'floor' : ISO_KEEP.has(top.name) ? 'keep' : 'room', hollow: top.name === 'Faucets' ? 0.05 : undefined })
    }
  })
  if (faucet) {
    const f = faucet as THREE.Mesh
    const fm = f.material as THREE.MeshStandardMaterial
    const own = fm.clone()
    // (clone() drops the room shader patch)
    own.onBeforeCompile = fm.onBeforeCompile
    own.customProgramCacheKey = fm.customProgramCacheKey
    f.material = own
    anchors.faucet = new THREE.Box3().setFromObject(f).getCenter(new THREE.Vector3())
  }
  // doorways into the cut-off villa: panes like the panoramic windows (daylight glow, dark by night) instead of the
  // backdrop. Found by casting rays out of the room (dev: exits of rays that leave without a hit), three space
  if (!LITE && !root.getObjectByName('Static_Openings')) {
    const panes = new THREE.Group()
    panes.name = 'Static_Openings' // "Static": architecture, so the walker and the orbit camera stop at them
    const pane = new THREE.PlaneGeometry(1, 1)
    for (const [axis, at, u0, u1, y0, y1] of OPENINGS) {
      const mat = toWindow(new THREE.MeshStandardMaterial({ name: 'opening' }))
      windows.push(mat)
      const m = new THREE.Mesh(pane, mat)
      // a little oversize, so no crack along the jambs shows the backdrop
      m.scale.set(u1 - u0 + 0.06, y1 - y0 + 0.06, 1)
      m.position.y = (y0 + y1) / 2
      if (axis === 'x') {
        m.position.set(at, m.position.y, (u0 + u1) / 2)
        m.rotation.y = Math.PI / 2
      } else m.position.set((u0 + u1) / 2, m.position.y, at)
      panes.add(m)
      glass.push(m) // fades with the windows in "island only"
    }
    root.add(panes)
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
  const setup = { mixers, faucet, floors, glass, lenses, windows, lampGlows }
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
// the backdrop is only seen through cracks between panels and openings into the cut-off villa (the windows glow
// by themselves): bright sky there read as holes, so it stays dim
export const moodLook = { daySky: 0.06, nightSky: 0.02 }

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
  const { mixers, faucet, floors, glass, lenses, windows, lampGlows } = useMemo(() => {
    const setup = setupScene(gltf.scene, assets)
    if (chandelier) {
      // hangers run up to the ceilings: ray-cast against the architecture (BVH set up by setupScene)
      setupChandelier(chandelier.scene, gl, world.colliders, (m) => patchRoom(m, { kind: 'none' }), MOBILE)
      if (!probeHide.includes(chandelier.scene)) probeHide.push(chandelier.scene)
    }
    return setup
  }, [gltf, chandelier, assets, gl])
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera
  const setFrameloop = useThree((s) => s.setFrameloop)
  const raycaster = useThree((s) => s.raycaster)
  raycaster.firstHitOnly = true
  const size = useThree((s) => s.size)
  const dpr = useThree((s) => s.viewport.dpr)
  const sky = useMemo(() => makeSkyBackdrop(), [])
  // the room is cut out of the villa: doorways into the cut-off rooms and cracks between panels would show the
  // backdrop. A dark shell just outside the crop box (inside faces) reads as shadowed depth instead.
  const shell = useMemo(() => {
    const m = new THREE.Mesh(
      new THREE.BoxGeometry(22.8, 10.5, 13.2),
      new THREE.MeshBasicMaterial({ color: new THREE.Color(0.045, 0.028, 0.017), side: THREE.BackSide, fog: false }),
    )
    m.position.set(7.5, 4.6, 0) // crop box x -3.5..18.5, z -6.2..6.2 (+0.4 m), floor -0.6 .. roof 9.9
    m.name = 'RoomShell'
    m.raycast = () => {}
    return m
  }, [])
  // phones: the floor mirror pass at a third of the (already capped) resolution
  const reflection = useMemo(() => new PlanarReflection(LITE || MOBILE ? 0.33 : 0.5), [])
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
  /** "island only" progress 0 (room) .. 1 (island in the studio) */
  const isoLive = useRef(0)
  const isoBg = useMemo(() => new THREE.Color(), [])
  const glassDist = useMemo(() => new Map<THREE.Object3D, number>(), [])

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
    const kDef = MIX_DEFAULTS.kitchen.color[1] * MIX_DEFAULTS.kitchen.intensity
    for (const g of lampGlows) g.emissiveIntensity = lm.groups.kitchen.y / Math.max(1e-6, kDef)
    // windows: daylight glow fading to dusk-blue glass that mirrors the lit room
    const l2 = live.light * live.light
    for (const w of windows) {
      w.emissive.copy(WIN_DUSK).lerp(WIN_DAY, l2)
      w.emissiveIntensity = 0.012 + 0.853 * l2
      w.envMapIntensity = 2.2 - l2
    }

    // "island only": the room dissolves in a ring sweeping in towards the island, and grows back out of it
    const prevIso = isoLive.current
    isoLive.current = s.isolate ? Math.min(1, prevIso + dt / ISO_TIME) : Math.max(0, prevIso - dt / ISO_TIME)
    const ip = isoLive.current
    const ie = ip * ip * (3 - 2 * ip)
    isoBg.setRGB(0.006, 0.0055, 0.005).lerp(ISO_BG_DAY, live.light)
    isoUniforms.nikIsoBg.value.copy(isoBg)
    if (LITE) {
      // phone scene: the island, table and stools stand on a disc of the kitchen floor in the studio space
      isoUniforms.nikIsoR.value = 1e4
      // fully faded before the kitchen floor ends (its edge at the walls, 2.2 m to the sides, read as a torn rug)
      isoUniforms.nikIsoFloorR.value = 2.1
      isoUniforms.nikIsoFade.value = 1.15
      isoUniforms.nikIsoEdge.value = 0
    } else if (ip > 0) {
      isoUniforms.nikIsoR.value = THREE.MathUtils.lerp(24, -0.3, ie)
      isoUniforms.nikIsoFloorR.value = THREE.MathUtils.lerp(24, 2.1, ie) // the kitchen floor ends 2.0-2.2 m from the island
      isoUniforms.nikIsoFade.value = THREE.MathUtils.lerp(0.4, 0.8, ie)
      isoUniforms.nikIsoEdge.value = 2.4 * Math.sin(Math.PI * ie)
    } else {
      isoUniforms.nikIsoR.value = isoUniforms.nikIsoFloorR.value = 1e4
      isoUniforms.nikIsoEdge.value = 0
    }
    // what the shader patch does not cover: glass, the shell around the crop, the hairline hangers
    const R = isoUniforms.nikIsoR.value
    for (const g of glass) {
      let d = glassDist.get(g)
      if (d === undefined) {
        const c = new THREE.Box3().setFromObject(g).getCenter(new THREE.Vector3())
        glassDist.set(g, (d = Math.hypot(c.x, c.z)))
      }
      g.visible = d < R
    }
    shell.visible = !LITE && R > 12
    const hangers = chandelier?.scene.getObjectByName('Chandelier_hangers')
    if (hangers) hangers.visible = R > 3.5

    // sky through the windows: bright daylight, deep blue evening (the studio backdrop in "island only")
    scene.background = ip > 0 || LITE ? isoBg : sky
    scene.backgroundBlurriness = 0
    scene.backgroundIntensity = moodLook.nightSky + (moodLook.daySky - moodLook.nightSky) * live.light * live.light

    // reflection probes follow the light (throttled while it is changing, once more when it settles)
    probeAge.current++
    if (changed) {
      probeDirty.current = true
      probeBounces.current = 3
    }
    // (paused while the room is dissolved: the island keeps the room's reflections and the room comes back with them)
    if ((ip === 0 || LITE) && (probeDirty.current || probeBounces.current > 0) && (probeAge.current > 6 || !scene.environment)) {
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
    Promise.all([import('../dev/solveCamera'), import('../dev/cameraSpecs'), import('../dev/measure')]).then(([m, c, ms]) =>
      Object.assign(window, {
        __solveCamera: (spec: never) => m.solveCamera(scene, spec),
        __cameraSpecs: c.cameraSpecs,
        __measure: (ref: string, regions: import('../dev/measure').Regions) => ms.measure(gl.domElement, ref, regions),
        __REGIONS: ms.REGIONS,
      }),
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
      <primitive object={shell} />
      {chandelier && <primitive object={chandelier.scene} />}
    </>
  )
}
