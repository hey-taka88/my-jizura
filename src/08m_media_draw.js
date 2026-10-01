/* ============================================================
   my-jizura (fork) — media layer: drawing
   J.media.drawTrack(ctx, plan, t, track, o) draws the pictures of one track in design space (ctx already scaled by o.scale).
   Called from J.Renderer.frame(): 'back' right after the background colour, 'front' after the HUD.
   Pictures that are not loaded (yet) are skipped; nothing here throws into the renderer.
   ============================================================ */
(() => {
'use strict';
const M = (J.media = J.media || {});
const BLEND = { normal: 'source-over', multiply: 'multiply', screen: 'screen', overlay: 'overlay' };
const ease = x => 0.5 - 0.5 * Math.cos(Math.PI * J.clamp(x));
const NEAR = 0.06;

/* one cut at time t with opacity a */
function drawCut(ctx, plan, c, t, W, H, a, scale) {
  const asset = J.mediaAssets.get(c.assetId);
  if (!asset || a <= 0.001) return false;
  let vt = null, frame = null;
  if (asset.type === 'video') {                // a clip: the frame for this song time (exact when exporting)
    vt = M.videoTimes(plan, c, t);
    frame = vt && M.videoFrame(asset, vt.main);
    if (!frame) return false;
  } else if (!asset.source) return false;
  const sw = asset.w, sh = asset.h;
  const base = c.fit === 'contain' ? Math.min(W / sw, H / sh) : Math.max(W / sw, H / sh);
  let z = 1, px = 0, py = 0;
  if (c.hold === 'kenburns' && c.kb) {
    const p = ease((t - c.start) / Math.max(0.1, c.dur));
    z = J.lerp(c.kb.s0, c.kb.s1, p); px = J.lerp(c.kb.x0, c.kb.x1, p) * W; py = J.lerp(c.kb.y0, c.kb.y1, p) * H;
  }
  const dw = sw * base * z, dh = sh * base * z;
  if (c.fit !== 'contain') {               // a filled frame never shows its edge while drifting
    const mx = Math.max(0, (dw - W) / 2), my = Math.max(0, (dh - H) / 2);
    px = J.clamp(px, -mx, mx); py = J.clamp(py, -my, my);
  }
  // the size bucket depends on the cut's largest size, not on this frame's zoom (no new copy while zooming)
  const zMax = c.kb ? Math.max(c.kb.s0, c.kb.s1) : 1;
  const src = frame || M.sourceFor(asset, sw * base * zMax * scale, sh * base * zMax * scale);
  if (!src) return false;
  // the copy is already close to the drawn size (made once with high quality), so plain bilinear is enough per frame;
  // only a large step down (a picture drawn far smaller than its copy) needs the slower filter
  const step = frame ? 1 : Math.max(src.width / (dw * scale), src.height / (dh * scale));
  ctx.imageSmoothingQuality = step > 1.6 ? 'high' : 'low';
  ctx.globalAlpha = a;
  ctx.drawImage(src, W / 2 - dw / 2 + px, H / 2 - dh / 2 + py, dw, dh);
  // loop seam (exports): the start of the clip fades in over its end
  if (vt && vt.alt != null && vt.k > 0) {
    const s2 = M.videoCap(asset, vt.alt);
    if (s2) { ctx.globalAlpha = a * vt.k; ctx.drawImage(s2, W / 2 - dw / 2 + px, H / 2 - dh / 2 + py, dw, dh); }
  }
  return true;
}

M.drawTrack = (ctx, plan, t, track, o = {}) => {
  const P = plan && plan.media && plan.media[track];
  if (!P || !P.cuts.length) return;
  const c = M.cutAt(plan, t, track);
  if (!c) return;
  const W = plan.W, H = plan.H, scale = o.scale || 1;
  ctx.save();
  try {
    ctx.imageSmoothingEnabled = true;
    ctx.globalCompositeOperation = BLEND[P.blend] || 'source-over';
    const lt = t - c.start;
    let a = c.opacity, under = 0;
    if (c.enter === 'fade' && c.inDur > 0 && lt < c.inDur) {
      const k = ease(lt / c.inDur);
      // cross-fade: the picture before keeps moving underneath while this one appears
      const prev = c.index > 0 ? P.cuts[c.index - 1] : null;
      if (prev && Math.abs(prev.end - c.start) < NEAR && drawCut(ctx, plan, prev, t, W, H, P.opacity * prev.opacity, scale)) under = 1;
      a *= k;
    }
    if (c.exit === 'fade' && c.outDur > 0 && c.end - t < c.outDur) a *= ease((c.end - t) / c.outDur);
    const drawn = drawCut(ctx, plan, c, t, W, H, P.opacity * a, scale);
    // 暗さ: a dark veil over the pictures so the lyrics stay readable (follows the pictures in and out)
    const seen = Math.max(under, drawn ? a / Math.max(0.001, c.opacity) : 0);
    if (P.dim > 0 && seen > 0) {
      ctx.globalCompositeOperation = 'source-over';
      ctx.globalAlpha = P.dim * Math.min(1, seen);
      ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H);
    }
  } catch (e) { console.warn('media', track, e); }
  finally { ctx.restore(); }
};

/* the lyric background graphic (J.BG) is left out where a background picture shows, unless 「重ねる」 is on */
M.hidesBg = (plan, t) => {
  if (!plan || !plan.media || plan.media.lyricBg === 'over') return false;
  const c = M.cutAt(plan, t, 'back');
  return !!(c && J.mediaAssets.has(c.assetId));
};
})();
