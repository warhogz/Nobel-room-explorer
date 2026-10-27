/**
 * Which scene this visit gets.
 *   full   : the whole kitchen + hall (~150 MB, ~2 M triangles) - desktops
 *   mobile : the same room, lighter (a fifth of the triangles, 1K textures, 8 bit lightmaps) - phones and tablets
 *   lite   : the island, the table and the stools around it on the kitchen floor in a studio space (~46 MB) - phones
 *            with little memory, or after the browser killed a bigger load (the endless loading loop)
 * ?full / ?mobile / ?lite force a version. A load that never finished in this tab falls back one step
 * (full -> mobile -> lite) instead of trying again.
 */
const params = new URLSearchParams(location.search)
const GUARD = { full: 'nik-full-loading', mobile: 'nik-mobile-loading' }

function storage(): Storage | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

export type Tier = 'full' | 'mobile' | 'lite'

function decide(): Tier {
  if (params.has('lite')) return 'lite'
  if (params.has('mobile')) return 'mobile'
  if (params.has('full')) return 'full'
  const s = storage()
  if (s?.getItem(GUARD.mobile)) return 'lite' // the last mobile load in this tab crashed
  const coarse = matchMedia('(pointer: coarse)').matches && !matchMedia('(pointer: fine)').matches
  const mem = (navigator as Navigator & { deviceMemory?: number }).deviceMemory
  if (mem !== undefined && mem <= 2) return 'lite'
  if (s?.getItem(GUARD.full)) return 'mobile' // the last full load in this tab crashed
  return coarse || (mem !== undefined && mem < 4) ? 'mobile' : 'full'
}

export const TIER = decide()
/** the island, table and stools in a studio space (phones with little memory, or after a crash) */
export const LITE = TIER === 'lite'
/** the whole room, lighter: a fifth of the triangles, 1K textures, 8 bit lightmaps (phones, tablets) */
export const MOBILE = TIER === 'mobile'
/** asset folder of this version (under the site base) */
export const ASSETS = LITE ? 'assets-lite/' : MOBILE ? 'assets-mobile/' : 'assets/'

/** call before the heavy downloads start / once the scene is on screen */
export function guardFullLoad(on: boolean) {
  if (LITE) return
  const s = storage()
  try {
    if (on) s?.setItem(GUARD[TIER as 'full' | 'mobile'], '1')
    else s?.removeItem(GUARD[TIER as 'full' | 'mobile'])
  } catch {
    /* private mode: no guard */
  }
}
