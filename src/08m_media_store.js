/* ============================================================
   my-jizura (fork) — media layer: image store
   · the original bytes of every image are kept in this browser (IndexedDB 'jizura' / 'files' / 'media:<id>'),
     never in the project JSON or localStorage
   · decoded pictures live in J.mediaAssets (id → { id, type, name, w, h, source, scaled })
   · id = the first 12 hex digits of the file's SHA-256, so dropping the same picture twice keeps one copy
   ============================================================ */
(() => {
'use strict';
const M = (J.media = J.media || {});
J.mediaAssets = J.mediaAssets || new Map();
const MAX_EDGE = 4096;                     // decoded size cap (4K output + a little room for the slow zoom)
const IMG_EXT = /\.(png|jpe?g|webp|gif|bmp|avif)$/i;

/* ---------- IndexedDB (same database / store as the song and imported fonts in 10_audio.js) ---------- */
let dbp = null;
const db = () => dbp || (dbp = new Promise((res, rej) => {
  if (typeof indexedDB === 'undefined') return rej(new Error('no IndexedDB'));
  const r = indexedDB.open('jizura', 1);
  r.onupgradeneeded = () => { if (!r.result.objectStoreNames.contains('files')) r.result.createObjectStore('files'); };
  r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
}));
const tx = async (mode, fn) => {
  const d = await db();
  return new Promise((res, rej) => { const t = d.transaction('files', mode); const q = fn(t.objectStore('files')); t.oncomplete = () => res(q && q.result); t.onerror = () => rej(t.error); t.onabort = () => rej(t.error); });
};
const idbPut = (id, rec) => tx('readwrite', s => s.put(rec, 'media:' + id));
const idbGet = id => tx('readonly', s => s.get('media:' + id));
const idbDel = id => tx('readwrite', s => s.delete('media:' + id));

/* ---------- hashing ---------- */
async function hashId(buf) {
  try {
    if (crypto && crypto.subtle) {
      const d = new Uint8Array(await crypto.subtle.digest('SHA-256', buf));
      return Array.from(d.slice(0, 6), b => b.toString(16).padStart(2, '0')).join('');
    }
  } catch (e) {}
  // no WebCrypto (very old browsers): FNV-1a over the bytes + length
  const u = new Uint8Array(buf); let h = 2166136261 >>> 0, g = 0x9e3779b9;
  for (let i = 0; i < u.length; i++) { h = Math.imul(h ^ u[i], 16777619) >>> 0; if ((i & 1023) === 0) g = Math.imul(g ^ h, 2246822519) >>> 0; }
  return (h.toString(16).padStart(8, '0') + (g ^ u.length).toString(16).padStart(8, '0')).slice(0, 12);
}

/* ---------- decoding ---------- */
async function decode(blob) {
  const bmp = await createImageBitmap(blob);
  const w = bmp.width, h = bmp.height, k = Math.min(1, MAX_EDGE / Math.max(w, h));
  if (k >= 1) return { source: bmp, w, h };
  // very large pictures are scaled down once (keeps memory and every-frame drawing cheap)
  const c = document.createElement('canvas'); c.width = Math.round(w * k); c.height = Math.round(h * k);
  const x = c.getContext('2d'); x.imageSmoothingQuality = 'high'; x.drawImage(bmp, 0, 0, c.width, c.height);
  try { bmp.close(); } catch (e) {}
  return { source: c, w, h };
}
function keep(id, meta, dec) {
  const old = J.mediaAssets.get(id);
  if (old) release(old);
  const a = { id, type: 'image', name: meta.name, w: dec.w, h: dec.h, source: dec.source, sw: dec.source.width, sh: dec.source.height, scaled: new Map() };
  J.mediaAssets.set(id, a);
  return a;
}
function release(a) {
  if (a.type === 'video') { M.releaseVideo(a); return; }
  try { if (a.source && a.source.close) a.source.close(); } catch (e) {} a.scaled && a.scaled.clear();
}
const MAX_VIDEO = 500 * 1048576;           // per clip (they are kept whole in this browser)

M.isImageFile = f => !!f && (/^image\//.test(f.type || '') || IMG_EXT.test(f.name || ''));

/* add picture / video files → [{ id, name, type, w, h, size, duration? }] (already known ones are skipped);
   errors: [{ name, reason: 'type' | 'decode' | 'video' | 'size' }] */
M.addFiles = async (files, known = []) => {
  const added = [], errors = [], ids = new Set(known.map(a => a.id));
  for (const f of Array.from(files || [])) {
    const isVideo = M.isVideoFile && M.isVideoFile(f);
    if (!isVideo && !M.isImageFile(f)) { errors.push({ name: f && f.name, reason: 'type' }); continue; }
    if (isVideo && f.size > MAX_VIDEO) { errors.push({ name: f.name, reason: 'size' }); continue; }
    try {
      const buf = await f.arrayBuffer();
      const id = await hashId(buf);
      if (ids.has(id) && J.mediaAssets.has(id)) continue;
      if (isVideo) {
        const type = f.type || 'video/mp4';
        let a;
        try { a = await M.videoAsset(id, { name: String(f.name || id).slice(0, 160) }, new Blob([buf], { type })); }
        catch (e) { console.warn('media: cannot play', f.name, e); errors.push({ name: f.name, reason: 'video' }); continue; }
        const old = J.mediaAssets.get(id); if (old) release(old);
        J.mediaAssets.set(id, a);
        const meta = { id, name: a.name, type: 'video', w: a.w, h: a.h, size: buf.byteLength, duration: +a.duration.toFixed(3) };
        let stored = true;
        try { await idbPut(id, { name: meta.name, type, data: buf }); } catch (e) { stored = false; console.warn('media: could not keep', meta.name, e); }
        if (!ids.has(id)) { ids.add(id); added.push(Object.assign(meta, stored ? {} : { unsaved: true })); }
        continue;
      }
      const type = f.type || 'image/*';
      const dec = await decode(new Blob([buf], { type }));
      const meta = { id, name: String(f.name || id).slice(0, 160), type: 'image', w: dec.w, h: dec.h, size: buf.byteLength };
      keep(id, meta, dec);
      let stored = true;
      try { await idbPut(id, { name: meta.name, type, data: buf }); } catch (e) { stored = false; console.warn('media: could not keep', meta.name, e); }
      if (!ids.has(id)) { ids.add(id); added.push(Object.assign(meta, stored ? {} : { unsaved: true })); }
    } catch (e) {
      console.warn('media: could not read', f && f.name, e);
      errors.push({ name: f && f.name, reason: 'decode' });
    }
  }
  return { added, errors };
};

/* load the pictures of a project from this browser → { loaded, missing: [names] } */
M.restore = async project => {
  const list = (project && project.media && project.media.assets) || [];
  let loaded = 0; const missing = [];
  for (const meta of list) {
    if (J.mediaAssets.has(meta.id)) { loaded++; continue; }
    try {
      const rec = await idbGet(meta.id);
      if (!rec || !rec.data) { missing.push(meta.name); continue; }
      if (meta.type === 'video') J.mediaAssets.set(meta.id, await M.videoAsset(meta.id, meta, new Blob([rec.data], { type: rec.type || 'video/mp4' })));
      else keep(meta.id, meta, await decode(new Blob([rec.data], { type: rec.type || '' })));
      loaded++;
    } catch (e) { console.warn('media: could not restore', meta.name, e); missing.push(meta.name); }
  }
  return { loaded, missing };
};

M.remove = async id => {
  const a = J.mediaAssets.get(id);
  if (a) { release(a); J.mediaAssets.delete(id); }
  try { await idbDel(id); } catch (e) {}
};

/* a copy of the picture no larger than needed for (needW × needH) device pixels — made once per size bucket
   (drawing a 4000px photo every frame for a 1280px preview is the slow part) */
M.sourceFor = (a, needW, needH) => {
  if (!a || !a.source) return null;
  const k = Math.max(needW / a.sw, needH / a.sh);
  if (!(k > 0) || k > 0.66) return a.source;
  const bw = Math.min(a.sw, Math.ceil(a.sw * k / 256 + 0.5) * 256);
  const key = bw;
  let c = a.scaled.get(key);
  if (c) return c;
  c = document.createElement('canvas'); c.width = bw; c.height = Math.max(1, Math.round(a.sh * bw / a.sw));
  const x = c.getContext('2d'); x.imageSmoothingQuality = 'high'; x.drawImage(a.source, 0, 0, c.width, c.height);
  if (a.scaled.size >= 3) a.scaled.delete(a.scaled.keys().next().value);
  a.scaled.set(key, c);
  return c;
};

/* tests / embedding: register a picture that is not stored (e.g. a generated canvas) */
M.registerSource = (id, source, name = id) => keep(id, { name }, { source, w: source.width, h: source.height });
})();
