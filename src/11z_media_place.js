/* ============================================================
   my-jizura (fork) — media layer: 前景の配置編集 (Phase 3b-3)
   · 「前景（歌詞の上）」 in the pictures panel: every picture placed over the lyrics (project.media.tracks.front, timed cuts) with
     its time, opacity and クロマキー; 「前」 on a picture of the list puts it there for the whole song (then its time is set here).
   · the selected one gets a frame over the preview: drag it to move, a corner to resize (keeps the picture's shape), the knob
     above it to turn (Shift: 15° steps). Dragging updates the project and plan (no replan per move); letting go replans, cancelling restores both.
   · スポイト: the next click on the picture in the preview takes the colour under it (from the picture itself, not the
     frame with the lyrics) as the key colour.
   11z_media_ui.js calls J.mediaPlace.init(api, section) and .onPlan(); its list gets a 「前景に置く」 button per picture.
   ============================================================ */
(() => {
'use strict';
const M = J.media;
const JA = /^ja/.test(document.documentElement.lang || 'ja');
const L = (ja, en) => (JA ? ja : en);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
const $ = id => document.getElementById(id);
const r3 = x => Math.round(x * 1000) / 1000;
let api = null, S = null, sel = null, spoid = false, box = null, raf = 0, drag = null, rowsKey = '', pickAbort = null;
let pickFrames = Promise.resolve();

const CSS = `
.media-front { margin-top: 10px; border-top: 1px solid var(--line); padding-top: 8px; }
.media-front h3 { font: 600 12px/1.4 var(--sans, inherit); margin: 0 0 6px; color: var(--text); }
.media-front .hint { font-size: 11px; color: var(--muted, #8e8a94); margin: 0 0 6px; }
.mf-row { border: 1px solid var(--line); border-radius: var(--r, 4px); padding: 6px; margin-bottom: 6px; display: grid; gap: 4px; cursor: pointer; }
.mf-row.sel { border-color: var(--cyan, #3cc8e6); box-shadow: 0 0 0 1px var(--cyan, #3cc8e6) inset; }
.mf-row .top { display: flex; gap: 6px; align-items: center; }
.mf-row .nm { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.mf-row .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 8px; }
.mf-row label { font-size: 11px; display: grid; gap: 2px; }
.mf-row input[type=number] { width: 100%; }
.mf-row .sw { display: inline-block; width: 12px; height: 12px; border-radius: 2px; vertical-align: -2px; border: 1px solid var(--line); }
.media-box { position: absolute; border: 1px dashed #3cc8e6; box-shadow: 0 0 0 1px rgba(0,0,0,0.5); cursor: move; touch-action: none; z-index: 5; }
.media-box.off { border-color: rgba(60,200,230,0.45); }
.media-box i { position: absolute; width: 10px; height: 10px; background: #3cc8e6; border: 1px solid #000; }
.media-box i.nw { left: -6px; top: -6px; cursor: nwse-resize; } .media-box i.ne { right: -6px; top: -6px; cursor: nesw-resize; }
.media-box i.sw { left: -6px; bottom: -6px; cursor: nesw-resize; } .media-box i.se { right: -6px; bottom: -6px; cursor: nwse-resize; }
.media-box i.rot { left: calc(50% - 6px); top: -28px; border-radius: 50%; cursor: grab; }
.media-box i.rot::after { content: ''; position: absolute; left: 4px; top: 10px; width: 1px; height: 16px; background: #3cc8e6; }
.viewport.media-spoid, .viewport.media-spoid canvas { cursor: crosshair; }
`;

const media = () => S.project.media;
const front = () => media().tracks.front;
const cutById = id => front().cuts.find(c => c.id === id) || null;
const planCut = id => (S.plan && S.plan.media && S.plan.media.front.cuts.find(c => c.id === id)) || null;
// the width a picture without a place of its own shows at (as the frame shows it whole) — the start of a drag
function wholeWidth(c, meta) {
  const P = S.plan, k = c.fit === 'cover' ? Math.max(P.W / meta.w, P.H / meta.h) : Math.min(P.W / meta.w, P.H / meta.h);
  return meta.w * k / P.W;
}
const rectOf = (c, meta) => c.rect || { x: 0, y: 0, w: r3(wholeWidth(c, meta)), rot: 0 };
function commit(msg) { S.project.media = M.normalize(media()); api.replan(); if (msg) api.toast(msg); }

/* ---------- 前景に置く ---------- */
function place(assetId) {
  const m = media(), meta = M.assetById(S.project, assetId);
  if (!meta) return null;
  const used = new Set([...m.tracks.back.cuts, ...m.tracks.front.cuts].map(c => c.id));
  let k = 1; while (used.has('f' + k)) k++;
  // the whole song to begin with (it shows right away, wherever the playhead is); its time is set in the list
  const c = { id: 'f' + k, assetId, lineRef: null, start: 0, end: null, fit: 'auto',
    enter: 'auto', hold: 'auto', exit: 'auto', opacity: 1, rect: { x: 0, y: 0, w: 0.4, rot: 0 } };
  m.tracks.front.cuts.push(c);
  commit(L(`「${meta.name}」を前景に置きました。プレビューの枠で動かせます`, `"${meta.name}" is over the lyrics now — move it with the frame on the preview`));
  select(c.id);
  return c.id;
}

/* ---------- the list ---------- */
// the values of the rows that are already there (a field being typed into or dragged keeps what it shows)
function syncValues(wrap, cs) {
  for (const c of cs) {
    const row = wrap.querySelector(`.mf-row[data-id="${c.id}"]`); if (!row) continue;
    const set = (sel2, v) => { const el = row.querySelector(sel2); if (el && el !== document.activeElement && el.value !== String(v)) el.value = String(v); };
    set('.st', c.start); set('.en', c.end == null ? '' : c.end); set('.op', c.opacity);
    if (c.chroma) { set('.tol', c.chroma.tol); set('.spill', c.chroma.spill); }
  }
}
function rows() {
  const wrap = $('mediaFront'); if (!wrap) return;
  const m = media(), cs = m.tracks.front.cuts.filter(c => !c.lineRef);
  // rebuilt only when what the rows are changes (an edit in a row only updates the values: the next field keeps its focus)
  const key = JSON.stringify([cs.map(c => [c.id, c.assetId, c.chroma ? c.chroma.color : 0]), sel, m.assets.map(a => a.id + (J.mediaAssets.has(a.id) ? '+' : '-'))]);
  if (key === rowsKey) { syncValues(wrap, cs); return; }
  rowsKey = key;
  const list = wrap.querySelector('.mf-list');
  wrap.querySelector('.hint').hidden = !!cs.length;
  list.innerHTML = '';
  for (const c of cs) {
    const meta = M.assetById(S.project, c.assetId) || { name: '?' }, K = c.chroma;
    const col = K ? M.keyColor(J.mediaAssets.get(c.assetId) || {}, K) : null;
    const row = document.createElement('div');
    row.className = 'mf-row' + (c.id === sel ? ' sel' : ''); row.dataset.id = c.id;
    row.innerHTML = `<div class="top"><span class="nm" title="${esc(meta.name)}">${meta.type === 'video' ? '▶ ' : ''}${esc(meta.name)}</span>
      <button class="ghost small fit" title="${L('画面の中央・元の大きさに戻します', 'Back to the middle, at its own size')}">${L('中央に戻す', 'Reset')}</button>
      <button class="ghost small del" title="${L('前景から外す', 'Remove from over the lyrics')}" aria-label="${L(`${meta.name} を前景から外す`, `Remove ${meta.name} from over the lyrics`)}">✕</button></div>
      <div class="grid">
        <label>${L('開始（秒）', 'From (s)')}<input type="number" class="st" min="0" step="0.1" value="${c.start}"></label>
        <label>${L('終了（秒・空＝最後まで）', 'To (s, empty = the end)')}<input type="number" class="en" min="0" step="0.1" value="${c.end == null ? '' : c.end}"></label>
        <label>${L('不透明度', 'Opacity')} <input type="range" class="op" min="0" max="1" step="0.05" value="${c.opacity}"></label>
        <label>${L('クロマキー', 'Chroma key')}<select class="key"><option value="">${L('なし', 'Off')}</option><option value="auto">${L('自動（ふちの色）', 'Auto (edge colour)')}</option>${K && K.color !== 'auto' ? `<option value="${esc(K.color)}">${esc(K.color)}</option>` : ''}<option value="spoid">${L('スポイトで選ぶ…', 'Pick with the eyedropper…')}</option></select></label>
        ${K ? `<label>${L('抜く範囲', 'Tolerance')} <span class="sw" style="background:${esc(col)}"></span><input type="range" class="tol" min="0" max="0.4" step="0.01" value="${K.tol}"></label>
        <label>${L('緑のふちを消す', 'Spill')}<input type="range" class="spill" min="0" max="1" step="0.05" value="${K.spill}"></label>` : ''}
      </div>`;
    const sk = row.querySelector('.key'); sk.value = K ? K.color : '';
    row.addEventListener('click', e => { if (!e.target.closest('input,select,button')) select(c.id === sel ? null : c.id); });
    row.querySelector('.del').addEventListener('click', () => { front().cuts = front().cuts.filter(x => x.id !== c.id); if (sel === c.id) select(null); commit(L('前景から外しました', 'Removed')); });
    row.querySelector('.fit').addEventListener('click', () => { const x = cutById(c.id); x.rect = { x: 0, y: 0, w: 0.4, rot: 0 }; select(c.id); commit(); });
    row.querySelector('.st').addEventListener('change', e => { const x = cutById(c.id), v = Math.max(0, +e.target.value || 0); x.start = v; if (x.end != null && x.end <= v) x.end = null; commit(); });
    row.querySelector('.en').addEventListener('change', e => { const x = cutById(c.id), v = e.target.value === '' ? null : +e.target.value; x.end = v != null && v > x.start ? v : null; commit(); });
    row.querySelector('.op').addEventListener('change', e => { cutById(c.id).opacity = J.clamp(+e.target.value, 0, 1); commit(); });
    sk.addEventListener('change', e => {
      const x = cutById(c.id), v = e.target.value;
      if (v === 'spoid') { select(c.id); startSpoid(); e.target.value = K ? K.color : ''; return; }
      stopSpoid();
      if (!v) delete x.chroma; else x.chroma = Object.assign({ tol: 0.1, soft: 0.08, spill: 0.6 }, x.chroma, { color: v });
      commit();
    });
    const tol = row.querySelector('.tol'), spill = row.querySelector('.spill');
    if (tol) tol.addEventListener('change', e => { cutById(c.id).chroma.tol = +e.target.value; commit(); });
    if (spill) spill.addEventListener('change', e => { cutById(c.id).chroma.spill = +e.target.value; commit(); });
    list.appendChild(row);
  }
}

/* ---------- the frame over the preview ---------- */
function geometry(c) {
  const meta = M.assetById(S.project, c.assetId), cv = $('view'), vp = $('viewport');
  if (!meta || !cv || !vp) return null;
  const cr = cv.getBoundingClientRect(), vr = vp.getBoundingClientRect(), P = S.plan, k = cr.width / P.W, R = rectOf(c, meta);
  const w = R.w * P.W * k, h = w * meta.h / meta.w;
  // centre in client pixels (for dragging) and in the viewport (for the frame)
  const cx = cr.left + (P.W / 2 + R.x * P.W) * k, cy = cr.top + (P.H / 2 + R.y * P.H) * k;
  return { meta, R, k, w, h, cx, cy, ox: vr.left, oy: vr.top, cr };
}
function layout() {
  raf = 0;
  const c = sel && cutById(sel);
  if (!c || !box) { if (box) box.hidden = true; return; }
  const g = geometry(c);
  if (!g) { box.hidden = true; return; }
  box.hidden = false;
  Object.assign(box.style, { left: (g.cx - g.ox - g.w / 2) + 'px', top: (g.cy - g.oy - g.h / 2) + 'px', width: g.w + 'px', height: g.h + 'px', transform: `rotate(${g.R.rot}deg)` });
  box.classList.toggle('off', !(c.start <= S.t && (c.end == null || S.t < c.end)));
  raf = requestAnimationFrame(layout);                 // follows the playhead and the window while one is selected
}
function select(id) {
  if (id !== sel) stopSpoid();
  sel = id; rowsKey = '';
  if (box) box.hidden = !id;
  if (id && !raf) raf = requestAnimationFrame(layout);
  rows();
}
// a change while dragging: the project's copy and the plan's copy (drawn right away, no replan)
function setRect(c, R) {
  c.rect = { x: r3(J.clamp(R.x, -1, 1)), y: r3(J.clamp(R.y, -1, 1)), w: r3(J.clamp(R.w, 0.02, 4)), rot: Math.round(((R.rot + 540) % 360) - 180) };
  const pc = planCut(c.id); if (pc) pc.rect = Object.assign({}, c.rect);
  S.need = true;
}
function onDown(e) {
  if (spoid) return;                          // picking a colour must not also start a placement drag
  const c = sel && cutById(sel); if (!c || e.button !== 0) return;
  const g = geometry(c); if (!g) return;
  e.preventDefault(); e.stopPropagation();
  const kind = e.target.classList.contains('rot') ? 'rot' : e.target.tagName === 'I' ? 'size' : 'move';
  drag = { kind, c, g, R0: Object.assign({}, g.R), orig: c.rect ? Object.assign({}, c.rect) : null,
    x0: e.clientX, y0: e.clientY, d0: Math.max(4, Math.hypot(e.clientX - g.cx, e.clientY - g.cy)) };
  box.setPointerCapture(e.pointerId);
}
function onMove(e) {
  if (!drag) return;
  const { kind, c, g, R0 } = drag, P = S.plan, R = Object.assign({}, R0);
  if (kind === 'move') { R.x = R0.x + (e.clientX - drag.x0) / g.k / P.W; R.y = R0.y + (e.clientY - drag.y0) / g.k / P.H; }
  else if (kind === 'size') R.w = R0.w * Math.hypot(e.clientX - g.cx, e.clientY - g.cy) / drag.d0;
  else {
    let a = Math.atan2(e.clientY - g.cy, e.clientX - g.cx) * 180 / Math.PI + 90;
    if (e.shiftKey) a = Math.round(a / 15) * 15;
    R.rot = a;
  }
  setRect(c, R);
}
function onUp() { if (!drag) return; drag = null; commit(); }
// an interrupted drag (pointercancel: a touch taken over by the system, Esc) puts it back where it was — nothing is kept
function onCancel() {
  if (!drag) return;
  const { c, orig } = drag; drag = null;
  if (orig) c.rect = orig; else delete c.rect;
  const pc = planCut(c.id); if (pc) pc.rect = orig ? Object.assign({}, orig) : null;
  S.need = true;
  J.uiApi.flushSave();                       // an autosave may already have kept the intermediate rect
}

/* ---------- スポイト ---------- */
function startSpoid() {
  stopSpoid(); spoid = true; $('viewport').classList.add('media-spoid');
  api.toast(L('プレビューで、抜きたい色（前景の画像の上）をクリックしてください（Esc でやめる）', 'Click the colour to take out, on the picture in the preview (Esc to cancel)'));
}
function stopSpoid() {
  spoid = false; if (pickAbort) { pickAbort.abort(); pickAbort = null; }
  const vp = $('viewport'); if (vp) vp.classList.remove('media-spoid');
}
/* the colour of the picture itself under a point of the preview, or null outside it — through where it is drawn at this moment
   (its motion and 登場・退場 included: M.cutBox, as the renderer), or where it is placed when it is not on screen now */
M.pickColor = async (c, clientX, clientY, signal) => {
  const g = geometry(c); if (!g) return null;
  const a = J.mediaAssets.get(c.assetId); if (!a) return null;
  const P = S.plan, pc = planCut(c.id), t0 = S.t;
  let cx = g.cx, cy = g.cy, w = g.w, h = g.h, turn = g.R.rot * Math.PI / 180;
  if (pc && M.cutBox && pc.start <= t0 && t0 < pc.end) {
    const B = M.cutBox(P, pc, t0, P.W, P.H, M.layerFx(pc, t0), g.meta.w, g.meta.h);
    if (B.clip) {
      const x = (clientX - g.cr.left) / g.k, y = (clientY - g.cr.top) / g.k, q = B.clip;
      if (x < q.x || x > q.x + q.w || y < q.y || y > q.y + q.h) return null;
    }
    cx = g.cr.left + (B.x0 + B.dw / 2) * g.k; cy = g.cr.top + (B.y0 + B.dh / 2) * g.k; w = B.dw * g.k; h = B.dh * g.k; turn = B.turn;
  }
  const t = -turn, dx = clientX - cx, dy = clientY - cy;
  const u = (dx * Math.cos(t) - dy * Math.sin(t)) / w + 0.5, v = (dx * Math.sin(t) + dy * Math.cos(t)) / h + 0.5;
  if (u < 0 || u > 1 || v < 0 || v > 1) return null;
  const sample = (src, alt, blend) => {
    if (!src) return null;
    const cv = document.createElement('canvas'); cv.width = cv.height = 1;
    const x = cv.getContext('2d', { willReadFrequently: true });
    const paint = (frame, alpha) => {
      const sw = frame.videoWidth || frame.width, sh = frame.videoHeight || frame.height;
      x.globalAlpha = alpha;
      x.drawImage(frame, Math.min(sw - 1, Math.floor(u * sw)), Math.min(sh - 1, Math.floor(v * sh)), 1, 1, 0, 0, 1, 1);
    };
    paint(src, 1); if (alt && blend > 0) paint(alt, blend); // the same source-over blend as drawCut's loop seam
    const d = x.getImageData(0, 0, 1, 1).data;
    return '#' + [d[0], d[1], d[2]].map(n => n.toString(16).padStart(2, '0')).join('');
  };
  if (a.type !== 'video' || !pc || !M.videoTimes(P, pc, t0)) return sample(a.type === 'video' ? a.thumb : a.source);
  // Hold the song at the clicked time and decode this cut's own frame(s) with the existing decoder (both sides of a loop
  // seam; also when the cut is not showing now), then give the clips straight back to the preview.
  J.uiApi.pause();
  const read = pickFrames.then(async () => {
    if (signal && signal.aborted) return null;
    try {
      const vt = await M.prepareCut(P, pc, t0, signal);
      if (!vt || (signal && signal.aborted)) return null;
      const src = M.videoCap(a, vt.main), alt = vt.alt != null && vt.k > 0 ? M.videoCap(a, vt.alt) : null;
      if (!src || (vt.alt != null && vt.k > 0 && !alt)) return null;
      return sample(src, alt, vt.k);
    } finally { M.releaseVideos(); S.need = true; }
  });
  pickFrames = read.catch(() => {}); // cancelled/failed reads must not block the next request
  return read;

};
async function onViewClick(e) {
  if (!spoid) return;
  e.preventDefault(); e.stopPropagation();
  const c = sel && cutById(sel), plan = S.plan;
  if (pickAbort) pickAbort.abort();
  const request = new AbortController(); pickAbort = request;
  try {
    const col = c && await M.pickColor(c, e.clientX, e.clientY, request.signal);
    if (request.signal.aborted || !spoid || !c || cutById(sel) !== c || S.plan !== plan) return;
    if (!col) { api.toast(L('前景の画像の上をクリックしてください', 'Click on the picture over the lyrics')); return; }
    stopSpoid();
    c.chroma = Object.assign({ tol: 0.1, soft: 0.08, spill: 0.6 }, c.chroma, { color: col });
    commit(L(`${col} を抜きます`, `Taking ${col} out`));
  } catch (err) {
    if (!request.signal.aborted) api.toast(L('このフレームの色を読み取れませんでした。もう一度お試しください', 'Could not read this frame. Please try again.'));
  } finally { if (pickAbort === request) pickAbort = null; }
}

J.mediaPlace = {
  init(a, sec) {
    api = a; S = a.S;
    if (!$('mediaPlaceCss')) { const st = document.createElement('style'); st.id = 'mediaPlaceCss'; st.textContent = CSS; document.head.appendChild(st); }
    const ctl = $('mediaCtl');
    if (ctl && !$('mediaFront')) {
      const wrap = document.createElement('div');
      wrap.id = 'mediaFront'; wrap.className = 'media-front';
      wrap.innerHTML = `<h3>${L('前景（歌詞の上）', 'Over the lyrics')}</h3>
        <p class="hint">${L('一覧の画像の「前」で、歌詞の上に重ねます（ロゴ・立ち絵・グリーンバックの動画など）。出す時間はここで変えられます。', 'Put a picture over the lyrics with 「前」 on it in the list (a logo, a character, a green-screen clip); set its time here.')}</p>
        <div class="mf-list"></div>`;
      ctl.appendChild(wrap);
    }
    const vp = $('viewport');
    if (vp && !box) {
      box = document.createElement('div');
      box.className = 'media-box'; box.id = 'mediaBox'; box.hidden = true;
      box.innerHTML = '<i class="nw"></i><i class="ne"></i><i class="sw"></i><i class="se"></i><i class="rot" title="' + L('回す（Shift で 15° ずつ）', 'Turn (Shift: 15° steps)') + '"></i>';
      vp.appendChild(box);
      box.addEventListener('pointerdown', onDown);
      box.addEventListener('pointermove', onMove);
      box.addEventListener('pointerup', onUp);
      box.addEventListener('pointercancel', onCancel);
      vp.addEventListener('click', onViewClick, true);
      document.addEventListener('keydown', e => { if (e.key !== 'Escape') return; if (drag) onCancel(); else if (spoid) stopSpoid(); });
    }
    rows();
  },
  onPlan() {
    if (!api) return;
    if (sel && !cutById(sel)) select(null);
    rows();
  },
  // for 11z_media_ui.js (the 「前」 button) and tools / tests
  place: id => place(id),
  select: id => select(id),
  selected: () => sel,
  spoid: () => startSpoid(),
};
})();
