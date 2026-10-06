/* ============================================================
   my-jizura (fork) — media layer: project.media → plan.media
   Deterministic: the same project + lyrics timing always gives the same media cuts.
   plan.media = { lyricBg, back: { cuts, opacity, blend, dim }, front: { … } }
   cut = { index, assetId, type, start, end, dur, line, anchor (where a clip's clock starts), timed, fit, enter, hold, exit, join, transP, inDur, outDur, dir, treat, opacity, seed, kb, hp, v, rect, chroma }
   join: how it takes over from the picture right before ('fade' / 'cut' / a J.TRANS key), null when nothing touches it
   ============================================================ */
(() => {
'use strict';
const M = (J.media = J.media || {});
const NEAR = 0.06;                         // two cuts closer than this touch (same rule as the lyric transitions)

// the n-th image of the automatic sequence: in the order added, or shuffled once per round (seeded), never the same twice in a row
function sequence(ids, A) {
  const perms = [];
  const perm = round => {
    if (perms[round]) return perms[round];
    const p = ids.slice();
    if (A.order === 'random' && p.length > 1) {
      const r = J.rng(J.h(A.seed, round, 0x6d65));
      for (let i = p.length - 1; i > 0; i--) { const j = Math.floor(r() * (i + 1)); [p[i], p[j]] = [p[j], p[i]]; }
      const prev = round > 0 ? perm(round - 1) : null;
      if (prev && p[0] === prev[prev.length - 1]) [p[0], p[1]] = [p[1], p[0]];
    }
    return (perms[round] = p);
  };
  return n => perm(Math.floor(n / ids.length))[n % ids.length];
}

/* the pictures placed at a time of the song → [{ c, s, e }]: an end given, else (back track) the next one's start, else the song end.
   A cut with no picture ('' = 「なし」, or a picture that is gone) still takes its time: nothing automatic shows there */
function timedSpans(timed, D, layered) {
  return timed.filter(c => c.start < D).sort((a, b) => a.start - b.start)
    .map((c, i, arr) => ({ c, s: c.start, e: Math.min(D, c.end != null ? c.end : !layered && i + 1 < arr.length ? arr[i + 1].start : D) }))
    .filter(x => x.e - x.s > 0.02);
}

function resolveTrack(m, k, plan) {
  const T = m.tracks[k], A = m.autoFill[k], D = Math.max(0.1, plan.duration || 0);
  const ids = m.assets.map(a => a.id);
  const known = new Set(ids), meta = new Map(m.assets.map(a => [a.id, a]));
  const out = { cuts: [], opacity: T.opacity, blend: T.blend, dim: T.dim };
  const byLine = new Map(), timed = [];
  for (const c of T.cuts) { if (c.lineRef) byLine.set(c.lineRef.line, c); else timed.push(c); }
  // a picture placed over the lyrics (a logo, a character) is not also one of the automatic backgrounds
  const onFront = k === 'back' ? new Set(m.tracks.front.cuts.map(c => c.assetId).filter(Boolean)) : null;
  const autoIds = onFront && onFront.size ? ids.filter(id => !onFront.has(id)) : ids;
  const next = autoIds.length ? sequence(autoIds, A) : null;
  const lines = (plan.lines || []).slice().sort((a, b) => a.start - b.start);
  // what each lyric line shows: a picture chosen for that line (own), or the next one of the automatic order
  const auto = [], own = [];
  let n = 0;
  if (!lines.length) {
    if (A.mode === 'perLine' && next) auto.push({ assetId: next(0), start: 0, end: D, line: -1, src: null });
  } else {
    lines.forEach((ln, j) => {
      const start = j === 0 ? 0 : ln.start;                 // the first image also covers the intro / title card
      const end = j + 1 < lines.length ? lines[j + 1].start : D;
      if (!(end - start > 0.02)) return;
      const ov = byLine.get(ln.index);
      if (ov) own.push({ assetId: ov.assetId && known.has(ov.assetId) ? ov.assetId : null, start, end, line: ln.index, src: ov });   // 「なし」 stays empty
      else if (A.mode === 'perLine' && next) auto.push({ assetId: next(n++), start, end, line: ln.index, src: null });
    });
  }
  // pictures placed at a time of the song (a clip under the whole song, a picture for a section): end = given, else the next one's start.
  // They cover the automatic pictures; a picture chosen for a line still shows over them, and a clip keeps its own clock
  // (anchor) around it, so it never jumps back to its start at a lyric line.
  // the front track is layers: its pictures may overlap (a logo all song long, a character for a verse), one without an end stays
  // to the end of the song, and each comes and goes by itself (no つなぎ)
  const layered = k === 'front';
  const tl = timedSpans(timed, D, layered);
  const cut = (list, holes) => {                            // the parts of each [start, end) outside the holes
    const out = [];
    for (const g of list) {
      let pieces = [[g.start, g.end]];
      for (const h of holes) pieces = pieces.flatMap(([a, b]) => (h.e <= a || h.s >= b ? [[a, b]] : [[a, Math.min(b, h.s)], [Math.max(a, h.e), b]]));
      for (const [a, b] of pieces) if (b - a > 0.02) out.push(Object.assign({}, g, { start: a, end: b }));
    }
    return out;
  };
  let segs = cut(auto, tl).concat(own)
    .concat(cut(tl.map(x => ({ assetId: x.c.assetId, start: x.s, end: x.e, line: -1, src: x.c, anchor: x.s })), own.map(o => ({ s: o.start, e: o.end }))))
    .filter(s => s.assetId && known.has(s.assetId));
  segs.sort((a, b) => a.start - b.start);
  segs.forEach(s => { s.end = Math.min(s.end, D); });
  segs = segs.filter(s => s.end - s.start > 0.02);
  // one automatic image over several lines in a row stays one cut (its slow move does not restart)
  const merged = [];
  for (const s of segs) {
    const p = merged[merged.length - 1];
    if (p && !p.src && !s.src && p.assetId === s.assetId && Math.abs(p.end - s.start) < NEAR) p.end = s.end;
    else merged.push(s);
  }
  const transKeys = M.TRANS_KEYS.filter(k => J.TRANS && J.TRANS[k]);
  merged.forEach((s, i) => {
    const src = s.src, prv = merged[i - 1], nxt = merged[i + 1];
    const dur = s.end - s.start;
    const own = (key, dflt) => (src && src[key] && src[key] !== 'auto' ? src[key] : dflt);
    const seed = src && src.seed != null ? src.seed : J.h(A.seed, J.sid(s.assetId), Math.round(s.start * 100));
    const touchPrev = !layered && !!(prv && Math.abs(prv.end - s.start) < NEAR), touchNext = !layered && !!(nxt && Math.abs(nxt.start - s.end) < NEAR);
    const r = J.rng(J.h(seed, 0x6b62));
    const zoomIn = r.chance(0.6), z = r.range(0.06, 0.11);
    const a = meta.get(s.assetId) || {}, isVideo = a.type === 'video';
    // a second stream for everything added in Phase 3 (the slow zoom above keeps its numbers)
    const r2 = J.rng(J.h(seed, 0x6d76));
    const dir = r2.pick(['L', 'R', 'L', 'R', 'U', 'D']);
    // つなぎ: a picture that follows another one takes over by a cross-fade, a hard cut or a transition (J.TRANS);
    // 登場: otherwise it comes in by itself
    let join = null, enter, inDur, transP = null;
    if (touchPrev) {
      let j = own('trans', src && src.enter === 'cut' ? 'cut' : A.trans);
      if (j === 'mix') j = transKeys.length && !r2.chance(0.3) ? r2.pick(transKeys) : 'fade';
      if (j !== 'fade' && j !== 'cut' && !(J.TRANS && J.TRANS[j])) j = 'fade';
      join = j;
      if (j === 'fade') { enter = 'fade'; inDur = Math.min(0.6, dur * 0.3); }
      else if (j === 'cut') { enter = 'cut'; inDur = 0; }
      else {
        const TD = J.TRANS[j];
        enter = 'cut'; inDur = Math.min(dur * 0.4, Math.max(0.45, (TD.dur || 0.35) * 1.5));
        try { transP = TD.plan ? TD.plan(J.rng(J.h(seed, 0x7470)), plan.style) : {}; } catch (e) { transP = {}; }
      }
    } else {
      enter = own('enter', A.enter || 'fade');
      inDur = enter === 'cut' ? 0 : Math.min(enter === 'fade' ? 0.6 : 0.7, dur * 0.3);
    }
    const exit = touchNext ? 'cut' : own('exit', A.exit || 'fade');     // the next picture takes over from this one
    const outDur = exit === 'cut' ? 0 : Math.min(exit === 'fade' ? 0.45 : 0.6, dur * 0.25);
    out.cuts.push({
      index: i, assetId: s.assetId, type: isVideo ? 'video' : 'image', start: s.start, end: s.end, dur, line: s.line,
      anchor: s.anchor != null ? s.anchor : s.start, timed: !!(src && !src.lineRef),
      fit: own('fit', A.fit), enter, hold: own('hold', isVideo ? 'still' : A.hold), exit,   // a clip moves by itself: no slow zoom unless asked
      join, transP, inDur, outDur, dir, treat: own('treat', A.treat || 'none'),
      v: isVideo ? clip(a, Object.assign({}, A.video, src && src.video)) : null,
      opacity: src ? src.opacity : 1, seed, rect: src && src.rect ? Object.assign({}, src.rect) : null,   // placed by hand (x, y, w, rot)
      chroma: src && src.chroma ? Object.assign({}, src.chroma) : null,                                      // クロマキー
      id: src && src.id ? src.id : null,                                                                     // the project cut it came from (配置編集)
      // ゆっくり寄る / 引く: scale s0 → s1 and a small drift (fractions of the frame), kept inside the picture
      kb: { s0: zoomIn ? 1 : 1 + z, s1: zoomIn ? 1 + z : 1, x0: r.range(-0.03, 0.03), y0: r.range(-0.02, 0.02), x1: r.range(-0.03, 0.03), y1: r.range(-0.02, 0.02) },
      // パン / 漂う: which way, and where the float starts
      hp: { sign: r2.chance(0.5) ? 1 : -1, ph: r2.range(0, Math.PI * 2), per: r2.range(6, 9) },
    });
  });
  return out;
}

/* which part of a clip plays and how it fills its cut (see M.EXTEND) */
function clip(a, o) {
  const d = Math.max(0.05, +a.duration || 0.05);
  const s = J.clamp(+o.start || 0, 0, Math.max(0, d - 0.05));
  const e = J.clamp(o.end != null ? +o.end : d, s + 0.05, d);
  const len = e - s;
  // loop seam: the last moments of the clip cross-fade into its start (0.3 s, or a tenth of a short clip)
  return { a: s, b: e, len, extend: o.extend || 'loop', rate: +o.rate || 1, beats: +o.beats || 4, seam: len >= 1 ? Math.min(0.3, len * 0.1) : 0 };
}

/* where in the clip we are at song time t → { main, alt?, k? } (seconds in the clip; alt is shown over main with weight k) */
M.videoTimes = (plan, c, t) => {
  const v = c.v; if (!v) return null;
  const L = v.len, end = v.a + Math.max(0, L - 1 / 120);
  const at = x => Math.min(end, v.a + Math.max(0, x));
  const looped = x => {
    const o = v.seam;
    if (!(o > 0) || L <= o * 2) return { main: at(x % L) };
    // first pass plays the whole clip; then every pass starts at a+o and, in its last o seconds, the start fades in over it
    const q = x < L ? x : o + ((x - L) % (L - o));
    if (q < L - o) return { main: at(q) };
    return { main: at(q), alt: at(q - (L - o)), k: (q - (L - o)) / o };
  };
  const u = Math.max(0, t - (c.anchor != null ? c.anchor : c.start)) * v.rate;     // a clip placed at a time runs on its own clock
  switch (v.extend) {
    case 'hold': return { main: at(u) };
    case 'pingpong': { const m = u % (2 * L); return { main: at(m <= L ? m : 2 * L - m) }; }
    case 'beat': return looped(Math.max(0, t - barStart(plan, c, t, v.beats)) * v.rate);
    default: return looped(u);
  }
};
/* the start of the bar (every n beats, counted from the first beat in the cut) that t is in; the cut start when there are no beats */
function barStart(plan, c, t, n) {
  const B = plan.beats || [];
  if (!B.length) return c.anchor != null ? c.anchor : c.start;
  const last = i => { let lo = 0, hi = B.length - 1, ans = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (B[m] <= i) { ans = m; lo = m + 1; } else hi = m - 1; } return ans; };
  const c0 = c.anchor != null ? c.anchor : c.start;
  const i0 = last(c0 - 0.05) + 1, it = last(t);
  if (i0 >= B.length || it < i0) return c0;
  return B[i0 + Math.floor((it - i0) / n) * n];
}

M.resolve = (project, plan) => {
  if (!project || !project.media) return null;
  const m = M.normalize(project.media);          // cheap, and plans built from test / preview projects get the same checks
  if (M.applyText) M.applyText(m, plan, project);          // lyric placement / colour set by hand, the interlude title (08m_media_text.js)
  const out = { lyricBg: m.lyricBg === 'over' ? 'over' : 'off', scrim: Object.assign({}, m.scrim) };
  for (const k of M.TRACKS) out[k] = resolveTrack(m, k, plan);
  return out;
};

/* おまかせ × pictures: does a background picture show during [t0, t1) of lyric line li? (the order of resolveTrack: a picture
   chosen for the line, else one placed at a time, else the automatic one). Read from the project, before the lyrics are planned */
M.backUnder = (project, li, t0, t1) => {
  const m = project && project.media;
  if (!m || !m.assets || !m.assets.length || !m.tracks || !m.tracks.back || (J.keyMode && J.keyMode(project))) return false;
  const known = new Set(m.assets.map(a => a.id)), cuts = m.tracks.back.cuts || [];
  let own = null; for (const c of cuts) if (c.lineRef && c.lineRef.line === li) own = c;   // the last one, as resolveTrack's byLine
  if (own) return !!own.assetId && known.has(own.assetId);                          // 「なし」 = nothing under this line
  // placed at a time: a picture there counts; any placed cut (also 「なし」) takes its span from the automatic pictures
  const spans = timedSpans(cuts.filter(c => !c.lineRef), Infinity, false).filter(x => x.s < t1 && x.e > t0);
  if (spans.some(x => x.c.assetId && known.has(x.c.assetId))) return true;
  const A = m.autoFill && m.autoFill.back;
  if (!A || A.mode !== 'perLine') return false;
  const onFront = new Set(((m.tracks.front && m.tracks.front.cuts) || []).map(c => c.assetId).filter(Boolean));
  if (!m.assets.some(a => !onFront.has(a.id))) return false;
  // the automatic picture shows in whatever part of [t0, t1) no placed cut takes
  let from = t0;
  for (const x of spans.sort((a, b) => a.s - b.s)) { if (x.s > from + 0.02) return true; from = Math.max(from, x.e); }
  return t1 - from > 0.02;
};
/* the style the planner picks a cut's layout with: over a background picture (and with 「画像の上では控えめに」 on), the layouts that
   fill the screen (busy) are rarely chosen. Same number of random draws; without a picture the style itself (so nothing changes) */
const CALM_BUSY = 0.12, calmCache = new WeakMap();
M.calmStyle = (st, project, li, t0, t1) => {
  if (!st || !project || !project.media || project.media.calm !== true || !M.backUnder(project, li, t0, t1)) return st;
  let c = calmCache.get(st);
  if (!c) {
    const lay = Object.assign({}, st.bias && st.bias.layout);
    for (const k of J.LAYOUT_ORDER || []) { const L = J.LAYOUTS[k]; if (L && L.busy) lay[k] = (lay[k] != null ? lay[k] : L.w ?? 1) * CALM_BUSY; }
    c = Object.assign(Object.create(st), { bias: Object.assign({}, st.bias, { layout: lay }) });
    calmCache.set(st, c);
  }
  return c;
};

/* every cut showing at time t (the front track's layers overlap; the back track shows one) */
M.cutsAt = (plan, t, track) => {
  if (track !== 'front') { const c = M.cutAt(plan, t, track); return c ? [c] : []; }
  const cs = plan && plan.media && plan.media.front && plan.media.front.cuts;
  return cs ? cs.filter(c => c.start <= t && t < c.end) : [];
};
/* the media cut showing at time t on a track (binary search, like J.cutAt) */
M.cutAt = (plan, t, track = 'back') => {
  const cs = plan && plan.media && plan.media[track] && plan.media[track].cuts;
  if (!cs || !cs.length) return null;
  let lo = 0, hi = cs.length - 1, ans = -1;
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (cs[mid].start <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1; }
  if (ans < 0) return null;
  const c = cs[ans];
  return t < c.end ? c : null;
};
})();
