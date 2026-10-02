/* ============================================================
   my-jizura (fork) — lyric text set by hand: where a line (or one cut of it) sits, how big, in which colour,
   and whether a long interlude shows the song title. (P1 of the production feedback, 2026-10-02)
   project.media.text = { interludeTitle: 'show' | 'hide',
                          lines: { '<line>': { x, y, scale, color, cuts: { '<cut>': { x, y, scale, color } } } } }
     x, y: offset in frame widths / heights (-0.5 … 0.5) · scale: 0.2 … 3 · color: '#rrggbb' (the text colour of that line / cut)
   Layout, motion, decorations, background graphic and cut times stay in the app's own per-line settings (project.overrides).
   Applied to plan.cuts right after J.plan() (from M.resolve): a fixed camera 'place' that moves / scales the lyric of the cut on top
   of the camera move it already had, and a copy of the cut's colour scheme with the text colour. The same project gives the same plan.
   ============================================================ */
(() => {
'use strict';
const M = (J.media = J.media || {});
const isObj = v => !!v && typeof v === 'object' && !Array.isArray(v);
const num = (v, lo, hi) => { const n = +v; return v != null && v !== '' && Number.isFinite(n) ? J.clamp(n, lo, hi) : null; };

// 位置・大きさの指定: the cut's own camera, then this offset / scale (never picked at random: special)
J.register('cam', 'place', { name: '位置・大きさの指定', special: true, w: 0, tags: [],
  get(env, P) {
    const B = P.base && P.base !== 'place' && J.CAMERA[P.base] ? J.CAMERA[P.base] : J.CAMERA.push;
    let b = null;
    try { b = B.get(env, P.baseP || {}); } catch (e) { b = null; }
    b = b || {};
    return Object.assign({}, b, { x: (b.x || 0) + (P.x || 0) * env.W, y: (b.y || 0) + (P.y || 0) * env.H, s: (b.s ?? 1) * (P.s || 1) });
  } }, 'my-jizura');

M.textDefaults = () => ({ interludeTitle: 'show', lines: {} });
/* untrusted input → valid project.media.text */
M.normalizeText = t => {
  const d = M.textDefaults();
  if (!isObj(t)) return d;
  const one = o => {
    const r = {};
    const x = num(o.x, -0.5, 0.5), y = num(o.y, -0.5, 0.5), s = num(o.scale, 0.2, 3);
    if (x != null && x !== 0) r.x = x;
    if (y != null && y !== 0) r.y = y;
    if (s != null && s !== 1) r.scale = s;
    if (typeof o.color === 'string' && /^#[0-9a-f]{6}$/i.test(o.color)) r.color = o.color.toLowerCase();
    return r;
  };
  for (const [k, v] of Object.entries(isObj(t.lines) ? t.lines : {}).slice(0, 5000)) {
    if (!/^\d{1,5}$/.test(k) || !isObj(v)) continue;
    const o = one(v), cuts = {};
    for (const [ck, cv] of Object.entries(isObj(v.cuts) ? v.cuts : {}).slice(0, 12)) {
      if (!/^\d{1,2}$/.test(ck) || !isObj(cv)) continue;
      const c = one(cv); if (Object.keys(c).length) cuts[ck] = c;
    }
    if (Object.keys(cuts).length) o.cuts = cuts;
    if (Object.keys(o).length) d.lines[k] = o;
  }
  d.interludeTitle = t.interludeTitle === 'hide' ? 'hide' : 'show';
  return d;
};

/* the cuts of one lyric line, in order (the same list the app's line lock keeps) */
M.lineCuts = (plan, li) => plan.cuts.filter(c => c.line === li && c.utext != null);

/* project.media.text → plan.cuts (called from M.resolve with the checked media) */
M.applyText = (m, plan) => {
  const T = m && m.text;
  if (!T || !plan || !plan.cuts) return;
  // 間奏の曲名: the title / artist stay in the project (and the LRC tags), only the interlude card leaves them out
  if (T.interludeTitle === 'hide') for (const c of plan.cuts) if (c.layout === 'interlude' && c.params && c.params.showTitle) c.params = Object.assign({}, c.params, { showTitle: false, titleText: '' });
  const lines = T.lines || {};
  if (!Object.keys(lines).length) return;
  const n0 = plan.style.schemes.length, made = new Map();
  for (const [lk, L] of Object.entries(lines)) {
    M.lineCuts(plan, +lk).forEach((c, k) => {
      const spec = Object.assign({}, L, (L.cuts || {})[k] || {});
      if (spec.x || spec.y || (spec.scale && spec.scale !== 1)) {
        // a cut that already carries the placement (a locked line keeps its snapshot) keeps its first camera underneath
        const P0 = c.cam === 'place' ? c.camP || {} : null;
        c.camP = { x: spec.x || 0, y: spec.y || 0, s: spec.scale || 1, base: P0 ? P0.base : c.cam, baseP: P0 ? P0.baseP : c.camP };
        c.cam = 'place';
      }
      if (spec.color) {
        const base = ((c.scheme | 0) % n0 + n0) % n0, key = base + spec.color;
        if (!made.has(key)) {
          if (made.size === 0) plan.style.schemes = plan.style.schemes.slice();     // this plan's own copy (J.resolveStyle copies the style)
          plan.style.schemes.push(Object.assign({}, plan.style.schemes[base], { fg: spec.color }));
          made.set(key, plan.style.schemes.length - 1);
        }
        c.scheme = made.get(key);
      }
    });
  }
};
})();
