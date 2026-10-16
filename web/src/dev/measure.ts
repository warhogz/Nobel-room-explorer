/**
 * Dev-only calibration helper (?dev): average sRGB of the same regions in a reference render and in the live frame.
 * The render is placed like the compare overlay does it: full height, centred. Regions are in render pixels.
 *   await __measure('/ref/10.jpg', { wall: [870, 650, 1050, 900] })  ->  { wall: { ref: [r,g,b], ours: [r,g,b] } }
 * The frame is copied in the animation frame after a render (the drawing buffer is not preserved).
 */
export type Regions = Record<string, [number, number, number, number]>

export const REGIONS: Record<string, Regions> = {
  '10': { wallR: [870, 650, 1050, 900], ceiling: [500, 60, 800, 200], floor: [100, 1350, 400, 1550], island: [200, 1000, 330, 1150], seat: [690, 1040, 800, 1080], niche: [80, 720, 330, 900], wallL: [0, 500, 60, 900] },
  '12': { ceiling: [300, 50, 800, 300], wallL: [20, 350, 150, 650], hallWall: [720, 640, 980, 760], hallRoof: [420, 600, 700, 700], island: [300, 1150, 650, 1350], floor: [300, 1420, 800, 1550], hallFloor: [900, 1200, 1100, 1300] },
}

function frame(canvas: HTMLCanvasElement): Promise<HTMLCanvasElement> {
  return new Promise((resolve) =>
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        const c = document.createElement('canvas')
        c.width = canvas.width
        c.height = canvas.height
        c.getContext('2d')!.drawImage(canvas, 0, 0)
        resolve(c)
      }),
    ),
  )
}

function avg(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number) {
  const d = ctx.getImageData(Math.round(x), Math.round(y), Math.max(1, Math.round(w)), Math.max(1, Math.round(h))).data
  let r = 0
  let g = 0
  let b = 0
  const n = d.length / 4
  for (let i = 0; i < d.length; i += 4) {
    r += d[i]
    g += d[i + 1]
    b += d[i + 2]
  }
  return [r / n, g / n, b / n].map(Math.round)
}

export async function measure(canvas: HTMLCanvasElement, refUrl: string, regions: Regions) {
  const img = new Image()
  img.src = refUrl
  await img.decode()
  const rc = document.createElement('canvas')
  rc.width = img.width
  rc.height = img.height
  const rx = rc.getContext('2d')!
  rx.drawImage(img, 0, 0)
  const shot = (await frame(canvas)).getContext('2d')!
  const W = canvas.clientWidth
  const H = canvas.clientHeight
  const scale = H / img.height
  const x0 = (W - img.width * scale) / 2
  const k = canvas.width / W
  const out: Record<string, { ref: number[]; ours: number[] }> = {}
  for (const [name, [u0, v0, u1, v1]] of Object.entries(regions)) {
    out[name] = {
      ref: avg(rx, u0, v0, u1 - u0, v1 - v0),
      ours: avg(shot, (x0 + u0 * scale) * k, v0 * scale * k, (u1 - u0) * scale * k, (v1 - v0) * scale * k),
    }
  }
  return out
}
