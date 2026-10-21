import { CameraControls } from '@react-three/drei'
import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useRef } from 'react'
import { suspend } from 'suspend-react'
import * as THREE from 'three'
import { useLoad } from '../loading'
import { useStore, type PresetId } from '../store'
import { world } from './Kitchen'
import { anchors } from './live'
import { nearCollider, WALK_FOV } from './Walk'
import CameraControlsImpl from 'camera-controls'
import { LITE } from '../lite'

const TOUCH = typeof matchMedia !== 'undefined' && matchMedia('(pointer: coarse)').matches
/** phones: the island, table and stools in one frame, a step back */
const LITE_HOME = { position: [3.6, 2.4, 4.6] as const, target: [0.3, 0.5, 0.0] as const }

const BASE = import.meta.env.BASE_URL
const DEG = 180 / Math.PI

export interface CameraPreset {
  position: [number, number, number]
  target: [number, number, number]
  lens: number
  sensor: number
  shiftY: number
  resolution: [number, number]
  /** Corona near clipping plane (cuts the walls in front of the render cameras) */
  near?: number
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

/**
 * Spring-arm camera (as in games): the orbit target never moves, but the camera is pulled in front of any wall,
 * glass or ceiling between it and the target, and eases back out when the way is clear. While it is still behind
 * a wall (springing in from a preset), the near plane cuts that wall away - nothing outside is ever shown.
 * Presets themselves stay the exact Corona cameras (they cut the walls in front with their own near clip), until
 * the visitor takes the camera.
 */
const raycaster = new THREE.Raycaster()
raycaster.firstHitOnly = true
const _dir = new THREE.Vector3()
const _side = new THREE.Vector3()
const _up = new THREE.Vector3()
const _o = new THREE.Vector3()
const _t2 = new THREE.Vector3()
const _p = new THREE.Vector3()
const ARM_PAD = 0.28 // stay this far in front of walls
function clearDistance(target: THREE.Vector3, dir: THREE.Vector3, far: number) {
  // a thick ray: centre + 4 offsets, so the near plane corners do not graze walls either
  _side.crossVectors(dir, THREE.Object3D.DEFAULT_UP)
  if (_side.lengthSq() < 1e-6) _side.set(1, 0, 0)
  _side.normalize()
  _up.crossVectors(_side, dir).normalize()
  let d = far
  for (const [sx, sy] of [[0, 0], [0.1, 0], [-0.1, 0], [0, 0.07], [0, -0.07]]) {
    _o.copy(target).addScaledVector(_side, sx).addScaledVector(_up, sy)
    raycaster.set(_o, dir)
    raycaster.far = d
    const hit = raycaster.intersectObjects(world.colliders, false)[0]
    if (hit) d = Math.min(d, hit.distance)
  }
  return d
}

/**
 * Where the orbit target may go (panning, click-to-move): like the walker, it cannot cross a wall, and there is
 * always floor under it; it stays between knee and lamp height. On phones it stays over the island's floor disc.
 */
const _down = new THREE.Vector3(0, -1, 0)
const _step = new THREE.Vector3()
const LITE_C = new THREE.Vector3(0.4, 0, 0)
function hasFloorUnder(p: THREE.Vector3) {
  raycaster.set(p, _down)
  raycaster.far = 4
  const hit = raycaster.intersectObjects(world.colliders, false)[0]
  let o: THREE.Object3D | null = hit?.object ?? null
  while (o && !/^Floor_/.test(o.name)) o = o.parent
  return !!o
}
function allowedTarget(from: THREE.Vector3, to: THREE.Vector3, out: THREE.Vector3) {
  out.copy(to)
  if ((window as Window & { __camFree?: boolean }).__camFree) return out // ?dev inspection
  out.y = THREE.MathUtils.clamp(out.y, 0.25, LITE ? 1.6 : 2.6)
  if (LITE) {
    const dx = out.x - LITE_C.x
    const dz = out.z - LITE_C.z
    const r = Math.hypot(dx, dz)
    if (r > 1.8) out.set(LITE_C.x + (dx / r) * 1.8, out.y, LITE_C.z + (dz / r) * 1.8)
    return out
  }
  _step.copy(out).sub(from)
  const len = _step.length()
  if (len < 1e-5) return out
  _step.divideScalar(len)
  raycaster.set(from, _step)
  raycaster.far = len + 0.35
  const wall = raycaster.intersectObjects(world.colliders, false)[0]
  if (wall) out.copy(from).addScaledVector(_step, Math.max(0, wall.distance - 0.35))
  if (!hasFloorUnder(out)) out.copy(from)
  return out
}

const ISO_VIEW = { position: [2.75, 1.85, 2.65] as const, target: [0, 0.42, 0] as const }

// intro: from high up in the hall under the trusses, gliding down to the island
const INTRO_FROM = { position: [11.5, 4.6, 0.6] as const, target: [0.4, 0.9, 0] as const }

export function CameraRig() {
  const ref = useRef<CameraControls>(null)
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera
  const size = useThree((s) => s.size)
  const exact = suspend(
    async () => (await (await fetch(`${BASE}assets/cameras.json`)).json()) as Record<PresetId, CameraPreset>,
    ['nik-cameras'],
  )
  const ready = useLoad((s) => s.stage === 'ready')
  const { preset, presetNonce, introDone, setIntroDone, freeLook, focus, compareOn, mode, isolate } = useStore()
  /** the visitor has taken the camera since the last preset (spring arm on) */
  const userCam = useRef(false)
  const arm = useRef<number | null>(null)
  const beforeFocus = useRef<{ pos: THREE.Vector3; target: THREE.Vector3; nonce: number } | null>(null)
  const proj = useRef({ fov: 50, shiftPx: 0 })
  useEffect(() => {
    if (useStore.getState().dev) Object.assign(window, { __cam: { exact, controls: ref, camera } })
  }, [exact, camera])
  const goal = useRef({ fov: 50, shiftPx: 0 })
  const near = useRef(0.05)
  const lastPreset = useRef<PresetId>('10')
  const dragFrom = useRef(new THREE.Vector3())

  // intro (only once everything is loaded and lit): start wide and high, then glide into the hero shot
  useEffect(() => {
    const c = ref.current
    if (!c) return
    if (!ready) {
      c.setLookAt(...INTRO_FROM.position, ...INTRO_FROM.target, false)
      return
    }
    // the first shot is an interior camera (render 10): the whole glide stays inside the room
    const p = exact['10']
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
      if (LITE) {
        useStore.getState().freeLook()
        c.setLookAt(...LITE_HOME.position, ...LITE_HOME.target, true).then(finish)
      } else c.setLookAt(...p.position, ...p.target, true).then(finish)
    }, 250)
    // the transition promise only resolves at full rest; reveal the UI once the move has visibly settled
    const t2 = setTimeout(finish, 4100)
    return () => {
      clearTimeout(t)
      clearTimeout(t2)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready])

  useEffect(() => {
    if (!introDone || !preset || !ref.current || mode !== 'orbit') return
    const p = exact[preset]
    userCam.current = false
    ref.current.setLookAt(...p.position, ...p.target, true)
  }, [preset, presetNonce, introDone, exact, mode])

  // "island only": a three-quarter view of the island while the room dissolves around it
  useEffect(() => {
    const c = ref.current
    if (!c || !introDone || !isolate) return
    userCam.current = true
    c.smoothTime = 1.5
    c.setLookAt(...ISO_VIEW.position, ...ISO_VIEW.target, true).then(() => (c.smoothTime = 0.85))
  }, [isolate, introDone])

  // the comparison always shows the exact render camera
  useEffect(() => {
    const st = useStore.getState()
    if (!compareOn || !st.preset || !ref.current) return
    userCam.current = false
    const p = exact[st.preset]
    ref.current.setLookAt(...p.position, ...p.target, true)
  }, [compareOn, exact])

  // leaving the walk: orbit from where we stand, around a point a little ahead
  const prevMode = useRef(mode)
  useEffect(() => {
    const c = ref.current
    if (!c) return
    if (prevMode.current === 'walk' && mode === 'orbit' && !useStore.getState().preset) {
      const dir = camera.getWorldDirection(new THREE.Vector3())
      const t = camera.position.clone().addScaledVector(dir, 2.2)
      c.setLookAt(camera.position.x, camera.position.y, camera.position.z, t.x, t.y, t.z, false)
      userCam.current = true
      arm.current = null
    }
    prevMode.current = mode
  }, [mode, camera])

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
      userCam.current = true
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
      userCam.current = true
      c.moveTo(x, 0.85, z, true)
    }
    window.addEventListener('nik-move-to', onMove)
    return () => window.removeEventListener('nik-move-to', onMove)
  }, [freeLook])

  // panning: drag up/down moves along the floor (not up the wall), like a plan
  useEffect(() => {
    const c = ref.current
    if (!c) return
    c.verticalDragToForward = true
    // touch: one finger orbits, a pinch zooms (on phones a pure, fast pinch - no accidental panning)
    c.touches.one = CameraControlsImpl.ACTION.TOUCH_ROTATE
    c.touches.two = LITE ? CameraControlsImpl.ACTION.TOUCH_DOLLY : CameraControlsImpl.ACTION.TOUCH_DOLLY_TRUCK
    c.touches.three = CameraControlsImpl.ACTION.TOUCH_TRUCK
    c.draggingSmoothTime = TOUCH ? 0.06 : 0.125
  }, [])

  // spring arm: after camera-controls placed the camera (-1), before the walker (-0.5) and the scene (0)
  const armNear = useRef(0.05)
  /** last orbit target that was inside the rooms */
  const validTarget = useRef<THREE.Vector3 | null>(null)
  useFrame((_, dt) => {
    const st = useStore.getState()
    const c = ref.current
    // (no walls to stop at while the room is dissolved around the island)
    const active = !!c && ready && st.mode === 'orbit' && !st.compareOn && !st.isolate && (userCam.current || !st.preset)
    if (!active || !c) {
      // presets / the intro / the walker place the target inside the rooms: that is where panning starts from
      validTarget.current = c ? c.getTarget(validTarget.current ?? new THREE.Vector3()) : null
      arm.current = null
      armNear.current = 0.05
      return
    }
    const target = c.getTarget(_o.clone())
    if (!validTarget.current) validTarget.current = target.clone()
    else {
      const ok = allowedTarget(validTarget.current, target, _t2)
      if (ok.distanceToSquared(target) > 1e-8) {
        c.moveTo(ok.x, ok.y, ok.z, false)
        c.update(0)
        target.copy(ok)
      }
      validTarget.current.copy(target)
    }
    _dir.copy(camera.position).sub(target)
    const want = _dir.length()
    if (want < 1e-3) return
    _dir.divideScalar(want)
    const clear = Math.max(0.3, clearDistance(target, _dir, want + ARM_PAD) - ARM_PAD)
    let allowed = Math.min(want, clear)
    // furniture: the camera may look past a chair or the island (orbit viewers do), but never sits inside one
    for (let i = 0; i < 30 && allowed > 0.5 && nearCollider(_p.copy(target).addScaledVector(_dir, allowed), 0.2); i++) allowed -= 0.08
    let a = arm.current ?? want
    // in: quick but continuous (the near plane hides the wall meanwhile); out: gentle
    a += (allowed - a) * (1 - Math.exp(-dt * (allowed < a ? 7 : 3)))
    a = Math.min(a, want)
    arm.current = a
    armNear.current = Math.max(0.05, a - clear + 0.15)
    camera.position.copy(target).addScaledVector(_dir, a)
    camera.updateMatrixWorld()
  }, -0.9)

  useFrame((_, dt) => {
    const st = useStore.getState()
    if (st.preset) lastPreset.current = st.preset
    const walking = st.mode === 'walk'
    const p = exact[lastPreset.current]
    const pr = presetProjection(p, size.width, size.height)
    const focused = st.focus === 'faucet'
    // portrait phones: the render frame fit gives a ~100 deg fisheye; capped, the island stays large and undistorted
    goal.current.fov = walking ? WALK_FOV : focused ? 34 : TOUCH ? Math.min(pr.fov, 72) : pr.fov
    // keep the architectural lens shift of the last preset while orbiting (no jump on the first drag)
    // (touch screens: no architectural lens shift - on a portrait phone it pushed the island to the bottom third)
    goal.current.shiftPx = walking || focused || TOUCH ? 0 : pr.shiftPx
    const k = 1 - Math.exp(-dt * (introDone ? 4 : 1.6))
    proj.current.fov += (goal.current.fov - proj.current.fov) * k
    proj.current.shiftPx += (goal.current.shiftPx - proj.current.shiftPx) * k
    // near plane: a preset's own Corona clip while it is shown untouched, the spring arm's cut while it moves in
    const presetShown = !!st.preset && !walking && (!userCam.current || st.compareOn)
    // a preset's Corona clip, but never closer than 1.5 m in front of the orbit target (mid-transition the
    // camera is nearer to the island than the render camera was)
    let presetNear = 0.05
    if (presetShown && ref.current) {
      const dist = camera.position.distanceTo(ref.current.getTarget(_o.clone()))
      presetNear = Math.max(0.05, Math.min(exact[st.preset!].near ?? 0.05, dist - 1.5))
    }
    const n = walking ? 0.05 : presetShown ? presetNear : armNear.current
    near.current = arm.current !== null ? n : near.current + (n - near.current) * (n > near.current ? 1 : k)
    let dirty = false
    if (Math.abs(camera.near - near.current) > 1e-4) {
      camera.near = near.current
      dirty = true
    }
    if (Math.abs(camera.fov - proj.current.fov) > 1e-4 || camera.view?.offsetY !== -proj.current.shiftPx) {
      camera.fov = proj.current.fov
      camera.setViewOffset(size.width, size.height, 0, -proj.current.shiftPx, size.width, size.height)
      dirty = true
    }
    if (dirty) camera.updateProjectionMatrix()
  })

  return (
    <CameraControls
      ref={ref}
      makeDefault
      enabled={mode === 'orbit' && ready}
      minDistance={focus ? 0.35 : 0.8}
      maxDistance={LITE ? 8.5 : 9}
      maxPolarAngle={THREE.MathUtils.degToRad(88)}
      dollySpeed={TOUCH ? 1.6 : 0.6}
      azimuthRotateSpeed={TOUCH ? 0.75 : 1}
      polarRotateSpeed={TOUCH ? 0.75 : 1}
      truckSpeed={1.2}
      onStart={() => {
        ref.current?.getPosition(dragFrom.current)
        // taking the camera: from here on the walls are solid
        if (introDone) userCam.current = true
      }}
      onEnd={() => {
        // a click is not a camera move: leave the preset only if the camera really travelled
        const now = ref.current?.getPosition(new THREE.Vector3())
        if (introDone && now && now.distanceTo(dragFrom.current) > 0.02) freeLook()
      }}
    />
  )
}
