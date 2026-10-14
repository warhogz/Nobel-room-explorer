import { Canvas, useFrame } from '@react-three/fiber'
import { Bloom, EffectComposer, SMAA } from '@react-three/postprocessing'
import { BlendFunction } from 'postprocessing'
import { Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import * as THREE from 'three'
import { CameraRig } from './three/CameraRig'
import { CoronaToneMappingEffect } from './three/CoronaToneMapping'
import { FloorLamps } from './three/FloorLamps'
import { Kitchen } from './three/Kitchen'
import { GROUPS } from './three/lightmix'
import { live } from './three/live'
import { WalkControls } from './three/Walk'
import { STAGE_LABEL, STAGE_SPAN, useLoad } from './loading'
import { Joystick, WalkButton, WalkHint } from './ui/WalkUI'
import { FINISHES, GROUP_LABELS, PRESETS, useStore, type PresetId } from './store'
import { CompareRender, RenderPeek } from './ui/Compare'
import './App.css'

function PostFX() {
  const tm = useStore((s) => s.tm)
  const effect = useMemo(() => new CoronaToneMappingEffect(), [])
  useEffect(() => effect.setParams(tm), [effect, tm])
  useFrame(() => effect.setLight(live.light))
  return (
    <EffectComposer frameBufferType={THREE.HalfFloatType} multisampling={0}>
      {/* glare in scene-linear HDR, only from real light sources (LEDs, glowing onyx peaks), then tone mapping */}
      <Bloom intensity={0.55} luminanceThreshold={1.6} luminanceSmoothing={0.5} mipmapBlur radius={0.82} blendFunction={BlendFunction.ADD} />
      <primitive object={effect} />
      <SMAA />
    </EffectComposer>
  )
}

/**
 * Honest preloader: bytes of every file, then decoding, shader compilation and the first lit frames. The scene is
 * revealed only when it can be shown at full quality (no black frames, no pop-in).
 */
function Loader() {
  const stage = useLoad((s) => s.stage)
  const bar = useRef<HTMLSpanElement>(null)
  const pct = useRef<HTMLSpanElement>(null)
  const mb = useRef<HTMLSpanElement>(null)
  const [gone, setGone] = useState(false)
  useEffect(() => {
    let raf = 0
    let shown = 0
    const tick = () => {
      const { stage, loaded, total, stageSince } = useLoad.getState()
      const [a, b] = STAGE_SPAN[stage]
      let target: number
      if (stage === 'download') target = a + (b - a) * (total ? loaded / total : 0)
      else if (stage === 'ready') target = 1
      // stages without a measurable size: creep towards (never reach) their end until they really finish
      else target = a + (b - a) * 0.9 * (1 - Math.exp(-(performance.now() - stageSince) / 2500))
      shown = Math.max(shown, shown + (target - shown) * 0.12)
      if (bar.current) bar.current.style.transform = `scaleX(${Math.max(0.02, shown)})`
      if (pct.current) pct.current.textContent = `${Math.floor(shown * 100)}%`
      if (mb.current) mb.current.textContent = total ? `${(loaded / 2 ** 20).toFixed(0)} / ${(total / 2 ** 20).toFixed(0)} MB` : ''
      if (stage !== 'ready' || shown < 0.999) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])
  useEffect(() => {
    if (stage !== 'ready') return
    const t = setTimeout(() => setGone(true), 1600)
    return () => clearTimeout(t)
  }, [stage])
  return (
    <div className={`loader ${stage === 'ready' ? 'loader--hidden' : ''} ${gone ? 'loader--gone' : ''}`}>
      <div className="loader__brand">Nobel Island Kitchen</div>
      <div className="loader__bar">
        <span ref={bar} />
      </div>
      <div className="loader__row">
        <span className="loader__stage" key={stage}>
          {STAGE_LABEL[stage]}
        </span>
        <span ref={pct} className="loader__pct" />
      </div>
      <span ref={mb} className="loader__mb" />
    </div>
  )
}

/** label that follows the pointer (floor lights, faucet) with a little lag */
function Tooltip() {
  const hover = useStore((s) => s.hover)
  const el = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const target = { x: 0, y: 0 }
    const pos = { x: 0, y: 0 }
    let raf = 0
    const onMove = (e: PointerEvent) => {
      target.x = e.clientX + 18
      target.y = e.clientY + 20
    }
    const tick = () => {
      pos.x += (target.x - pos.x) * 0.28
      pos.y += (target.y - pos.y) * 0.28
      if (el.current) el.current.style.translate = `${pos.x}px ${pos.y}px`
      raf = requestAnimationFrame(tick)
    }
    window.addEventListener('pointermove', onMove)
    raf = requestAnimationFrame(tick)
    return () => {
      window.removeEventListener('pointermove', onMove)
      cancelAnimationFrame(raf)
    }
  }, [])
  return (
    <div ref={el} className={`tooltip ${hover ? 'tooltip--on' : ''}`}>
      <b>{hover?.label}</b>
      {hover?.hint && <span>{hover.hint}</span>}
    </div>
  )
}

/** day / evening: sunlight through the clerestory windows vs the interior lights alone */
function LightSwitch() {
  const on = useStore((s) => s.day)
  const toggle = useStore((s) => s.toggleDay)
  return (
    <button className={`switch ${on ? 'switch--on' : ''}`} onClick={toggle} aria-pressed={on} aria-label="Toggle daylight">
      <span className="switch__track">
        <span className="switch__knob">
          <svg viewBox="0 0 24 24" aria-hidden>
            <g className="sun">
              <circle cx="12" cy="12" r="4.2" />
              {Array.from({ length: 8 }, (_, i) => (
                <line key={i} x1="12" y1="2.6" x2="12" y2="5" transform={`rotate(${i * 45} 12 12)`} />
              ))}
            </g>
            <path className="moon" d="M15.5 4.2a8 8 0 1 0 4.3 12.9A7 7 0 0 1 15.5 4.2Z" />
          </svg>
        </span>
      </span>
      <span className="switch__label">{on ? 'Day' : 'Evening'}</span>
    </button>
  )
}

/** camera views with a sliding active indicator, render preview on hover, compare toggle */
function Views() {
  const { preset, goTo, introDone, focus, compareOn, setCompareOn } = useStore()
  const list = useRef<HTMLDivElement>(null)
  const [pill, setPill] = useState<{ y: number; h: number; x: number; w: number } | null>(null)
  const [peek, setPeek] = useState<{ id: PresetId | null; top: number }>({ id: null, top: 0 })
  useLayoutEffect(() => {
    const update = () => {
      const btn = list.current?.querySelector<HTMLButtonElement>('button.active')
      setPill(btn ? { y: btn.offsetTop, h: btn.offsetHeight, x: btn.offsetLeft, w: btn.offsetWidth } : null)
    }
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [preset, introDone])
  return (
    <nav className={`views ${introDone && !focus ? 'ui--on' : ''}`} onPointerLeave={() => setPeek((p) => ({ ...p, id: null }))}>
      <div className="views__label">Views</div>
      <div className="views__list" ref={list}>
        <span
          className={`views__pill ${pill ? '' : 'views__pill--off'}`}
          style={pill ? ({ '--y': `${pill.y}px`, '--h': `${pill.h}px`, '--x': `${pill.x}px`, '--w': `${pill.w}px` } as CSSProperties) : undefined}
        />
        {PRESETS.map((p, i) => (
          <button
            key={p.id}
            className={preset === p.id ? 'active' : ''}
            onClick={() => goTo(p.id)}
            onPointerEnter={(e) => setPeek({ id: p.id, top: (e.currentTarget as HTMLElement).offsetTop })}
            style={{ '--i': i } as CSSProperties}
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className={`views__free ${preset === null ? 'views__free--on' : ''}`}>Free view</div>
      <button
        className={`views__compare ${compareOn ? 'active' : ''}`}
        onClick={() => setCompareOn(!compareOn)}
        disabled={!preset}
        title={preset ? 'Overlay the original render for this view' : 'Pick a view first'}
      >
        <svg viewBox="0 0 24 24" aria-hidden>
          <rect x="3.5" y="5" width="17" height="14" rx="2.5" />
          <path d="M12 3v18" />
        </svg>
        {compareOn ? 'Hide render' : 'Compare with render'}
      </button>
      <RenderPeek id={compareOn ? null : peek.id} top={peek.top} />
    </nav>
  )
}

/** faucet close-up: finish picker */
function FinishPicker() {
  const focus = useStore((s) => s.focus)
  const finish = useStore((s) => s.finish)
  const setFinish = useStore((s) => s.setFinish)
  const setFocus = useStore((s) => s.setFocus)
  return (
    <div className={`finish ${focus === 'faucet' ? 'finish--on' : ''}`}>
      <div className="finish__head">
        <div>
          <div className="finish__eyebrow">Faucet</div>
          <div className="finish__title">Choose a finish</div>
        </div>
        <button className="finish__back" onClick={() => setFocus(null)}>
          <svg viewBox="0 0 24 24" aria-hidden>
            <path d="M14.5 6.5 9 12l5.5 5.5" />
          </svg>
          Back
        </button>
      </div>
      <div className="finish__list">
        {FINISHES.map((f, i) => (
          <button key={f.id} className={`swatch ${finish === f.id ? 'active' : ''}`} onClick={() => setFinish(f.id)} style={{ '--i': i } as CSSProperties}>
            <i style={{ background: f.swatch }} />
            <span>{f.label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function Slider(props: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void }) {
  return (
    <label className="slider">
      <span>{props.label}</span>
      <input type="range" min={props.min} max={props.max} step={props.step} value={props.value} onChange={(e) => props.onChange(+e.target.value)} />
      <em>{props.value.toFixed(2)}</em>
    </label>
  )
}

/** calibration tools, only with ?dev */
function DevPanel() {
  const s = useStore()
  const ref = PRESETS.find((p) => p.id === s.preset)?.ref
  if (!s.dev) return null
  return (
    <>
      {ref && <img className="compare" src={ref} style={{ opacity: s.compare.on ? s.compare.opacity : 0 }} alt="" />}
      <details className="dev">
        <summary>Calibration</summary>
        {GROUPS.map((g) => (
          <Slider key={g} label={GROUP_LABELS[g]} value={s.mix[g].intensity} min={0} max={3} step={0.01} onChange={(v) => s.setMix(g, { intensity: v })} />
        ))}
        <Slider label="Exposure" value={s.tm.userEV} min={-3} max={3} step={0.05} onChange={(v) => s.setTM({ userEV: v })} />
        <Slider label="Calibration EV" value={s.tm.calibrationEV} min={-4} max={2} step={0.05} onChange={(v) => s.setTM({ calibrationEV: v })} />
        <Slider label="White balance" value={s.tm.whiteBalanceK} min={3000} max={9000} step={50} onChange={(v) => s.setTM({ whiteBalanceK: v })} />
        <Slider label="Contrast K" value={s.tm.contrastK} min={0} max={1} step={0.01} onChange={(v) => s.setTM({ contrastK: v })} />
        <Slider label="Reflections" value={s.envIntensity} min={0} max={3} step={0.01} onChange={s.setEnvIntensity} />
        <Slider label="Render overlay" value={s.compare.on ? s.compare.opacity : 0} min={0} max={1} step={0.01} onChange={(v) => s.setCompare({ on: v > 0, opacity: v })} />
      </details>
    </>
  )
}

function UI() {
  const introDone = useStore((s) => s.introDone)
  const focus = useStore((s) => s.focus)
  const compareOn = useStore((s) => s.compareOn)
  const mode = useStore((s) => s.mode)
  const ready = introDone ? 'ui--on' : ''
  return (
    <>
      <DevPanel />
      <CompareRender />
      <Tooltip />
      <header className={`brand ${ready}`}>
        <div className="brand__title">Nobel Island Kitchen</div>
        <div className="brand__sub">Onyx island · Villa kitchen & hall</div>
      </header>
      <div className={`top-right ${ready}`}>
        <WalkButton />
        <LightSwitch />
      </div>
      <WalkHint />
      <Joystick />
      <Views />
      <FinishPicker />
      <footer className={`hint ${introDone && !focus && !compareOn && mode === 'orbit' ? 'ui--on' : ''}`}>
        <span><kbd>Drag</kbd> orbit</span>
        <span><kbd>Scroll</kbd> zoom</span>
        <span><kbd>Click</kbd> floor lights · faucet</span>
      </footer>
    </>
  )
}

export default function App() {
  // UI theme follows the daylight
  const bright = useStore((s) => s.day)
  const walking = useStore((s) => s.mode === 'walk')
  return (
    <div className={`app ${bright ? 'app--light' : ''} ${walking ? 'app--walk' : ''}`}>
      <Canvas
        dpr={[1, 2]}
        gl={{ antialias: false, alpha: true, toneMapping: THREE.NoToneMapping, outputColorSpace: THREE.SRGBColorSpace, powerPreference: 'high-performance' }}
        camera={{ fov: 50, near: 0.02, far: 100, position: [-6.5, 3.6, 6.8] }}
        onCreated={({ gl, scene }) => {
          // transparent clear: the background is composited in the post effect from scene coverage (alpha)
          scene.background = null
          gl.setClearColor(0x000000, 0)
        }}
      >
        <Suspense fallback={null}>
          <Kitchen />
          <FloorLamps />
          <CameraRig />
          <WalkControls />
          <PostFX />
        </Suspense>
      </Canvas>
      <Loader />
      <UI />
    </div>
  )
}
