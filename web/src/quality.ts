/**
 * Render resolution (device pixel ratio of the canvas), separate from the asset tier (lite.ts).
 *   max   : native DPR (phones up to 2.5x: with 4x MSAA a 3x framebuffer costs too much memory for little gain),
 *           limited by a framebuffer pixel budget (memory, fill rate)
 *   start : phones begin at 2x and climb to native only while the frame rate holds
 *   min   : the floor the adaptive resolution may fall to on a struggling device
 * ?dpr=<n> pins the resolution (tests); the adaptive steps are then off.
 */
import { LITE, MOBILE } from './lite'

const PHONE = LITE || MOBILE
const forced = Number(new URLSearchParams(location.search).get('dpr')) || 0
const native = Math.min(window.devicePixelRatio || 1, 3)
// a 393 x 852 iPhone at 3x is 3.0 MP; desktops up to 4K
const budget = PHONE ? 3.3e6 : 8.3e6
const fit = Math.sqrt(budget / Math.max(1, innerWidth * innerHeight))

export const DPR_FORCED = forced > 0
export const DPR_MAX = DPR_FORCED ? forced : Math.max(1, Math.min(native, fit, PHONE ? 2.5 : 2))
export const DPR_START = DPR_FORCED ? forced : PHONE ? Math.min(DPR_MAX, 2) : DPR_MAX
export const DPR_MIN = DPR_FORCED ? forced : Math.min(DPR_START, 0.75)

/** loading, shader warm-up, the day / evening switch and camera presets cost one-off frames: the adaptive resolution
 *  ignores the frame rate until this time (performance.now ms) */
let holdUntil = 0
export function holdAdaptive(ms: number) {
  holdUntil = Math.max(holdUntil, performance.now() + ms)
}
export const adaptiveHeld = () => performance.now() < holdUntil
