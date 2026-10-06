/* ============================================================
   my-jizura (fork) — 素材込みファイル .jizura.zip (Phase 4-1)
   · 「素材込みで保存」: project.json + the original bytes of every picture / clip (assets/<id>.<ext>), the imported fonts
     (fonts/<key>.bin) and the song (song/<name>), in a plain ZIP (no compression, J.ZipWriter from 11_export.js)
   · 「開く」 takes a .zip too (12_ui.js: J.mediaBundle.unpack(f) instead of f.text()): the files go into this browser's
     store first (IndexedDB, as if they had been added here), then the project opens as a .jizura.json would — so the
     pictures, fonts and song come back through the usual restore. A picture whose bytes do not match its id is left out.
   · bundle.json lists what is inside; what could not be included (a picture missing in this browser, a font of the PC)
     is reported when saving, and the media panel reports what is still missing after opening
   ============================================================ */
(() => {
'use strict';
const M = J.media;
if (!M) return;
const JA = /^ja/.test(document.documentElement.lang || 'ja');
const L = (ja, en) => (JA ? ja : en);
const $ = id => document.getElementById(id);
const B = (J.mediaBundle = {});
const enc = s => new TextEncoder().encode(s);
const EXT = { 'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp', 'image/gif': '.gif', 'image/bmp': '.bmp', 'image/avif': '.avif',
  'video/mp4': '.mp4', 'video/webm': '.webm', 'video/quicktime': '.mov', 'video/ogg': '.ogv' };
const TYPE = Object.fromEntries(Object.entries(EXT).map(([t, e]) => [e, t]));
Object.assign(TYPE, { '.jpeg': 'image/jpeg', '.m4v': 'video/mp4' });
const extOf = (name, type) => EXT[type] || ((/\.[a-z0-9]{1,5}$/i.exec(name || '') || [''])[0].toLowerCase()) || '.bin';
const safeName = s => String(s || 'song').replace(/[\\/:*?"<>|\u0000-\u001f]+/g, '_').slice(0, 120) || 'song';
let busy = 0;
B.busy = () => busy > 0;
B.isBundle = f => !!f && (/\.zip$/i.test(f.name || '') || /zip/.test(f.type || ''));

/* ---------- write ---------- */
/* → { blob, assets, fonts, song, missing: [names not included], pcFonts: [labels of fonts installed on the PC] } */
B.pack = async (project, version) => {
  const zip = new J.ZipWriter(), m = (project && project.media) || { assets: [] };
  const man = { format: 'jizura-bundle', version: 1, assets: [], fonts: [], song: null }, missing = [], pcFonts = [];
  for (const a of m.assets || []) {
    const rec = await M.storedFile(a.id);
    if (!rec) { missing.push(a.name || a.id); continue; }
    const file = 'assets/' + a.id + extOf(rec.name || a.name, rec.type);
    zip.add(file, new Uint8Array(rec.data));
    man.assets.push({ id: a.id, name: a.name, type: rec.type || '', file });
  }
  for (const uf of project.userFonts || []) {
    if (!J.SAFE_FONT_KEY.test(uf.key)) { pcFonts.push(uf.label || uf.family || uf.key); continue; }   // a font of the PC: by name only
    const buf = J.loadFontData ? await J.loadFontData(uf.key) : null;
    if (!buf) { missing.push(uf.label || uf.key); continue; }
    const file = 'fonts/' + uf.key + '.bin';
    zip.add(file, new Uint8Array(buf)); man.fonts.push({ key: uf.key, file });
  }
  // the song of this project (a new project keeps the song that is loaded, without its name: that one then)
  const loaded = !project.audioName && J.ui && J.ui.project === project && !!J.ui.audio;
  if ((project.audioName || loaded) && J.loadSong) {
    const f = await J.loadSong();
    if (f && (loaded || f.name === project.audioName)) {
      const file = 'song/' + safeName(f.name);
      zip.add(file, new Uint8Array(await f.arrayBuffer())); man.song = { name: f.name, type: f.type || '', file };
    } else missing.push(project.audioName || L('曲', 'the song'));
  }
  zip.add('bundle.json', enc(JSON.stringify(man, null, 1)));
  zip.add('project.json', enc(JSON.stringify(Object.assign({}, project, { appVersion: version || project.appVersion }), null, 1)));
  return { blob: zip.finish(), assets: man.assets.length, fonts: man.fonts.length, song: !!man.song, missing, pcFonts };
};

/* ---------- read (stored entries, and deflated ones where the browser can inflate) ---------- */
async function entries(buf) {
  const u = new Uint8Array(buf), dv = new DataView(buf), out = new Map();
  let eocd = -1;
  for (let i = u.length - 22; i >= Math.max(0, u.length - 65557); i--) if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  if (eocd < 0) throw new Error('not a zip');
  let p = dv.getUint32(eocd + 16, true);
  const n = dv.getUint16(eocd + 10, true), dec = new TextDecoder();
  for (let k = 0; k < n && p + 46 <= u.length; k++) {
    if (dv.getUint32(p, true) !== 0x02014b50) break;
    const method = dv.getUint16(p + 10, true), csize = dv.getUint32(p + 20, true), nl = dv.getUint16(p + 28, true);
    const xl = dv.getUint16(p + 30, true), cl = dv.getUint16(p + 32, true), lo = dv.getUint32(p + 42, true);
    const name = dec.decode(u.subarray(p + 46, p + 46 + nl));
    p += 46 + nl + xl + cl;
    if (name.endsWith('/') || lo + 30 > u.length || dv.getUint32(lo, true) !== 0x04034b50) continue;
    const start = lo + 30 + dv.getUint16(lo + 26, true) + dv.getUint16(lo + 28, true);
    if (start + csize > u.length) continue;
    out.set(name.replace(/^.*?(?=(project|bundle)\.json$|assets\/|fonts\/|song\/)/, ''), { method, data: u.subarray(start, start + csize) });
  }
  return out;
}
async function bytes(e) {
  if (!e) return null;
  if (e.method === 0) return e.data;
  if (e.method === 8 && typeof DecompressionStream === 'function') {
    return new Uint8Array(await new Response(new Blob([e.data]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).arrayBuffer());
  }
  throw new Error('compressed');
}
const copy = u8 => u8.buffer.slice(u8.byteOffset, u8.byteOffset + u8.byteLength);

/* the project text of a .jizura.zip; its pictures, fonts and song are put into this browser first */
B.unpack = async file => {
  busy++;
  try { return await unpack(file); }
  catch (e) {   // 12_ui.js says it could not open the project; this says why
    if (J.uiApi && J.uiApi.toast) setTimeout(() => J.uiApi.toast(e && e.message || String(e)), 0);
    throw e;
  } finally { busy--; }
};
async function unpack(file) {
  let all;
  try { all = await entries(await file.arrayBuffer()); }
  catch (e) { throw new Error(L('ZIP を読み込めませんでした', 'Could not read the ZIP')); }
  let text;
  try { text = new TextDecoder().decode(await bytes(all.get('project.json'))); } catch (e) { text = null; }
  if (!text) throw new Error(L('素材込みファイルではありません（project.json がありません）', 'Not a bundle (no project.json)'));
  let man = {};
  try { man = JSON.parse(new TextDecoder().decode(await bytes(all.get('bundle.json')))) || {}; } catch (e) { man = {}; }
  const listed = new Map((Array.isArray(man.assets) ? man.assets : []).filter(a => a && M.ID.test(a.id)).map(a => [a.id, a]));
  const r = { assets: 0, fonts: 0, song: false, bad: [] };
  for (const [name, e] of all) {
    const am = /^assets\/([\w-]{1,32})(\.[a-z0-9]{1,5})?$/i.exec(name);
    if (am) {
      const id = am[1], info = listed.get(id) || {};
      try {
        const u8 = await bytes(e);
        if (await M.hashBytes(copy(u8)) !== id) { r.bad.push(info.name || name); continue; }   // the bytes are not that picture
        const type = String(info.type || TYPE[(am[2] || '').toLowerCase()] || '').slice(0, 60);
        if (!J.mediaAssets.has(id)) await M.putStoredFile(id, { name: String(info.name || id).slice(0, 160), type, data: copy(u8) });
        r.assets++;
      } catch (err) { console.warn('media bundle: asset', name, err); r.bad.push(info.name || name); }
      continue;
    }
    const fm = /^fonts\/(user_[A-Za-z0-9_-]{1,80})\.bin$/.exec(name);
    if (fm && J.SAFE_FONT_KEY.test(fm[1]) && J.saveFontData) {
      try { await J.saveFontData(fm[1], copy(await bytes(e))); r.fonts++; } catch (err) { console.warn('media bundle: font', name, err); }
      continue;
    }
    if (/^song\//.test(name) && J.uiApi && J.uiApi.loadAudioFile) {
      try {
        const s = man.song || {};
        const f = new File([copy(await bytes(e))], String(s.name || name.slice(5)).slice(0, 200), { type: String(s.type || '').slice(0, 60) });
        r.song = true;
        // after 12_ui.js has opened the project (the rest of its 「開く」 handler runs before this)
        setTimeout(() => { Promise.resolve(J.uiApi.loadAudioFile(f)).catch(err => console.warn('media bundle: song', err)).finally(() => busy--); }, 0);
        busy++;
      } catch (err) { console.warn('media bundle: song', name, err); }
    }
  }
  B.last = r;
  setTimeout(() => {
    const parts = [L(`画像・動画 ${r.assets} 件`, `${r.assets} picture(s) / clip(s)`)];
    if (r.fonts) parts.push(L(`フォント ${r.fonts} 件`, `${r.fonts} font(s)`));
    if (r.song) parts.push(L('曲', 'the song'));
    const bad = r.bad.length ? L(`。中身が合わないため ${r.bad.length} 件を読み込みませんでした（${r.bad.slice(0, 3).join('、')}）`, `. ${r.bad.length} file(s) did not match and were left out (${r.bad.slice(0, 3).join(', ')})`) : '';
    if (J.uiApi && J.uiApi.toast) J.uiApi.toast(L(`素材込みファイルを開きました（${parts.join('・')}）`, `Opened the bundle (${parts.join(', ')})`) + bad);
  }, 0);
  return text;
}

/* ---------- 「素材込みで保存」 ---------- */
function baseName(p) {
  const k = J.keyMode ? J.keyMode(p) : '';
  return ((p.title || 'jizura').replace(/[\\/:*?"<>|]+/g, '_').slice(0, 60) || 'jizura') + (k ? (k === 'green' ? '_greenback' : '_blackback') : '');
}
B.save = async (project, toast) => {
  const r = await B.pack(project, '@VERSION@');
  await J.saveFile(baseName(project) + '.jizura.zip', r.blob);
  const notes = [];
  if (r.missing.length) notes.push(L(`このブラウザに無いため入っていないもの：${r.missing.slice(0, 4).join('、')}${r.missing.length > 4 ? ' ほか' : ''}`, `Not included (not in this browser): ${r.missing.slice(0, 4).join(', ')}`));
  if (r.pcFonts.length) notes.push(L(`PC のフォント（${r.pcFonts.join('・')}）は名前だけです。開く PC にも入れてください`, `PC fonts (${r.pcFonts.join(', ')}) are by name only — install them on the other PC too`));
  if (toast) toast(L(`素材込みで保存しました（画像・動画 ${r.assets} 件${r.fonts ? `・フォント ${r.fonts} 件` : ''}${r.song ? '・曲' : ''}）`, `Saved with media (${r.assets} picture(s) / clip(s)${r.fonts ? `, ${r.fonts} font(s)` : ''}${r.song ? ', the song' : ''})`) + (notes.length ? '。' + notes.join('。') : ''));
  return r;
};

B.init = api => {
  const save = $('btnSave'), open = $('fileProject');
  if (open && !/zip/.test(open.accept)) open.accept += ',.zip,application/zip';
  if (open && open.parentNode && open.parentNode.title) open.parentNode.title = L('保存したプロジェクト（.json / 素材込みの .zip）を開く', 'Open a saved project (.json, or a .zip with its media)');
  if (!save || $('btnSaveBundle')) return;
  const b = document.createElement('button');
  b.id = 'btnSaveBundle'; b.textContent = L('素材込みで保存', 'Save with media');
  b.title = L('プロジェクトと画像・動画・読み込んだフォント・曲を 1 つの .zip に保存（別の PC でも「開く」で同じ状態に戻せます）', 'Save the project with its pictures, clips, imported fonts and song in one .zip (「開く」 on another PC brings everything back)');
  save.insertAdjacentElement('afterend', b);
  b.addEventListener('click', async () => {
    b.disabled = true;
    try { await B.save(api.S.project, api.toast); }
    catch (e) { console.warn('media bundle: save', e); api.toast(L('素材込みで保存できませんでした：', 'Could not save with media: ') + (e && e.message || e)); }
    finally { b.disabled = false; }
  });
};
})();
