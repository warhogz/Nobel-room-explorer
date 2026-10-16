import { useEffect, useRef, useState, type PointerEvent as RPointerEvent } from 'react'
import { useStore } from '../store'
import { walkInput } from '../three/Walk'

const isTouch = () => typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches

/** enter / leave first-person walking */
export function WalkButton() {
  const mode = useStore((s) => s.mode)
  const setMode = useStore((s) => s.setMode)
  const walking = mode === 'walk'
  return (
    <button
      className={`walkbtn ${walking ? 'walkbtn--on' : ''}`}
      onClick={() => setMode(walking ? 'orbit' : 'walk')}
      aria-pressed={walking}
      title={walking ? 'Back to the orbit view (Esc)' : 'Walk through the room in first person'}
    >
      <svg viewBox="0 0 24 24" aria-hidden>
        {walking ? (
          <path d="M6 6l12 12M18 6 6 18" />
        ) : (
          <>
            <circle cx="13" cy="4.6" r="2" />
            <path d="M10.5 21l2-6.2 2.6 2.6V21M8 12.6l2.2-4.3 3.6-.9 2.4 3.4 2.3.6M12.6 14.8l-1.4-5.6" />
          </>
        )}
      </svg>
      <span>{walking ? 'Exit walk' : 'Walk'}</span>
    </button>
  )
}

/** controls card while walking (fades away once the visitor has moved) */
export function WalkHint() {
  const walking = useStore((s) => s.mode === 'walk')
  const [quiet, setQuiet] = useState(false)
  useEffect(() => {
    setQuiet(false)
    if (!walking) return
    const t = setTimeout(() => setQuiet(true), 7000)
    return () => clearTimeout(t)
  }, [walking])
  const touch = isTouch()
  return (
    <div className={`walkhint ${walking ? 'walkhint--on' : ''} ${quiet ? 'walkhint--quiet' : ''}`}>
      {touch ? (
        <>
          <span>
            <kbd>Stick</kbd> walk
          </span>
          <span>
            <kbd>Drag</kbd> look around
          </span>
          <span>
            <kbd>Tap</kbd> the floor to go there
          </span>
        </>
      ) : (
        <>
          <span>
            <kbd>W</kbd>
            <kbd>A</kbd>
            <kbd>S</kbd>
            <kbd>D</kbd> walk
          </span>
          <span>
            <kbd>Shift</kbd> faster
          </span>
          <span>
            <kbd>Drag</kbd> look
          </span>
          <span>
            <kbd>Click</kbd> floor to go
          </span>
          <span>
            <kbd>Esc</kbd> exit
          </span>
        </>
      )}
    </div>
  )
}

/** touch screens: a thumb stick, bottom left */
export function Joystick() {
  const walking = useStore((s) => s.mode === 'walk')
  const base = useRef<HTMLDivElement>(null)
  const [knob, setKnob] = useState({ x: 0, y: 0, active: false })
  const id = useRef<number | null>(null)
  useEffect(() => {
    if (!walking) {
      walkInput.x = walkInput.y = 0
      setKnob({ x: 0, y: 0, active: false })
    }
  }, [walking])
  if (!isTouch()) return null
  const R = 46
  const move = (e: RPointerEvent) => {
    if (id.current !== e.pointerId || !base.current) return
    const r = base.current.getBoundingClientRect()
    let x = e.clientX - (r.left + r.width / 2)
    let y = e.clientY - (r.top + r.height / 2)
    const l = Math.hypot(x, y)
    if (l > R) {
      x = (x / l) * R
      y = (y / l) * R
    }
    setKnob({ x, y, active: true })
    walkInput.x = x / R
    walkInput.y = -y / R
  }
  const end = (e: RPointerEvent) => {
    if (id.current !== e.pointerId) return
    id.current = null
    walkInput.x = walkInput.y = 0
    setKnob({ x: 0, y: 0, active: false })
  }
  return (
    <div
      ref={base}
      className={`joy ${walking ? 'joy--on' : ''} ${knob.active ? 'joy--active' : ''}`}
      onPointerDown={(e) => {
        id.current = e.pointerId
        ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
        move(e)
      }}
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={end}
    >
      <span style={{ transform: `translate(${knob.x}px, ${knob.y}px)` }} />
    </div>
  )
}

/** "island only" (the room dissolves, the island stands in a studio) / back to the full room */
export function IsolateButton() {
  const isolate = useStore((s) => s.isolate)
  const setIsolate = useStore((s) => s.setIsolate)
  return (
    <button
      className={`walkbtn ${isolate ? 'walkbtn--on' : ''}`}
      onClick={() => setIsolate(!isolate)}
      aria-pressed={isolate}
      title={isolate ? 'Bring the room back' : 'Show the island alone'}
    >
      <svg viewBox="0 0 24 24" aria-hidden>
        {isolate ? (
          <path d="M4 11.5 12 5l8 6.5M6.5 9.8V19h11V9.8" />
        ) : (
          <>
            <ellipse cx="12" cy="17.5" rx="8.5" ry="2.6" />
            <path d="M7.5 9.5h9l-1 7h-7z" />
          </>
        )}
      </svg>
      <span>{isolate ? 'Full room' : 'Island only'}</span>
    </button>
  )
}
