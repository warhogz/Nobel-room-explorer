/**
 * Which scene this visit gets.
 *   full : the whole kitchen + hall (~310 MB, ~4 M triangles) - desktops
 *   lite : the island, the table and the stools around it on the kitchen floor in a studio space (~46 MB) - phones and
 *          tablets, whose browsers kill a tab that big and reload it (the endless loading loop)
 * ?full / ?lite force a version. A full load that never finished in this tab (the browser killed and reloaded it)
 * falls back to the lite scene instead of trying again.
 */
const params = new URLSearchParams(location.search)
const GUARD = 'nik-full-loading'

function storage(): Storage | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

function decide(): boolean {
  if (params.has('lite')) return true
  if (params.has('full')) return false
  if (storage()?.getItem(GUARD)) return true // the last full load in this tab crashed
  const coarse = matchMedia('(pointer: coarse)').matches && !matchMedia('(pointer: fine)').matches
  const mem = (navigator as Navigator & { deviceMemory?: number }).deviceMemory
  return coarse || (mem !== undefined && mem < 4)
}

export const LITE = decide()
/** asset folder of this version (under the site base) */
export const ASSETS = LITE ? 'assets-lite/' : 'assets/'

/** call before the heavy downloads start / once the scene is on screen */
export function guardFullLoad(on: boolean) {
  if (LITE) return
  const s = storage()
  try {
    if (on) s?.setItem(GUARD, '1')
    else s?.removeItem(GUARD)
  } catch {
    /* private mode: no guard */
  }
}
