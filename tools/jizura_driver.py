"""my-jizura: drive the built app (index.html) in a headless browser.
The base of tools/jizura_cli.py (command line) and tools/jizura_mcp.py (MCP server for Claude / Codex).

The app runs entirely in the page, so this opens the built index.html (served from 127.0.0.1) in Playwright's Chromium —
Google Chrome / Edge first when installed, because only they can read and write H.264 MP4 — and calls the page's own
functions (J.ui, J.uiApi, J.mediaUI, J.exportMP4 …). Nothing here re-implements the app: what the panel does, the driver does.

    async with Jizura() as jz:
        await jz.new_project(title='夜明け', aspect='9:16')
        await jz.set_lyrics(path='song.json')          # LRC / SRT / VTT / Whisper・Suno JSON / plain text
        await jz.load_song('song.mp3')
        await jz.add_media(['pics/'])                  # pictures and clips (a folder = its files in name order)
        await jz.set_look(theme='ballad', variation=1)
        pngs = await jz.preview(count=6)              # [(t, line text, PNG bytes)]
        await jz.export_mp4('mv.mp4')

Network: the page may only reach the local app server and Google Fonts (everything else is blocked).
A fresh browser profile is used every time (nothing is kept between runs; save the project with save_project()).
"""
import asyncio, base64, functools, http.server, json, os, re, sys, tempfile, threading, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_HOSTS = ('fonts.googleapis.com', 'fonts.gstatic.com')
MEDIA_EXT = re.compile(r'\.(png|jpe?g|webp|gif|bmp|avif|mp4|m4v|webm|mov|ogv)$', re.I)
ASPECTS = ['16:9', '9:16', '4:3', '3:4', '1:1', '4:5', '21:9']
RES = [720, 1080, 1440, 2160]
FPS = [24, 30, 60]
QUALITY = ['standard', 'high', 'max']
MEDIA_ORDER = ['sequential', 'random']
MEDIA_HOLD = ['kenburns', 'pan', 'push', 'drift', 'beatPulse', 'still']
MEDIA_ENTER = ['fade', 'slide', 'zoom', 'wipe', 'cut']
MEDIA_TREAT = ['none', 'match', 'mono', 'sepia', 'duotone', 'blur']
MEDIA_SCRIM = ['auto', 'always', 'off']
MEDIA_FIT = ['cover', 'contain']
VIDEO_EXTEND = ['loop', 'pingpong', 'hold', 'beat']
VIDEO_RATES = [0.5, 0.75, 1, 1.25, 1.5, 2]
VIDEO_BEATS = [1, 2, 4, 8, 16]


class JizuraError(Exception):
    """a request the app cannot do (bad value, missing file, a file the browser cannot read …)"""


def _version():
    try: return open(os.path.join(ROOT, 'VERSION'), encoding='utf-8').read().strip()
    except OSError: return ''


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass


def _serve(directory):
    s = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(_Quiet, directory=directory))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def media_files(paths):
    """files and folders → the picture / clip files (a folder gives its files in name order, not recursive)"""
    out = []
    for p in paths:
        p = os.path.abspath(os.path.expanduser(str(p)))
        if os.path.isdir(p):
            out += [os.path.join(p, n) for n in sorted(os.listdir(p)) if MEDIA_EXT.search(n) and os.path.isfile(os.path.join(p, n))]
        elif os.path.isfile(p): out.append(p)
        else: raise JizuraError(f'ファイルが見つかりません: {p}')
    return out


def read_text(path):
    """a lyrics / timing file as text (UTF-8, or Shift_JIS like the app)"""
    with open(path, 'rb') as f: b = f.read()
    if len(b) > 2_000_000: raise JizuraError(f'歌詞ファイルが大きすぎます（2MB まで）: {path}')
    try: return b.decode('utf-8-sig')
    except UnicodeDecodeError: return b.decode('cp932', errors='replace')


# ---------------------------------------------------------------- page-side snippets
JS_READY = 'window.J && J.ui && J.ui.plan && J.uiApi && J.mediaUI && J.mediaUI.addFiles && J.media && J.lyricsImport'

JS_STATUS = r"""async () => {
  const enc = async codec => { try { return typeof VideoEncoder !== 'undefined' && !!(await VideoEncoder.isConfigSupported({ codec, width: 1920, height: 1080, bitrate: 8e6, framerate: 30 })).supported; } catch (e) { return false; } };
  const v = document.createElement('video');
  return { userAgent: navigator.userAgent, webcodecs: typeof VideoEncoder !== 'undefined',
    h264Encode: await enc('avc1.640028'), vp9Encode: await enc('vp09.00.40.08'),
    h264Decode: v.canPlayType('video/mp4; codecs="avc1.640028"') !== '', vp9Decode: v.canPlayType('video/webm; codecs="vp9"') !== '' };
}"""

JS_OPTIONS = r"""() => ({
  themes: Object.fromEntries(J.THEME_ORDER.map(k => [k, J.THEMES[k].name])),
  transitions: Object.fromEntries(J.media.TRANS_KEYS.filter(k => J.TRANS[k]).map(k => [k, J.TRANS[k].name])),
  // the lyric parts set_line_style accepts (key → name), as the line editor lists them
  lyric: Object.fromEntries(['layout', 'enter', 'exit', 'hold', 'cam', 'treat', 'bg', 'decor', 'trans'].map(g =>
    [g, Object.fromEntries(J.order(g).filter(k => !(J.registry(g)[k] || {}).special).map(k => [k, J.registry(g)[k].name]))])),
  styles: Object.fromEntries(J.STYLE_ORDER.map(k => [k, J.STYLES[k].name])),
  moods: Object.fromEntries(Object.keys(J.MOODS).map(k => [k, J.MOODS[k].name])),
})"""

# summary of the current project and plan (what a person sees in the panel)
JS_PLAN = r"""() => {
  const S = J.ui, P = S.project, plan = S.plan, m = P.media, mp = plan.media;
  const name = id => { const a = J.media.assetById(P, id); return a ? a.name : null; };
  const r2 = x => Math.round(x * 100) / 100 || 0;      // (never -0)
  const own = new Map(m.tracks.back.cuts.filter(c => c.lineRef).map(c => [c.lineRef.line, c.assetId]));
  return {
    title: P.title, artist: P.artist, aspect: P.aspect, res: P.res, fps: P.fps, quality: P.quality || 'high', includeAudio: P.includeAudio !== false,
    duration: r2(plan.duration), size: J.outputSize(P),
    look: { theme: P.themeId, style: P.style, styleName: J.STYLES[P.style] ? J.STYLES[P.style].name : P.style, mood: P.mood, seed: P.seed },
    song: S.audio ? { name: P.audioName, duration: r2(S.audio.duration), bpm: S.audio.bpm } : null,
    lines: plan.lines.map((ln, i) => {
      const c = mp ? J.media.cutAt(plan, ln.start + 0.001, 'back') : null;
      const wt = J.media.lineWords(P.media, ln);
      return { line: i + 1, start: r2(ln.start), end: r2(ln.end), text: ln.text, media: c ? name(c.assetId) : null,
        choice: own.has(i) ? (own.get(i) ? name(own.get(i)) : 'none') : 'auto',
        words: wt ? wt.w.length : 0, confidence: wt && wt.p != null ? r2(wt.p) : null };   // word times (cuts follow the singing); lowest alignment confidence
    }),
    media: m.assets.map((a, i) => ({ n: i + 1, name: a.name, id: a.id, type: a.type, w: a.w, h: a.h, duration: a.duration, loaded: J.mediaAssets.has(a.id) })),
    mediaOptions: { auto: m.autoFill.back.mode === 'perLine', order: m.autoFill.back.order, hold: m.autoFill.back.hold, fit: m.autoFill.back.fit,
      dim: m.tracks.back.dim, lyricBg: m.lyricBg, shuffle: m.autoFill.back.seed, video: m.autoFill.back.video,
      trans: m.autoFill.back.trans, enter: m.autoFill.back.enter, exit: m.autoFill.back.exit, treat: m.autoFill.back.treat, scrim: m.scrim.mode, scrimAmount: m.scrim.amount },
    cuts: mp ? mp.back.cuts.map(c => ({ media: name(c.assetId), start: r2(c.start), end: r2(c.end), timed: !!c.timed })) : [],
    // pictures placed at a time of the song (add_timed_media): over the automatic ones, under the ones chosen for a line
    timed: m.tracks.back.cuts.filter(c => !c.lineRef).map(c => ({ id: c.id, media: c.assetId ? name(c.assetId) : 'none', start: r2(c.start), end: c.end == null ? null : r2(c.end),
      clipStart: c.video && c.video.start != null ? c.video.start : null })),
    missing: m.assets.filter(a => !J.mediaAssets.has(a.id)).map(a => a.name),   // in the project but not loaded: add_media them again
  };
}"""

JS_SET_LYRICS = r"""([text, name]) => {
  const S = J.ui, P = S.project;
  const r = J.lyricsImport.toLrc(String(text), name || '');
  J.uiApi.pause();
  // the same as 「LRC を読み込む」: line times, per-line settings and the export range belonged to the old lines
  P.lyrics = String(r.text).replace(/^﻿/, '').replace(/\r\n?/g, '\n').trim(); P.timing.lineTimes = {}; P.overrides = {}; P.exportRange = null;
  for (const k of J.media.TRACKS) P.media.tracks[k].cuts = P.media.tracks[k].cuts.filter(c => !c.lineRef);   // …and so did the per-line pictures
  // word times (word lists / enhanced LRC): the cuts of a line change when their word is sung; none = the old ones go
  P.media.text = Object.assign({}, P.media.text, { words: r.words || [] });
  P.media = J.media.normalize(P.media);
  if (J.lyricsImport) J.lyricsImport.last = null;
  const el = document.getElementById('lyrics'); if (el) el.value = P.lyrics;
  J.uiApi.syncUI(); J.uiApi.replan(); J.uiApi.flushSave();
  return { kind: name ? r.kind : 'text', lines: S.plan.lines.length, timed: J.parseLyrics(P.lyrics).lines.filter(l => l.lrc != null).length,
    wordTimed: S.plan.lines.filter(ln => J.media.lineWords(P.media, ln)).length };
}"""

JS_LOAD_SONG = r"""async () => {
  const f = document.getElementById('jzDriverFiles').files[0];
  const ok = await J.uiApi.loadAudioFile(f);
  const S = J.ui;
  return ok && S.audio ? { name: f.name, duration: Math.round(S.audio.duration * 100) / 100, bpm: S.audio.bpm } : { error: document.getElementById('audioName').textContent };
}"""

JS_ADD_MEDIA = r"""async () => {
  const r = await J.mediaUI.addFiles(document.getElementById('jzDriverFiles').files);
  return r || { error: 'busy' };
}"""

JS_SET_LINE = r"""([i, v]) => {
  const S = J.ui, back = S.project.media.tracks.back;
  // the same as the picture selector of a line: '' = 自動, 'none' = 画像なし, else an asset id
  const cuts = back.cuts.filter(c => !(c.lineRef && c.lineRef.line === i));
  if (v) cuts.push({ id: 'l' + i, assetId: v === 'none' ? '' : v, lineRef: { line: i }, start: null, end: null, fit: 'auto', enter: 'auto', hold: 'auto', exit: 'auto', opacity: 1 });
  back.cuts = cuts;
  J.uiApi.replan(); J.uiApi.flushSave();
}"""

JS_ADD_TIMED = r"""(o) => {
  const S = J.ui, back = S.project.media.tracks.back;
  const used = new Set(back.cuts.map(c => c.id));
  let k = 1; while (used.has('t' + k)) k++;
  const c = { id: 't' + k, assetId: o.assetId, lineRef: null, start: o.start, end: o.end, fit: o.fit || 'auto', enter: 'auto', hold: 'auto', exit: 'auto', opacity: 1 };
  if (o.clipStart != null) c.video = { start: o.clipStart };
  back.cuts.push(c);
  S.project.media = J.media.normalize(S.project.media);     // the same checks as a project file
  J.uiApi.replan(); J.uiApi.flushSave();
  return c.id;
}"""

# one lyric line: its own settings and the cuts it became
JS_LINE = r"""(li) => {
  const S = J.ui, P = S.project, ln = S.plan.lines[li], ov = P.overrides[li] || {}, T = P.media.text.lines[li] || {};
  const r2 = x => Math.round(x * 100) / 100 || 0;
  const style = {};
  for (const k of ['layout', 'enter', 'exit', 'hold', 'cam', 'trans', 'bg', 'treat', 'cuts', 'single', 'decor', 'cutTime', 'cutTech', 'lock']) if (ov[k] != null) style[k] = ov[k];
  if (style.cutTime) style.cutTime = Object.keys(style.cutTime).sort((a, b) => a - b).map(k => style.cutTime[k]);
  const wt = J.media.lineWords(P.media, ln);
  const place = Object.assign({}, T); delete place.heldTimes;
  return { line: li + 1, text: ln.text, start: r2(ln.start), end: r2(ln.end), interlude: !!ln.interlude, style, place,
    // used: false = this word's time is not used for the cut starts (confidence below J.media.WEAK_WORD, or outside the line)
    words: wt ? wt.w.map(x => ({ t: r2(x[0]), at: x[1], text: [...J.media.normText(ln.text)].slice(x[1], (wt.w.find(y => y[1] > x[1]) || [0, 9999])[1]).join(''),
      p: x[2] != null ? r2(x[2]) : null, used: J.media.usableWord(x, ln) })) : [],
    confidence: wt && wt.p != null ? r2(wt.p) : null,
    cutTimes: style.cutTime ? (Object.keys(ov.cutTime).every(k => (T.heldTimes || []).includes(+k)) ? 'locked' : 'by hand') : wt ? 'words' : 'auto',
    cuts: J.media.lineCuts(S.plan, li).map((c, k) => ({ cut: k + 1, text: c.utext, start: r2(c.start), end: r2(c.end), layout: c.layout,
      enter: c.enter, exit: c.exit, hold: c.hold, cam: c.cam === 'place' ? (c.camP || {}).base : c.cam, bg: c.bg, decor: (c.decor || []).map(d => d.id),
      treat: c.treat, trans: c.trans || null, color: (S.plan.style.schemes[c.scheme] || {}).fg, sung: c.sungAt != null ? r2(c.sungAt) : null })) };
}"""

JS_SET_LINE_STYLE = r"""(o) => {
  const S = J.ui, P = S.project, li = o.li;
  const wasLocked = !!(P.overrides[li] || {}).lock;
  J.media.unlockLine(P, li);                     // re-locked below with the new look (the cut times a lock kept go too)
  const m = P.media, ov = Object.assign({}, P.overrides[li] || {});
  const put = (obj, k, v) => { if (v === undefined) return; if (v === null || v === 'auto') delete obj[k]; else obj[k] = v; };
  if (o.cut == null) {
    for (const k of ['layout', 'enter', 'exit', 'hold', 'cam', 'trans', 'bg', 'treat', 'cuts', 'single', 'decor', 'cutTime']) put(ov, k, o[k]);
  } else {                                       // このカットだけ (the app's cutTech: layout / motion / camera / treatment / transition)
    const ct = Object.assign({}, ov.cutTech || {}), t = Object.assign({}, ct[o.cut] || {});
    for (const k of ['layout', 'enter', 'exit', 'hold', 'cam', 'trans', 'treat', 'bg', 'decor']) put(t, k, o[k]);   // (decor: one key or 'none')
    if (Object.keys(t).length) ct[o.cut] = t; else delete ct[o.cut];
    if (Object.keys(ct).length) ov.cutTech = ct; else delete ov.cutTech;
  }
  // placement / size / colour (project.media.text)
  const lines = Object.assign({}, m.text.lines), L = Object.assign({}, lines[li] || {});
  const tg = o.cut == null ? L : Object.assign({}, (L.cuts || {})[o.cut] || {});
  for (const [k, v] of [['x', o.x], ['y', o.y], ['scale', o.size], ['color', o.color]]) put(tg, k, v);
  if (o.cut != null) { const cs = Object.assign({}, L.cuts || {}); if (Object.keys(tg).length) cs[o.cut] = tg; else delete cs[o.cut]; if (Object.keys(cs).length) L.cuts = cs; else delete L.cuts; }
  if (o.reset) { for (const k of Object.keys(ov)) delete ov[k]; for (const k of Object.keys(L)) delete L[k]; }
  if (Object.keys(L).length) lines[li] = L; else delete lines[li];
  m.text = Object.assign({}, m.text, { lines });
  P.media = J.media.normalize(m);
  if (Object.keys(ov).length) P.overrides[li] = ov; else delete P.overrides[li];
  J.uiApi.replan();
  // 固定: the line keeps exactly this look when other lines are rolled again (the app's line lock)
  if (o.lock === true || (o.lock == null && wasLocked && !o.reset)) {
    if (J.media.lockLine(P, S.plan, li)) J.uiApi.replan();
  }
  J.uiApi.flushSave();
}"""

# the cuts in a time range as the app made them (read-only)
JS_MOTION = r"""([a, b]) => {
  const S = J.ui, P = S.project, plan = S.plan, ovs = P.overrides || {}, r3 = x => Math.round(x * 1000) / 1000;
  const cuts = plan.cuts.filter(c => c.end > a && (b == null || c.start < b)).map(c => {
    const own = c.utext != null ? J.media.lineCuts(plan, c.line) : null;
    return { line: c.line + 1, cut: own ? own.indexOf(c) + 1 : null, interlude: c.utext == null, start: r3(c.start), end: r3(c.end),
      text: c.utext != null ? c.utext : '', lineText: c.lineText || '', recap: !!c.recap, layout: c.layout, enter: c.enter, exit: c.exit,
      hold: c.hold, treat: c.treat || null, cam: c.cam === 'place' ? (c.camP || {}).base : c.cam, trans: c.trans || null, bg: c.bg || null,
      decor: (c.decor || []).map(d => d.id), params: c.params || {}, scheme: c.scheme, inDur: r3(c.inDur), outDur: r3(c.outDur), seed: c.seed,
      locked: !!(ovs[c.line] || {}).lock };
  });
  const distinct = k => [...new Set(cuts.filter(c => !c.interlude).map(c => c[k]).filter(Boolean))];
  return { range: [a, b], duration: r3(S.plan.lines.length ? Math.max(...plan.cuts.map(c => c.end)) : 0), seed: P.seed, theme: P.themeId || null,
    style: P.style, mood: P.mood, fx: P.fx, cutCount: cuts.length,
    inventory: Object.fromEntries(['layout', 'enter', 'exit', 'hold', 'treat', 'cam'].map(k => [k, distinct(k)])), cuts };
}"""

# 固定 for every lyric line in a time range (+ the project's colours / chroma when given)
JS_LOCK_RANGE = r"""(o) => {
  const S = J.ui, P = S.project;
  const n0 = J.resolveStyle(P).schemes.length;
  if (o.scheme != null && !(o.scheme >= 0 && o.scheme < n0)) return { error: `scheme は 0〜${n0 - 1}（このスタイルの配色の数）: ${o.scheme}` };
  const ids = [...new Set(S.plan.cuts.filter(c => c.utext != null && c.end > o.start && c.start < o.end).map(c => c.line))].sort((x, y) => x - y);
  if (o.lock) for (const li of ids) J.media.lockLine(P, S.plan, li, o.scheme);
  else for (const li of ids) J.media.unlockLine(P, li);
  // the project's colours (every line, as the 配色 panel): base colours go into scheme 0, accent / ghosts into every scheme
  const changed = [];
  const c = Object.assign({}, P.colors);
  for (const [k, v] of [['bg', o.bg], ['fg', o.fg], ['sub', o.sub]]) if (v) { c[k] = v; c.enabled = true; changed.push(k); }
  for (const [k, v] of [['accent', o.accent], ['ghostA', o.ghostA], ['ghostB', o.ghostB]]) if (v) { c[k] = v; c.accentOn = true; changed.push(k); }
  if (changed.length) P.colors = c;
  if (o.chroma != null) { P.fx = Object.assign({}, P.fx, { chroma: o.chroma }); changed.push('chroma'); }
  J.uiApi.syncUI(); J.uiApi.replan(); J.uiApi.flushSave();
  return { lines: ids.map(li => li + 1), locked: !!o.lock, scheme: o.lock ? o.scheme : null, global: changed,
    colors: changed.some(k => k !== 'chroma') ? P.colors : undefined, chroma: P.fx.chroma };
}"""

# word times only (the lyrics stay): a word list / enhanced LRC / lines with words
JS_SET_WORDS = r"""([text, name]) => {
  const S = J.ui, P = S.project, r2 = x => Math.round(x * 100) / 100 || 0;
  const r = J.lyricsImport.toLrc(String(text), name || '');
  if (J.lyricsImport) J.lyricsImport.last = null;
  if (!(r.words || []).length) return { error: 'このファイルには語ごとの時刻がありません（Suno の aligned_words・WhisperX の単語・拡張 LRC・words 付きの lines）' };
  P.media.text = Object.assign({}, P.media.text, { words: r.words });
  P.media = J.media.normalize(P.media);
  J.uiApi.replan(); J.uiApi.flushSave();
  const used = new Set();
  const lines = S.plan.lines.filter(ln => !ln.interlude).map(ln => { const e = J.media.lineWords(P.media, ln); if (e) used.add(e); return [ln, e]; });
  return { entries: P.media.text.words.length, lines: lines.length, wordTimed: lines.filter(x => x[1]).length,
    without: lines.filter(x => !x[1]).slice(0, 40).map(([ln]) => ({ line: ln.index + 1, text: ln.text })),
    unmatched: P.media.text.words.filter(e => !used.has(e)).slice(0, 40).map(e => ({ text: e.text, start: r2(e.start) })),
    weak: lines.filter(([ln, e]) => e && e.w.some(w => !J.media.usableWord(w, ln))).map(([ln, e]) => ({ line: ln.index + 1, text: ln.text,
      confidence: e.p != null ? r2(e.p) : null, unused: e.w.filter(w => !J.media.usableWord(w, ln)).length, words: e.w.length })),
    // cuts that could not start when they are sung (more than 0.3 s off: the line is shown shorter than it is sung, or cuts too close)
    off: lines.map(([ln]) => [ln, J.media.lineCuts(S.plan, ln.index).filter(c => c.sungAt != null && Math.abs(c.start - c.sungAt) > 0.3)])
      .filter(x => x[1].length).map(([ln, cs]) => ({ line: ln.index + 1, text: ln.text, shownUntil: r2(ln.visEnd),
        cuts: cs.map(c => ({ text: c.utext, start: r2(c.start), sung: r2(c.sungAt) })) })) };
}"""

JS_SET_LOOK = r"""(o) => {
  const S = J.ui, P = S.project;
  if ('theme' in o) P.themeId = o.theme && J.THEMES[o.theme] ? o.theme : null;
  if (o.variation != null) {
    // おまかせ (as the button does, within the theme when one is set), with a fixed random stream: the same variation, the same look
    const th = J.THEMES[P.themeId] ? P.themeId : null;
    const r = J.omakase(P, J.rng(o.variation >>> 0), th);
    Object.assign(P, r);
  }
  if (o.style) { P.style = o.style; P.colors.enabled = false; }
  if (o.mood) P.mood = o.mood;
  if (o.seed != null) P.seed = o.seed >>> 0;
  J.uiApi.syncUI(); J.uiApi.replan(); J.uiApi.flushSave();
  return { theme: P.themeId, style: P.style, styleName: J.STYLES[P.style].name, mood: P.mood, seed: P.seed };
}"""

JS_SET_MEDIA = r"""(o) => {
  const S = J.ui, m = S.project.media, A = m.autoFill.back, T = m.tracks.back;
  if (o.auto != null) A.mode = o.auto ? 'perLine' : 'off';
  for (const k of ['order', 'hold', 'fit', 'trans', 'enter', 'exit', 'treat']) if (o[k] != null) A[k] = o[k];
  if (o.scrim != null || o.scrimAmount != null) m.scrim = Object.assign({}, m.scrim, o.scrim != null ? { mode: o.scrim } : {}, o.scrimAmount != null ? { amount: o.scrimAmount } : {});
  if (o.shuffle != null) A.seed = o.shuffle;
  if (o.dim != null) T.dim = o.dim;
  if (o.lyricBg != null) m.lyricBg = o.lyricBg ? 'over' : 'off';
  A.video = Object.assign({ extend: 'loop', rate: 1, beats: 4 }, A.video, o.video || {});
  S.project.media = J.media.normalize(m);                 // the same checks as a project file
  J.uiApi.replan(); J.uiApi.flushSave();
}"""

JS_SET_OUTPUT = r"""(o) => {
  const S = J.ui, P = S.project;
  for (const k of ['aspect', 'res', 'fps', 'quality', 'includeAudio']) if (o[k] != null) P[k] = o[k];
  J.uiApi.syncUI(); J.uiApi.replan(); J.uiApi.flushSave();
}"""

JS_PREVIEW = r"""async ([times, width]) => {
  const S = J.ui, plan = S.plan;
  try { await document.fonts.ready; } catch (e) {}
  const w = Math.max(64, Math.round(width / 2) * 2), h = Math.max(36, Math.round(width * plan.H / plan.W / 2) * 2);
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const x = c.getContext('2d', { alpha: false }), out = [];
  // one renderer for every preview of this page: its paper / grain textures are made once (at random), so frames compare across calls
  const R = window.__jzR || (window.__jzR = new J.Renderer());
  for (const t of times) {
    if (plan.media) await J.media.prepareFrame(plan, t);          // clips at their exact frame, as in an export
    R.frame(x, plan, t, { scale: w / plan.W });
    const ln = plan.lines.find(l => t >= l.start && t < l.end);
    out.push({ t, text: ln ? ln.text : '', png: c.toDataURL('image/png').split(',')[1] });
  }
  return out;
}"""

JS_EXPORT = r"""async (o) => {
  const S = J.ui;
  try { await document.fonts.ready; } catch (e) {}
  J.uiApi.pause();
  const P = Object.assign({}, S.project);
  if (o.res) P.res = o.res;
  if (o.audio === false) P.includeAudio = false;
  const range = o.t0 != null || o.t1 != null ? { t0: o.t0 || 0, t1: o.t1 != null ? o.t1 : S.plan.duration } : null;
  let last = 0;
  const onProgress = (f, msg) => { const n = performance.now(); if (n - last > 1500 || f >= 1) { last = n; console.log('[jz-progress] ' + f.toFixed(4) + ' ' + msg); } };
  const r = await J.exportMP4({ plan: S.plan, project: P, audio: P.includeAudio !== false ? S.audio : null, quality: o.quality || P.quality || 'high', onProgress, range });
  await J.saveFile(o.name, r.blob);
  const span = J.exportSpan(S.plan, range), fps = S.plan.fps, frames = Math.max(1, Math.round(span.dur * fps));
  const audioDur = r.audio && S.audio ? Math.min(span.dur, S.audio.buffer.duration - span.t0) : null;
  // the planned length, and what was written: whole video frames (the last partial frame is not drawn) and the sound
  return { codec: r.codec, audio: r.audio, audioWanted: r.audioWanted, width: r.width, height: r.height, size: r.size, duration: span.dur,
    fps, frames, videoDuration: frames / fps, audioDuration: audioDur };
}"""


class Jizura:
    """one app page in a headless browser. Not thread-safe: await one call at a time."""

    def __init__(self, app=None, browser='auto', headless=True, log=None):
        self.app = app or os.path.join(ROOT, 'index.html')
        self.browser_pref = browser                    # 'auto' | 'chrome' | 'msedge' | 'chromium'
        self.headless = headless
        self.log = log or (lambda msg: print(msg, file=sys.stderr))
        self.progress = None                           # (fraction, message) of a running export
        self.errors = []                               # page errors (exceptions thrown in the page)
        self.browser_name = None
        self._pw = self._browser = self._srv = self.page = None
        self._tmp = tempfile.TemporaryDirectory(prefix='jizura-')

    # ------------------------------------------------------------ life cycle
    async def __aenter__(self):
        await self.start(); return self

    async def __aexit__(self, *exc):
        await self.close()

    async def start(self):
        from playwright.async_api import async_playwright
        if re.match(r'https?://', self.app):
            url = self.app; allowed = {urllib.parse.urlparse(url).hostname}
        else:
            path = os.path.abspath(self.app)
            if os.path.isdir(path): path = os.path.join(path, 'index.html')
            if not os.path.isfile(path): raise JizuraError(f'アプリが見つかりません: {path}（先に python3 build.py）')
            self._srv = _serve(os.path.dirname(path))
            url = f'http://127.0.0.1:{self._srv.server_port}/{os.path.basename(path)}'; allowed = {'127.0.0.1'}
        self._pw = await async_playwright().start()
        await self._launch()
        ctx = await self._browser.new_context(viewport={'width': 1400, 'height': 900}, accept_downloads=True)
        await ctx.add_init_script("try { localStorage.setItem('jizura.tourDone', '1'); } catch (e) {}")   # no first-visit tour

        async def route(r):
            host = urllib.parse.urlparse(r.request.url).hostname
            if host in allowed or host in FONT_HOSTS: await r.continue_()
            else: await r.abort()
        await ctx.route('**/*', route)
        self.page = pg = await ctx.new_page()
        pg.on('pageerror', lambda e: self.errors.append(str(e)))
        pg.on('dialog', lambda d: asyncio.ensure_future(d.accept()))       # 「置き換えますか？」「外しますか？」 → yes
        pg.on('console', self._console)
        await pg.goto(url)
        try: await pg.wait_for_function(JS_READY, timeout=60000)
        except Exception as e: raise JizuraError(f'アプリを開けませんでした（このフォークの index.html ですか？）: {e}')
        await pg.evaluate("""() => { const i = document.createElement('input'); i.type = 'file'; i.multiple = true; i.id = 'jzDriverFiles';
          i.style.display = 'none'; document.body.appendChild(i); }""")
        self.log(f'jizura: {self.browser_name} で {url} を開きました')

    async def _launch(self):
        order = {'auto': ['chrome', 'msedge', 'chromium'], 'chrome': ['chrome'], 'msedge': ['msedge'], 'chromium': ['chromium']}.get(self.browser_pref)
        if not order: raise JizuraError(f'browser は auto / chrome / msedge / chromium のどれか: {self.browser_pref}')
        last = None
        for ch in order:
            try:
                kw = {} if ch == 'chromium' else {'channel': ch}
                self._browser = await self._pw.chromium.launch(headless=self.headless, **kw)
                self.browser_name = {'chrome': 'Google Chrome', 'msedge': 'Microsoft Edge', 'chromium': 'Chromium (Playwright)'}[ch]
                return
            except Exception as e: last = e
        raise JizuraError(f'ブラウザを起動できませんでした: {last}')

    async def close(self):
        try:
            if self._browser: await self._browser.close()
        finally:
            if self._pw: await self._pw.stop()
            if self._srv: self._srv.shutdown()
            self._tmp.cleanup()
            self._browser = self._pw = self._srv = self.page = None

    def _console(self, msg):
        t = msg.text
        if t.startswith('[jz-progress] '):
            f, _, m = t[14:].partition(' ')
            try: self.progress = (float(f), m)
            except ValueError: return
            self.log(f'  {float(f) * 100:5.1f}%  {m}')

    async def _files(self, paths):
        for p in paths:
            if not os.path.isfile(p): raise JizuraError(f'ファイルが見つかりません: {p}')
        await self.page.set_input_files('#jzDriverFiles', [os.path.abspath(p) for p in paths])

    async def _ev(self, js, arg=None):
        return await self.page.evaluate(js, arg)

    # ------------------------------------------------------------ queries
    async def status(self):
        """browser and what it can read / write (H.264 needs Google Chrome or Edge)"""
        s = await self._ev(JS_STATUS)
        s.update(browser=self.browser_name, appVersion=_version(), pageErrors=self.errors[-5:])
        if not s['h264Decode']: s['note'] = 'このブラウザは H.264 の MP4 を読めません（動画は WebM にするか、Google Chrome を入れて browser=chrome）'
        return s

    async def options(self):
        """the values the setters accept"""
        o = await self._ev(JS_OPTIONS)
        o.update(aspects=ASPECTS, res=RES, fps=FPS, quality=QUALITY, mediaOrder=MEDIA_ORDER, mediaHold=MEDIA_HOLD, mediaFit=MEDIA_FIT,
                 mediaJoin=['fade', 'cut', 'mix'] + list(o['transitions']), mediaEnter=MEDIA_ENTER, mediaTreat=MEDIA_TREAT, mediaScrim=MEDIA_SCRIM,
                 videoExtend=VIDEO_EXTEND, videoRates=VIDEO_RATES, videoBeats=VIDEO_BEATS)
        return o

    async def get_plan(self):
        """the project as the panel shows it: lines with their times and pictures, the look, the song, the pictures"""
        return await self._ev(JS_PLAN)

    # ------------------------------------------------------------ project
    async def _open_json(self, path):
        await self._ev('() => { window.__jzOld = J.ui.project; }')
        await self.page.set_input_files('#fileProject', path)
        try: await self.page.wait_for_function('J.ui.project !== window.__jzOld', timeout=15000)
        except Exception: raise JizuraError('プロジェクトを読み込めませんでした（JSON が壊れていないか確認してください）')

    async def new_project(self, title='', artist='', aspect='16:9', lyrics=None):
        """a new, empty project (the song, if loaded, stays). lyrics: text (LRC tags allowed)"""
        if aspect not in ASPECTS: raise JizuraError(f'aspect は {ASPECTS} のどれか: {aspect}')
        p = os.path.join(self._tmp.name, 'new.jizura.json')
        with open(p, 'w', encoding='utf-8') as f: json.dump({'title': str(title)[:200], 'artist': str(artist)[:200], 'aspect': aspect, 'lyrics': ''}, f, ensure_ascii=False)
        await self._open_json(p)
        if lyrics: await self.set_lyrics(text=lyrics)
        return await self.get_plan()

    async def open_project(self, path):
        """a saved .jizura.json (checked like the 「開く」 button). Its pictures must be added again with add_media()
        (they are matched by content, so the per-line choices come back)"""
        if not os.path.isfile(path): raise JizuraError(f'ファイルが見つかりません: {path}')
        await self._open_json(os.path.abspath(path))
        await asyncio.sleep(0.3)
        return await self.get_plan()

    async def save_project(self, path):
        """the project as .jizura.json (the same as 「保存」; pictures are referenced, not included)"""
        txt = await self._ev('(v) => JSON.stringify(Object.assign({}, J.ui.project, { appVersion: v }), null, 1)', _version())
        with open(path, 'w', encoding='utf-8') as f: f.write(txt)
        return path

    # ------------------------------------------------------------ inputs
    async def set_lyrics(self, text=None, path=None):
        """lyrics as text, or a file: LRC / SRT / VTT / Whisper・Suno JSON (with times) or plain text (one line per phrase)"""
        if path is not None:
            if not os.path.isfile(path): raise JizuraError(f'ファイルが見つかりません: {path}')
            text, name = read_text(path), os.path.basename(path)
        elif text is None: raise JizuraError('text か path を指定してください')
        else: name = ''
        if len(text) > 2_000_000: raise JizuraError('歌詞が長すぎます')
        return await self._ev(JS_SET_LYRICS, [text, name])

    async def load_song(self, path):
        """the song (mp3 / wav / m4a … or the sound of a video file): duration and tempo are analysed"""
        await self._files([path])
        r = await self._ev(JS_LOAD_SONG)
        if 'error' in r: raise JizuraError(f'曲を読み込めませんでした: {r["error"]}')
        return r

    async def add_media(self, paths):
        """pictures and clips (files or folders). Returns what was added and what could not be read"""
        files = media_files(paths)
        if not files: raise JizuraError('画像・動画のファイルがありません')
        await self._files(files)
        r = await self._ev(JS_ADD_MEDIA)
        if r.get('error'): raise JizuraError('画像・動画を読み込めませんでした（ほかの読み込みの途中か、読み込みに失敗）')
        r['total'] = await self._ev('() => J.ui.project.media.assets.length')
        return r

    async def _asset_id(self, ref):
        """a picture by name, id or number (1 = first in the list)"""
        assets = await self._ev('() => J.ui.project.media.assets.map(a => [a.id, a.name])')
        s = str(ref)
        if s.isdigit() and 1 <= int(s) <= len(assets): return assets[int(s) - 1][0]
        for i, n in assets:
            if s in (i, n): return i
        hits = [i for i, n in assets if os.path.splitext(n)[0] == s]
        if len(hits) == 1: return hits[0]
        raise JizuraError(f'画像・動画が見つかりません: {ref}（{", ".join(n for _, n in assets) or "まだありません"}）')

    async def remove_media(self, ref):
        await self._ev('(id) => J.mediaUI.remove(id)', await self._asset_id(ref))
        await self.page.wait_for_timeout(200)
        return await self._ev('() => J.ui.project.media.assets.map(a => a.name)')

    async def add_timed_media(self, media, start=0, end=None, clip_start=None, fit=None):
        """a picture or clip at a time of the song (seconds), e.g. one clip under the whole song: start=0, end=None (= until the next
        timed one, or the end). It covers the automatic per-line pictures there; a picture chosen for a line still shows over it, and a
        clip keeps running on its own clock (it never restarts at a lyric line). media='none' leaves that time without a picture.
        clip_start: where in the clip to begin (seconds). Returns the id (for remove_timed_media)"""
        start = float(start)
        if start < 0 or (end is not None and float(end) <= start): raise JizuraError(f'start / end の範囲が正しくありません: {start} / {end}')
        if fit is not None and fit not in MEDIA_FIT: raise JizuraError(f'fit は {MEDIA_FIT} のどれか: {fit}')
        aid = '' if media == 'none' else await self._asset_id(media)
        cid = await self._ev(JS_ADD_TIMED, {'assetId': aid, 'start': start, 'end': None if end is None else float(end),
                                             'clipStart': None if clip_start is None else float(clip_start), 'fit': fit})
        p = await self.get_plan()
        return {'id': cid, 'timed': p['timed'], 'cuts': len(p['cuts'])}

    async def remove_timed_media(self, id='all'):
        """remove one picture placed at a time (its id from get_plan's 'timed'), or all of them"""
        n = await self._ev('''(id) => { const back = J.ui.project.media.tracks.back, before = back.cuts.length;
          back.cuts = back.cuts.filter(c => c.lineRef || (id !== 'all' && c.id !== id)); J.uiApi.replan(); J.uiApi.flushSave(); return before - back.cuts.length; }''', str(id))
        if not n: raise JizuraError(f'時刻で置いた画像・動画が見つかりません: {id}')
        return {'removed': n, 'timed': (await self.get_plan())['timed']}

    async def _line_index(self, line):
        n = await self._ev('() => J.ui.plan.lines.length')
        if not (isinstance(line, int) and 1 <= line <= n): raise JizuraError(f'line は 1〜{n}: {line}')
        return line - 1

    async def get_line(self, line):
        """one lyric line (1 = first): its text and time, its own settings (style: the app's per-line settings, place: position /
        size / colour) and the cuts it became (text, time, layout, motion, camera, background, decorations, colour)"""
        return await self._ev(JS_LINE, await self._line_index(line))

    async def set_line_style(self, line, cut=None, layout=None, enter=None, exit=None, hold=None, cam=None, trans=None, bg=None, decor=None,
                             treat=None, cuts=None, cut_times=None, single=None, x=None, y=None, size=None, color=None, lock=None, reset=False):
        """fix how a lyric line looks (or only its cut `cut`, 1 = first; a cut takes one decoration at most). Parts by key (see options()['lyric']);
        'auto' = back to automatic.
        cuts: how many cuts the line is split into; cut_times: when cuts 2, 3 … start (seconds from the line start); single: one cut.
        x / y: move the lyric (-0.5 … 0.5 of the frame), size: 0.2 … 3, color: '#rrggbb' text colour.
        lock: keep exactly this look when other lines change (a locked line is re-locked after a change). reset: clear everything"""
        li = await self._line_index(line)
        O = (await self.options())['lyric']
        o = {'li': li}
        for k, v in (('layout', layout), ('enter', enter), ('exit', exit), ('hold', hold), ('cam', cam), ('treat', treat), ('bg', bg)):
            if v is None: continue
            ok = list(O[k]) + ['auto'] + (['none'] if k in ('bg', 'treat') else [])
            if v not in ok: raise JizuraError(f'{k} は options の lyric.{k} のどれか（または auto）: {v}')
            o[k] = v
        if trans is not None:
            if trans not in list(O['trans']) + ['auto', 'none']: raise JizuraError(f'trans は options の lyric.trans・none・auto のどれか: {trans}')
            o['trans'] = trans
        if cut is not None:
            n = len((await self.get_line(line))['cuts'])
            if not (isinstance(cut, int) and 1 <= cut <= max(n, 12)): raise JizuraError(f'cut は 1〜{n}: {cut}')
            if any(v is not None for v in (cuts, cut_times, single)): raise JizuraError('cuts / cut_times / single は行全体の指定です（cut なしで）')
            o['cut'] = cut - 1
        if decor is not None:
            if decor == 'auto': o['decor'] = 'auto'
            else:
                if isinstance(decor, str): decor = [] if decor == 'none' else [decor]
                bad = [d for d in decor if d not in O['decor']]
                if bad: raise JizuraError(f'decor にない装飾: {bad}')
                if cut is None: o['decor'] = list(decor)
                elif len(decor) > 1: raise JizuraError('カットごとの装飾は 1 つまで（行全体なら cut なしで）')
                else: o['decor'] = decor[0] if decor else 'none'
        if cuts is not None:
            if cuts != 'auto' and not (isinstance(cuts, int) and 1 <= cuts <= 12): raise JizuraError(f'cuts は 1〜12 か auto: {cuts}')
            o['cuts'] = cuts
        if cut_times is not None:
            if cut_times == 'auto' or not cut_times: o['cutTime'] = 'auto'
            else:
                ts = [float(t) for t in cut_times]
                if any(t <= 0 for t in ts) or ts != sorted(ts): raise JizuraError(f'cut_times は行の頭からの秒（増えていく順）: {cut_times}')
                o['cutTime'] = {str(i + 1): t for i, t in enumerate(ts)}
                if cuts is None: o['cuts'] = len(ts) + 1
        if single is not None: o['single'] = True if single else 'auto'
        for k, v, lo, hi in (('x', x, -0.5, 0.5), ('y', y, -0.5, 0.5), ('size', size, 0.2, 3)):
            if v is None: continue
            if v == 'auto': o[k] = 'auto'; continue
            if not (lo <= float(v) <= hi): raise JizuraError(f'{k} は {lo}〜{hi}: {v}')
            o[k] = float(v)
        if color is not None:
            if color != 'auto' and not re.match(r'^#[0-9a-fA-F]{6}$', str(color)): raise JizuraError(f'color は #rrggbb: {color}')
            o['color'] = color
        if lock is not None: o['lock'] = bool(lock)
        if reset: o['reset'] = True
        await self._ev(JS_SET_LINE_STYLE, o)
        return await self.get_line(line)

    async def get_motion_plan(self, start=0, end=None):
        """the cuts the app made in [start, end) seconds (end None = to the end): line (1 = first) / cut number, time, text, layout,
        enter / exit / hold, treatment, camera, transition, background, decorations, params, colour scheme, in / out durations, seed,
        locked — and which parts the range uses. Read-only"""
        if start < 0 or (end is not None and end <= start): raise JizuraError('0 <= start < end の区間を指定してください')
        return await self._ev(JS_MOTION, [float(start), None if end is None else float(end)])

    async def lock_motion_palette(self, start, end, lock=True, scheme=None, bg_color=None, text_color=None, sub_color=None,
                                  accent_color=None, ghost_a=None, ghost_b=None, chroma=None):
        """固定 for every lyric line that plays in [start, end): each keeps its cuts, motion and cut times when other lines change
        (lock=False lets them go). scheme: pin their cuts to this colour scheme (0 = the main one; bg / text / sub colours apply there —
        given one of them, scheme defaults to 0). The colours and chroma are the PROJECT's (every line), as in the 配色 panel"""
        if start < 0 or end <= start: raise JizuraError('0 <= start < end の区間を指定してください')
        cols = {'bg': bg_color, 'fg': text_color, 'sub': sub_color, 'accent': accent_color, 'ghostA': ghost_a, 'ghostB': ghost_b}
        for k, v in cols.items():
            if v is not None and not re.match(r'^#[0-9a-fA-F]{6}$', str(v)): raise JizuraError(f'色は #rrggbb: {k}={v}')
        if chroma is not None and not 0 <= float(chroma) <= 1: raise JizuraError(f'chroma は 0〜1: {chroma}')
        if scheme is not None and not isinstance(scheme, int): raise JizuraError(f'scheme は配色の番号（0 = 基本）: {scheme}')
        if scheme is None and lock and any(cols[k] for k in ('bg', 'fg', 'sub')): scheme = 0
        if not lock and scheme is not None: raise JizuraError('scheme は lock=True のときだけ')
        o = {'start': float(start), 'end': float(end), 'lock': bool(lock), 'scheme': scheme, 'chroma': None if chroma is None else float(chroma)}
        o.update({k: (v.lower() if v else None) for k, v in cols.items()})
        r = await self._ev(JS_LOCK_RANGE, o)
        if 'error' in r: raise JizuraError(r['error'])
        return r

    async def set_word_times(self, text=None, path=None):
        """word times only (the lyrics and every setting stay): Suno aligned_words / WhisperX words / enhanced LRC / JSON lines that
        carry their own words. A line takes the entry with the same text that starts nearest to it. Returns which lines have them,
        the entries no line took, and the lines with words whose time is not used (confidence below 0.1, or outside the line)"""
        if path is not None:
            if not os.path.isfile(path): raise JizuraError(f'ファイルが見つかりません: {path}')
            text, name = read_text(path), os.path.basename(path)
        elif text is None: raise JizuraError('text か path を指定してください')
        else: name = ''
        if len(text) > 5_000_000: raise JizuraError('ファイルが大きすぎます')
        r = await self._ev(JS_SET_WORDS, [text, name])
        if 'error' in r: raise JizuraError(r['error'])
        return r

    async def set_text_options(self, interlude_title=None):
        """interlude_title: show the song title / artist on long interludes (the title stays in the project either way)"""
        if interlude_title is not None:
            await self._ev('''(v) => { const m = J.ui.project.media; m.text = Object.assign({}, m.text, { interludeTitle: v ? 'show' : 'hide' });
              J.ui.project.media = J.media.normalize(m); J.uiApi.replan(); J.uiApi.flushSave(); }''', bool(interlude_title))
        return {'interludeTitle': await self._ev('() => J.ui.project.media.text.interludeTitle') == 'show'}

    async def relink_media(self, paths):
        """bring back the pictures / clips a project names but this browser has not loaded: files are matched by their content
        (the id is the start of their SHA-256), so a renamed file is found too and a different file with the same name is not"""
        import hashlib
        missing = await self._ev('() => J.ui.project.media.assets.filter(a => !J.mediaAssets.has(a.id)).map(a => [a.id, a.name])')
        want = {i: n for i, n in missing}
        hits, seen = [], set()
        for f in media_files(paths):
            h = hashlib.sha256()
            with open(f, 'rb') as fh:
                for b in iter(lambda: fh.read(1 << 20), b''): h.update(b)
            i = h.hexdigest()[:12]
            if i in want and i not in seen: hits.append(f); seen.add(i)
        if hits: await self.add_media(hits)
        still = await self._ev('() => J.ui.project.media.assets.filter(a => !J.mediaAssets.has(a.id)).map(a => a.name)')
        return {'relinked': [want[i] for i in seen], 'files': [os.path.basename(f) for f in hits], 'missing': still}

    async def set_line_media(self, line, media):
        """the picture behind lyric line `line` (1 = first): a name / id / number, 'none' (画像なし) or 'auto' (in turn)"""
        n = await self._ev('() => J.ui.plan.lines.length')
        if not (isinstance(line, int) and 1 <= line <= n): raise JizuraError(f'line は 1〜{n}: {line}')
        v = '' if media in (None, '', 'auto') else 'none' if media == 'none' else await self._asset_id(media)
        await self._ev(JS_SET_LINE, [line - 1, v])

    # ------------------------------------------------------------ look and output
    async def set_look(self, theme=None, style=None, mood=None, variation=None, seed=None):
        """theme (おまかせ within a direction) and/or variation (おまかせ again: the same number gives the same look);
        style / mood pin those after; seed = the cut layout. theme='' clears the theme"""
        o = await self.options(); arg = {}
        if theme is not None:
            if theme and theme not in o['themes']: raise JizuraError(f'theme は {list(o["themes"])} のどれか: {theme}')
            arg['theme'] = theme or None
            if variation is None and theme: variation = 1
        if style is not None and style not in o['styles']: raise JizuraError(f'style は {list(o["styles"])} のどれか: {style}')
        if mood is not None and mood not in o['moods']: raise JizuraError(f'mood は {list(o["moods"])} のどれか: {mood}')
        arg.update(style=style, mood=mood, variation=None if variation is None else int(variation), seed=None if seed is None else int(seed))
        return await self._ev(JS_SET_LOOK, arg)

    async def set_media_options(self, auto=None, order=None, hold=None, fit=None, dim=None, lyric_bg=None, shuffle=None, extend=None, rate=None, beats=None,
                                trans=None, enter=None, exit=None, treat=None, scrim=None, scrim_amount=None):
        """how the pictures fill the song: auto (one per line in turn), order, hold (kenburns = slow zoom, pan, push, drift, beatPulse, still),
        fit, dim (0–0.9, a dark veil so the lyrics stay readable), lyric_bg (also draw the lyrics' own background graphic), shuffle (a number:
        another random order), trans (between two pictures: fade / cut / mix / a transition key), enter / exit (fade / slide / zoom / wipe / cut,
        where no picture touches), treat (none / match / mono / sepia / duotone / blur), scrim (a plate behind the lyrics: auto / always / off)
        and scrim_amount (0–0.9); for clips: extend (when a clip is shorter than its line), rate, beats (extend='beat': restart every N beats)"""
        chk = lambda v, ok, k: None if v is None or v in ok else (_ for _ in ()).throw(JizuraError(f'{k} は {ok} のどれか: {v}'))
        chk(order, MEDIA_ORDER, 'order'); chk(hold, MEDIA_HOLD, 'hold'); chk(fit, MEDIA_FIT, 'fit')
        chk(trans, (await self.options())['mediaJoin'], 'trans'); chk(enter, MEDIA_ENTER, 'enter'); chk(exit, MEDIA_ENTER, 'exit')
        chk(treat, MEDIA_TREAT, 'treat'); chk(scrim, MEDIA_SCRIM, 'scrim')
        if scrim_amount is not None and not (0 <= float(scrim_amount) <= 0.9): raise JizuraError(f'scrim_amount は 0〜0.9: {scrim_amount}')
        chk(extend, VIDEO_EXTEND, 'extend'); chk(rate, VIDEO_RATES, 'rate'); chk(beats, VIDEO_BEATS, 'beats')
        if dim is not None and not (0 <= float(dim) <= 0.9): raise JizuraError(f'dim は 0〜0.9: {dim}')
        video = {k: v for k, v in (('extend', extend), ('rate', rate), ('beats', beats)) if v is not None}
        await self._ev(JS_SET_MEDIA, {'auto': auto, 'order': order, 'hold': hold, 'fit': fit, 'dim': None if dim is None else float(dim),
                                      'lyricBg': lyric_bg, 'shuffle': None if shuffle is None else int(shuffle), 'video': video,
                                      'trans': trans, 'enter': enter, 'exit': exit, 'treat': treat, 'scrim': scrim,
                                      'scrimAmount': None if scrim_amount is None else float(scrim_amount)})
        return (await self.get_plan())['mediaOptions']

    async def media_omakase(self):
        """メディアのおまかせ (as the button): motion, transitions, in / out, treatment, darkness and order picked together at random"""
        r = await self._ev('() => { const S = J.ui; const r = J.media.randomLook(S.project.media, !!(S.plan.beats && S.plan.beats.length)); J.uiApi.replan(); J.uiApi.flushSave(); return r; }')
        o = (await self.get_plan())['mediaOptions']; o['summary'] = r
        return o

    async def set_output(self, aspect=None, res=None, fps=None, quality=None, include_audio=None):
        if aspect is not None and aspect not in ASPECTS: raise JizuraError(f'aspect は {ASPECTS} のどれか: {aspect}')
        if res is not None and int(res) not in RES: raise JizuraError(f'res は {RES} のどれか: {res}')
        if fps is not None and int(fps) not in FPS: raise JizuraError(f'fps は {FPS} のどれか: {fps}')
        if quality is not None and quality not in QUALITY: raise JizuraError(f'quality は {QUALITY} のどれか: {quality}')
        await self._ev(JS_SET_OUTPUT, {'aspect': aspect, 'res': None if res is None else int(res), 'fps': None if fps is None else int(fps),
                                       'quality': quality, 'includeAudio': include_audio})
        p = await self.get_plan()
        return {k: p[k] for k in ('aspect', 'res', 'fps', 'quality', 'includeAudio', 'size', 'duration')}

    # ------------------------------------------------------------ outputs
    async def preview(self, times=None, count=6, width=640):
        """frames as PNG → [(t, lyric line shown, png bytes)]. No times: `count` frames spread over the lyric lines"""
        width = int(min(1920, max(64, width)))
        if not times:
            p = await self.get_plan(); L = p['lines']; count = max(1, min(24, int(count)))
            if L: times = [round((L[i]['start'] + L[i]['end']) / 2, 2) for i in sorted({round(k * (len(L) - 1) / max(1, count - 1)) for k in range(count)})]
            else: times = [round(p['duration'] * (k + 0.5) / count, 2) for k in range(count)]
        times = [float(t) for t in times][:24]
        out = await self._ev(JS_PREVIEW, [times, width])
        return [(o['t'], o['text'], base64.b64decode(o['png'])) for o in out]

    async def export_mp4(self, path, res=None, t0=None, t1=None, audio=True, quality=None):
        """the MP4 (as 「MP4 を書き出す」) to `path`. t0 / t1: only that part of the song (seconds). Progress goes to the log"""
        if res is not None and int(res) not in RES: raise JizuraError(f'res は {RES} のどれか: {res}')
        if quality is not None and quality not in QUALITY: raise JizuraError(f'quality は {QUALITY} のどれか: {quality}')
        self.progress = (0.0, '開始')
        arg = {'name': os.path.basename(path), 'res': None if res is None else int(res), 't0': t0, 't1': t1, 'audio': bool(audio), 'quality': quality}
        try:
            async with self.page.expect_download(timeout=0) as dl:
                info = await self._ev(JS_EXPORT, arg)
            await (await dl.value).save_as(path)
        except JizuraError: raise
        except Exception as e:
            m = re.sub(r'^.*?Error: ', '', str(e).split('\n')[0])
            raise JizuraError(f'書き出せませんでした: {m}')
        finally: self.progress = None
        info['path'] = path
        if info['audioWanted'] and not info['audio']: info['note'] = '音声を入れられませんでした（このブラウザの音声エンコーダー）'
        return info
