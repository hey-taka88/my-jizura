/* ============================================================
   my-jizura (fork) — media layer: クロマキー (Phase 3b-2)
   M.keyed(asset, src, cut, slot) → the picture with its key colour taken out (see-through), as a canvas.
   · cut.chroma = { color: '#rrggbb' | 'auto', tol, soft, spill } (08m_media_model.js). 'auto' = the colour round the picture's
     edge (a green / blue screen fills it), found once per picture from a tiny copy — the same answer every time.
   · The distance is measured in YCbCr (colour only, so a shadow on the screen keys out like the lit part): closer than tol =
     gone, tol … tol + soft = partly see-through, beyond = kept. spill pulls the key colour out of what stays (green fringes).
   · WebGL2 (one shared canvas, the frame uploaded as a texture); without it, the same maths on a smaller copy (≤ 960 px).
   · Pictures are keyed once and kept (one canvas per picture copy); clip frames into one canvas per clip and slot.
   ============================================================ */
(() => {
'use strict';
const M = (J.media = J.media || {});
const mk = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };
const fit = (cv, w, h) => { if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; } return cv; };
const hex = c => [parseInt(c.slice(1, 3), 16) / 255, parseInt(c.slice(3, 5), 16) / 255, parseInt(c.slice(5, 7), 16) / 255];
const cbcr = (r, g, b) => [-0.168736 * r - 0.331264 * g + 0.5 * b, 0.5 * r - 0.418688 * g - 0.081312 * b];
const smooth = (a, b, x) => { const t = J.clamp((x - a) / Math.max(1e-4, b - a)); return t * t * (3 - 2 * t); };
const LIMIT = { image: 2048, video: 1280 }, CPU_LIMIT = 960;

/* ---------- the key colour: 'auto' = the median colour of the picture's top edge and its sides ---------- */
function autoKey(asset) {
  if (asset.keyAuto) return asset.keyAuto;
  const src = asset.type === 'video' ? asset.thumb : asset.source;
  let col = '#00ff00';
  try {
    if (src) {
      const c = mk(32, 18), x = c.getContext('2d', { willReadFrequently: true });
      x.drawImage(src, 0, 0, 32, 18);
      const d = x.getImageData(0, 0, 32, 18).data, R = [], G = [], B = [];
      const take = (px, py) => { const i = (py * 32 + px) * 4; R.push(d[i]); G.push(d[i + 1]); B.push(d[i + 2]); };
      for (let px = 0; px < 32; px++) take(px, 0);                                       // the top edge
      for (let py = 1; py < 18; py++) { take(0, py); take(31, py); }                      // both sides (the subject often stands on the bottom edge)
      const med = a => { a.sort((p, q) => p - q); return a[a.length >> 1]; };
      col = '#' + [med(R), med(G), med(B)].map(v => v.toString(16).padStart(2, '0')).join('');
    }
  } catch (e) { console.warn('media: chroma auto colour', e); }
  asset.keyAuto = col;
  return col;
}
M.keyColor = (asset, K) => (K && K.color && K.color !== 'auto' ? K.color : autoKey(asset));

/* ---------- WebGL2 ---------- */
let G = null, glFailed = false;
const VS = `#version 300 es
in vec2 p; out vec2 v;
void main() { v = p * 0.5 + 0.5; gl_Position = vec4(p, 0.0, 1.0); }`;
const FS = `#version 300 es
precision highp float;
in vec2 v; out vec4 o;
uniform sampler2D tex; uniform vec2 key; uniform float tol, soft, spill;
vec2 cbcr(vec3 c) { return vec2(-0.168736 * c.r - 0.331264 * c.g + 0.5 * c.b, 0.5 * c.r - 0.418688 * c.g - 0.081312 * c.b); }
void main() {
  vec4 s = texture(tex, vec2(v.x, 1.0 - v.y));
  vec3 c = s.rgb;
  float dist = length(cbcr(c) - key);
  float a = smoothstep(tol, tol + max(soft, 1e-4), dist);
  float y = dot(c, vec3(0.299, 0.587, 0.114));
  c = mix(c, vec3(y), (1.0 - smoothstep(tol, tol + soft + 0.25, dist)) * spill);
  float A = a * s.a;
  o = vec4(c * A, A);
}`;
function gl() {
  if (G || glFailed || M.chromaCPU) return M.chromaCPU ? null : G;
  try {
    const cv = mk(2, 2);
    const g = cv.getContext('webgl2', { premultipliedAlpha: true, alpha: true, antialias: false, preserveDrawingBuffer: true });
    if (!g) throw new Error('no webgl2');
    const sh = (type, src) => { const s = g.createShader(type); g.shaderSource(s, src); g.compileShader(s); if (!g.getShaderParameter(s, g.COMPILE_STATUS)) throw new Error(g.getShaderInfoLog(s)); return s; };
    const pr = g.createProgram();
    g.attachShader(pr, sh(g.VERTEX_SHADER, VS)); g.attachShader(pr, sh(g.FRAGMENT_SHADER, FS)); g.linkProgram(pr);
    if (!g.getProgramParameter(pr, g.LINK_STATUS)) throw new Error(g.getProgramInfoLog(pr));
    g.useProgram(pr);
    const buf = g.createBuffer(); g.bindBuffer(g.ARRAY_BUFFER, buf);
    g.bufferData(g.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), g.STATIC_DRAW);
    const loc = g.getAttribLocation(pr, 'p'); g.enableVertexAttribArray(loc); g.vertexAttribPointer(loc, 2, g.FLOAT, false, 0, 0);
    const tex = g.createTexture(); g.bindTexture(g.TEXTURE_2D, tex);
    for (const [k, v] of [[g.TEXTURE_MIN_FILTER, g.LINEAR], [g.TEXTURE_MAG_FILTER, g.LINEAR], [g.TEXTURE_WRAP_S, g.CLAMP_TO_EDGE], [g.TEXTURE_WRAP_T, g.CLAMP_TO_EDGE]]) g.texParameteri(g.TEXTURE_2D, k, v);
    g.pixelStorei(g.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    cv.addEventListener('webglcontextlost', e => { e.preventDefault(); G = null; glFailed = true; console.warn('media: chroma lost WebGL, using the CPU'); });
    G = { cv, g, u: { key: g.getUniformLocation(pr, 'key'), tol: g.getUniformLocation(pr, 'tol'), soft: g.getUniformLocation(pr, 'soft'), spill: g.getUniformLocation(pr, 'spill') } };
  } catch (e) { glFailed = true; G = null; console.warn('media: chroma without WebGL2', e.message || e); }
  return G;
}
M.chromaInfo = () => ({ webgl: !!gl() });

/* src → out (w × h), keyed */
function keyInto(out, src, w, h, col, K) {
  const [r, g0, b] = hex(col), key = cbcr(r, g0, b);
  const W = gl();
  if (W) {
    try {
      const g = W.g;
      fit(W.cv, w, h); g.viewport(0, 0, w, h);
      g.texImage2D(g.TEXTURE_2D, 0, g.RGBA, g.RGBA, g.UNSIGNED_BYTE, src);
      g.uniform2f(W.u.key, key[0], key[1]); g.uniform1f(W.u.tol, K.tol); g.uniform1f(W.u.soft, K.soft); g.uniform1f(W.u.spill, K.spill);
      g.clearColor(0, 0, 0, 0); g.clear(g.COLOR_BUFFER_BIT); g.drawArrays(g.TRIANGLE_STRIP, 0, 4);
      const x = fit(out, w, h).getContext('2d');
      x.setTransform(1, 0, 0, 1, 0, 0); x.globalAlpha = 1; x.globalCompositeOperation = 'copy'; x.drawImage(W.cv, 0, 0);
      x.globalCompositeOperation = 'source-over';
      return out;
    } catch (e) { console.warn('media: chroma WebGL failed, using the CPU', e); G = null; glFailed = true; }
  }
  // the same maths on a smaller copy (never a full-size getImageData)
  const k = Math.min(1, CPU_LIMIT / w), cw = Math.max(1, Math.round(w * k)), ch = Math.max(1, Math.round(h * k));
  const x = fit(out, cw, ch).getContext('2d', { willReadFrequently: true });
  x.setTransform(1, 0, 0, 1, 0, 0); x.globalAlpha = 1; x.globalCompositeOperation = 'copy'; x.drawImage(src, 0, 0, cw, ch);
  x.globalCompositeOperation = 'source-over';
  const im = x.getImageData(0, 0, cw, ch), d = im.data;
  for (let i = 0; i < d.length; i += 4) {
    let R = d[i] / 255, Gc = d[i + 1] / 255, B = d[i + 2] / 255;
    const q = cbcr(R, Gc, B), dist = Math.hypot(q[0] - key[0], q[1] - key[1]);
    const a = smooth(K.tol, K.tol + K.soft, dist), y = 0.299 * R + 0.587 * Gc + 0.114 * B;
    const sp = (1 - smooth(K.tol, K.tol + K.soft + 0.25, dist)) * K.spill;
    R += (y - R) * sp; Gc += (y - Gc) * sp; B += (y - B) * sp;
    d[i] = R * 255; d[i + 1] = Gc * 255; d[i + 2] = B * 255; d[i + 3] *= a;
  }
  x.putImageData(im, 0, 0);
  return out;
}

const kept = new WeakMap();   // picture copy → { key, cv }
M.keyed = (asset, src, c, slot = 0) => {
  const K = c && c.chroma;
  if (!K || !src) return src;
  const sw = src.videoWidth || src.width, sh = src.videoHeight || src.height;
  if (!sw || !sh) return src;
  const col = M.keyColor(asset, K);
  const lim = LIMIT[asset.type === 'video' ? 'video' : 'image'], k = Math.min(1, lim / sw);
  const w = Math.max(1, Math.round(sw * k)), h = Math.max(1, Math.round(sh * k));
  try {
    if (asset.type !== 'video') {
      const key = [col, K.tol, K.soft, K.spill, w, h].join('|');
      let e = kept.get(src);
      if (!e) kept.set(src, (e = { key: null, cv: mk(2, 2) }));
      if (e.key !== key) { keyInto(e.cv, src, w, h, col, K); e.key = key; }
      return e.cv;
    }
    const cvs = asset.keyCv || (asset.keyCv = []);
    return keyInto(cvs[slot] || (cvs[slot] = mk(2, 2)), src, w, h, col, K);
  } catch (e) { console.warn('media: chroma', asset.name, e); return src; }
};
})();
