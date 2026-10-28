/**
 * ?diag: quality diagnostics in a corner (and window.__diag for the headless checks): asset tier, DPR (render /
 * device), framebuffer size, frame rate, CPU time of the frame (JS + three's command submission), GPU time of the
 * whole frame where EXT_disjoint_timer_query_webgl2 exists (desktop Chrome; not Safari), draw calls and triangles of
 * every pass of the frame (shadows, reflections, post), GPU memory objects and the load time.
 */
import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useRef } from 'react'
import { TIER } from '../lite'
import { DPR_MAX, DPR_MIN } from '../quality'

export const DIAG = new URLSearchParams(location.search).has('diag')

type TimerExt = { TIME_ELAPSED_EXT: number; GPU_DISJOINT_EXT: number }

export function Diag() {
  const gl = useThree((s) => s.gl)
  const el = useRef<HTMLPreElement | null>(null)
  const st = useRef({ frames: 0, t0: performance.now(), cpu: 0, cpuStart: 0, gpu: [] as number[], calls: 0, tris: 0 })
  const timer = useRef<{ ext: TimerExt; ctx: WebGL2RenderingContext; open: WebGLQuery | null; pending: WebGLQuery[] } | null>(null)

  useEffect(() => {
    const pre = document.createElement('pre')
    pre.className = 'diag'
    document.body.appendChild(pre)
    el.current = pre
    const ctx = gl.getContext() as WebGL2RenderingContext
    const ext = ctx.getExtension('EXT_disjoint_timer_query_webgl2') as TimerExt | null
    if (ext) timer.current = { ext, ctx, open: null, pending: [] }
    gl.info.autoReset = false
    return () => {
      pre.remove()
      gl.info.autoReset = true
    }
  }, [gl])

  // first subscriber of the frame: start the clocks
  useFrame(() => {
    const s = st.current
    s.cpuStart = performance.now()
    gl.info.autoReset = false  // (other code may switch it back: the composer's passes would reset the counts)
    gl.info.reset()
    const t = timer.current
    if (t && !t.open && t.pending.length < 4) {
      t.open = t.ctx.createQuery()
      t.ctx.beginQuery(t.ext.TIME_ELAPSED_EXT, t.open!)
    }
  }, -1000)

  // last one, after the composer rendered every pass
  useFrame(() => {
    const s = st.current
    s.cpu += performance.now() - s.cpuStart
    s.calls = gl.info.render.calls
    s.tris = gl.info.render.triangles
    s.frames++
    const t = timer.current
    if (t) {
      if (t.open) {
        t.ctx.endQuery(t.ext.TIME_ELAPSED_EXT)
        t.pending.push(t.open)
        t.open = null
      }
      const disjoint = t.ctx.getParameter(t.ext.GPU_DISJOINT_EXT)
      while (t.pending.length && t.ctx.getQueryParameter(t.pending[0], t.ctx.QUERY_RESULT_AVAILABLE)) {
        const q = t.pending.shift()!
        if (!disjoint) s.gpu.push(t.ctx.getQueryParameter(q, t.ctx.QUERY_RESULT) / 1e6)
        t.ctx.deleteQuery(q)
      }
    }
    const now = performance.now()
    if (now - s.t0 < 1000) return
    const sec = (now - s.t0) / 1000
    const gpu = s.gpu.length ? s.gpu.reduce((a, b) => a + b, 0) / s.gpu.length : null
    const ready = performance.getEntriesByName('nik-ready')[0]
    const d = {
      tier: TIER,
      dpr: +gl.getPixelRatio().toFixed(2),
      dprRange: [DPR_MIN, +DPR_MAX.toFixed(2)],
      device: window.devicePixelRatio,
      framebuffer: [gl.domElement.width, gl.domElement.height],
      fps: +(s.frames / sec).toFixed(1),
      cpuMs: +(s.cpu / s.frames).toFixed(2),
      gpuMs: gpu === null ? null : +gpu.toFixed(2),
      calls: s.calls,
      triangles: s.tris,
      textures: gl.info.memory.textures,
      geometries: gl.info.memory.geometries,
      loadS: ready ? +(ready.startTime / 1000).toFixed(1) : null,
    }
    ;(window as unknown as { __diag: typeof d }).__diag = d
    if (el.current)
      el.current.textContent =
        `${d.tier}  dpr ${d.dpr} / ${d.device}  (${d.dprRange[0]}..${d.dprRange[1]})\n` +
        `${d.framebuffer[0]}x${d.framebuffer[1]}  ${d.fps} fps\n` +
        `cpu ${d.cpuMs} ms  gpu ${d.gpuMs ?? 'n/a'} ms\n` +
        `${d.calls} calls  ${(d.triangles / 1e6).toFixed(2)} M tris\n` +
        `tex ${d.textures}  geo ${d.geometries}  load ${d.loadS ?? '…'} s`
    s.frames = 0
    s.cpu = 0
    s.gpu = []
    s.t0 = now
  }, 1000)
  return null
}
