/* ============================================================
   my-jizura (fork) — media layer: project.media schema + validation
   project.media holds metadata only; the image bytes live in IndexedDB ('files' / 'media:<id>', see 08m_media_store.js).
   Project files are untrusted: everything read from them goes through J.media.normalize().
   ============================================================ */
(() => {
'use strict';
const M = (J.media = J.media || {});

M.ID = /^[\w-]{1,32}$/;
M.TRACKS = ['back', 'front'];
M.TYPES = ['image', 'video'];             // 'video' is accepted now so Phase 2 projects open here; only images are drawn yet
M.FIT = ['cover', 'contain'];
M.ENTER = ['auto', 'cut', 'fade'];
M.HOLD = ['auto', 'still', 'kenburns'];
M.EXIT = ['auto', 'cut', 'fade'];
M.BLEND = ['normal', 'multiply', 'screen', 'overlay'];
M.LYRIC_BG = ['off', 'over'];             // the per-line background graphic (J.BG) where a background image shows
M.AUTO = ['off', 'perLine'];
M.ORDER = ['sequential', 'random'];
M.MAX_ASSETS = 500;
M.MAX_CUTS = 2000;

M.defaults = () => ({
  version: 1,
  assets: [],
  tracks: {
    back: { cuts: [], opacity: 1, blend: 'normal', dim: 0.25 },
    front: { cuts: [], opacity: 1, blend: 'normal', dim: 0 },
  },
  autoFill: {
    back: { mode: 'perLine', order: 'sequential', seed: 1, fit: 'cover', hold: 'kenburns' },
    front: { mode: 'off', order: 'sequential', seed: 1, fit: 'contain', hold: 'still' },
  },
  lyricBg: 'off',
});

const num = (v, lo, hi, d) => { const n = +v; return Number.isFinite(n) ? J.clamp(n, lo, hi) : d; };
const int = (v, lo, hi, d) => { const n = Math.round(+v); return Number.isFinite(n) ? J.clamp(n, lo, hi) : d; };
const pick = (v, list, d) => (list.includes(v) ? v : d);
const str = (v, n) => String(v == null ? '' : v).replace(/[\u0000-\u001f]/g, '').slice(0, n);
const isObj = v => !!v && typeof v === 'object' && !Array.isArray(v);

function asset(a) {
  if (!isObj(a) || !M.ID.test(a.id) || !M.TYPES.includes(a.type)) return null;
  const o = { id: a.id, name: str(a.name, 160) || a.id, type: a.type, w: int(a.w, 1, 32768, 1), h: int(a.h, 1, 32768, 1), size: int(a.size, 0, 2 ** 40, 0) };
  if (a.type === 'video') o.duration = num(a.duration, 0, 86400, 0);
  return o;
}
function cut(c, i) {
  if (!isObj(c)) return null;
  const lineRef = isObj(c.lineRef) && Number.isInteger(+c.lineRef.line) && +c.lineRef.line >= 0 ? { line: Math.min(+c.lineRef.line, 99999) } : null;
  const start = c.start == null ? null : num(c.start, 0, 86400, null);
  if (!lineRef && start == null) return null;                       // a cut is tied to a lyric line or to a time
  const o = {
    id: M.ID.test(c.id) ? c.id : 'c' + i,
    assetId: c.assetId === '' ? '' : (M.ID.test(c.assetId) ? c.assetId : ''),   // '' = no image here
    lineRef, start, end: c.end == null ? null : num(c.end, 0, 86400, null),
    fit: pick(c.fit, M.FIT.concat(['auto']), 'auto'),
    enter: pick(c.enter, M.ENTER, 'auto'), hold: pick(c.hold, M.HOLD, 'auto'), exit: pick(c.exit, M.EXIT, 'auto'),
    opacity: num(c.opacity, 0, 1, 1),
  };
  if (c.seed != null) o.seed = int(c.seed, 0, 2 ** 31 - 1, 0);
  return o;
}
function track(t, d) {
  t = isObj(t) ? t : {};
  return {
    cuts: (Array.isArray(t.cuts) ? t.cuts : []).slice(0, M.MAX_CUTS).map((c, i) => cut(c, i)).filter(Boolean),
    opacity: num(t.opacity, 0, 1, d.opacity), blend: pick(t.blend, M.BLEND, d.blend), dim: num(t.dim, 0, 0.9, d.dim),
  };
}
function auto(a, d) {
  a = isObj(a) ? a : {};
  return { mode: pick(a.mode, M.AUTO, d.mode), order: pick(a.order, M.ORDER, d.order), seed: int(a.seed, 0, 2 ** 31 - 1, d.seed),
    fit: pick(a.fit, M.FIT, d.fit), hold: pick(a.hold, M.HOLD.filter(k => k !== 'auto'), d.hold) };
}

/* untrusted input → a complete, valid project.media */
M.normalize = m => {
  const d = M.defaults();
  if (!isObj(m)) return d;
  const seen = new Set(), assets = [];
  for (const a of (Array.isArray(m.assets) ? m.assets : []).slice(0, M.MAX_ASSETS)) { const o = asset(a); if (o && !seen.has(o.id)) { seen.add(o.id); assets.push(o); } }
  const tr = isObj(m.tracks) ? m.tracks : {}, af = isObj(m.autoFill) ? m.autoFill : {};
  const out = { version: 1, assets, tracks: {}, autoFill: {}, lyricBg: pick(m.lyricBg, M.LYRIC_BG, d.lyricBg) };
  for (const k of M.TRACKS) { out.tracks[k] = track(tr[k], d.tracks[k]); out.autoFill[k] = auto(af[k], d.autoFill[k]); }
  // a cut may only point at an asset of this project ('' = deliberately none); cuts of a picture that is gone are dropped
  for (const k of M.TRACKS) out.tracks[k].cuts = out.tracks[k].cuts.filter(c => !c.assetId || seen.has(c.assetId));
  return out;
};

M.assetById = (project, id) => ((project && project.media && project.media.assets) || []).find(a => a.id === id) || null;
})();
