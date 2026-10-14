import { useFrame, type ThreeEvent } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import { suspend } from 'suspend-react'
import * as THREE from 'three'
import { useStore } from '../store'
import { approach, lampsLive } from './live'

const BASE = import.meta.env.BASE_URL

interface Fixture {
  index: number
  name: string
  position: [number, number, number]
}

const LENS_ON = new THREE.Color(1.0, 0.78, 0.52)
const ledGeo = new THREE.CircleGeometry(0.013, 32).rotateX(-Math.PI / 2)
const haloGeo = new THREE.PlaneGeometry(0.42, 0.42).rotateX(-Math.PI / 2)
const hitGeo = new THREE.CircleGeometry(0.12, 24).rotateX(-Math.PI / 2)
const hitMat = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false, colorWrite: false })

/** soft radial falloff for the light pool around each fixture */
const haloTex = (() => {
  const c = document.createElement('canvas')
  c.width = c.height = 128
  const g = c.getContext('2d')!
  const r = g.createRadialGradient(64, 64, 0, 64, 64, 64)
  r.addColorStop(0, 'rgba(255,255,255,1)')
  r.addColorStop(0.18, 'rgba(255,255,255,0.45)')
  r.addColorStop(0.5, 'rgba(255,255,255,0.08)')
  r.addColorStop(1, 'rgba(255,255,255,0)')
  g.fillStyle = r
  g.fillRect(0, 0, 128, 128)
  const t = new THREE.CanvasTexture(c)
  t.colorSpace = THREE.NoColorSpace
  return t
})()

/** the fixtures act as one circuit: hovering any of them highlights all, a click switches all */
const circuit = { hovered: false }

function circuitLabel() {
  const on = useStore.getState().lamps.some(Boolean)
  return { label: 'Floor lights', hint: on ? 'Click to turn off' : 'Click to turn on' }
}

/** One recessed floor uplight: LED hot spot (bloom) + soft light pool, hover/click target. */
function Lamp({ f }: { f: Fixture }) {
  const toggleAll = useStore((s) => s.toggleAllLamps)
  const setHover = useStore((s) => s.setHover)
  const group = useRef<THREE.Group>(null!)
  const hovered = circuit
  const scale = useRef(1)
  const mats = useMemo(
    () => ({
      ring: new THREE.MeshStandardMaterial({ color: new THREE.Color(0.2, 0.14, 0.09), metalness: 1, roughness: 0.32 }),
      lens: new THREE.MeshStandardMaterial({ color: new THREE.Color(0.03, 0.028, 0.026), metalness: 0, roughness: 0.15, emissive: LENS_ON.clone() }),
      led: new THREE.MeshBasicMaterial({ color: new THREE.Color(0, 0, 0) }),
      halo: new THREE.MeshBasicMaterial({
        map: haloTex,
        color: new THREE.Color(0, 0, 0),
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    }),
    [],
  )

  useFrame((_, dt) => {
    const v = (lampsLive.values[f.index] ?? 1) * Math.min(1.5, lampsLive.group)
    mats.lens.emissiveIntensity = 3.5 * v
    mats.led.color.setRGB(30 * v, 23 * v, 15 * v)
    mats.halo.color.setRGB(0.16 * v, 0.11 * v, 0.065 * v)
    const h = hovered.hovered ? 1 : 0
    mats.ring.color.setRGB(0.2 + 0.35 * h, 0.14 + 0.24 * h, 0.09 + 0.12 * h)
    scale.current = approach(scale.current, hovered.hovered ? 1.3 : 1, dt, 9)
    group.current.scale.setScalar(scale.current)
  })


  return (
    <group ref={group} position={[f.position[0], 0.0012, f.position[2]]}>
      <mesh geometry={haloGeo} material={mats.halo} position-y={0.0006} renderOrder={1} />
      {/* the real fixture (trim + lens) is part of the scene; here only the LED hot spot and the light pool */}
      <mesh geometry={ledGeo} material={mats.led} position-y={0.0001} />
      <mesh
        geometry={hitGeo}
        material={hitMat}
        onPointerOver={(e: ThreeEvent<PointerEvent>) => {
          e.stopPropagation()
          hovered.hovered = true
          document.body.style.cursor = 'pointer'
          setHover(circuitLabel())
        }}
        onPointerOut={() => {
          hovered.hovered = false
          document.body.style.cursor = ''
          setHover(null)
        }}
        onClick={(e: ThreeEvent<MouseEvent>) => {
          if (e.delta > 4) return
          e.stopPropagation()
          toggleAll()
          setHover(circuitLabel())
        }}
      />
    </group>
  )
}

export function FloorLamps() {
  const data = suspend(async () => (await (await fetch(`${BASE}assets/lights.json`)).json()) as { pol: Fixture[] }, ['nik-lights'])
  const setLampCount = useStore((s) => s.setLampCount)
  useEffect(() => setLampCount(data.pol.length), [data, setLampCount])
  return (
    <>
      {data.pol.map((f) => (
        <Lamp key={f.index} f={f} />
      ))}
    </>
  )
}
