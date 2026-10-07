import { create } from 'zustand'
import { CORONA_DEFAULTS, type CoronaTMParams } from './three/CoronaToneMapping'
import type { GroupId, GroupMix } from './three/lightmix'

export type PresetId = '030' | '08' | '10' | '12'

export const PRESETS: { id: PresetId; label: string; ref: string }[] = [
  { id: '030', label: 'Overview', ref: 'ref/030.jpg' },
  { id: '10', label: 'Island & table', ref: 'ref/10.jpg' },
  { id: '08', label: 'Table side', ref: 'ref/08.jpg' },
  { id: '12', label: 'Island front', ref: 'ref/12.jpg' },
]

export const GROUP_LABELS: Record<GroupId, string> = {
  kitchen: 'Kitchen lights',
  ostrov: 'Onyx glow',
  pol: 'Floor lights',
  env: 'Bounce light',
}

/**
 * LightMix defaults: colours follow the Corona LightMix groups (TOCHKI KUHNA ~3200K / OSTROV / TOCHKI POL);
 * intensities calibrated by eye against render 030 (the scene's own lights are not in the .max file).
 */
export const MIX_DEFAULTS: Record<GroupId, GroupMix> = {
  kitchen: { color: [1.0, 0.72, 0.47], intensity: 0.3, enabled: true },
  ostrov: { color: [1.0, 0.6, 0.33], intensity: 1.3, enabled: true },
  pol: { color: [1.0, 0.774, 0.505], intensity: 2.6, enabled: true },
  env: { color: [1.0, 1.0, 1.0], intensity: 0.3, enabled: true },
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
  preset: '030',
  presetNonce: 0,
  introDone: false,
  mix: structuredClone(MIX_DEFAULTS),
  tm: { ...CORONA_DEFAULTS },
  envIntensity: 0.6,
  compare: { on: false, opacity: 0.5 },
  dev: new URLSearchParams(location.search).has('dev'),
  lamps: Array(8).fill(true),
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
  goTo: (p) => set((s) => ({ preset: p, presetNonce: s.presetNonce + 1, focus: null, hover: null })),
  freeLook: () => set({ preset: null, compareOn: false }),
  setIntroDone: () => set({ introDone: true }),
  setMix: (g, m) => set((s) => ({ mix: { ...s.mix, [g]: { ...s.mix[g], ...m } } })),
  resetMix: () => set((s) => ({ mix: structuredClone(MIX_DEFAULTS), lamps: s.lamps.map(() => true) })),
  setTM: (p) => set((s) => ({ tm: { ...s.tm, ...p } })),
  setEnvIntensity: (v) => set({ envIntensity: v }),
  setCompare: (c) => set((s) => ({ compare: { ...s.compare, ...c } })),
}))
