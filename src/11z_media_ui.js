/* ============================================================
   my-jizura (fork) — media layer: editor UI (Phase 1: background pictures, Phase 2: video clips)
   · a 「画像・動画」 section above 「行とカット」 (built here, so app/body.html stays as upstream ships it)
   · a picture selector on every lyric line, a strip for the pictures on the timeline
   12_ui.js calls: J.mediaUI.init(api) in boot(), onPlan() at the end of replan(),
                   lineRow(li, ln, i) for each row of the line list, drawLane(…) inside drawTimeline()
   ============================================================ */
(() => {
'use strict';
const M = J.media;
if (!M) return;
const JA = /^ja/.test(document.documentElement.lang || 'ja');
const L = (ja, en) => (JA ? ja : en);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
const $ = id => document.getElementById(id);
let api = null, S = null, lastProject = null, listKey = '', busy = false;

const CSS = `
.media-drop { border: 1px dashed var(--line2); border-radius: var(--r); padding: 10px; font-size: 12px; color: var(--muted); text-align: center; cursor: pointer; }
.media-drop:hover, .media-drop.over { border-color: var(--amber); color: var(--text); background: rgba(245,165,12,0.06); }
.media-list { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(92px, 1fr)); gap: 6px; }
.media-list li { position: relative; border: 1px solid var(--line); border-radius: var(--r); overflow: hidden; background: var(--raised); }
.media-list canvas { display: block; width: 100%; aspect-ratio: 16 / 9; background: #0c0c0e; }
.media-list .nm { display: block; font: 400 10px/1.3 var(--mono); color: var(--muted); padding: 2px 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.media-list .no { position: absolute; left: 3px; top: 3px; font: 600 10px/1 var(--mono); color: #fff; background: rgba(0,0,0,0.6); padding: 2px 4px; border-radius: 2px; }
.media-list .acts { position: absolute; right: 2px; top: 2px; display: flex; gap: 2px; opacity: 0; transition: opacity .12s; }
.media-list li:hover .acts, .media-list li:focus-within .acts, #app.is-mobile .media-list .acts { opacity: 1; }
.media-list .acts button { padding: 1px 5px; font-size: 11px; line-height: 1.3; background: rgba(0,0,0,0.65); border-color: transparent; }
.media-list li.missing canvas { opacity: 0.35; }
.media-opts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.media-opts label.field { font-size: 11px; }
.media-checks { display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
.media-checks label { display: inline-flex; gap: 6px; align-items: center; }
.media-note { font-size: 11px; color: var(--muted); }
.media-note.warn { color: var(--amber); }
.ln .tools select.media-sel { max-width: 120px; }
.media-list .dur { position: absolute; right: 3px; bottom: 19px; font: 600 10px/1 var(--mono); color: #fff; background: rgba(0,0,0,0.65); padding: 2px 4px; border-radius: 2px; }
.media-video[hidden] { display: none !important; }
.ln .tools select.media-sel.is-forced { border-color: var(--cyan); }
`;

function section() {
  const sec = document.createElement('div');
  sec.className = 'sec media-sec'; sec.id = 'mediaSec';
  sec.innerHTML = `
    <div class="sec-h"><h2>${L('画像・動画', 'Pictures & clips')}</h2><span class="sec-btns"><label class="file ghost small" title="${L('背景に使う画像や動画を追加します（複数選べます）', 'Add pictures or video clips for the background (several at once)')}">${L('追加', 'Add')}<input id="mediaFiles" type="file" accept="image/*,video/*,.png,.jpg,.jpeg,.webp,.gif,.avif,.mp4,.m4v,.webm,.mov" multiple></label></span></div>
    <div id="mediaDrop" class="media-drop" role="button" tabindex="0">${L('ここに画像や動画をドロップ（複数可）。歌詞の行ごとに背景として切り替わります', 'Drop pictures or video clips here (several at once). They change with every lyric line.')}</div>
    <ul id="mediaList" class="media-list" aria-label="${L('素材の一覧', 'Pictures and clips')}"></ul>
    <div id="mediaCtl">
      <div class="media-checks">
        <label><input type="checkbox" id="mediaAuto"> ${L('行ごとに自動で切り替える', 'Change with every line')}</label>
        <label><input type="checkbox" id="mediaLyricBg"> ${L('背景グラフィックも重ねる', 'Also draw the background graphics')}</label>
      </div>
      <div class="media-opts" style="margin-top:8px">
        <label class="field">${L('順番', 'Order')}<select id="mediaOrder"><option value="sequential">${L('追加した順', 'As added')}</option><option value="random">${L('ランダム', 'Random')}</option></select></label>
        <label class="field">${L('動き', 'Motion')}<select id="mediaHold"><option value="kenburns">${L('ゆっくり動かす', 'Slow zoom / pan')}</option><option value="still">${L('止める', 'Still')}</option></select></label>
        <label class="field">${L('写し方', 'Fit')}<select id="mediaFit"><option value="cover">${L('画面いっぱい', 'Fill the frame')}</option><option value="contain">${L('全体を表示', 'Show it whole')}</option></select></label>
        <label class="field">${L('暗さ', 'Darken')} <span id="mediaDimVal" class="mono"></span><input id="mediaDim" type="range" min="0" max="0.8" step="0.05"></label>
      </div>
      <div id="mediaVideo" class="media-opts media-video" style="margin-top:8px" hidden>
        <label class="field">${L('動画が短いとき', 'When a clip is short')}<select id="mediaExtend"><option value="loop">${L('くり返す', 'Loop')}</option><option value="pingpong">${L('往復する', 'Ping-pong')}</option><option value="hold">${L('最後で止める', 'Hold the last frame')}</option><option value="beat">${L('小節ごとに頭から', 'Restart every bar')}</option></select></label>
        <label class="field">${L('動画の速さ', 'Clip speed')}<select id="mediaRate">${[0.5, 0.75, 1, 1.25, 1.5, 2].map(r => `<option value="${r}">${r}×</option>`).join('')}</select></label>
        <label class="field" id="mediaBeatsWrap">${L('頭出しの間隔', 'Restart every')}<select id="mediaBeats">${[1, 2, 4, 8, 16].map(n => `<option value="${n}">${n} ${L('拍', n > 1 ? 'beats' : 'beat')}</option>`).join('')}</select></label>
      </div>
      <div class="row" style="margin-top:8px"><button id="mediaShuffle" class="ghost small" title="${L('ランダムの並びを作り直します', 'Shuffle the random order again')}">${L('並べ直す', 'Reshuffle')}</button></div>
    </div>
    <div id="mediaNote" class="media-note" aria-live="polite"></div>`;
  return sec;
}

const media = () => S.project.media || (S.project.media = M.defaults());
const back = () => media().tracks.back;
const autoB = () => media().autoFill.back;
function changed(msg) { api.replan(); if (msg) api.toast(msg); }
function note(text, warn) { const n = $('mediaNote'); if (!n) return; n.textContent = text || ''; n.classList.toggle('warn', !!warn); }

async function addFiles(fileList) {
  const files = Array.from(fileList || []);          // a copy: the input's FileList is emptied right after the call
  if (busy || !files.length) return;
  busy = true; note(L('読み込み中…', 'Loading…'));
  try {
    const m = media();
    const room = M.MAX_ASSETS - m.assets.length;
    const list = files.filter(f => M.isImageFile(f) || (M.isVideoFile && M.isVideoFile(f))).slice(0, Math.max(0, room));
    const { added, errors } = await M.addFiles(list, m.assets);
    const unsaved = added.filter(a => a.unsaved).length;
    for (const a of added) { delete a.unsaved; m.assets.push(a); }
    const skipped = files.length - list.length;
    const msgs = [];
    if (added.length) msgs.push(L(`${added.length} 件追加しました`, `Added ${added.length}`));
    const vbad = errors.filter(e => e.reason === 'video').length, big = errors.filter(e => e.reason === 'size').length, other = errors.length - vbad - big + skipped;
    if (vbad) msgs.push(L(`${vbad} 本の動画はこのブラウザで再生できませんでした（HEVC・ProRes など）。H.264 の MP4 か WebM に変換してください`, `${vbad} clip(s) cannot be played in this browser (HEVC, ProRes …). Convert them to H.264 MP4 or WebM.`));
    if (big) msgs.push(L(`${big} 本の動画は大きすぎます（1 本 500MB まで）`, `${big} clip(s) are too large (500 MB each at most)`));
    if (other) msgs.push(L(`${other} 件は読み込めませんでした（画像・動画ではないか、HEIC などこのブラウザで開けない形式です）`, `${other} could not be read (not a picture or clip, or a format this browser cannot open, such as HEIC)`));
    if (unsaved) msgs.push(L('このブラウザに保存できなかったので、再読み込みすると消えます', 'Could not be kept in this browser; they will be gone after a reload'));
    note(msgs.join('。'), !!(errors.length || skipped || unsaved));
    listKey = '';
    changed(added.length ? L(`${added.length} 件追加しました`, `Added ${added.length}`) : null);
    return { added: added.map(x => x.name), errors: errors.map(x => ({ name: x.name, reason: x.reason })), skipped: files.filter(f => !list.includes(f)).map(f => f.name) };
  } catch (e) { console.warn(e); note(L('読み込めませんでした', 'Could not read the files'), true); }
  finally { busy = false; }
}

async function removeAsset(id) {
  const m = media(), a = m.assets.find(x => x.id === id); if (!a) return;
  if (!window.confirm(L(`「${a.name}」を外しますか？このブラウザに保存したデータも消えます。`, `Remove "${a.name}"? Its copy kept in this browser is deleted too.`))) return;
  m.assets = m.assets.filter(x => x.id !== id);
  for (const k of M.TRACKS) m.tracks[k].cuts = m.tracks[k].cuts.filter(c => c.assetId !== id);   // those lines go back to 自動
  await M.remove(id);
  listKey = ''; changed(L('外しました', 'Removed'));
}
function moveAsset(id, d) {
  const A = media().assets, i = A.findIndex(x => x.id === id), j = i + d;
  if (i < 0 || j < 0 || j >= A.length) return;
  [A[i], A[j]] = [A[j], A[i]];
  listKey = ''; changed();
}

function thumb(cv, a) {
  const x = cv.getContext('2d'), w = cv.width, h = cv.height;
  x.fillStyle = '#0c0c0e'; x.fillRect(0, 0, w, h);
  if (!a) return;
  if (a.type === 'video') { if (a.thumb) x.drawImage(a.thumb, 0, 0, w, h); return; }
  if (!a.source) return;
  const k = Math.max(w / a.sw, h / a.sh), dw = a.sw * k, dh = a.sh * k;
  x.imageSmoothingQuality = 'high'; x.drawImage(a.source, (w - dw) / 2, (h - dh) / 2, dw, dh);
}
function renderList() {
  const ul = $('mediaList'); if (!ul) return;
  const m = media();
  const key = m.assets.map(a => a.id + (J.mediaAssets.has(a.id) ? '+' : '-')).join(',');
  if (key === listKey) return;
  listKey = key;
  ul.innerHTML = '';
  m.assets.forEach((meta, i) => {
    const a = J.mediaAssets.get(meta.id);
    const li = document.createElement('li'); li.className = a ? '' : 'missing';
    li.title = a ? `${meta.name}（${meta.w}×${meta.h}）` : L(`${meta.name}：このブラウザにデータがありません。もう一度追加してください`, `${meta.name}: not in this browser. Add it again.`);
    li.innerHTML = `<canvas width="160" height="90"></canvas><span class="no">${i + 1}</span>${meta.type === 'video' ? `<span class="dur">▶ ${(+meta.duration || 0).toFixed(1)}s</span>` : ''}<span class="nm">${esc(meta.name)}</span>
      <span class="acts"><button class="up" title="${L('前へ', 'Earlier')}" aria-label="${L('前へ', 'Earlier')}">←</button><button class="del" title="${L('外す', 'Remove')}" aria-label="${L(`${meta.name} を外す`, `Remove ${meta.name}`)}">✕</button></span>`;
    thumb(li.querySelector('canvas'), a);
    li.querySelector('.del').addEventListener('click', () => removeAsset(meta.id));
    li.querySelector('.up').addEventListener('click', () => moveAsset(meta.id, -1));
    li.querySelector('.up').disabled = i === 0;
    ul.appendChild(li);
  });
  $('mediaCtl').hidden = !m.assets.length;
  $('mediaDrop').textContent = m.assets.length
    ? L('ここに画像や動画をドロップして追加', 'Drop more pictures or clips here')
    : L('ここに画像や動画をドロップ（複数可）。歌詞の行ごとに背景として切り替わります', 'Drop pictures or video clips here (several at once). They change with every lyric line.');
}
function syncControls() {
  const m = media(), A = autoB(), B = back();
  $('mediaAuto').checked = A.mode === 'perLine';
  $('mediaLyricBg').checked = m.lyricBg === 'over';
  $('mediaOrder').value = A.order; $('mediaHold').value = A.hold; $('mediaFit').value = A.fit;
  $('mediaDim').value = String(B.dim); $('mediaDimVal').textContent = Math.round(B.dim * 100) + '%';
  $('mediaShuffle').hidden = A.order !== 'random';
  const V = A.video || { extend: 'loop', rate: 1, beats: 4 };
  $('mediaVideo').hidden = !m.assets.some(a => a.type === 'video');
  $('mediaExtend').value = V.extend; $('mediaRate').value = String(V.rate); $('mediaBeats').value = String(V.beats);
  $('mediaBeatsWrap').hidden = V.extend !== 'beat';
}

async function restore() {
  const m = media();
  if (!m.assets.length) { renderList(); return; }
  const r = await M.restore(S.project);
  listKey = ''; renderList(); S.need = true;
  if (r.missing.length) note(L(`このブラウザに無い画像・動画が ${r.missing.length} 件あります（${r.missing.slice(0, 3).join('、')}${r.missing.length > 3 ? ' ほか' : ''}）。もう一度追加すると戻ります`, `${r.missing.length} file(s) are not in this browser (${r.missing.slice(0, 3).join(', ')}). Add them again to bring them back.`), true);
  else note('');
}

function bind(sec) {
  const fileIn = $('mediaFiles'), drop = $('mediaDrop');
  fileIn.addEventListener('change', e => { addFiles(e.target.files); e.target.value = ''; });
  drop.addEventListener('click', () => fileIn.click());
  drop.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileIn.click(); } });
  const over = on => e => { e.preventDefault(); drop.classList.toggle('over', on); };
  sec.addEventListener('dragover', over(true)); sec.addEventListener('dragenter', over(true));
  sec.addEventListener('dragleave', e => { if (!sec.contains(e.relatedTarget)) drop.classList.remove('over'); });
  sec.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); addFiles(e.dataTransfer && e.dataTransfer.files); });
  $('mediaAuto').addEventListener('change', e => { autoB().mode = e.target.checked ? 'perLine' : 'off'; changed(); });
  $('mediaLyricBg').addEventListener('change', e => { media().lyricBg = e.target.checked ? 'over' : 'off'; changed(); });
  $('mediaOrder').addEventListener('change', e => { autoB().order = e.target.value; changed(); });
  $('mediaHold').addEventListener('change', e => { autoB().hold = e.target.value; changed(); });
  $('mediaFit').addEventListener('change', e => { autoB().fit = e.target.value; changed(); });
  const vset = (k, v) => { const A = autoB(); A.video = Object.assign({ extend: 'loop', rate: 1, beats: 4 }, A.video, { [k]: v }); changed(); };
  $('mediaExtend').addEventListener('change', e => vset('extend', e.target.value));
  $('mediaRate').addEventListener('change', e => vset('rate', +e.target.value));
  $('mediaBeats').addEventListener('change', e => vset('beats', +e.target.value));
  $('mediaShuffle').addEventListener('click', () => { autoB().seed = (autoB().seed + 1) % 2147483647; changed(L('並べ直しました', 'Reshuffled')); });
  // 暗さ: live while dragging (no replan), saved when let go
  $('mediaDim').addEventListener('input', e => {
    const v = J.clamp(+e.target.value, 0, 0.9);
    back().dim = v; if (S.plan && S.plan.media) S.plan.media.back.dim = v;
    $('mediaDimVal').textContent = Math.round(v * 100) + '%'; S.need = true;
  });
  $('mediaDim').addEventListener('change', () => api.replan());
  // スマホ: the heading folds the section like the others
  sec.querySelector('h2').addEventListener('click', () => { if (S.mode === 'mobile') sec.classList.toggle('fold'); });
}

J.mediaUI = {
  init(a) {
    api = a; S = a.S;
    if (!document.getElementById('mediaUiCss')) { const st = document.createElement('style'); st.id = 'mediaUiCss'; st.textContent = CSS; document.head.appendChild(st); }
    const lines = $('lineList'), anchor = lines && lines.closest('.sec');
    if (!anchor) return;
    const sec = section();
    anchor.parentNode.insertBefore(sec, anchor);
    bind(sec);
    // the sound of a video file can be the song (decodeAudioData reads the audio track of MP4 / WebM)
    const au = $('audioFile'); if (au && !/video/.test(au.accept)) au.accept += ',video/mp4,video/webm,.mp4,.m4v,.webm,.mov';
    lastProject = S.project; syncControls(); restore();
  },
  onPlan() {
    if (!api || !$('mediaSec')) return;
    if (S.project !== lastProject) { lastProject = S.project; listKey = ''; note(''); restore(); }   // another project was opened / reset
    syncControls(); renderList();
  },
  /* the picture selector of one lyric line (only when the project has pictures) */
  lineRow(li, ln, i) {
    if (!api) return;
    const m = media();
    if (!m.assets.length) return;
    const tools = li.querySelector('.tools'); if (!tools) return;
    const own = back().cuts.find(c => c.lineRef && c.lineRef.line === i);
    const shown = M.cutAt(S.plan, ln.start + 0.001, 'back');
    const shownName = shown && !own ? (M.assetById(S.project, shown.assetId) || {}).name : null;
    const sel = document.createElement('select');
    sel.className = 'media-sel' + (own ? ' is-forced' : '');
    sel.setAttribute('aria-label', L(`${i + 1}行目の背景（画像・動画）`, `Picture or clip behind line ${i + 1}`));
    sel.title = L('この行の背景の画像・動画（自動＝順番に切り替え）', 'Picture or clip behind this line (auto = in turn)');
    sel.innerHTML = `<option value="">${esc(shownName ? L(`画像 自動（${shownName}）`, `Auto (${shownName})`) : L('画像 自動', 'Picture: auto'))}</option><option value="none">${L('画像なし', 'No picture')}</option>`
      + m.assets.map((a, k) => `<option value="${esc(a.id)}">${k + 1}. ${a.type === 'video' ? '▶ ' : ''}${esc(a.name)}</option>`).join('');
    sel.value = own ? (own.assetId || 'none') : '';
    sel.addEventListener('change', e => {
      const v = e.target.value, cuts = back().cuts.filter(c => !(c.lineRef && c.lineRef.line === i));
      if (v) cuts.push({ id: 'l' + i, assetId: v === 'none' ? '' : v, lineRef: { line: i }, start: null, end: null, fit: 'auto', enter: 'auto', hold: 'auto', exit: 'auto', opacity: 1 });
      back().cuts = cuts;
      api.replan(); api.seek(ln.start + 0.001);
    });
    tools.insertBefore(sel, tools.firstChild);
  },
  // for tools/jizura_driver.py (the CLI / MCP server): the same steps as choosing files / ✕ in the panel
  addFiles: fileList => addFiles(fileList),
  remove: id => removeAsset(id),
  /* the pictures as a thin strip along the bottom of the cut band */
  drawLane(x, X, w, top, bot, dpr) {
    const P = S && S.plan && S.plan.media && S.plan.media.back;
    if (!P || !P.cuts.length) return;
    const y = bot - 5 * dpr, hh = 4 * dpr;
    for (const c of P.cuts) {
      const x0 = X(c.start), x1 = X(c.end);
      if (x1 < 0 || x0 > w) continue;
      const hue = J.sid(c.assetId) % 360, ok = J.mediaAssets.has(c.assetId);
      x.fillStyle = ok ? `hsla(${hue},65%,60%,0.9)` : 'rgba(142,138,148,0.5)';
      x.fillRect(x0, y, Math.max(1, x1 - x0 - 1), hh);
    }
  },
};
})();
