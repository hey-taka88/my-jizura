/* ============================================================
   my-jizura (fork) — media layer: 「ダンス動画を重ねる」 in the かんたん panel
   · pick a clip (or a PNG of a character): it goes over the lyrics for the whole song (a front cut of 11z_media_place.js),
     standing on the bottom of the frame, about as tall as the frame
   · its background is taken out by itself: a clip with transparency (WebM with alpha, a PNG) stays as it is, a green / blue screen
     gets クロマキー 'auto'; anything else is put over as it is (the key can be chosen by hand)
   · 位置 (左 / 中央 / 右), 大きさ, 背景, and 「歌詞を左右に分ける」 (the app's 中央を空ける); the frame over the preview moves it finely
   · the panel works on the last picture placed over the lyrics for the whole song or a time (any of them, also one placed in 詳細)
   11z_media_ui.js calls J.mediaEasy.init(api) and .onPlan(); nothing of the upstream files changes.
   ============================================================ */
(() => {
'use strict';
const M = J.media;
if (!M) return;
const JA = /^ja/.test(document.documentElement.lang || 'ja');
const L = (ja, en) => (JA ? ja : en);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
const $ = id => document.getElementById(id);
const r3 = x => Math.round(x * 1000) / 1000;
const POS = { left: -0.25, center: 0, right: 0.25 };
const SIZE = 0.9;                                    // the height of a new one, as a part of the frame's height
const KEY = { tol: 0.1, soft: 0.08, spill: 0.6 };
let api = null, S = null, sec = null, busy = false, uiKey = '';
const found = new Map();                             // asset id → what detect() found (for the note under 背景)

const CSS = `
.easy-dance h3 small { font-weight: 400; color: var(--muted); margin-left: 6px; font-size: 11px; }
.easy-dance .hint { font-size: 11px; color: var(--muted); margin: 6px 0 0; }
.easy-dance .dz-top { display: flex; gap: 6px; align-items: center; }
.easy-dance .dz-top .nm { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.easy-dance .dz-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 8px; }
.easy-dance .dz-grid .field { font-size: 11px; }
.easy-dance .seg { display: flex; gap: 4px; }
.easy-dance .seg button { flex: 1; padding: 6px 4px; }
.easy-dance .seg button[aria-pressed="true"] { border-color: var(--cyan, #3cc8e6); color: var(--text); box-shadow: 0 0 0 1px var(--cyan, #3cc8e6) inset; }
.easy-dance label.check { margin: 8px 0 0; }
.easy-dance .found { font-size: 11px; color: var(--muted); }
`;

const media = () => S.project.media;
const front = () => media().tracks.front;
// the one this panel works on: the last picture placed over the lyrics for a time of the song (not one chosen for a lyric line)
const dancer = () => front().cuts.filter(c => !c.lineRef).pop() || null;
const metaOf = c => (c ? M.assetById(S.project, c.assetId) : null);
const frameSize = () => (S.plan ? { W: S.plan.W, H: S.plan.H } : { W: 1920, H: 1080 });

/* ---------- what a picture's background is: transparent, a green / blue screen, or something else ---------- */
function edges(asset) {
  const src = asset && (asset.type === 'video' ? asset.thumb : asset.source);
  if (!src) return null;
  const c = document.createElement('canvas'); c.width = 32; c.height = 18;
  const x = c.getContext('2d', { willReadFrequently: true });
  x.drawImage(src, 0, 0, 32, 18);
  const d = x.getImageData(0, 0, 32, 18).data, px = [];
  const take = (u, v) => { const i = (v * 32 + u) * 4; px.push([d[i], d[i + 1], d[i + 2], d[i + 3]]); };
  for (let u = 0; u < 32; u++) take(u, 0);                                   // the top edge and both sides (the dancer stands on the bottom)
  for (let v = 1; v < 18; v++) { take(0, v); take(31, v); }
  return px;
}
function hueSat(r, g, b) {
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  let h = 0;
  if (d > 0) h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return { h: (h * 60 + 360) % 360, s: mx ? d / mx : 0, v: mx / 255 };
}
/* → { kind: 'alpha' | 'green' | 'blue' | 'plain', color } (never throws: an unreadable picture is 'plain') */
function detect(assetId) {
  if (found.has(assetId)) return found.get(assetId);
  let out = { kind: 'plain', color: null };
  try {
    const px = edges(J.mediaAssets.get(assetId));
    if (px && px.length) {
      if (px.filter(p => p[3] < 200).length >= px.length / 2) out = { kind: 'alpha', color: null };
      else {
        const med = k => px.map(p => p[k]).sort((a, b) => a - b)[px.length >> 1];
        const r = med(0), g = med(1), b = med(2), hs = hueSat(r, g, b);
        // most of the edge close to that colour (a screen, not a picture that happens to be green somewhere)
        const near = px.filter(p => Math.abs(p[0] - r) + Math.abs(p[1] - g) + Math.abs(p[2] - b) < 90).length >= px.length * 0.6;
        const col = '#' + [r, g, b].map(n => n.toString(16).padStart(2, '0')).join('');
        if (near && hs.s > 0.35 && hs.v > 0.2 && hs.h >= 75 && hs.h <= 170) out = { kind: 'green', color: col };
        else if (near && hs.s > 0.35 && hs.v > 0.2 && hs.h >= 190 && hs.h <= 260) out = { kind: 'blue', color: col };
      }
    }
  } catch (e) { console.warn('media: easy dance detect', e); }
  if (J.mediaAssets.has(assetId)) found.set(assetId, out);
  return out;
}
const foundText = k => ({ alpha: L('透過の動画（そのまま重ねます）', 'Has transparency (put over as it is)'),
  green: L('グリーンバック（自動で抜きます）', 'Green screen (taken out)'), blue: L('ブルーバック（自動で抜きます）', 'Blue screen (taken out)'),
  plain: L('背景を判定できませんでした', 'No screen colour found') })[k] || '';

/* ---------- where it stands ---------- */
// its height as a part of the frame's, and where it stands (from its rect: also after it was moved with the frame)
function sizeOf(c, meta) {
  const { W, H } = frameSize();
  return c && c.rect && meta ? c.rect.w * W * meta.h / (meta.w * H) : SIZE;
}
const posOf = c => (!c || !c.rect ? 'center' : c.rect.x < -0.08 ? 'left' : c.rect.x > 0.08 ? 'right' : 'center');
const bottomOf = (c, meta) => (c && c.rect ? c.rect.y + sizeOf(c, meta) / 2 : 0.5);
function rectFor(meta, pos, s, bottom, rot, x) {
  const { W, H } = frameSize();
  return { x: x != null ? x : POS[pos] || 0, y: r3(J.clamp(bottom - s / 2, -1, 1)), w: r3(J.clamp(s * H * meta.w / (meta.h * W), 0.02, 4)), rot: rot || 0 };
}
function commit(msg) { S.project.media = M.normalize(media()); api.replan(); if (msg) api.toast(msg); }
const cutNow = id => front().cuts.find(c => c.id === id) || null;

/* ---------- put a clip there (or swap the one there for it) ---------- */
function use(assetId) {
  const meta = M.assetById(S.project, assetId);
  if (!meta || !J.mediaPlace) return null;
  const d = detect(assetId);
  let c = dancer();
  const first = !c;
  if (c) {                                           // another clip in the same place: same position and height
    const om = metaOf(c), s = sizeOf(c, om), b = bottomOf(c, om);
    c.assetId = assetId;
    c.rect = rectFor(meta, posOf(c), s, b, c.rect ? c.rect.rot : 0, c.rect ? c.rect.x : null);
  } else {
    const id = J.mediaPlace.place(assetId);
    c = id && cutNow(id);
    if (!c) return null;
    c.rect = rectFor(meta, 'center', SIZE, 0.5, 0);
  }
  if (d.kind === 'green' || d.kind === 'blue') c.chroma = Object.assign({}, KEY, { color: 'auto' });
  else delete c.chroma;
  const msg = d.kind === 'alpha' ? L('透過の動画なので、そのまま歌詞の上に重ねました', 'It has transparency: put over the lyrics as it is')
    : d.kind === 'green' ? L('グリーンバックを抜いて、歌詞の上に重ねました', 'Green screen taken out, put over the lyrics')
    : d.kind === 'blue' ? L('ブルーバックを抜いて、歌詞の上に重ねました', 'Blue screen taken out, put over the lyrics')
    : L('背景の色を判定できなかったので、そのまま重ねました。「背景」で抜く色を選べます', 'No screen colour found: put over as it is. Choose a colour to take out under 「背景」');
  const id = c.id;
  commit(msg);
  J.mediaPlace.select(id);
  // the first one in the middle: the lyrics go to its sides (the app's 中央を空ける; it can be turned off right there)
  if (first && !S.project.centerFree) setCenter(true);
  return id;
}
async function add(files) {
  const f = files && files[0];
  if (!f || busy) return null;
  busy = true; render();
  try {
    const before = new Set(media().assets.map(a => a.id));
    const res = await J.mediaUI.addFiles([f]);
    const m = media(), name = String(f.name || '').slice(0, 160);
    let a = m.assets.find(x => !before.has(x.id)) || m.assets.find(x => x.name === name);
    // a clip already in the list under another name (nothing new was added): the id is the hash of its bytes
    if (!a && res && !res.added.length && !res.errors.length && M.hashBytes) { const id = await M.hashBytes(await f.arrayBuffer()); a = m.assets.find(x => x.id === id); }
    if (!a || !J.mediaAssets.has(a.id)) {
      const vbad = res && res.errors && res.errors.some(e => e.reason === 'video');
      api.toast(vbad ? L('この動画はこのブラウザで再生できませんでした。H.264 の MP4 か WebM に変換してください', 'This browser cannot play this clip. Convert it to H.264 MP4 or WebM.')
        : L('読み込めませんでした（動画か画像を選んでください）', 'Could not read it (choose a clip or a picture)'));
      return null;
    }
    return use(a.id);
  } catch (e) { console.warn('media: easy dance', e); api.toast(L('読み込めませんでした', 'Could not read it')); return null; }
  finally { busy = false; render(); }
}

/* ---------- the controls ---------- */
function set(o) {
  const c = dancer(), meta = metaOf(c);
  if (!c || !meta) return false;
  const s0 = sizeOf(c, meta), b = bottomOf(c, meta), rot = c.rect ? c.rect.rot : 0;
  if (o.pos != null && POS[o.pos] != null) c.rect = rectFor(meta, o.pos, s0, b, rot);
  if (o.size != null) { const s = J.clamp(+o.size || SIZE, 0.2, 1.6); c.rect = rectFor(meta, posOf(c), s, b, rot, c.rect ? c.rect.x : null); }
  if (o.key != null) {
    if (o.key === 'none') delete c.chroma;
    else if (o.key === 'auto' || /^#[0-9a-f]{6}$/i.test(o.key)) c.chroma = Object.assign({}, KEY, c.chroma, { color: o.key });
  }
  if (o.tol != null && c.chroma) c.chroma.tol = J.clamp(+o.tol, 0, 0.6);
  commit();
  return true;
}
function setCenter(on) {
  const el = $('eCenter');
  if (!el || el.checked === !!on) return;
  el.checked = !!on;
  el.dispatchEvent(new Event('change'));             // the app's own handler: 中央を空ける, replan, save, its message
}
function remove() {
  const c = dancer(); if (!c) return;
  front().cuts = front().cuts.filter(x => x !== c);
  commit(L('ダンス動画を外しました（素材は「画像・動画」に残っています）', 'Removed (the clip stays under 「画像・動画」)'));
}

function render() {
  if (!sec || !S) return;
  const c = dancer(), meta = metaOf(c), loaded = !!(c && J.mediaAssets.has(c.assetId));
  const key = JSON.stringify([c && c.id, c && c.assetId, !!(c && c.chroma), c && c.chroma && c.chroma.color, loaded, busy]);
  const body = sec.querySelector('.dz-body');
  if (key !== uiKey) {
    uiKey = key;
    const pick = (label, cls) => `<label class="file ${cls}">${label}<input type="file" class="dz-file" accept="video/*,.mp4,.m4v,.webm,.mov,image/png,image/webp,.png,.webp"></label>`;
    if (!c || !meta) {
      body.innerHTML = `${pick(busy ? L('読み込み中…', 'Loading…') : L('動画を選ぶ', 'Choose a clip'), 'primary')}
        <p class="hint">${L('歌詞の上に、曲の最初から最後まで重ねます。透過の WebM・グリーンバック／ブルーバックの動画は、背景を自動で抜きます。人物の PNG も使えます', 'It goes over the lyrics for the whole song. A WebM with transparency or a green / blue screen clip gets its background taken out by itself. A PNG of a character works too.')}</p>`;
    } else {
      const K = c.chroma, d = detect(c.assetId);
      body.innerHTML = `<div class="dz-top"><span class="nm" title="${esc(meta.name)}">${meta.type === 'video' ? '▶ ' : ''}${esc(meta.name)}</span>
          ${pick(L('差し替え', 'Replace'), 'ghost small')}
          <button class="ghost small dz-del" aria-label="${L('ダンス動画を外す', 'Remove the clip')}">✕</button></div>
        ${loaded ? '' : `<p class="hint">${L('この素材はまだ読み込まれていません（「画像・動画」で読み込み直してください）', 'Not loaded yet (add it again under 「画像・動画」)')}</p>`}
        <div class="dz-grid">
          <div class="field">${L('位置', 'Position')}<div class="seg">${['left', 'center', 'right'].map(p => `<button class="ghost small dz-pos" data-pos="${p}">${({ left: L('左', 'Left'), center: L('中央', 'Middle'), right: L('右', 'Right') })[p]}</button>`).join('')}</div></div>
          <label class="field">${L('大きさ', 'Size')} <span class="dz-sizev mono"></span><input type="range" class="dz-size" min="0.3" max="1.4" step="0.05"></label>
          <label class="field">${L('背景', 'Background')}<select class="dz-key"><option value="none">${L('抜かない', 'Keep')}</option><option value="auto">${L('背景の色を抜く（自動）', 'Take out the screen colour')}</option>${K && K.color !== 'auto' ? `<option value="${esc(K.color)}">${esc(K.color)}</option>` : ''}<option value="spoid">${L('スポイトで選ぶ…', 'Pick with the eyedropper…')}</option></select></label>
          ${K ? `<label class="field">${L('抜く範囲', 'Tolerance')}<input type="range" class="dz-tol" min="0" max="0.4" step="0.01"></label>` : '<span></span>'}
        </div>
        <p class="found">${loaded ? L('判定：', 'Found: ') + esc(foundText(d.kind)) : ''}</p>
        <label class="check"><input type="checkbox" class="dz-center"><span>${L('歌詞を左右に分ける', 'Lyrics to the sides')}<small>${L('「中央を空ける」と同じです。踊りの上に歌詞が重ならないように、文字を左右（縦長なら上下）に置きます', 'The same as 「中央を空ける」: the lyrics go to the sides (top and bottom on a tall frame), off the dancer')}</small></span></label>
        <p class="hint">${L('プレビューの枠をドラッグすると細かく動かせます（角で大きさ、上の丸で回転）。出す時間や不透明度は詳細の「画像・動画」で変えられます', 'Drag the frame on the preview to move it finely (corners: size, the knob: turn). Its time and opacity are under 「画像・動画」 in the full editor.')}</p>`;
      const sk = body.querySelector('.dz-key');
      sk.addEventListener('change', e => {
        const v = e.target.value;
        if (v === 'spoid') { e.target.value = c.chroma ? c.chroma.color : 'none'; J.mediaPlace.select(c.id); J.mediaPlace.spoid(); return; }
        set({ key: v });
      });
      body.querySelector('.dz-del').addEventListener('click', remove);
      body.querySelectorAll('.dz-pos').forEach(b => b.addEventListener('click', () => { set({ pos: b.dataset.pos }); J.mediaPlace.select(c.id); }));
      const sz = body.querySelector('.dz-size');
      sz.addEventListener('input', e => { body.querySelector('.dz-sizev').textContent = Math.round(+e.target.value * 100) + '%'; });
      sz.addEventListener('change', e => set({ size: +e.target.value }));
      const tol = body.querySelector('.dz-tol');
      if (tol) tol.addEventListener('change', e => set({ tol: +e.target.value }));
      body.querySelector('.dz-center').addEventListener('change', e => setCenter(e.target.checked));
    }
    body.querySelector('.dz-file').addEventListener('change', e => { const fs = Array.from(e.target.files || []); e.target.value = ''; add(fs); });
  }
  // the values (a control being dragged keeps what it shows)
  if (c && meta) {
    const put = (sel, v) => { const el = body.querySelector(sel); if (el && el !== document.activeElement && String(el.value) !== String(v)) el.value = String(v); };
    const s = sizeOf(c, meta), pos = posOf(c);
    put('.dz-size', Math.round(s * 20) / 20);
    const sv = body.querySelector('.dz-sizev'); if (sv && document.activeElement !== body.querySelector('.dz-size')) sv.textContent = Math.round(s * 100) + '%';
    body.querySelectorAll('.dz-pos').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.pos === pos)));
    const sk = body.querySelector('.dz-key'); if (sk && sk !== document.activeElement) sk.value = c.chroma ? c.chroma.color : 'none';
    if (c.chroma) put('.dz-tol', c.chroma.tol);
    const ce = body.querySelector('.dz-center'); if (ce) ce.checked = !!S.project.centerFree;
  }
}

J.mediaEasy = {
  init(a) {
    api = a; S = a.S;
    const panel = $('easyPanel'), out = $('eMP4');
    if (!panel || sec) return;
    if (!$('mediaEasyCss')) { const st = document.createElement('style'); st.id = 'mediaEasyCss'; st.textContent = CSS; document.head.appendChild(st); }
    sec = document.createElement('div');
    sec.className = 'easy-sec easy-dance'; sec.id = 'easyDance';
    sec.innerHTML = `<h3>${L('ダンス動画を重ねる', 'A dance clip over the lyrics')}<small>${L('お試し', 'trial')}</small></h3><div class="dz-body"></div>`;
    const before = out && out.closest('.easy-sec');
    if (before && before.parentNode === panel) panel.insertBefore(sec, before); else panel.appendChild(sec);
    render();
  },
  onPlan() { if (api) render(); },
  // for tools / tests: the same steps as the panel
  add: files => add(Array.from(files || [])),
  use: id => use(id),
  set: o => set(o || {}),
  remove: () => remove(),
  detect: id => detect(id),
  dancer: () => { const c = dancer(); return c ? JSON.parse(JSON.stringify(c)) : null; },
};
})();
