import * as THREE from 'three'

/**
 * Mirror of the scene in the floor plane (y = 0), rendered every frame before the main pass
 * (same math as three's Reflector: reflected camera + oblique near plane), plus a blurred copy
 * for the honed-stone look. The floor shader projects with `textureMatrix` (world -> mirror UV).
 */
export class PlanarReflection {
  readonly sharp: THREE.WebGLRenderTarget
  readonly blurred: THREE.WebGLRenderTarget
  private readonly tmp: THREE.WebGLRenderTarget
  readonly textureMatrix = new THREE.Matrix4()
  private readonly cam = new THREE.PerspectiveCamera()
  private readonly blurMat: THREE.ShaderMaterial
  private readonly quadScene = new THREE.Scene()
  private readonly quadCam = new THREE.Camera()
  private scale: number

  constructor(scale = 0.5) {
    this.scale = scale
    const opts = { type: THREE.HalfFloatType, colorSpace: THREE.NoColorSpace, depthBuffer: true }
    this.sharp = new THREE.WebGLRenderTarget(1, 1, { ...opts, samples: 4 })
    this.blurred = new THREE.WebGLRenderTarget(1, 1, { ...opts, depthBuffer: false })
    this.tmp = new THREE.WebGLRenderTarget(1, 1, { ...opts, depthBuffer: false })
    this.blurMat = new THREE.ShaderMaterial({
      uniforms: { src: { value: null }, dir: { value: new THREE.Vector2() } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',
      fragmentShader: /* glsl */ `
        uniform sampler2D src; uniform vec2 dir; varying vec2 vUv;
        void main() {
          vec4 c = texture2D(src, vUv) * 0.2270270270;
          c += (texture2D(src, vUv + dir * 1.3846153846) + texture2D(src, vUv - dir * 1.3846153846)) * 0.3162162162;
          c += (texture2D(src, vUv + dir * 3.2307692308) + texture2D(src, vUv - dir * 3.2307692308)) * 0.0702702703;
          gl_FragColor = c;
        }`,
      depthTest: false,
      depthWrite: false,
    })
    const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.blurMat)
    quad.frustumCulled = false
    this.quadScene.add(quad)
  }

  setSize(width: number, height: number) {
    const w = Math.max(2, Math.round(width * this.scale))
    const h = Math.max(2, Math.round(height * this.scale))
    if (this.sharp.width !== w || this.sharp.height !== h) {
      this.sharp.setSize(w, h)
      this.blurred.setSize(w, h)
      this.tmp.setSize(w, h)
    }
  }

  private readonly v = {
    camPos: new THREE.Vector3(),
    view: new THREE.Vector3(),
    look: new THREE.Vector3(),
    target: new THREE.Vector3(),
    rot: new THREE.Matrix4(),
    normal: new THREE.Vector3(0, 1, 0),
    origin: new THREE.Vector3(0, 0, 0),
    plane: new THREE.Plane(),
    clip: new THREE.Vector4(),
    q: new THREE.Vector4(),
  }

  update(gl: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.PerspectiveCamera, hide: THREE.Object3D[], blurPx = 2.2) {
    const { camPos, view, look, target, rot, normal, origin, plane, clip, q } = this.v
    camPos.setFromMatrixPosition(camera.matrixWorld)
    if (camPos.y <= 0.001) return // below the floor: nothing to mirror

    view.subVectors(origin, camPos).reflect(normal).negate().add(origin)
    rot.extractRotation(camera.matrixWorld)
    look.set(0, 0, -1).applyMatrix4(rot).add(camPos)
    target.subVectors(origin, look).reflect(normal).negate().add(origin)

    const cam = this.cam
    cam.position.copy(view)
    cam.up.set(0, 1, 0).applyMatrix4(rot).reflect(normal)
    cam.lookAt(target)
    cam.far = camera.far
    cam.updateMatrixWorld()
    cam.projectionMatrix.copy(camera.projectionMatrix)

    this.textureMatrix.set(0.5, 0, 0, 0.5, 0, 0.5, 0, 0.5, 0, 0, 0.5, 0.5, 0, 0, 0, 1)
    this.textureMatrix.multiply(cam.projectionMatrix).multiply(cam.matrixWorldInverse)

    // oblique near plane = floor plane (nothing below the floor gets mirrored)
    plane.setFromNormalAndCoplanarPoint(normal, origin).applyMatrix4(cam.matrixWorldInverse)
    clip.set(plane.normal.x, plane.normal.y, plane.normal.z, plane.constant)
    const pm = cam.projectionMatrix.elements
    q.x = (Math.sign(clip.x) + pm[8]) / pm[0]
    q.y = (Math.sign(clip.y) + pm[9]) / pm[5]
    q.z = -1
    q.w = (1 + pm[10]) / pm[14]
    clip.multiplyScalar(2 / clip.dot(q))
    pm[2] = clip.x
    pm[6] = clip.y
    pm[10] = clip.z + 1 - 0.003
    pm[14] = clip.w
    cam.projectionMatrixInverse.copy(cam.projectionMatrix).invert()

    const vis = hide.map((o) => o.visible)
    hide.forEach((o) => (o.visible = false))
    const prev = gl.getRenderTarget()
    const prevAlpha = gl.getClearAlpha()
    gl.setClearAlpha(0)
    gl.setRenderTarget(this.sharp)
    gl.clear()
    gl.render(scene, cam)
    hide.forEach((o, i) => (o.visible = vis[i]))

    // separable gaussian, twice (wider, smoother kernel)
    const w = this.sharp.width
    const h = this.sharp.height
    let src: THREE.Texture = this.sharp.texture
    for (let i = 0; i < 2; i++) {
      this.blurMat.uniforms.src.value = src
      this.blurMat.uniforms.dir.value.set(blurPx / w, 0)
      gl.setRenderTarget(this.tmp)
      gl.render(this.quadScene, this.quadCam)
      this.blurMat.uniforms.src.value = this.tmp.texture
      this.blurMat.uniforms.dir.value.set(0, blurPx / h)
      gl.setRenderTarget(this.blurred)
      gl.render(this.quadScene, this.quadCam)
      src = this.blurred.texture
    }
    gl.setRenderTarget(prev)
    gl.setClearAlpha(prevAlpha)
  }

  dispose() {
    this.sharp.dispose()
    this.blurred.dispose()
    this.tmp.dispose()
    this.blurMat.dispose()
  }
}
