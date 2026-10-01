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
MEDIA_HOLD = ['kenburns', 'still']
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
  styles: Object.fromEntries(J.STYLE_ORDER.map(k => [k, J.STYLES[k].name])),
  moods: Object.fromEntries(Object.keys(J.MOODS).map(k => [k, J.MOODS[k].name])),
})"""

# summary of the current project and plan (what a person sees in the panel)
JS_PLAN = r"""() => {
  const S = J.ui, P = S.project, plan = S.plan, m = P.media, mp = plan.media;
  const name = id => { const a = J.media.assetById(P, id); return a ? a.name : null; };
  const r2 = x => Math.round(x * 100) / 100;
  const own = new Map(m.tracks.back.cuts.filter(c => c.lineRef).map(c => [c.lineRef.line, c.assetId]));
  return {
    title: P.title, artist: P.artist, aspect: P.aspect, res: P.res, fps: P.fps, quality: P.quality || 'high', includeAudio: P.includeAudio !== false,
    duration: r2(plan.duration), size: J.outputSize(P),
    look: { theme: P.themeId, style: P.style, styleName: J.STYLES[P.style] ? J.STYLES[P.style].name : P.style, mood: P.mood, seed: P.seed },
    song: S.audio ? { name: P.audioName, duration: r2(S.audio.duration), bpm: S.audio.bpm } : null,
    lines: plan.lines.map((ln, i) => {
      const c = mp ? J.media.cutAt(plan, ln.start + 0.001, 'back') : null;
      return { line: i + 1, start: r2(ln.start), end: r2(ln.end), text: ln.text, media: c ? name(c.assetId) : null,
        choice: own.has(i) ? (own.get(i) ? name(own.get(i)) : 'none') : 'auto' };
    }),
    media: m.assets.map((a, i) => ({ n: i + 1, name: a.name, id: a.id, type: a.type, w: a.w, h: a.h, duration: a.duration, loaded: J.mediaAssets.has(a.id) })),
    mediaOptions: { auto: m.autoFill.back.mode === 'perLine', order: m.autoFill.back.order, hold: m.autoFill.back.hold, fit: m.autoFill.back.fit,
      dim: m.tracks.back.dim, lyricBg: m.lyricBg, shuffle: m.autoFill.back.seed, video: m.autoFill.back.video },
    cuts: mp ? mp.back.cuts.map(c => ({ media: name(c.assetId), start: r2(c.start), end: r2(c.end) })) : [],
  };
}"""

JS_SET_LYRICS = r"""([text, name]) => {
  const S = J.ui, P = S.project;
  const r = J.lyricsImport.toLrc(String(text), name || '');
  J.uiApi.pause();
  // the same as 「LRC を読み込む」: line times, per-line settings and the export range belonged to the old lines
  P.lyrics = String(r.text).replace(/^﻿/, '').replace(/\r\n?/g, '\n').trim(); P.timing.lineTimes = {}; P.overrides = {}; P.exportRange = null;
  for (const k of J.media.TRACKS) P.media.tracks[k].cuts = P.media.tracks[k].cuts.filter(c => !c.lineRef);   // …and so did the per-line pictures
  const el = document.getElementById('lyrics'); if (el) el.value = P.lyrics;
  J.uiApi.syncUI(); J.uiApi.replan(); J.uiApi.flushSave();
  return { kind: name ? r.kind : 'text', lines: S.plan.lines.length, timed: J.parseLyrics(P.lyrics).lines.filter(l => l.lrc != null).length };
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
  for (const k of ['order', 'hold', 'fit']) if (o[k] != null) A[k] = o[k];
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
  for (const t of times) {
    if (plan.media) await J.media.prepareFrame(plan, t);          // clips at their exact frame, as in an export
    new J.Renderer().frame(x, plan, t, { scale: w / plan.W });
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
  return { codec: r.codec, audio: r.audio, audioWanted: r.audioWanted, width: r.width, height: r.height, size: r.size, duration: J.exportSpan(S.plan, range).dur };
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

    async def set_media_options(self, auto=None, order=None, hold=None, fit=None, dim=None, lyric_bg=None, shuffle=None, extend=None, rate=None, beats=None):
        """how the pictures fill the song: auto (one per line in turn), order, hold (kenburns = slow zoom), fit, dim (0–0.9, a dark veil
        so the lyrics stay readable), lyric_bg (also draw the lyrics' own background graphic), shuffle (a number: another random order),
        and for clips: extend (when a clip is shorter than its line), rate, beats (extend='beat': restart every N beats)"""
        chk = lambda v, ok, k: None if v is None or v in ok else (_ for _ in ()).throw(JizuraError(f'{k} は {ok} のどれか: {v}'))
        chk(order, MEDIA_ORDER, 'order'); chk(hold, MEDIA_HOLD, 'hold'); chk(fit, MEDIA_FIT, 'fit')
        chk(extend, VIDEO_EXTEND, 'extend'); chk(rate, VIDEO_RATES, 'rate'); chk(beats, VIDEO_BEATS, 'beats')
        if dim is not None and not (0 <= float(dim) <= 0.9): raise JizuraError(f'dim は 0〜0.9: {dim}')
        video = {k: v for k, v in (('extend', extend), ('rate', rate), ('beats', beats)) if v is not None}
        await self._ev(JS_SET_MEDIA, {'auto': auto, 'order': order, 'hold': hold, 'fit': fit, 'dim': None if dim is None else float(dim),
                                      'lyricBg': lyric_bg, 'shuffle': None if shuffle is None else int(shuffle), 'video': video})
        return (await self.get_plan())['mediaOptions']

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
