/**
 * Measurements taken on the client renders (pixels of the original 2000x1414 / 1414x2000 images).
 * Silhouette extremes: Island = all onyx parts; table top = Table vertices above 0.9 m.
 * Points: table pedestal bottom centre, top of the tall gooseneck faucet.
 */
import type { SolveSpec } from './solveCamera'

type V3 = [number, number, number]
const tableTop = (p: V3) => p[1] > 0.9

export function cameraSpecs(pedestal: V3, faucetTop: V3): Record<string, SolveSpec> {
  return {
    '030': {
      resolution: [2000, 1414],
      silhouettes: [
        { mesh: 'Island', umin: 502, umax: 1070, vmin: 1037, vmax: 1370 },
        { mesh: 'Table', filter: tableTop, umin: 945, umax: 1410, vmin: 1028, vmax: 1055 },
      ],
      points: [
        { at: pedestal, uv: [1175, 1315] },
        { at: faucetTop, uv: [696, 942] },
      ],
      init: { x: 0.25, y: 1.3, z: 5.8, yaw: 0.12, lens: 27, shift: 0.12 },
    },
    '08': {
      resolution: [1414, 2000],
      silhouettes: [
        { mesh: 'Island', umin: 225, umax: 1170, vmin: 1158 },
        { mesh: 'Table', filter: tableTop, umin: 385, umax: 1022, vmin: 1162, vmax: 1200 },
      ],
      points: [
        { at: pedestal, uv: [705, 1590] },
        { at: faucetTop, uv: [707, 1057] },
      ],
      init: { x: 3.7, y: 1.4, z: 0, yaw: -Math.PI / 2, lens: 24, shift: 0.1 },
    },
    '10': {
      resolution: [1414, 2000],
      silhouettes: [
        { mesh: 'Island', umin: 108, vmin: 1172, vmax: 1548 },
        { mesh: 'Table', filter: tableTop, umin: 543, umax: 1160, vmin: 1172, vmax: 1222 },
      ],
      points: [
        { at: pedestal, uv: [840, 1570] },
        { at: faucetTop, uv: [504, 1085] },
      ],
      init: { x: 2.05, y: 1.38, z: 2.85, yaw: -0.62, lens: 24, shift: 0.1 },
    },
    '12': {
      resolution: [1414, 2000],
      silhouettes: [
        { mesh: 'Island', umin: 148, umax: 1210, vmin: 1352, vmax: 1750 },
        { mesh: 'Table', filter: tableTop, vmin: 1328 },
      ],
      points: [{ at: faucetTop, uv: [688, 1228] }],
      init: { x: -2.55, y: 1.3, z: 0, yaw: Math.PI / 2, lens: 22, shift: 0.1 },
    },
  }
}
