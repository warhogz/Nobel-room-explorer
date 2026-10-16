import { create } from 'zustand'
import { CORONA_DEFAULTS, type CoronaTMParams } from './three/CoronaToneMapping'
import type { GroupId, GroupMix } from './three/lightmix'

export type PresetId = '030' | '08' | '10' | '12' | '28'

export const PRESETS: { id: PresetId; label: string; ref: string }[] = [
  { id: '030', label: 'Overview', ref: 'ref/030.jpg' },
  { id: '10', label: 'Island & table', ref: 'ref/10.jpg' },
  { id: '08', label: 'Table side', ref: 'ref/08.jpg' },
  { id: '12', label: 'Island front', ref: 'ref/12.jpg' },
  { id: '28', label: 'Dining hall', ref: 'ref/28.jpg' },
]

export const GROUP_LABELS: Record<GroupId, string> = {
  kitchen: 'Interior lights',
  ostrov: 'Onyx glow',
  pol: 'Floor lights',
  env: 'Daylight',
}

/**
 * LightMix defaults. The Corona LightMix colours/intensities of the villa scene are already baked into the
 * lights (kitchen = every artificial light, env = suns + sky); these are master faders calibrated by eye.
 */
export const MIX_DEFAULTS: Record<GroupId, GroupMix> = {
  // the blackbody/LightMix tints of the converted lights come out more saturated than in Corona: cooled a little
  kitchen: { color: [0.84, 1.0, 0.72], intensity: 4.6, enabled: true },
  ostrov: { color: [1.0, 0.55, 0.25], intensity: 2.5, enabled: true },
  pol: { color: [1.0, 1.0, 1.0], intensity: 100.0, enabled: true },
  env: { color: [1.0, 0.88, 0.7], intensity: 2.8, enabled: true },
}

export type FaucetFinish = 'black' | 'brass' | 'beige'

export const FINISHES: { id: FaucetFinish; label: string; swatch: string }[] = [
  { id: 'black', label: 'Matte black', swatch: 'radial-gradient(circle at 35% 30%, #4a4744, #141312 70%)' },
  { id: 'brass', label: 'Brass', swatch: 'radial-gradient(circle at 35% 30%, #f6dca0, #b8863f 55%, #6e4a1c)' },
  { id: 'beige', label: 'Sand beige', swatch: 'radial-gradient(circle at 35% 30%, #efe3cf, #c9b597 60%, #9c8667)' },
]

export interface HoverInfo {
  label: string
  hint?: string
}

interface State {
  preset: PresetId | null
  presetNonce: number
  introDone: boolean
  mix: Record<GroupId, GroupMix>
  tm: CoronaTMParams
  envIntensity: number
  compare: { on: boolean; opacity: number }
  dev: boolean
  lamps: boolean[]
  /** daylight through the windows (sun + sky) vs evening */
  day: boolean
  /** orbit around the island, or walk the room in first person */
  mode: 'orbit' | 'walk'
  /** "island only": the room dissolves, the island stands on a floor disc in a studio backdrop */
  isolate: boolean
  setIsolate: (v: boolean) => void
  setMode: (m: 'orbit' | 'walk') => void
  toggleDay: () => void
  finish: FaucetFinish
  focus: 'faucet' | null
  hover: HoverInfo | null
  compareOn: boolean
  setCompareOn: (v: boolean) => void
  setLampCount: (n: number) => void
  toggleLamp: (i: number) => void
  toggleAllLamps: () => void
  toggleLights: () => void
  setFinish: (f: FaucetFinish) => void
  setFocus: (f: State['focus']) => void
  setHover: (h: HoverInfo | null) => void
  goTo: (p: PresetId) => void
  freeLook: () => void
  setIntroDone: () => void
  setMix: (g: GroupId, m: Partial<GroupMix>) => void
  resetMix: () => void
  setTM: (p: Partial<CoronaTMParams>) => void
  setEnvIntensity: (v: number) => void
  setCompare: (c: Partial<State['compare']>) => void
}

export const useStore = create<State>((set) => ({
  preset: '10',
  presetNonce: 0,
  introDone: false,
  mix: structuredClone(MIX_DEFAULTS),
  tm: { ...CORONA_DEFAULTS },
  envIntensity: 1.0,
  compare: { on: false, opacity: 0.5 },
  dev: new URLSearchParams(location.search).has('dev'),
  lamps: Array(8).fill(true),
  day: true,
  toggleDay: () => set((s) => ({ day: !s.day })),
  mode: 'orbit',
  setMode: (m) =>
    set((s) => (m === 'walk' ? { mode: m, preset: null, focus: null, compareOn: false, hover: null, isolate: false } : { mode: m, presetNonce: s.presetNonce })),
  isolate: false,
  // back to the room: fly to the "Island & table" view while the room reappears around the island
  setIsolate: (v) =>
    set((s) =>
      v
        ? { isolate: true, mode: 'orbit', preset: null, focus: null, compareOn: false, hover: null }
        : { isolate: false, preset: '10', presetNonce: s.presetNonce + 1 },
    ),
  finish: 'black',
  focus: null,
  hover: null,
  compareOn: false,
  setCompareOn: (v) => set((s) => ({ compareOn: v && !!s.preset, focus: v ? null : s.focus })),
  setLampCount: (n) => set((s) => (s.lamps.length === n ? s : { lamps: Array(n).fill(true) })),
  toggleLamp: (i) => set((s) => ({ lamps: s.lamps.map((v, j) => (j === i ? !v : v)) })),
  toggleAllLamps: () => set((s) => {
    const on = !s.lamps.some(Boolean)
    return { lamps: s.lamps.map(() => on) }
  }),
  toggleLights: () => set((s) => ({ mix: { ...s.mix, kitchen: { ...s.mix.kitchen, enabled: !s.mix.kitchen.enabled } } })),
  setFinish: (f) => set({ finish: f }),
  setFocus: (f) => set((s) => ({ focus: f, compareOn: f ? false : s.compareOn })),
  setHover: (h) => set({ hover: h }),
  goTo: (p) => set((s) => ({ preset: p, presetNonce: s.presetNonce + 1, focus: null, hover: null, mode: 'orbit', isolate: false })),
  freeLook: () => set({ preset: null, compareOn: false }),
  setIntroDone: () => set({ introDone: true }),
  setMix: (g, m) => set((s) => ({ mix: { ...s.mix, [g]: { ...s.mix[g], ...m } } })),
  resetMix: () => set((s) => ({ mix: structuredClone(MIX_DEFAULTS), lamps: s.lamps.map(() => true) })),
  setTM: (p) => set((s) => ({ tm: { ...s.tm, ...p } })),
  setEnvIntensity: (v) => set({ envIntensity: v }),
  setCompare: (c) => set((s) => ({ compare: { ...s.compare, ...c } })),
}))
