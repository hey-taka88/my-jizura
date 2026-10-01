/* ============================================================
   my-jizura (fork) — media layer: project.media → plan.media
   Deterministic: the same project + lyrics timing always gives the same media cuts.
   plan.media = { lyricBg, back: { cuts, opacity, blend, dim }, front: { … } }
   cut = { index, assetId, start, end, dur, line, fit, enter, hold, exit, inDur, outDur, opacity, seed, kb }
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

function resolveTrack(m, k, plan) {
  const T = m.tracks[k], A = m.autoFill[k], D = Math.max(0.1, plan.duration || 0);
  const ids = m.assets.map(a => a.id);
  const known = new Set(ids);
  const out = { cuts: [], opacity: T.opacity, blend: T.blend, dim: T.dim };
  const byLine = new Map(), timed = [];
  for (const c of T.cuts) { if (c.lineRef) byLine.set(c.lineRef.line, c); else timed.push(c); }
  const next = ids.length ? sequence(ids, A) : null;
  const lines = (plan.lines || []).slice().sort((a, b) => a.start - b.start);
  let segs = [], n = 0;
  if (!lines.length) {
    if (A.mode === 'perLine' && next) segs.push({ assetId: next(0), start: 0, end: D, line: -1, src: null });
  } else {
    lines.forEach((ln, j) => {
      const start = j === 0 ? 0 : ln.start;                 // the first image also covers the intro / title card
      const end = j + 1 < lines.length ? lines[j + 1].start : D;
      if (!(end - start > 0.02)) return;
      const ov = byLine.get(ln.index);
      let id = null;
      if (ov) id = ov.assetId && known.has(ov.assetId) ? ov.assetId : null;     // a line set to 「なし」 stays empty
      else if (A.mode === 'perLine' && next) id = next(n++);
      if (id) segs.push({ assetId: id, start, end, line: ln.index, src: ov || null });
    });
  }
  // cuts placed at a time (no editor for them yet): end = the next cut's start
  for (const c of timed) if (c.assetId && known.has(c.assetId) && c.start < D) segs.push({ assetId: c.assetId, start: c.start, end: c.end, line: -1, src: c });
  segs.sort((a, b) => a.start - b.start);
  segs.forEach((s, i) => { if (s.end == null) s.end = i + 1 < segs.length ? segs[i + 1].start : D; s.end = Math.min(s.end, D); });
  segs = segs.filter(s => s.end - s.start > 0.02);
  // one automatic image over several lines in a row stays one cut (its slow move does not restart)
  const merged = [];
  for (const s of segs) {
    const p = merged[merged.length - 1];
    if (p && !p.src && !s.src && p.assetId === s.assetId && Math.abs(p.end - s.start) < NEAR) p.end = s.end;
    else merged.push(s);
  }
  merged.forEach((s, i) => {
    const src = s.src, nxt = merged[i + 1];
    const dur = s.end - s.start;
    const own = (key, dflt) => (src && src[key] && src[key] !== 'auto' ? src[key] : dflt);
    const seed = src && src.seed != null ? src.seed : J.h(A.seed, J.sid(s.assetId), Math.round(s.start * 100));
    const enter = own('enter', 'fade');
    const exit = own('exit', nxt && Math.abs(nxt.start - s.end) < NEAR ? 'cut' : 'fade');   // the next image fades in over this one
    const r = J.rng(J.h(seed, 0x6b62));
    const zoomIn = r.chance(0.6), z = r.range(0.06, 0.11);
    out.cuts.push({
      index: i, assetId: s.assetId, start: s.start, end: s.end, dur, line: s.line,
      fit: own('fit', A.fit), enter, hold: own('hold', A.hold), exit,
      inDur: enter === 'fade' ? Math.min(0.6, dur * 0.3) : 0,
      outDur: exit === 'fade' ? Math.min(0.45, dur * 0.25) : 0,
      opacity: src ? src.opacity : 1, seed,
      // ゆっくり寄る / 引く: scale s0 → s1 and a small drift (fractions of the frame), kept inside the picture
      kb: { s0: zoomIn ? 1 : 1 + z, s1: zoomIn ? 1 + z : 1, x0: r.range(-0.03, 0.03), y0: r.range(-0.02, 0.02), x1: r.range(-0.03, 0.03), y1: r.range(-0.02, 0.02) },
    });
  });
  return out;
}

M.resolve = (project, plan) => {
  if (!project || !project.media) return null;
  const m = M.normalize(project.media);          // cheap, and plans built from test / preview projects get the same checks
  const out = { lyricBg: m.lyricBg === 'over' ? 'over' : 'off' };
  for (const k of M.TRACKS) out[k] = resolveTrack(m, k, plan);
  return out;
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
