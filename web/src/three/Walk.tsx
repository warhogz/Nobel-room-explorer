import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { MeshBVH } from 'three-mesh-bvh'
import { GenerateMeshBVHWorker } from 'three-mesh-bvh/src/workers/GenerateMeshBVHWorker.js'
import { useStore } from '../store'
import { world } from './Kitchen'

/**
 * First-person walking: a capsule (shoulder radius 0.28 m, eyes at 1.62 m) collides with the walls, the island,
 * furniture and the glass (three-mesh-bvh shape casts against one merged collision mesh), slides along them and
 * stays on the floor under gravity. WASD / arrows (+ Shift to hurry), drag to look, click the floor to walk there,
 * on-screen stick on touch screens.
 */
const EYE = 1.62
const RADIUS = 0.28
const TOP = EYE - 0.1 // capsule top sphere centre above the floor
const WALK = 1.45
const RUN = 3.0
const GRAVITY = 9.8
/** vertical field of view while walking (CameraRig applies it) */
export const WALK_FOV = 62

/** shared input written by the DOM joystick */
export const walkInput = { x: 0, y: 0 }

// ------------------------------------------------------------------------------------------------ collision mesh
let collider: { geometry: THREE.BufferGeometry; bvh: MeshBVH } | null = null
let building: Promise<void> | null = null

/**
 * One world-space triangle soup of everything solid. Dense furniture only contributes the triangles at body
 * height (legs, seats, backs), architecture and the island everything. BVH built in a worker.
 */
export function buildWalkCollider() {
  if (building) return building
  building = (async () => {
    const a = new THREE.Vector3()
    const b = new THREE.Vector3()
    const c = new THREE.Vector3()
    let out = new Float32Array(1 << 22)
    let n = 0
    const push = (p: THREE.Vector3) => {
      if (n + 3 > out.length) {
        const grown = new Float32Array(out.length * 2)
        grown.set(out)
        out = grown
      }
      out[n++] = p.x
      out[n++] = p.y
      out[n++] = p.z
    }
    for (const m of world.walkSources) {
      let top: THREE.Object3D = m
      while (top.parent && top.parent.parent) top = top.parent
      const dense = /^VX_/.test(top.name)
      const g = m.geometry
      const pos = g.getAttribute('position') as THREE.BufferAttribute
      const idx = g.index
      const count = idx ? idx.count : pos.count
      const mw = m.matrixWorld
      for (let i = 0; i < count; i += 3) {
        const i0 = idx ? idx.getX(i) : i
        const i1 = idx ? idx.getX(i + 1) : i + 1
        const i2 = idx ? idx.getX(i + 2) : i + 2
        a.fromBufferAttribute(pos, i0).applyMatrix4(mw)
        b.fromBufferAttribute(pos, i1).applyMatrix4(mw)
        c.fromBufferAttribute(pos, i2).applyMatrix4(mw)
        if (dense) {
          const cy = (a.y + b.y + c.y) / 3
          if (cy < 0.08 || cy > 1.35) continue
        } else if (Math.min(a.y, b.y, c.y) > 2.4) continue // ceilings and trusses: out of reach
        push(a)
        push(b)
        push(c)
      }
    }
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.BufferAttribute(out.slice(0, n), 3))
    let bvh: MeshBVH
    try {
      const worker = new GenerateMeshBVHWorker()
      bvh = await worker.generate(geometry, { maxLeafTris: 8 })
      worker.dispose()
    } catch {
      bvh = new MeshBVH(geometry, { maxLeafTris: 8 })
    }
    collider = { geometry, bvh }
  })()
  return building
}

const castRay = new THREE.Ray()
/**
 * Distance to the first solid surface facing the ray (furniture, island, walls up to 2.4 m), or Infinity.
 * Back faces are ignored: a ray starting inside the island (orbit target) leaves it freely.
 */
export function castCollider(origin: THREE.Vector3, dir: THREE.Vector3, far: number) {
  if (!collider) return Infinity
  castRay.origin.copy(origin)
  castRay.direction.copy(dir)
  const hit = collider.bvh.raycastFirst(castRay, THREE.FrontSide, 0, far)
  return hit ? hit.distance : Infinity
}

/**
 * Distance along the ray to the first back face = where the ray leaves a solid it started in (the orbit target
 * often sits inside the island), or Infinity.
 */
export function castExit(origin: THREE.Vector3, dir: THREE.Vector3, far: number) {
  if (!collider) return Infinity
  castRay.origin.copy(origin)
  castRay.direction.copy(dir)
  const hit = collider.bvh.raycastFirst(castRay, THREE.BackSide, 0, far)
  return hit ? hit.distance : Infinity
}

const nearHit = { point: new THREE.Vector3(), distance: 0, faceIndex: 0 }
/** is a point closer than r to any solid surface (furniture, island, walls up to 2.4 m)? */
export function nearCollider(p: THREE.Vector3, r: number) {
  if (!collider) return false
  return !!collider.bvh.closestPointToPoint(p, nearHit, 0, r)
}

// ------------------------------------------------------------------------------------------------ controller
const tmpBox = new THREE.Box3()
const tmpSeg = new THREE.Line3()
const triPoint = new THREE.Vector3()
const capPoint = new THREE.Vector3()
const fwd = new THREE.Vector3()
const right = new THREE.Vector3()

/** pushes the capsule out of every triangle it overlaps; returns the corrected top position */
function resolve(top: THREE.Vector3) {
  if (!collider) return { pos: top, ground: false }
  tmpSeg.start.copy(top)
  tmpSeg.end.copy(top).y -= TOP - RADIUS
  tmpBox.makeEmpty().expandByPoint(tmpSeg.start).expandByPoint(tmpSeg.end)
  tmpBox.min.addScalar(-RADIUS)
  tmpBox.max.addScalar(RADIUS)
  const before = tmpSeg.start.clone()
  collider.bvh.shapecast({
    intersectsBounds: (box) => box.intersectsBox(tmpBox),
    intersectsTriangle: (tri) => {
      const d = tri.closestPointToSegment(tmpSeg, triPoint, capPoint)
      if (d < RADIUS) {
        const depth = RADIUS - d
        const dir = capPoint.sub(triPoint).normalize()
        tmpSeg.start.addScaledVector(dir, depth)
        tmpSeg.end.addScaledVector(dir, depth)
      }
      return false
    },
  })
  const push = tmpSeg.start.clone().sub(before)
  return { pos: tmpSeg.start.clone(), ground: push.y > 1e-4 }
}

/** floor height under a point (ray down), or null outside the walkable space */
function floorAt(p: THREE.Vector3) {
  if (!collider) return null
  const ray = new THREE.Ray(new THREE.Vector3(p.x, 2.2, p.z), new THREE.Vector3(0, -1, 0))
  const hit = collider.bvh.raycastFirst(ray, THREE.DoubleSide)
  return hit ? hit.point.y : null
}

export function WalkControls() {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera
  const gl = useThree((s) => s.gl)
  const raycaster = useThree((s) => s.raycaster)
  const mode = useStore((s) => s.mode)
  const st = useRef({
    top: new THREE.Vector3(),
    vel: new THREE.Vector3(),
    yaw: 0,
    pitch: 0,
    ground: false,
    bob: 0,
    target: null as THREE.Vector3 | null,
    intro: 0, // 0..1 glide from the orbit camera into the eyes
    fromPos: new THREE.Vector3(),
    fromQuat: new THREE.Quaternion(),
  })
  const keys = useRef(new Set<string>())

  // enter: spawn where the camera is (if that is inside the room), facing the same way
  useEffect(() => {
    if (mode !== 'walk') return
    const s = st.current
    s.fromPos.copy(camera.position)
    s.fromQuat.copy(camera.quaternion)
    camera.getWorldDirection(fwd)
    s.yaw = Math.atan2(-fwd.x, -fwd.z)
    s.pitch = 0
    const p = camera.position.clone()
    p.x = THREE.MathUtils.clamp(p.x, -1.6, 16.8)
    p.z = THREE.MathUtils.clamp(p.z, -2.2, 2.2)
    const fy = floorAt(p)
    if (fy === null || camera.position.x < -2 || Math.abs(camera.position.z) > 2.6) {
      // outside: start in the hall, looking at the island
      p.set(4.6, 0, 1.4)
      s.yaw = Math.atan2(4.6, 1.4) // towards the island at the origin
    }
    s.top.set(p.x, (fy ?? 0) + TOP, p.z)
    // nudge out of anything we spawned in
    for (let i = 0; i < 6; i++) s.top.copy(resolve(s.top).pos)
    s.vel.set(0, 0, 0)
    s.target = null
    s.intro = 0
    walkInput.x = walkInput.y = 0
  }, [mode, camera])

  // keyboard
  useEffect(() => {
    if (mode !== 'walk') return
    const down = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        useStore.getState().setMode('orbit')
        return
      }
      keys.current.add(e.code)
      if (/^(Arrow|Key[WASD])/.test(e.code)) st.current.target = null
    }
    const up = (e: KeyboardEvent) => keys.current.delete(e.code)
    const blur = () => keys.current.clear()
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    window.addEventListener('blur', blur)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('blur', blur)
      keys.current.clear()
    }
  }, [mode])

  // look by dragging; a click on the floor walks there
  useEffect(() => {
    if (mode !== 'walk') return
    const el = gl.domElement
    let drag: { x: number; y: number; moved: number; id: number } | null = null
    const down = (e: PointerEvent) => {
      if (e.pointerType === 'touch' && (e.target as HTMLElement).closest?.('.joy')) return
      drag = { x: e.clientX, y: e.clientY, moved: 0, id: e.pointerId }
      el.setPointerCapture(e.pointerId)
    }
    const move = (e: PointerEvent) => {
      if (!drag || e.pointerId !== drag.id) return
      const dx = e.clientX - drag.x
      const dy = e.clientY - drag.y
      drag.x = e.clientX
      drag.y = e.clientY
      drag.moved += Math.abs(dx) + Math.abs(dy)
      const k = e.pointerType === 'touch' ? 0.0045 : 0.0032
      st.current.yaw -= dx * k
      st.current.pitch = THREE.MathUtils.clamp(st.current.pitch - dy * k, -1.35, 1.35)
    }
    const up = (e: PointerEvent) => {
      if (!drag || e.pointerId !== drag.id) return
      const click = drag.moved < 6
      drag = null
      if (!click || !collider) return
      const r = el.getBoundingClientRect()
      const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
      raycaster.setFromCamera(ndc, camera)
      const hit = collider.bvh.raycastFirst(raycaster.ray, THREE.DoubleSide)
      if (hit && hit.point.y < 0.3 && hit.face && hit.face.normal.y > 0.7) st.current.target = hit.point.clone()
    }
    el.addEventListener('pointerdown', down)
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerup', up)
    return () => {
      el.removeEventListener('pointerdown', down)
      el.removeEventListener('pointermove', move)
      el.removeEventListener('pointerup', up)
    }
  }, [mode, gl, camera, raycaster])

  // after camera-controls (-1), before the scene's own frame work (0): the mirror pass sees this frame's eyes
  useFrame((_, rawDt) => {
    if (useStore.getState().mode !== 'walk') return
    const s = st.current
    const dt = Math.min(rawDt, 0.05)
    // intent
    const k = keys.current
    let ix = (k.has('KeyD') || k.has('ArrowRight') ? 1 : 0) - (k.has('KeyA') || k.has('ArrowLeft') ? 1 : 0) + walkInput.x
    let iy = (k.has('KeyW') || k.has('ArrowUp') ? 1 : 0) - (k.has('KeyS') || k.has('ArrowDown') ? 1 : 0) + walkInput.y
    fwd.set(-Math.sin(s.yaw), 0, -Math.cos(s.yaw))
    right.set(-fwd.z, 0, fwd.x)
    const want = new THREE.Vector3().addScaledVector(fwd, iy).addScaledVector(right, ix)
    let speed = k.has('ShiftLeft') || k.has('ShiftRight') ? RUN : WALK
    if (s.target) {
      const to = new THREE.Vector3(s.target.x - s.top.x, 0, s.target.z - s.top.z)
      const d = to.length()
      if (d < 0.25) s.target = null
      else {
        want.copy(to).divideScalar(d)
        speed = WALK * Math.min(1, d / 0.8 + 0.25)
        // turn gently towards where we walk
        const yawTo = Math.atan2(-to.x, -to.z)
        let dy = yawTo - s.yaw
        dy = Math.atan2(Math.sin(dy), Math.cos(dy))
        s.yaw += dy * (1 - Math.exp(-dt * 3))
      }
      ix = iy = 0
    }
    if (want.lengthSq() > 1) want.normalize()
    // velocity: quick but soft acceleration, gravity
    const kv = 1 - Math.exp(-dt * (want.lengthSq() > 0 ? 9 : 12))
    s.vel.x += (want.x * speed - s.vel.x) * kv
    s.vel.z += (want.z * speed - s.vel.z) * kv
    s.vel.y = s.ground ? -0.5 : s.vel.y - GRAVITY * dt
    // move in sub-steps (no tunnelling through thin glass), collide each step
    const steps = 4
    let grounded = false
    for (let i = 0; i < steps; i++) {
      const prev = s.top.clone()
      s.top.addScaledVector(s.vel, dt / steps)
      const before = s.top.clone()
      const r = resolve(s.top)
      s.top.copy(r.pos)
      grounded ||= r.ground
      // no floor under the next step (a doorway into the cut-off rest of the villa, an opening): treat it as a wall
      const fy = floorAt(s.top)
      if (fy === null || fy < prev.y - TOP - 0.35) {
        s.top.x = prev.x
        s.top.z = prev.z
        s.vel.x = s.vel.z = 0
        continue
      }
      // walked into something: drop the velocity component pushing into it (slide along walls)
      const pushed = r.pos.clone().sub(before)
      if (pushed.lengthSq() > 1e-10) {
        pushed.normalize()
        const into = s.vel.dot(pushed)
        if (into < 0) s.vel.addScaledVector(pushed, -into)
      }
    }
    s.ground = grounded
    if (s.top.y < -2) s.top.y = TOP // fell out (should not happen): back on the floor
    if (s.target && s.vel.lengthSq() < 0.02 && want.lengthSq() > 0) s.target = null // blocked
    // camera: eyes, a subtle step bob while walking
    const hs = Math.hypot(s.vel.x, s.vel.z)
    s.bob += dt * hs * 5.2
    const bobA = Math.min(1, hs / WALK) * 0.014
    const eye = new THREE.Vector3(s.top.x, s.top.y + (EYE - TOP) + Math.sin(s.bob) * bobA, s.top.z)
    const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(s.pitch, s.yaw, Math.sin(s.bob * 0.5) * bobA * 0.6, 'YXZ'))
    if (s.intro < 1) {
      s.intro = Math.min(1, s.intro + dt / 1.2)
      const t = s.intro * s.intro * (3 - 2 * s.intro)
      camera.position.lerpVectors(s.fromPos, eye, t)
      camera.quaternion.slerpQuaternions(s.fromQuat, q, t)
    } else {
      camera.position.copy(eye)
      camera.quaternion.copy(q)
    }
    camera.updateMatrixWorld()
  }, -0.5)

  return null
}
