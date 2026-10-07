/**
 * Values animated every frame (smoothed towards the store targets) and shared between the scene and the
 * post effect without React re-renders.
 */
export const live = {
  /** 0 = dark room, 1 = bright gallery space (follows the kitchen light group) */
  light: 1,
}

/** frame-rate independent exponential approach */
export function approach(current: number, target: number, dt: number, speed = 4) {
  return current + (target - current) * (1 - Math.exp(-dt * speed))
}

/** world-space anchors computed from the loaded scene (camera focus targets) */
export const anchors: { faucet?: import('three').Vector3 } = {}

/** displayed per-lamp brightness (0..1) and the floor-uplight group level, for the fixture meshes */
export const lampsLive: { values: number[]; group: number } = { values: [], group: 1 }
