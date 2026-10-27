import { create } from 'zustand'
import { guardFullLoad } from './lite'

/**
 * Honest preloader state. The scene is only revealed when everything the first frame needs is done:
 *   download (every byte of every file, sizes known up front) -> decode (glTF parse, mesh/texture transcoding)
 *   -> compile (all shader programs, parallel where the GPU allows) -> warmup (light mixing, reflection probes,
 *   first real frames) -> ready
 */
export type LoadStage = 'download' | 'decode' | 'compile' | 'warmup' | 'ready'

export const STAGE_LABEL: Record<LoadStage, string> = {
  download: 'Downloading the scene',
  decode: 'Unpacking geometry and textures',
  compile: 'Preparing materials',
  warmup: 'Lighting the room',
  ready: 'Ready',
}

/** share of the bar each stage owns (download is measured in bytes, the rest creep towards their end) */
export const STAGE_SPAN: Record<LoadStage, [number, number]> = {
  download: [0, 0.72],
  decode: [0.72, 0.82],
  compile: [0.82, 0.94],
  warmup: [0.94, 1],
  ready: [1, 1],
}

interface LoadState {
  stage: LoadStage
  loaded: number
  total: number
  stageSince: number
  setStage: (s: LoadStage) => void
}

export const useLoad = create<LoadState>((set, get) => ({
  stage: 'download',
  loaded: 0,
  total: 0,
  stageSince: performance.now(),
  setStage: (s) => {
    const order: LoadStage[] = ['download', 'decode', 'compile', 'warmup', 'ready']
    if (order.indexOf(s) > order.indexOf(get().stage)) {
      performance.mark('nik-' + s)  // load timeline for profiling (performance.getEntriesByType('mark'))
      set({ stage: s, stageSince: performance.now() })
    }
    if (s === 'ready') guardFullLoad(false)
  },
}))

const files = new Map<string, { loaded: number; total: number }>()

function publish() {
  let loaded = 0
  let total = 0
  for (const f of files.values()) {
    loaded += Math.min(f.loaded, f.total)
    total += f.total
  }
  useLoad.setState({ loaded, total })
  // every byte is in: what remains of the loading is parsing / transcoding
  if (total > 0 && loaded >= total) useLoad.getState().setStage('decode')
}

/** register the files that will be fetched (bytes from the asset manifest) before any download starts */
export function expectFiles(sizes: Record<string, number>) {
  for (const [url, total] of Object.entries(sizes)) if (!files.has(url)) files.set(url, { loaded: 0, total })
  publish()
}

export function reportBytes(url: string, loaded: number, total?: number) {
  const f = files.get(url) ?? { loaded: 0, total: total || loaded }
  f.loaded = Math.max(f.loaded, loaded)
  if (total && total > f.total) f.total = total
  files.set(url, f)
  publish()
}

export function fileDone(url: string) {
  const f = files.get(url)
  if (f) {
    f.loaded = f.total
    publish()
  }
}

/** fetch with streamed byte progress */
export async function fetchBuffer(base: string, url: string): Promise<ArrayBuffer> {
  const res = await fetch(base + url)
  if (!res.ok || !res.body) throw new Error(`${url}: ${res.status}`)
  const total = Number(res.headers.get('content-length')) || undefined
  const reader = res.body.getReader()
  const chunks: Uint8Array[] = []
  let loaded = 0
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    chunks.push(value)
    loaded += value.byteLength
    reportBytes(url, loaded, total)
  }
  const out = concat(chunks)
  // a host that ignores Git LFS serves the ~130 byte pointer file instead of the asset
  if (out.byteLength < 512 && new TextDecoder().decode(out).startsWith('version https://git-lfs'))
    throw new Error(`${url}: got a Git LFS pointer instead of the file`)
  fileDone(url)
  return out.buffer as ArrayBuffer
}

/** fetch a file stored in pieces, all pieces in parallel */
export async function fetchParts(base: string, urls: string[]): Promise<ArrayBuffer> {
  const parts = await Promise.all(urls.map((u) => fetchBuffer(base, u)))
  return concat(parts.map((p) => new Uint8Array(p))).buffer as ArrayBuffer
}

function concat(chunks: Uint8Array[]) {
  const out = new Uint8Array(chunks.reduce((n, c) => n + c.byteLength, 0))
  let o = 0
  for (const c of chunks) {
    out.set(c, o)
    o += c.byteLength
  }
  return out
}

;(window as unknown as { __load: typeof useLoad }).__load = useLoad  // dev probe: __load.getState()
