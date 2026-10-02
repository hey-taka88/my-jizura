/* ============================================================
   my-jizura (fork) — media layer: 加工 (colour treatments) and 文字の下の暗幕 (scrim)   (Phase 3)
   · M.treated(asset, src, cut, plan, slot) → a canvas with the treatment applied (pictures: made once and kept;
     clips: redrawn every frame into a kept canvas, at most 1280 px wide). Composite modes only (no ctx.filter).
   · M.drawScrim(ctx, plan, c, t, W, H, seen, P): a soft veil in the style's background colour behind the lyrics.
     Where the lyrics sit is measured once per lyric cut (a small render that logs the glyphs) and kept per plan;
     'auto' decides from a tiny luminance grid of the picture (made once per picture) whether the lyrics need it.
   ============================================================ */
(() => {
'use strict';
const M = (J.media = J.media || {});
const mk = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };
const fit = (cv, w, h) => { if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; } return cv; };

/* ---------------- 加工 ---------------- */
// the colours a treatment uses: the style's own (first scheme), so pictures sit in the look of the lyrics
function tones(plan) {
  const sc = (plan.style && plan.style.schemes && plan.style.schemes[0]) || { bg: '#101014', fg: '#ffffff', accent: '#ff4d6d' };
  const dark = J.lum(sc.bg) < J.lum(sc.fg) ? sc.bg : sc.fg, light = dark === sc.bg ? sc.fg : sc.bg;
  const acc = sc.accent || light;
  return { bg: sc.bg, dark: J.mix(dark, '#000000', 0.25), light: J.lum(acc) > 0.45 ? acc : J.mix(acc, light, 0.45), accent: acc };
}
const fill = (x, w, h, op, col, a = 1) => { x.globalCompositeOperation = op; x.globalAlpha = a; x.fillStyle = col; x.fillRect(0, 0, w, h); };
let blurA = null, blurB = null;
function paint(cv, src, w, h, kind, T, alpha) {
  const x = fit(cv, w, h).getContext('2d');
  x.setTransform(1, 0, 0, 1, 0, 0); x.globalAlpha = 1; x.filter = 'none'; x.imageSmoothingEnabled = true;
  x.globalCompositeOperation = 'copy';
  if (kind === 'blur') {
    // two steps down and one up: a soft blur without ctx.filter (cheap, and the same in every browser)
    const a = fit(blurA || (blurA = mk(2, 2)), Math.max(2, Math.round(w / 4)), Math.max(2, Math.round(h / 4)));
    const b = fit(blurB || (blurB = mk(2, 2)), Math.max(2, Math.round(w / 14)), Math.max(2, Math.round(h / 14)));
    const ax = a.getContext('2d'), bx = b.getContext('2d');
    ax.globalCompositeOperation = 'copy'; ax.imageSmoothingQuality = 'high'; ax.drawImage(src, 0, 0, a.width, a.height);
    bx.globalCompositeOperation = 'copy'; bx.imageSmoothingQuality = 'high'; bx.drawImage(a, 0, 0, b.width, b.height);
    x.imageSmoothingQuality = 'high'; x.drawImage(b, 0, 0, w, h);
  } else x.drawImage(src, 0, 0, w, h);
  if (kind === 'mono' || kind === 'sepia' || kind === 'duotone') fill(x, w, h, 'saturation', '#808080');   // keeps the brightness, drops the colour
  if (kind === 'sepia') fill(x, w, h, 'color', '#9a7350', 0.85);
  if (kind === 'duotone') { fill(x, w, h, 'multiply', T.light); fill(x, w, h, 'screen', T.dark); }
  if (kind === 'match') { fill(x, w, h, 'color', T.accent, 0.32); fill(x, w, h, 'soft-light', T.bg, 0.35); }
  if (alpha) { x.globalAlpha = 1; x.globalCompositeOperation = 'destination-in'; x.drawImage(src, 0, 0, w, h); }   // see-through stays see-through
  x.globalCompositeOperation = 'source-over'; x.globalAlpha = 1;
  return cv;
}
const kept = new WeakMap();   // picture copy → { key, cv }: its treated copy
M.treated = (asset, src, c, plan, slot = 0) => {
  const kind = c.treat;
  if (!kind || kind === 'none' || !src) return src;
  const T = tones(plan);
  if (asset.type !== 'video') {
    // one treated copy per picture copy: another treatment or style colour repaints it (no pile of full-size canvases);
    // only duotone / match use the style's colours
    const key = kind === 'duotone' || kind === 'match' ? kind + '|' + T.bg + T.dark + T.light + T.accent : kind;
    let e = kept.get(src);
    if (!e) kept.set(src, (e = { key: null, cv: mk(2, 2) }));
    if (e.key !== key) { paint(e.cv, src, src.width, src.height, kind, T, true); e.key = key; }
    return e.cv;
  }
  // a clip frame: into the clip's own canvas (one per slot: the seam of a loop draws two frames)
  const sw = src.videoWidth || src.width, sh = src.videoHeight || src.height;
  if (!sw || !sh) return src;
  const k = Math.min(1, 1280 / sw), cvs = asset.treatCv || (asset.treatCv = []);
  return paint(cvs[slot] || (cvs[slot] = mk(2, 2)), src, Math.round(sw * k), Math.round(sh * k), kind, T, false);
};

/* ---------------- 文字の下の暗幕 ---------------- */
let measuring = false;
M.measuring = () => measuring;
const boxes = new WeakMap();  // plan → Map(lyric cut index → box | null, 'n:<media>:<lyric>' → needs a veil)
const store = plan => { let m = boxes.get(plan); if (!m) boxes.set(plan, (m = new Map())); return m; };
let mR = null, mCv = null;
/* where the lyrics of one lyric cut sit (design units), from a small render of the lyrics alone (the front layer) that logs every glyph */
function lyricBox(plan, lc) {
  const S = store(plan);
  if (S.has(lc.index)) return S.get(lc.index);
  let box = null;
  if (!measuring) {
    measuring = true;
    try {
      const k = 0.2, log = [];
      const cv = fit(mCv || (mCv = mk(2, 2)), Math.max(2, Math.round(plan.W * k)), Math.max(2, Math.round(plan.H * k)));
      (mR || (mR = new J.Renderer())).frame(cv.getContext('2d'), plan, (lc.start + lc.end) / 2, { scale: k, noPost: true, noHud: true, noTrans: true, noGhost: true, fast: true, glyphLog: log, transparent: true, layer: 'front' });
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      const gl = log.filter(g => g.a > 0.3 && g.m).map(g => ({ s: (g.px || 0) * Math.hypot(g.m[0], g.m[1]) / k, cx: g.m[4] / k, cy: g.m[5] / k })).filter(g => g.s > 0);
      const big = gl.reduce((m, g) => Math.max(m, g.s), 0);
      for (const g of gl) {
        if (g.s < big * 0.35) continue;          // the lyric itself, not the small labels / captions around it
        x0 = Math.min(x0, g.cx - g.s * 0.6); x1 = Math.max(x1, g.cx + g.s * 0.6); y0 = Math.min(y0, g.cy - g.s * 0.6); y1 = Math.max(y1, g.cy + g.s * 0.6);
      }
      if (x1 > x0 && y1 > y0) box = { x: Math.max(0, x0), y: Math.max(0, y0), w: Math.min(plan.W, x1) - Math.max(0, x0), h: Math.min(plan.H, y1) - Math.max(0, y0) };
    } catch (e) { console.warn('media: scrim measure', e); }
    finally { measuring = false; }
  }
  S.set(lc.index, box);
  return box;
}
// relative luminance (WCAG) of a picture as a small grid, made once per picture
const linear = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
function lumGrid(a) {
  if (a.lumGrid) return a.lumGrid;
  const src = a.type === 'video' ? a.thumb : a.source;
  if (!src) return null;
  const sw = a.type === 'video' ? src.width : a.sw, sh = a.type === 'video' ? src.height : a.sh;
  const gw = 32, gh = J.clamp(Math.round(32 * sh / sw), 4, 64);
  try {
    const cv = mk(gw, gh), x = cv.getContext('2d', { willReadFrequently: true });
    x.drawImage(src, 0, 0, gw, gh);
    const d = x.getImageData(0, 0, gw, gh).data, g = new Float32Array(gw * gh);
    for (let i = 0; i < g.length; i++) g[i] = 0.2126 * linear(d[i * 4]) + 0.7152 * linear(d[i * 4 + 1]) + 0.0722 * linear(d[i * 4 + 2]);
    return (a.lumGrid = { gw, gh, g, aspect: sw / sh });
  } catch (e) { return null; }
}
/* does the picture under the lyrics leave them hard to read? (contrast of the text colour with the darkened picture) */
function needsVeil(plan, c, box, sc, dim) {
  const a = J.mediaAssets.get(c.assetId), G = a && lumGrid(a);
  if (!G) return false;
  const W = plan.W, H = plan.H, ar = G.aspect;
  const base = c.fit === 'contain' ? Math.min(W / ar, H) : Math.max(W / ar, H);
  const dw = ar * base, dh = base, ox = (W - dw) / 2, oy = (H - dh) / 2;
  let sum = 0, n = 0;
  for (let j = 0; j < G.gh; j++) for (let i = 0; i < G.gw; i++) {
    const cx = ox + (i + 0.5) / G.gw * dw, cy = oy + (j + 0.5) / G.gh * dh;
    if (cx < box.x || cx > box.x + box.w || cy < box.y || cy > box.y + box.h) continue;
    sum += G.g[j * G.gw + i]; n++;
  }
  if (!n) return false;
  const pic = (sum / n) * (1 - dim), txt = (() => { const c2 = J.hex(sc.fg).map(linear); return 0.2126 * c2[0] + 0.7152 * c2[1] + 0.0722 * c2[2]; })();
  return (Math.max(pic, txt) + 0.05) / (Math.min(pic, txt) + 0.05) < 4.5;
}
// a soft-edged plate (made once per colour), stretched over the lyrics
const plates = new Map();
function plate(col) {
  if (plates.has(col)) return plates.get(col);
  const w = 96, h = 64, cv = mk(w, h), x = cv.getContext('2d'), im = x.createImageData(w, h), [r, g, b] = J.hex(col);
  const edge = 0.32, sm = e => e * e * (3 - 2 * e);
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
    const u = Math.min((i + 0.5) / w, 1 - (i + 0.5) / w) / edge, v = Math.min((j + 0.5) / h, 1 - (j + 0.5) / h) / edge;
    const k = (j * w + i) * 4;
    im.data[k] = r; im.data[k + 1] = g; im.data[k + 2] = b; im.data[k + 3] = Math.round(255 * sm(J.clamp(u)) * sm(J.clamp(v)));
  }
  x.putImageData(im, 0, 0);
  plates.set(col, cv);
  return cv;
}
M.drawScrim = (ctx, plan, c, t, W, H, seen, P) => {
  const S = plan.media && plan.media.scrim;
  if (!S || S.mode === 'off' || !(S.amount > 0) || !(seen > 0) || measuring) return;
  const lc = J.cutAt(plan, t);
  if (!lc || !(lc.end > lc.start)) return;
  // the plate of one lyric cut, or null when it has none (no lyric, or 'auto' and the lyric reads well)
  const want = L => {
    const box = lyricBox(plan, L);
    if (!box) return null;
    const sc = plan.style.schemes[L.scheme % plan.style.schemes.length] || plan.style.schemes[0];
    if (S.mode === 'auto') {
      const st = store(plan), key = 'n:' + c.index + ':' + L.index;
      if (!st.has(key)) st.set(key, needsVeil(plan, c, box, sc, P.dim || 0));
      if (!st.get(key)) return null;
    }
    return { box, col: sc.bg };
  };
  const touch = (a, b) => a && b && Math.abs(a.end - b.start) < 0.06;
  const prev = lc.index > 0 ? plan.cuts[lc.index - 1] : null, next = plan.cuts[lc.index + 1];
  const F = 0.3, pad = Math.min(W, H) * 0.09, cur = want(lc);
  // in with the line and out with it; from one lyric cut to the next, the plate moves over instead of blinking
  const kin = J.clamp((t - lc.start) / F), kout = touch(lc, next) && want(next) ? 1 : J.clamp((lc.end - t) / F);
  const draw = (pl, k) => {
    if (!pl || !(k > 0)) return;
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = J.clamp(S.amount * k * Math.min(1, seen) * 1.5);   // the plate's soft edge takes some away
    ctx.drawImage(plate(pl.col), pl.box.x - pad, pl.box.y - pad * 0.8, pl.box.w + pad * 2, pl.box.h + pad * 1.6);
  };
  if (kin < 1 && touch(prev, lc)) draw(want(prev), 1 - kin);
  draw(cur, Math.min(kin, kout));
};
})();
