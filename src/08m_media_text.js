/* ============================================================
   my-jizura (fork) — lyric text set by hand: where a line (or one cut of it) sits, how big, in which colour,
   and whether a long interlude shows the song title. (P1 of the production feedback, 2026-10-02)
   project.media.text = { interludeTitle: 'show' | 'hide',
                          lines: { '<line>': { x, y, scale, color, cuts: { '<cut>': { x, y, scale, color } } } },
                          words: [{ text, start, w: [[seconds, offset], …], p }] }   (word times from the lyrics import)
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

M.textDefaults = () => ({ interludeTitle: 'show', lines: {}, words: [] });
/* a lyric line as the word times count it: what the planner shows (no | note, no final !), without spaces and / * marks */
M.normText = s => { s = String(s == null ? '' : s); const bar = s.indexOf('|'); if (bar >= 0) s = s.slice(0, bar); return s.trim().replace(/!$/, '').replace(/[\s/*]/g, ''); };
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
    // the overrides cutTime entries M.lockLine added, with the value it wrote ({ cut key: seconds }): unlocking clears an
    // entry only while it still has that value (a time changed by hand afterwards stays)
    const held = {};
    for (const [hk, hv] of Object.entries(isObj(v.heldTimes) ? v.heldTimes : {}).slice(0, 12)) {
      const n = num(hv, 0, 3600);
      if (/^\d{1,2}$/.test(hk) && +hk >= 1 && n != null) held[+hk] = n;
    }
    if (Object.keys(held).length) o.heldTimes = held;
    if (v.tone === 'quiet' || v.tone === 'calm') o.tone = v.tone;   // set_range_style: how strongly the line moves (M.TONES)
    for (const [ck, cv] of Object.entries(isObj(v.cuts) ? v.cuts : {}).slice(0, 12)) {
      if (!/^\d{1,2}$/.test(ck) || !isObj(cv)) continue;
      const c = one(cv); if (Object.keys(c).length) cuts[ck] = c;
    }
    if (Object.keys(cuts).length) o.cuts = cuts;
    if (Object.keys(o).length) d.lines[k] = o;
  }
  d.interludeTitle = t.interludeTitle === 'hide' ? 'hide' : 'show';
  // word times: [{ text, start, w: [[t, offset, p?]…] (in time order), p }]
  for (const e of (Array.isArray(t.words) ? t.words : []).slice(0, 3000)) {
    if (!isObj(e) || typeof e.text !== 'string' || !Array.isArray(e.w)) continue;
    const text = M.normText(e.text).slice(0, 500), start = num(e.start, 0, 86400);
    const w = [];
    for (const x of e.w.slice(0, 400)) {
      if (!Array.isArray(x)) continue;
      const tt = num(x[0], 0, 86400), off = num(x[1], 0, 500), pw = num(x[2], 0, 1);
      if (tt != null && off != null && (!w.length || (tt >= w[w.length - 1][0] && off >= w[w.length - 1][1]))) w.push(pw != null ? [tt, Math.round(off), pw] : [tt, Math.round(off)]);
    }
    if (!text || !w.length) continue;
    const o = { text, start: start != null ? start : w[0][0], w };
    const pv = num(e.p, 0, 1); if (pv != null) o.p = pv;
    d.words.push(o);
  }
  return d;
};

/* the cuts of one lyric line, in order (the same list the app's line lock keeps) */
M.lineCuts = (plan, li) => plan.cuts.filter(c => c.line === li && c.utext != null);

/* project.media.text → plan.cuts (called from M.resolve with the checked media) */
/* the word times of a plan line: the entry with the same text that starts nearest to it (a repeated chorus line has several) */
M.lineWords = (m, ln) => {
  const W = m && m.text && m.text.words;
  if (!W || !W.length || !ln || ln.interlude) return null;
  const key = M.normText(ln.text);
  let best = null;
  for (const e of W) if (e.text === key && (!best || Math.abs(e.start - ln.start) < Math.abs(best.start - ln.start))) best = e;
  return best && Math.abs(best.start - ln.start) < 8 ? best : null;
};
/* when the character at `off` of the line is sung: its word's time, or between two words by how far into the word it is */
function timeAt(w, off) {
  let k = -1;
  for (let i = 0; i < w.length; i++) if (w[i][1] <= off) k = i; else break;
  if (k < 0) return null;
  if (w[k][1] === off || k + 1 >= w.length) return w[k][1] === off ? w[k][0] : null;
  return w[k][0] + (w[k + 1][0] - w[k][0]) * (off - w[k][1]) / Math.max(1, w[k + 1][1] - w[k][1]);
}
/* the words of a line whose time is believable: confidence ≥ WEAK_WORD (when the source gives one) and inside the line
   (a little before its start is fine) — the others are left out, so a cut start falls between the believable words around it */
M.WEAK_WORD = 0.1;
M.usableWord = (x, ln) => (x[2] == null || x[2] >= M.WEAK_WORD) && x[0] >= ln.start - 0.3 && x[0] <= Math.max(ln.end, ln.visEnd || 0) + 0.3;
/* 語の時刻: the cuts inside a line change when their first word is sung (not by how long their text is).
   A line whose cut times were set by hand (overrides cutTime) keeps them; a recap cut (the whole line again) keeps its place. */
M.alignWords = (m, plan, project) => {
  const W = m && m.text && m.text.words;
  if (!W || !W.length) return;
  const ovs = (project && project.overrides) || {};
  plan.lines.forEach((ln, li) => {
    const ov = ovs[li] || {};
    if (ov.cutTime && Object.keys(ov.cutTime).length) return;
    const e = M.lineWords(m, ln);
    if (!e) return;
    const cuts = M.lineCuts(plan, li).filter(c => !c.recap);
    if (cuts.length < 2) return;
    const full = M.normText(ln.text), ws = e.w.filter(x => M.usableWord(x, ln));
    let cursor = 0;
    for (let k = 0; k < cuts.length; k++) {
      const piece = M.normText(cuts[k].utext);
      const at = piece ? full.indexOf(piece, cursor) : -1;
      if (at < 0) return;                                  // a cut that is not a plain piece of the line: leave the line as planned
      cuts[k]._off = [...full.slice(0, at)].length; cursor = at + piece.length;
    }
    for (let k = 1; k < cuts.length; k++) {
      const prev = cuts[k - 1], c = cuts[k], t = timeAt(ws, c._off);
      if (t == null) continue;
      c.sungAt = t;                                        // when it is sung (get_line shows it: a line shown shorter than it is sung can't follow)
      const T = J.clamp(t, prev.start + 0.22, c.end - 0.22);    // the same 0.22 s the planner keeps between cut starts
      if (!(T > prev.start && T < c.end)) continue;
      prev.end = T; c.start = T;
    }
    for (const c of cuts) {
      delete c._off;
      c.dur = c.end - c.start;
      c.inDur = Math.min(c.inDur, c.dur * 0.45); c.outDur = Math.min(c.outDur, c.dur * 0.45);
    }
  });
};

/* 固定 (the app's line lock, as its lock button does) + the cut times the line shows: J.lineSnapshot alone lets a line
   with a recap cut move its cut starts (the planner weighs a locked recap cut by its text length, not as it first did),
   so the times are kept as overrides cutTime too (beside any set by hand), the added ones with their value in heldTimes (M.unlockLine).
   scheme: pin every cut of the line to this colour scheme. Returns false for an interlude or a line not in the plan. */
M.lockLine = (project, plan, li, scheme) => {
  const ln = plan.lines[li], spec = ln && !ln.interlude ? J.lineSnapshot(plan, li) : null;
  if (!spec) return false;
  if (scheme != null) spec.forEach(c => { c.scheme = scheme; });
  const ov = Object.assign({}, (project.overrides = project.overrides || {})[li] || {}, { lock: true, lockedSeed: ln.seed, lockedCuts: spec });
  const cuts = M.lineCuts(plan, li);
  if (cuts.length > 1 && project.media) {
    const ct = Object.assign({}, ov.cutTime || {});
    const lines = Object.assign({}, project.media.text.lines), L = Object.assign({}, lines[li] || {}), held = Object.assign({}, L.heldTimes || {});
    cuts.slice(1).forEach((c, k) => { if (ct[k + 1] == null) { ct[k + 1] = held[k + 1] = c.start - ln.start; } });
    ov.cutTime = ct;
    if (Object.keys(held).length) L.heldTimes = held;
    if (Object.keys(L).length) lines[li] = L;
    project.media.text = Object.assign({}, project.media.text, { lines });
  }
  project.overrides[li] = ov;
  return true;
};
/* the other way: lock off, and the cut times M.lockLine kept go too (cut times set by hand stay, also one changed after the lock) */
M.unlockLine = (project, li) => {
  const ov = Object.assign({}, (project.overrides || {})[li] || {});
  delete ov.lock; delete ov.lockedSeed; delete ov.lockedCuts;
  const L = project.media && project.media.text.lines[li];
  if (L && L.heldTimes) {
    const ct = Object.assign({}, ov.cutTime || {});
    for (const [k, v] of Object.entries(L.heldTimes)) if (ct[k] != null && Math.abs(+ct[k] - v) < 1e-6) delete ct[k];
    if (Object.keys(ct).length) ov.cutTime = ct; else delete ov.cutTime;
    const lines = Object.assign({}, project.media.text.lines), L2 = Object.assign({}, L);
    delete L2.heldTimes;
    if (Object.keys(L2).length) lines[li] = L2; else delete lines[li];
    project.media.text = Object.assign({}, project.media.text, { lines });
  }
  if (project.overrides) { if (Object.keys(ov).length) project.overrides[li] = ov; else delete project.overrides[li]; }
};

/* 見せ方の強さ (set_range_style): the per-line settings a tone writes into project.overrides — the same keys as the app's
   per-line settings, so the planner lays the line out with them. On top, a toned line shows no screen effects
   (shake / glitch / flash / colour split … — M.applyText drops the events while it is on screen).
   quiet: one cut, big and centred, soft in and out, a slow breath — a rest between busy parts.
   calm:  JIZURA's own layout and cuts, but soft in and out, a slow drift, no decorations, no camera hits.
   Both leave out the cut-to-cut transitions (they turn the entrance into a hard cut): the app's 「つなぎなし」 per cut (cutTech trans 'none'). */
M.TONE_KEYS = ['single', 'cuts', 'layout', 'enter', 'exit', 'hold', 'cam', 'treat', 'decor'];
M.TONES = {
  quiet: { single: true, layout: 'center', enter: 'blur', exit: 'blur', hold: 'breathe', cam: 'push', treat: 'none', decor: [] },
  calm: { enter: 'blur', exit: 'blur', hold: 'drift', cam: 'push', treat: 'none', decor: [] },
};
/* one line's overrides with a tone ('normal' = without): what a tone sets replaces what was set for those parts */
M.applyTone = (ov, tone) => {
  const o = Object.assign({}, ov);
  for (const k of M.TONE_KEYS) delete o[k];
  const ct = {};
  for (const [k, t] of Object.entries(o.cutTech || {})) { const t2 = Object.assign({}, t); if (t2.trans === 'none') delete t2.trans; if (Object.keys(t2).length) ct[k] = t2; }
  if (M.TONES[tone]) {
    Object.assign(o, JSON.parse(JSON.stringify(M.TONES[tone])));
    for (let k = 0; k < (tone === 'quiet' ? 1 : 12); k++) ct[k] = Object.assign({}, ct[k] || {}, { trans: 'none' });
  }
  if (Object.keys(ct).length) o.cutTech = ct; else delete o.cutTech;
  return o;
};

M.applyText = (m, plan, project) => {
  const T = m && m.text;
  if (!T || !plan || !plan.cuts) return;
  M.alignWords(m, plan, project);
  // 間奏の曲名: the title / artist stay in the project (and the LRC tags), only the interludes leave them out —
  // both a [間奏] line (params.showTitle) and the interlude the planner puts into a long gap between lines (the title as its text;
  // a blank, since an empty text would show '— interlude —')
  if (T.interludeTitle === 'hide') for (const c of plan.cuts) {
    if (c.layout !== 'interlude') continue;
    if (c.params && c.params.showTitle) c.params = Object.assign({}, c.params, { showTitle: false, titleText: '' });
    if (c.text && c.utext == null) c.text = ' ';
  }
  const lines = T.lines || {};
  // a toned line (set_range_style) shows no screen effects while it is on screen
  const calm = Object.keys(lines).filter(k => lines[k].tone).map(k => M.lineCuts(plan, +k)).filter(cs => cs.length)
    .map(cs => [cs[0].start - 0.05, cs[cs.length - 1].end]);
  if (calm.length) plan.events = plan.events.filter(e => !calm.some(([a, b]) => e.t >= a && e.t < b));
  const n0 = plan.style.schemes.length;
  // text colours: for every colour used, a copy of every scheme at n0 + i·n0 + base — so any index, also one a locked line kept
  // from an earlier plan, still tells its own scheme (index % n0) and the colour never takes the background / accents of another
  const colors = [...new Set(Object.values(lines).flatMap(L => [L.color, ...Object.values(L.cuts || {}).map(c => c.color)]).filter(Boolean))].sort();
  for (const c of plan.cuts) if (c.scheme >= n0) c.scheme = c.scheme % n0;
  if (!Object.keys(lines).length) return;
  if (colors.length) {
    plan.style.schemes = plan.style.schemes.slice();                       // this plan's own copy (J.resolveStyle copies the style)
    for (const col of colors) for (let b = 0; b < n0; b++) plan.style.schemes.push(Object.assign({}, plan.style.schemes[b], { fg: col }));
  }
  for (const [lk, L] of Object.entries(lines)) {
    M.lineCuts(plan, +lk).forEach((c, k) => {
      const spec = Object.assign({}, L, (L.cuts || {})[k] || {});
      if (spec.x || spec.y || (spec.scale && spec.scale !== 1)) {
        // a cut that already carries the placement (a locked line keeps its snapshot) keeps its first camera underneath
        const P0 = c.cam === 'place' ? c.camP || {} : null;
        c.camP = { x: spec.x || 0, y: spec.y || 0, s: spec.scale || 1, base: P0 ? P0.base : c.cam, baseP: P0 ? P0.baseP : c.camP };
        c.cam = 'place';
      } else if (c.cam === 'place' && c.camP) { c.cam = c.camP.base; c.camP = c.camP.baseP || {}; }   // placement cleared on a locked line
      if (spec.color) c.scheme = n0 + colors.indexOf(spec.color) * n0 + ((c.scheme | 0) % n0);
    });
  }
};
})();
