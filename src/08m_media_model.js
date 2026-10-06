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
M.TYPES = ['image', 'video'];
M.FIT = ['cover', 'contain'];
// 登場・退場 (when no picture touches this one), 動き, 加工 (Phase 3)
M.ENTER = ['auto', 'cut', 'fade', 'slide', 'zoom', 'wipe'];
M.HOLD = ['auto', 'still', 'kenburns', 'pan', 'push', 'drift', 'beatPulse'];
M.EXIT = ['auto', 'cut', 'fade', 'slide', 'zoom', 'wipe'];
M.TREAT = ['none', 'mono', 'sepia', 'blur', 'duotone', 'match'];
// つなぎ (one picture to the next): a cross-fade, a hard cut, a mix of the lyric transitions below (seeded), or one of them
M.JOIN = ['fade', 'cut', 'mix'];
M.TRANS_KEYS = ['wipe', 'diagonalWipe', 'clockWipe', 'irisOpen', 'pushSlide', 'cover', 'uncover', 'zoomThrough', 'doorsOpen', 'blinds',
  'whipPan', 'inkBlob', 'flashCross', 'pixelate', 'sliceShift', 'blockDissolve'];
M.SCRIM = ['off', 'auto', 'always'];        // 文字の下の暗幕: auto = only where the picture makes the lyrics hard to read
M.BLEND = ['normal', 'multiply', 'screen', 'overlay'];
M.LYRIC_BG = ['off', 'over'];             // the per-line background graphic (J.BG) where a background image shows
M.AUTO = ['off', 'perLine'];
M.ORDER = ['sequential', 'random'];
// how a video clip shorter than its cut fills it (AI clips are 5–10 s, a cut can be a whole verse):
//   loop: from the start again (with a short cross-fade at the seam in preview and export) · pingpong: forwards, then backwards ·
//   hold: stop on the last frame · beat: back to the start on every bar (N beats) of the song, looping inside a long bar
M.EXTEND = ['loop', 'pingpong', 'hold', 'beat'];
M.RATES = [0.5, 0.75, 1, 1.25, 1.5, 2];
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
    back: { mode: 'perLine', order: 'sequential', seed: 1, fit: 'cover', hold: 'kenburns', enter: 'fade', exit: 'fade', trans: 'fade', treat: 'none', video: { extend: 'loop', rate: 1, beats: 4 } },
    front: { mode: 'off', order: 'sequential', seed: 1, fit: 'contain', hold: 'still', enter: 'fade', exit: 'fade', trans: 'fade', treat: 'none', video: { extend: 'loop', rate: 1, beats: 4 } },
  },
  lyricBg: 'off',
  scrim: { mode: 'auto', amount: 0.55 },
  text: M.textDefaults ? M.textDefaults() : { interludeTitle: 'show', lines: {} },   // lyric placement / colour by hand (08m_media_text.js)
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
    treat: pick(c.treat, ['auto'].concat(M.TREAT), 'auto'), trans: join(c.trans, 'auto'),
  };
  if (c.seed != null) o.seed = int(c.seed, 0, 2 ** 31 - 1, 0);
  // 配置 (Phase 3b): placed by hand instead of filling the frame — the centre as an offset from the frame centre (fractions of the
  // frame, ±0.5 = the edge; beyond it partly outside), the width as a fraction of the frame width (height by the picture), degrees
  if (isObj(c.rect)) o.rect = { x: num(c.rect.x, -1, 1, 0), y: num(c.rect.y, -1, 1, 0), w: num(c.rect.w, 0.02, 4, 1), rot: num(c.rect.rot, -180, 180, 0) };
  // クロマキー (Phase 3b-2, 08m_media_chroma.js): the key colour ('auto' = round the picture's edge), how close counts as it (tol),
  // the soft edge (soft) and how much of its tint is taken out of what stays (spill) — distances in YCbCr colour
  if (isObj(c.chroma)) o.chroma = { color: /^#[0-9a-f]{6}$/i.test(c.chroma.color) ? c.chroma.color.toLowerCase() : 'auto',
    tol: num(c.chroma.tol, 0, 0.6, 0.1), soft: num(c.chroma.soft, 0, 0.6, 0.08), spill: num(c.chroma.spill, 0, 1, 0.6) };
  if (isObj(c.video)) o.video = video(c.video, null);   // per-cut clip settings (no editor yet; Phase 3)
  return o;
}
/* video clip settings: start / end inside the clip (s), how it fills the cut, speed, bar length in beats; null d = keep only what is set */
function video(v, d) {
  v = isObj(v) ? v : {};
  const o = {};
  if (v.start != null || d) o.start = num(v.start, 0, 86400, 0);
  if (v.end != null) { const e = num(v.end, 0, 86400, null); if (e != null) o.end = e; }
  if (v.extend != null || d) o.extend = pick(v.extend, M.EXTEND, d ? d.extend : 'loop');
  if (v.rate != null || d) o.rate = M.RATES.includes(+v.rate) ? +v.rate : (d ? d.rate : 1);
  if (v.beats != null || d) o.beats = [1, 2, 4, 8, 16].includes(+v.beats) ? +v.beats : (d ? d.beats : 4);
  return o;
}
/* つなぎ: 'auto' (cuts only), fade / cut / mix, or a transition key (checked against J.TRANS when the plan is made) */
function join(v, d) { return v === 'auto' || M.JOIN.includes(v) || M.TRANS_KEYS.includes(v) ? v : d; }
function track(t, d) {
  t = isObj(t) ? t : {};
  return {
    cuts: (Array.isArray(t.cuts) ? t.cuts : []).slice(0, M.MAX_CUTS).map((c, i) => cut(c, i)).filter(Boolean),
    opacity: num(t.opacity, 0, 1, d.opacity), blend: pick(t.blend, M.BLEND, d.blend), dim: num(t.dim, 0, 0.9, d.dim),
  };
}
function auto(a, d) {
  a = isObj(a) ? a : {};
  const no = l => l.filter(k => k !== 'auto');
  return { mode: pick(a.mode, M.AUTO, d.mode), order: pick(a.order, M.ORDER, d.order), seed: int(a.seed, 0, 2 ** 31 - 1, d.seed),
    fit: pick(a.fit, M.FIT, d.fit), hold: pick(a.hold, no(M.HOLD), d.hold), enter: pick(a.enter, no(M.ENTER), d.enter), exit: pick(a.exit, no(M.EXIT), d.exit),
    trans: join(a.trans === 'auto' ? null : a.trans, d.trans), treat: pick(a.treat, M.TREAT, d.treat), video: video(a.video, d.video) };
}

/* untrusted input → a complete, valid project.media */
M.normalize = m => {
  const d = M.defaults();
  if (!isObj(m)) return d;
  const seen = new Set(), assets = [];
  for (const a of (Array.isArray(m.assets) ? m.assets : []).slice(0, M.MAX_ASSETS)) { const o = asset(a); if (o && !seen.has(o.id)) { seen.add(o.id); assets.push(o); } }
  const tr = isObj(m.tracks) ? m.tracks : {}, af = isObj(m.autoFill) ? m.autoFill : {};
  const sc = isObj(m.scrim) ? m.scrim : {};
  const out = { version: 1, assets, tracks: {}, autoFill: {}, lyricBg: pick(m.lyricBg, M.LYRIC_BG, d.lyricBg),
    scrim: { mode: pick(sc.mode, M.SCRIM, d.scrim.mode), amount: num(sc.amount, 0, 0.9, d.scrim.amount) },
    text: M.normalizeText ? M.normalizeText(m.text) : d.text };
  for (const k of M.TRACKS) { out.tracks[k] = track(tr[k], d.tracks[k]); out.autoFill[k] = auto(af[k], d.autoFill[k]); }
  // a cut may only point at an asset of this project ('' = deliberately none); cuts of a picture that is gone are dropped
  for (const k of M.TRACKS) out.tracks[k].cuts = out.tracks[k].cuts.filter(c => !c.assetId || seen.has(c.assetId));
  return out;
};

M.assetById = (project, id) => ((project && project.media && project.media.assets) || []).find(a => a.id === id) || null;
})();
