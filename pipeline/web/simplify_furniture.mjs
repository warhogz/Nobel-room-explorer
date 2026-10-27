// Furniture lit per vertex (VX_* meshes: light in _NIKK/_NIKE) has ~4.4 M triangles, far more than the eye needs at
// walking distance. Simplify every primitive with meshoptimizer, keeping normals, UVs and the baked light in the error
// metric, then drop the vertices nobody references any more (before the 8 bit quantisation / meshopt compression).
// usage: node simplify_furniture.mjs <in.glb> <out.glb> [ratio=0.5] [error=0.004] [names: comma list of mesh name prefixes, or a regex starting with ^ (default ^VX_)]
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const cli = path.join(process.env.APPDATA, 'npm', 'node_modules', '@gltf-transform', 'cli', 'node_modules')
const lib = path.join(cli, '@gltf-transform')
const { NodeIO } = await import(pathToFileURL(path.join(lib, 'core', 'dist', 'index.js')).href)
const { ALL_EXTENSIONS } = await import(pathToFileURL(path.join(lib, 'extensions', 'dist', 'index.js')).href)
const { MeshoptSimplifier } = await import(pathToFileURL(path.join(cli, 'meshoptimizer', 'meshopt_simplifier.js')).href)

const [, , src, dst, ratioArg = '0.5', errArg = '0.004', nameArg = '^VX_'] = process.argv
const ratio = Number(ratioArg)
const error = Number(errArg)
const pick = new RegExp(nameArg.startsWith('^') ? nameArg : '^(' + nameArg.split(',').join('|') + ')')  // 'Static_,Plants' or a regex
await MeshoptSimplifier.ready
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS)
const doc = await io.read(src)

const floats = (acc) => {
  const n = acc.getElementSize()
  const out = new Float32Array(acc.getCount() * n)
  const v = []
  for (let i = 0; i < acc.getCount(); i++) {
    acc.getElement(i, v)
    for (let k = 0; k < n; k++) out[i * n + k] = v[k]
  }
  return out
}

let before = 0
let after = 0
let prims = 0
for (const mesh of doc.getRoot().listMeshes()) {
  if (!pick.test(mesh.getName())) continue
  for (const prim of mesh.listPrimitives()) {
    const posAcc = prim.getAttribute('POSITION')
    const idxAcc = prim.getIndices()
    if (!posAcc || !idxAcc || prim.getMode() !== 4) continue
    const indices = Uint32Array.from(idxAcc.getArray())
    before += indices.length / 3
    if (indices.length < 3 * 600) {
      after += indices.length / 3
      continue
    }
    const pos = floats(posAcc)
    // attributes in the metric: normal (3), uv (2), light (4 + 4 when present)
    const parts = [['NORMAL', 0.6], ['TEXCOORD_0', 1.0], ['_NIKK', 1.0], ['_NIKE', 1.0]]
      .map(([n, w]) => [prim.getAttribute(n), w]).filter(([a]) => a)
    const stride = parts.reduce((s, [a]) => s + a.getElementSize(), 0)
    const attrs = new Float32Array(posAcc.getCount() * stride)
    const weights = []
    let off = 0
    for (const [a, w] of parts) {
      const f = floats(a)
      const n = a.getElementSize()
      for (let i = 0; i < a.getCount(); i++) for (let k = 0; k < n; k++) attrs[i * stride + off + k] = f[i * n + k]
      for (let k = 0; k < n; k++) weights.push(w)
      off += n
    }
    const target = Math.max(3 * 300, Math.floor((indices.length * ratio) / 3) * 3)
    const [out] = MeshoptSimplifier.simplifyWithAttributes(indices, pos, 3, attrs, stride, weights, null, target, error, (process.env.NIK_SIMP_FLAGS ?? 'LockBorder').split(',').filter(Boolean))
    after += out.length / 3
    // compact: keep only referenced vertices
    const remap = new Int32Array(posAcc.getCount()).fill(-1)
    const keep = []
    const newIdx = new Uint32Array(out.length)
    for (let i = 0; i < out.length; i++) {
      const o = out[i]
      if (remap[o] < 0) { remap[o] = keep.length; keep.push(o) }
      newIdx[i] = remap[o]
    }
    for (const sem of prim.listSemantics()) {
      const a = prim.getAttribute(sem)
      const n = a.getElementSize()
      const arr = a.getArray()
      const na = new arr.constructor(keep.length * n)
      for (let i = 0; i < keep.length; i++) for (let k = 0; k < n; k++) na[i * n + k] = arr[keep[i] * n + k]
      prim.setAttribute(sem, doc.createAccessor().setType(a.getType()).setArray(na).setNormalized(a.getNormalized()).setBuffer(a.getBuffer()))
    }
    prim.setIndices(doc.createAccessor().setType('SCALAR').setArray(keep.length > 65535 ? newIdx : Uint16Array.from(newIdx)).setBuffer(idxAcc.getBuffer()))
    prims++
  }
}
for (const acc of doc.getRoot().listAccessors()) if (acc.listParents().every((p) => p.propertyType === 'Root')) acc.dispose()
await io.write(dst, doc)
console.log(`simplified ${prims} primitives: ${Math.round(before)} -> ${Math.round(after)} triangles (${((after / before) * 100).toFixed(0)}%)`)
