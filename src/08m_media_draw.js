/* ============================================================
   my-jizura (fork) — media layer: drawing
   J.media.drawTrack(ctx, plan, t, track, o) draws the pictures of one track in design space (ctx already scaled by o.scale).
   Called from J.Renderer.frame(): 'back' right after the background colour, 'front' after the HUD.
   Pictures that are not loaded (yet) are skipped; nothing here throws into the renderer.
   Phase 3: 動き (still / kenburns / pan / push / drift / beatPulse), 登場・退場 (fade / slide / zoom / wipe),
   つなぎ (cross-fade, or a lyric transition J.TRANS between two pictures), 加工 (08m_media_look.js), 暗幕.
   Phase 3b: a cut with a rect is placed by hand (centre, width, rotation) instead of filling the frame — a logo, a character over
   the lyrics on the front track; its motion moves it around that place. A cut with chroma is keyed first (08m_media_chroma.js).
   ============================================================ */
(() => {
'use strict';
const M = (J.media = J.media || {});
const BLEND = { normal: 'source-over', multiply: 'multiply', screen: 'screen', overlay: 'overlay' };
const ease = x => 0.5 - 0.5 * Math.cos(Math.PI * J.clamp(x));
const NEAR = 0.06;
const mk = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };
const fit = (cv, w, h) => { if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; } return cv; };
// how far a motion zooms in at most (the size of the kept copy follows it, not the zoom of one frame)
const ZMAX = { pan: 1.14, push: 1.2, drift: 1.08, beatPulse: 1.07 };

function lastBeat(B, t) {
  let lo = 0, hi = B.length - 1, ans = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (B[m] <= t) { ans = m; lo = m + 1; } else hi = m - 1; }
  return ans < 0 ? null : B[ans];
}

/* where a cut is drawn at time t (design units): its size, top-left corner, turn and 登場・退場 (fx = { in, out }, 0..1) — also what
   the eyedropper of the placement editor maps a click through (11z_media_place.js). a: what the opacity is multiplied by */
M.cutBox = (plan, c, t, W, H, fx, sw, sh) => {
  const R = c.rect;
  const base = R ? W * R.w / sw : c.fit === 'contain' ? Math.min(W / sw, H / sh) : Math.max(W / sw, H / sh);
  const lt = t - c.start, p = J.clamp(lt / Math.max(0.1, c.dur)), hp = c.hp || { sign: 1, ph: 0, per: 7 };
  let z = 1, px = 0, py = 0, pan = 0, a = 1;
  switch (c.hold) {
    case 'kenburns': if (c.kb) { const e = ease(p); z = J.lerp(c.kb.s0, c.kb.s1, e); px = J.lerp(c.kb.x0, c.kb.x1, e) * W; py = J.lerp(c.kb.y0, c.kb.y1, e) * H; } break;
    case 'pan': z = ZMAX.pan; pan = (0.5 - 0.5 * Math.cos(Math.PI * (0.15 + 0.7 * p))) * 2 - 1; break;    // across, at an even pace
    case 'push': z = 1 + (ZMAX.push - 1) * ease(p); break;
    case 'drift': { z = ZMAX.drift; const ph = hp.ph + Math.PI * 2 * lt / hp.per; px = Math.sin(ph) * W * 0.022; py = Math.cos(ph * 0.8) * H * 0.018; break; }
    case 'beatPulse': { const b = plan.beats && plan.beats.length ? lastBeat(plan.beats, t) : null; z = 1.025 + (b != null && t - b < 0.6 ? 0.045 * Math.exp(-(t - b) * 7) : 0); break; }
  }
  // 登場・退場 that move the picture (a fade only changes its opacity)
  let clip = null;
  const move = (kind, k, out) => {             // k: 0 = hidden … 1 = in place
    const d = c.dir || 'L', sx = d === 'L' ? -1 : d === 'R' ? 1 : 0, sy = d === 'U' ? -1 : d === 'D' ? 1 : 0;
    if (kind === 'fade') a *= k;
    else if (kind === 'slide') { const off = (1 - k) * 0.22 * (out ? -1 : 1); px += sx * off * W; py += sy * off * H; a *= Math.min(1, k * 1.6); }
    else if (kind === 'zoom') { z *= out ? 1 + 0.12 * (1 - k) : 1 + 0.18 * (1 - k); a *= k; }
    else if (kind === 'wipe') clip = { d: out ? ({ L: 'R', R: 'L', U: 'D', D: 'U' })[d] : d, k };
  };
  if (fx && fx.in != null) move(c.enter, fx.in, false);
  if (fx && fx.out != null) move(c.exit, fx.out, true);
  const dw = sw * base * z, dh = sh * base * z;
  if (pan) { const mx = Math.max(0, (dw - W) / 2), my = Math.max(0, (dh - H) / 2); if (mx >= my) px = pan * mx * hp.sign; else py = pan * my * hp.sign; }
  if (!R && c.fit !== 'contain' && !(fx && (fx.in != null || fx.out != null) && (c.enter === 'slide' || c.exit === 'slide'))) {
    const mx = Math.max(0, (dw - W) / 2), my = Math.max(0, (dh - H) / 2);   // a filled frame never shows its edge while drifting
    px = J.clamp(px, -mx, mx); py = J.clamp(py, -my, my);
  }
  let x0 = W / 2 - dw / 2 + px, y0 = H / 2 - dh / 2 + py;
  if (R) { x0 += R.x * W; y0 += R.y * H; }
  return { x0, y0, dw, dh, turn: R && R.rot ? R.rot * Math.PI / 180 : 0, a, clip, base };
};
/* 登場・退場 of a front layer at t (each comes and goes by itself) */
M.layerFx = (c, t) => {
  const lt = t - c.start, fx = {};
  if (c.enter !== 'cut' && c.inDur > 0 && lt < c.inDur) fx.in = ease(lt / c.inDur);
  if (c.exit !== 'cut' && c.outDur > 0 && c.end - t < c.outDur) fx.out = ease((c.end - t) / c.outDur);
  return fx;
};

/* one cut at time t with opacity a. fx = { in, out } (0..1, 1 = fully shown) for 登場 / 退場, null = none */
function drawCut(ctx, plan, c, t, W, H, a, scale, fx) {
  const asset = J.mediaAssets.get(c.assetId);
  if (!asset || a <= 0.001) return false;
  let vt = null, frame = null;
  if (asset.type === 'video') {                // a clip: the frame for this song time (exact when exporting)
    vt = M.videoTimes(plan, c, t);
    frame = vt && M.videoFrame(asset, vt.main);
    if (!frame) return false;
  } else if (!asset.source) return false;
  const sw = asset.w, sh = asset.h;
  const box = M.cutBox(plan, c, t, W, H, fx, sw, sh), { dw, dh, turn, clip, base } = box;
  a *= box.a;
  if (a <= 0.001) return false;
  // the size bucket depends on the cut's largest size, not on this frame's zoom (no new copy while zooming)
  const zMax = c.hold === 'kenburns' && c.kb ? Math.max(c.kb.s0, c.kb.s1) : ZMAX[c.hold] || 1;
  let src = frame || M.sourceFor(asset, sw * base * zMax * scale, sh * base * zMax * scale);
  if (!src) return false;
  if (c.chroma && M.keyed) src = M.keyed(asset, src, c, 0);         // クロマキー first, on the picture's own colours
  if (c.treat && c.treat !== 'none' && M.treated) src = M.treated(asset, src, c, plan, 0);
  // the copy is already close to the drawn size (made once with high quality), so plain bilinear is enough per frame;
  // only a large step down (a picture drawn far smaller than its copy) needs the slower filter
  const step = frame ? 1 : Math.max(src.width / (dw * scale), src.height / (dh * scale));
  ctx.imageSmoothingQuality = step > 1.6 ? 'high' : 'low';
  let { x0, y0 } = box;
  if (clip) {
    const k = ease(clip.k), d = clip.d;
    ctx.save(); ctx.beginPath();
    if (d === 'L') ctx.rect(0, 0, W * k, H); else if (d === 'R') ctx.rect(W * (1 - k), 0, W * k, H);
    else if (d === 'U') ctx.rect(0, 0, W, H * k); else ctx.rect(0, H * (1 - k), W, H * k);
    ctx.clip();
  }
  if (turn) {                                  // turned around its own centre
    ctx.save(); ctx.translate(x0 + dw / 2, y0 + dh / 2); ctx.rotate(turn);
    x0 = -dw / 2; y0 = -dh / 2;
  }
  ctx.globalAlpha = a;
  ctx.drawImage(src, x0, y0, dw, dh);
  // loop seam (exports): the start of the clip fades in over its end
  if (vt && vt.alt != null && vt.k > 0) {
    let s2 = M.videoCap(asset, vt.alt);
    if (s2 && c.chroma && M.keyed) s2 = M.keyed(asset, s2, c, 1);
    if (s2 && c.treat && c.treat !== 'none' && M.treated) s2 = M.treated(asset, s2, c, plan, 1);
    if (s2) { ctx.globalAlpha = a * vt.k; ctx.drawImage(s2, x0, y0, dw, dh); }
  }
  if (turn) ctx.restore();
  if (clip) ctx.restore();
  return true;
}

/* つなぎ with a lyric transition: the picture before and this one, each over the frame as it is, composited by J.TRANS */
let TA = null, TB = null, TC = null;
function transJoin(ctx, plan, P, prev, c, t, W, H, scale, o) {
  const TD = J.TRANS[c.join], cw = ctx.canvas.width, ch = ctx.canvas.height;
  const A = fit(TA || (TA = mk(2, 2)), cw, ch), B = fit(TB || (TB = mk(2, 2)), cw, ch);
  let any = false;
  for (const [cv, cut] of [[A, prev], [B, c]]) {
    const x = cv.getContext('2d');
    x.setTransform(1, 0, 0, 1, 0, 0); x.globalAlpha = 1; x.filter = 'none'; x.globalCompositeOperation = 'copy'; x.drawImage(ctx.canvas, 0, 0);
    x.setTransform(scale, 0, 0, scale, 0, 0); x.imageSmoothingEnabled = true; x.globalCompositeOperation = BLEND[P.blend] || 'source-over';
    if (drawCut(x, plan, cut, t, W, H, P.opacity * cut.opacity, scale, null)) any = true;
    x.globalCompositeOperation = 'source-over'; x.globalAlpha = 1;
  }
  if (!any) return false;
  const sc = (plan.style && plan.style.schemes && plan.style.schemes[0]) || {};
  ctx.save();
  try {
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over'; ctx.filter = 'none';
    ctx.clearRect(0, 0, cw, ch);                // A and B already hold what was under the pictures
    TD.draw(ctx, A, B, J.clamp((t - c.start) / c.inDur), { cw, ch, sc, scPrev: sc, st: plan.style, P: c.transP || {}, step: Math.floor(t * 24), t, scale,
      allowFilter: !o.fast, seed: c.seed | 0, tmp: (w, h) => fit(TC || (TC = mk(2, 2)), w, h) });
  } catch (e) { console.warn('media: trans', c.join, e); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalCompositeOperation = 'copy'; ctx.drawImage(B, 0, 0); }
  finally { ctx.restore(); }
  return true;
}

M.drawTrack = (ctx, plan, t, track, o = {}) => {
  const P = plan && plan.media && plan.media[track];
  if (!P || !P.cuts.length || (M.measuring && M.measuring())) return;
  const W = plan.W, H = plan.H, scale = o.scale || 1;
  if (track === 'front') return drawLayers(ctx, plan, P, t, W, H, scale);
  const c = M.cutAt(plan, t, track);
  if (!c) return;
  ctx.save();
  try {
    ctx.imageSmoothingEnabled = true;
    ctx.globalCompositeOperation = BLEND[P.blend] || 'source-over';
    const lt = t - c.start;
    const prev = c.index > 0 ? P.cuts[c.index - 1] : null;
    const joining = !!(prev && c.join && c.join !== 'cut' && c.inDur > 0 && lt < c.inDur && Math.abs(prev.end - c.start) < NEAR);
    let seen = 0;
    if (joining && c.join !== 'fade' && J.TRANS[c.join]) {
      if (transJoin(ctx, plan, P, prev, c, t, W, H, scale, o)) seen = 1;
    } else {
      let a = c.opacity, under = 0, k = 1;
      // cross-fade: the picture before keeps moving underneath while this one appears
      if (joining && drawCut(ctx, plan, prev, t, W, H, P.opacity * prev.opacity, scale, null)) under = 1;
      if (joining) { k = ease(lt / c.inDur); a *= k; }
      const fx = {};
      if (!c.join && c.enter !== 'cut' && c.inDur > 0 && lt < c.inDur) fx.in = ease(lt / c.inDur);
      if (c.exit !== 'cut' && c.outDur > 0 && c.end - t < c.outDur) fx.out = ease((c.end - t) / c.outDur);
      const drawn = drawCut(ctx, plan, c, t, W, H, P.opacity * a, scale, fx);
      const vis = (fx.in != null && c.enter !== 'wipe' ? fx.in : 1) * (fx.out != null && c.exit !== 'wipe' ? fx.out : 1) * k;
      seen = Math.max(under, drawn ? vis : 0);
    }
    // 暗さ: a dark veil over the pictures so the lyrics stay readable (follows the pictures in and out)
    if (P.dim > 0 && seen > 0) {
      ctx.globalCompositeOperation = 'source-over';
      ctx.globalAlpha = P.dim * Math.min(1, seen);
      ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H);
    }
    // 暗幕: a soft plate behind the lyrics where the picture makes them hard to read
    if (track === 'back' && M.drawScrim && seen > 0) M.drawScrim(ctx, plan, c, t, W, H, seen, P);
  } catch (e) { console.warn('media', track, e); }
  finally { ctx.restore(); }
};

/* the front track: every picture showing at t, in the order they start (later ones on top), each coming and going by itself */
function drawLayers(ctx, plan, P, t, W, H, scale) {
  const cs = M.cutsAt(plan, t, 'front');
  if (!cs.length) return;
  ctx.save();
  try {
    ctx.imageSmoothingEnabled = true;
    ctx.globalCompositeOperation = BLEND[P.blend] || 'source-over';
    for (const c of cs) {
      ctx.save();
      try { drawCut(ctx, plan, c, t, W, H, P.opacity * c.opacity, scale, M.layerFx(c, t)); } finally { ctx.restore(); }
    }
  } catch (e) { console.warn('media front', e); }
  finally { ctx.restore(); }
}

/* the lyric background graphic (J.BG) is left out where a background picture shows, unless 「重ねる」 is on */
M.hidesBg = (plan, t) => {
  if (!plan || !plan.media || plan.media.lyricBg === 'over') return false;
  const c = M.cutAt(plan, t, 'back');
  return !!(c && !c.rect && J.mediaAssets.has(c.assetId));     // a picture placed small does not cover the frame
};
})();
