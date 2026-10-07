import { useEffect, useRef, useState, type CSSProperties, type PointerEvent as RPointerEvent } from 'react'
import { PRESETS, useStore, type PresetId } from '../store'
import { presetFrameRect, type CameraPreset } from '../three/CameraRig'

const BASE = import.meta.env.BASE_URL

let presetCache: Promise<Record<PresetId, CameraPreset>> | null = null
function loadPresets() {
  presetCache ??= fetch(`${BASE}assets/cameras.json`).then((r) => r.json())
  return presetCache
}

function useViewport() {
  const [vp, setVp] = useState({ w: window.innerWidth, h: window.innerHeight })
  useEffect(() => {
    const on = () => setVp({ w: window.innerWidth, h: window.innerHeight })
    window.addEventListener('resize', on)
    return () => window.removeEventListener('resize', on)
  }, [])
  return vp
}

/**
 * Original render vs real-time 3D: the client render is laid exactly over the matching camera frame and
 * revealed with a wipe; a draggable divider splits render (left) and live scene (right).
 */
export function CompareRender() {
  const on = useStore((s) => s.compareOn)
  const preset = useStore((s) => s.preset)
  const setOn = useStore((s) => s.setCompareOn)
  const [presets, setPresets] = useState<Record<PresetId, CameraPreset> | null>(null)
  const vp = useViewport()
  const [mounted, setMounted] = useState(false)
  const [split, setSplit] = useState(0)
  const [dragging, setDragging] = useState(false)
  const [shown, setShown] = useState<PresetId | null>(null)
  const frame = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadPresets().then(setPresets)
  }, [])

  // open: mount at 0, then wipe to the middle; close: wipe back, then unmount
  useEffect(() => {
    if (on) {
      setMounted(true)
      setSplit(0)
      const t = setTimeout(() => setSplit(0.5), 60)
      return () => clearTimeout(t)
    }
    setSplit(0)
    const t = setTimeout(() => setMounted(false), 900)
    return () => clearTimeout(t)
  }, [on])

  // when the view changes, wait for the camera to arrive before swapping the render in
  useEffect(() => {
    if (!preset) return
    const t = setTimeout(() => setShown(preset), shown === null ? 0 : 650)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset])

  useEffect(() => {
    if (!on) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOn(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [on, setOn])

  if (!mounted || !presets || !shown) return null
  const p = presets[shown]
  const r = presetFrameRect(p, vp.w, vp.h)
  const src = PRESETS.find((x) => x.id === shown)!.ref

  const move = (e: RPointerEvent) => {
    const b = frame.current!.getBoundingClientRect()
    setSplit(Math.min(1, Math.max(0, (e.clientX - b.left) / b.width)))
  }

  return (
    <div className={`cmp ${on ? 'cmp--on' : ''} ${dragging ? 'cmp--drag' : ''}`}>
      <div
        ref={frame}
        className="cmp__frame"
        style={{ left: r.x, top: r.y, width: r.w, height: r.h, '--split': split } as CSSProperties}
        onPointerDown={(e) => {
          ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
          setDragging(true)
          move(e)
        }}
        onPointerMove={(e) => dragging && move(e)}
        onPointerUp={() => setDragging(false)}
        onPointerCancel={() => setDragging(false)}
      >
        <div className="cmp__img">
          <img key={src} src={src} alt="Original render" draggable={false} />
        </div>
        <div className="cmp__line">
          <span className="cmp__handle" aria-hidden>
            <svg viewBox="0 0 24 24">
              <path d="M9.5 7 4.5 12l5 5M14.5 7l5 5-5 5" />
            </svg>
          </span>
        </div>
        <span className="cmp__tag cmp__tag--l">Original render</span>
        <span className="cmp__tag cmp__tag--r">Real-time 3D</span>
      </div>
      <button className="cmp__close" onClick={() => setOn(false)}>
        <svg viewBox="0 0 24 24" aria-hidden>
          <path d="M6 6l12 12M18 6 6 18" />
        </svg>
        Close comparison
      </button>
    </div>
  )
}

/** floating preview of the original render while hovering a view */
export function RenderPeek({ id, top }: { id: PresetId | null; top: number }) {
  const [last, setLast] = useState<PresetId | null>(null)
  useEffect(() => {
    if (id) setLast(id)
  }, [id])
  const src = PRESETS.find((p) => p.id === (id ?? last))?.ref
  return (
    <div className={`peek ${id ? 'peek--on' : ''}`} style={{ '--top': `${top}px` } as CSSProperties}>
      {src && <img key={src} src={src} alt="" />}
      <span>Original render</span>
    </div>
  )
}
