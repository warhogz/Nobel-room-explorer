import { CameraControls } from '@react-three/drei'
import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useRef } from 'react'
import { suspend } from 'suspend-react'
import * as THREE from 'three'
import { useStore, type PresetId } from '../store'
import { anchors } from './live'

const BASE = import.meta.env.BASE_URL
const DEG = 180 / Math.PI

export interface CameraPreset {
  position: [number, number, number]
  target: [number, number, number]
  lens: number
  sensor: number
  shiftY: number
  resolution: [number, number]
}

/**
 * Frame fit for a preset render (w x h) shown "contain" in the viewport (same rule as the compare overlay):
 * returns vertical fov (deg) and the lens-shift offset in viewport pixels (Blender shift semantics).
 */
export function presetProjection(p: CameraPreset, vw: number, vh: number) {
  const [w, h] = p.resolution
  const aspectP = w / h
  const tanL = p.sensor / 2 / p.lens // tan(half fov) along the larger render side
  const tanV = w >= h ? tanL / aspectP : tanL
  const tanH = w >= h ? tanL : tanL * aspectP
  const a = vw / vh
  // wider screen: show the full render height; narrower (phones): halfway (geometric) between "contain" and
  // "cover", so the island stays large without cropping the table
  const tanVView = a > aspectP ? tanV : Math.sqrt((tanH / a) * tanV)
  const fov = 2 * Math.atan(tanVView) * DEG
  const shiftTan = p.shiftY * 2 * tanL // vertical frustum offset in tan space
  const shiftPx = (shiftTan / (2 * tanVView)) * vh
  return { fov, shiftPx }
}

/** where the preset's render frame sits in the viewport (CSS px) for the projection above */
export function presetFrameRect(p: CameraPreset, vw: number, vh: number) {
  const [w, h] = p.resolution
  const aspectP = w / h
  const tanL = p.sensor / 2 / p.lens
  const tanV = w >= h ? tanL / aspectP : tanL
  const tanH = w >= h ? tanL : tanL * aspectP
  const a = vw / vh
  const tanVView = a > aspectP ? tanV : Math.sqrt((tanH / a) * tanV)
  const fh = (vh * tanV) / tanVView
  const fw = fh * aspectP
  return { x: (vw - fw) / 2, y: (vh - fh) / 2, w: fw, h: fh }
}

const INTRO_FROM = { position: [-6.5, 3.6, 6.8] as const, target: [0.4, 0.5, 0] as const }

export function CameraRig() {
  const ref = useRef<CameraControls>(null)
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera
  const size = useThree((s) => s.size)
  const presets = suspend(
    async () => (await (await fetch(`${BASE}assets/cameras.json`)).json()) as Record<PresetId, CameraPreset>,
    ['nik-cameras'],
  )
  const { preset, presetNonce, introDone, setIntroDone, freeLook, focus } = useStore()
  const beforeFocus = useRef<{ pos: THREE.Vector3; target: THREE.Vector3; nonce: number } | null>(null)
  const proj = useRef({ fov: 50, shiftPx: 0 })
  useEffect(() => {
    if (useStore.getState().dev) Object.assign(window, { __cam: { presets, controls: ref, camera } })
  }, [presets, camera])
  const goal = useRef({ fov: 50, shiftPx: 0 })
  const lastPreset = useRef<PresetId>('030')
  const dragFrom = useRef(new THREE.Vector3())

  // intro: start wide and high, then glide into the hero shot
  useEffect(() => {
    const c = ref.current
    if (!c) return
    c.setLookAt(...INTRO_FROM.position, ...INTRO_FROM.target, false)
    const p = presets['030']
    const pr = presetProjection(p, size.width, size.height)
    proj.current = { fov: pr.fov + 14, shiftPx: 0 }
    c.smoothTime = 2.6
    let done = false
    const finish = () => {
      if (done) return
      done = true
      c.smoothTime = 0.85
      setIntroDone()
    }
    const t = setTimeout(() => {
      c.setLookAt(...p.position, ...p.target, true).then(finish)
    }, 350)
    // the transition promise only resolves at full rest; reveal the UI once the move has visibly settled
    const t2 = setTimeout(finish, 4200)
    return () => {
      clearTimeout(t)
      clearTimeout(t2)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!introDone || !preset || !ref.current) return
    const p = presets[preset]
    ref.current.setLookAt(...p.position, ...p.target, true)
  }, [preset, presetNonce, introDone, presets])

  // close-up on the faucet: approach from the current side, slightly above; return to the previous pose after
  useEffect(() => {
    const c = ref.current
    if (!c || !introDone) return
    if (focus === 'faucet' && anchors.faucet) {
      const pos = c.getPosition(new THREE.Vector3())
      const tgt = c.getTarget(new THREE.Vector3())
      beforeFocus.current = { pos, target: tgt, nonce: useStore.getState().presetNonce }
      // the taps stand in a row along z: look along x (from the back-wall side, slightly angled) so both read
      // clearly against the background; aim a little low so the taps sit above the finish card
      const f = anchors.faucet.clone()
      const dir = new THREE.Vector3(-1, 0, 0.32).normalize()
      const eye = f.clone().addScaledVector(dir, 1.05).add(new THREE.Vector3(0, 0.26, 0))
      const aim = f.clone().add(new THREE.Vector3(0, -0.1, 0))
      c.smoothTime = 1.1
      c.setLookAt(eye.x, eye.y, eye.z, aim.x, aim.y, aim.z, true)
    } else if (focus === null && beforeFocus.current) {
      const b = beforeFocus.current
      beforeFocus.current = null
      // a preset chosen while focused takes over; otherwise go back where we came from
      if (useStore.getState().presetNonce === b.nonce) c.setLookAt(b.pos.x, b.pos.y, b.pos.z, b.target.x, b.target.y, b.target.z, true)
      c.smoothTime = 0.85
    }
  }, [focus, introDone])

  useEffect(() => {
    const onMove = (e: Event) => {
      const [x, , z] = (e as CustomEvent<number[]>).detail
      const c = ref.current
      if (!c) return
      freeLook()
      c.moveTo(x, 0.85, z, true)
    }
    window.addEventListener('nik-move-to', onMove)
    return () => window.removeEventListener('nik-move-to', onMove)
  }, [freeLook])

  useFrame((_, dt) => {
    if (preset) lastPreset.current = preset
    const p = presets[lastPreset.current]
    const pr = presetProjection(p, size.width, size.height)
    const focused = useStore.getState().focus === 'faucet'
    goal.current.fov = focused ? 34 : pr.fov
    // keep the architectural lens shift of the last preset while orbiting (no jump on the first drag)
    goal.current.shiftPx = focused ? 0 : pr.shiftPx
    const k = 1 - Math.exp(-dt * (introDone ? 4 : 1.6))
    proj.current.fov += (goal.current.fov - proj.current.fov) * k
    proj.current.shiftPx += (goal.current.shiftPx - proj.current.shiftPx) * k
    if (Math.abs(camera.fov - proj.current.fov) > 1e-4 || camera.view?.offsetY !== -proj.current.shiftPx) {
      camera.fov = proj.current.fov
      camera.setViewOffset(size.width, size.height, 0, -proj.current.shiftPx, size.width, size.height)
      camera.updateProjectionMatrix()
    }
  })

  return (
    <CameraControls
      ref={ref}
      makeDefault
      minDistance={focus ? 0.35 : 1.2}
      maxDistance={12}
      maxPolarAngle={THREE.MathUtils.degToRad(88)}
      dollySpeed={0.6}
      truckSpeed={0}
      onStart={() => {
        ref.current?.getPosition(dragFrom.current)
      }}
      onEnd={() => {
        // a click is not a camera move: leave the preset only if the camera really travelled
        const now = ref.current?.getPosition(new THREE.Vector3())
        if (introDone && now && now.distanceTo(dragFrom.current) > 0.02) freeLook()
      }}
    />
  )
}
