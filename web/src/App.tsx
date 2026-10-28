import { PerformanceMonitor } from '@react-three/drei'
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
import { STAGE_SPAN, useLoad } from './loading'

const LOGO = `${import.meta.env.BASE_URL}logo.svg`
import { IsolateButton, Joystick, WalkButton, WalkHint } from './ui/WalkUI'
import { FINISHES, GROUP_LABELS, PRESETS, useStore, type PresetId } from './store'
import { LITE } from './lite'
import { adaptiveHeld, DPR_FORCED, DPR_MAX, DPR_MIN, DPR_START, holdAdaptive } from './quality'
import { Diag, DIAG } from './three/Diag'

const TOUCH = typeof matchMedia !== 'undefined' && matchMedia('(pointer: coarse)').matches
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
      <Bloom intensity={0.5} luminanceThreshold={2.6} luminanceSmoothing={0.4} mipmapBlur radius={0.7} blendFunction={BlendFunction.ADD} />
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
  const fill = useRef<HTMLImageElement>(null)
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
      if (pct.current) pct.current.textContent = `${Math.floor(shown * 100)}`
      // the logo is written in as the scene arrives
      if (fill.current) fill.current.style.clipPath = `inset(0 ${(100 - shown * 100).toFixed(2)}% 0 0)`
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
      <div className="loader__logo" aria-label="Nobel">
        <img src={LOGO} alt="" className="loader__logo-dim" />
        <img src={LOGO} alt="" className="loader__logo-fill" ref={fill} />
      </div>
      <div className="loader__line">
        <span ref={bar} />
      </div>
      <span ref={pct} className="loader__pct" />
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
      const el = list.current
      if (TOUCH && btn && el) el.scrollTo({ left: btn.offsetLeft - (el.clientWidth - btn.offsetWidth) / 2, behavior: 'smooth' })  // not scrollIntoView: it shifts the page
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
      {!LITE && <button
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
      </button>}
      <RenderPeek id={compareOn ? null : peek.id} top={peek.top} />
    </nav>
  )
}

/** touch screens: the faucet finish behind one tap (the taps themselves are a small target), shown as the current swatch */
function FaucetButton() {
  const { introDone, focus, finish, setFocus, mode } = useStore()
  const sw = FINISHES.find((f) => f.id === finish)?.swatch
  return (
    <button
      className={`faucetbtn ${introDone && !focus && mode === 'orbit' ? 'ui--on' : ''}`}
      onClick={() => setFocus('faucet')}
      aria-label="Faucet finish"
    >
      <i style={{ background: sw }} />
    </button>
  )
}

/** touch screens: how to move, until the first touch */
function GestureHint() {
  const introDone = useStore((s) => s.introDone)
  const focus = useStore((s) => s.focus)
  const [used, setUsed] = useState(false)
  useEffect(() => {
    if (!introDone || used) return
    const done = () => setUsed(true)
    const t = setTimeout(done, 9000)
    window.addEventListener('pointerdown', done, { once: true })
    return () => {
      clearTimeout(t)
      window.removeEventListener('pointerdown', done)
    }
  }, [introDone, used])
  return (
    <div className={`ghint ${introDone && !used && !focus ? 'ghint--on' : ''}`}>
      <svg viewBox="0 0 24 24" aria-hidden>
        <path d="M9 11V6.5a1.5 1.5 0 0 1 3 0V11m0-1.5a1.5 1.5 0 0 1 3 0V11m0-.5a1.5 1.5 0 0 1 3 0V15a5 5 0 0 1-5 5h-1.2a5 5 0 0 1-4.1-2.2L5.6 15a1.5 1.5 0 0 1 2.4-1.8L9 14.5" />
      </svg>
      Drag to turn · pinch to zoom
    </div>
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
      <span className="finish__grab" aria-hidden />
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
        <img className="brand__logo" src={LOGO} alt="Nobel" />
        <div className="brand__sub">{LITE ? 'Onyx island · table & stools' : 'Onyx island · Villa kitchen & hall'}</div>
      </header>
      <div className={`top-right ${ready}`}>
        {!LITE && <IsolateButton />}
        {!LITE && <WalkButton />}
        {!LITE && <LightSwitch />}
      </div>
      <WalkHint />
      <Joystick />
      <Views />
      {TOUCH && <FaucetButton />}
      {TOUCH && <GestureHint />}
      <FinishPicker />
      <footer className={`hint ${introDone && !focus && !compareOn && mode === 'orbit' ? 'ui--on' : ''}`}>
        <span><kbd>Drag</kbd> orbit</span>
        <span><kbd>{TOUCH ? 'Pinch' : 'Scroll'}</kbd> zoom</span>
        <span><kbd>Click</kbd> floor lights · faucet</span>
      </footer>
    </>
  )
}

export default function App() {
  // UI theme follows the daylight
  const bright = useStore((s) => s.day)
  const walking = useStore((s) => s.mode === 'walk')
  const loaded = useLoad((s) => s.stage === 'ready')
  // resolution follows the frame rate: a slow phone renders fewer pixels instead of stuttering, a strong one climbs to
  // its native density. Only sustained trends count (two averaged windows in a row), never loading, shader warm-up,
  // the day / evening switch or a camera preset
  const [dpr, setDpr] = useState(DPR_START)
  const trend = useRef(0)
  const day = useStore((s) => s.day)
  const preset = useStore((s) => s.presetNonce)
  useEffect(() => void (loaded && holdAdaptive(4000)), [loaded])
  useEffect(() => holdAdaptive(3000), [day, preset])
  const step = (dir: number) => {
    if (DPR_FORCED || useLoad.getState().stage !== 'ready' || adaptiveHeld()) return void (trend.current = 0)
    trend.current = Math.sign(trend.current) === dir ? trend.current + dir : dir
    if (Math.abs(trend.current) < 2) return
    trend.current = 0
    setDpr((c) => Math.min(DPR_MAX, Math.max(DPR_MIN, +(c + dir * 0.25).toFixed(2))))
  }
  return (
    <div className={`app ${bright ? 'app--light' : ''} ${walking ? 'app--walk' : ''} ${loaded ? 'app--ready' : ''}`}>
      <Canvas
        dpr={dpr}
        gl={{ antialias: false, alpha: true, toneMapping: THREE.NoToneMapping, outputColorSpace: THREE.SRGBColorSpace, powerPreference: 'high-performance' }}
        camera={{ fov: 50, near: 0.02, far: 100, position: [-6.5, 3.6, 6.8] }}
        onCreated={({ gl, scene }) => {
          // transparent clear: the background is composited in the post effect from scene coverage (alpha)
          scene.background = null
          ;(window as unknown as { __gl: THREE.WebGLRenderer }).__gl = gl  // dev probe: __gl.info
          gl.setClearColor(0x000000, 0)
        }}
      >
        <PerformanceMonitor
          bounds={() => [30, 52]}
          flipflops={4}
          onDecline={() => step(-1)}
          onIncline={() => step(1)}
        />
        {DIAG && <Diag />}
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
