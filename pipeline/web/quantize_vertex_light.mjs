// Per-vertex light attributes (_NIKK / _NIKE, RGBM in 0..1) float32 -> unsigned byte normalized.
// gltf-transform's quantize leaves custom float attributes alone; 8 bit is the precision RGBM was encoded for.
// usage: node quantize_vertex_light.mjs <in.glb> <out.glb>   (run before meshopt compression)
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const lib = path.join(process.env.APPDATA, 'npm', 'node_modules', '@gltf-transform', 'cli', 'node_modules', '@gltf-transform')
const { NodeIO } = await import(pathToFileURL(path.join(lib, 'core', 'dist', 'index.js')).href)
const { ALL_EXTENSIONS } = await import(pathToFileURL(path.join(lib, 'extensions', 'dist', 'index.js')).href)

const [, , src, dst] = process.argv
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS)
const doc = await io.read(src)
let n = 0
let before = 0
let after = 0
const done = new Set()
for (const mesh of doc.getRoot().listMeshes()) {
  for (const prim of mesh.listPrimitives()) {
    for (const name of ['_NIKK', '_NIKE']) {
      const acc = prim.getAttribute(name)
      if (!acc || done.has(acc) || acc.getComponentType() !== 5126) continue
      done.add(acc)
      const f = acc.getArray()
      const u = new Uint8Array(f.length)
      for (let i = 0; i < f.length; i++) u[i] = Math.max(0, Math.min(255, Math.round(f[i] * 255)))
      before += f.byteLength
      after += u.byteLength
      acc.setArray(u).setNormalized(true)
      n++
    }
  }
}
await io.write(dst, doc)
console.log(`quantized ${n} accessors: ${(before / 2 ** 20).toFixed(1)} MB -> ${(after / 2 ** 20).toFixed(1)} MB`)
