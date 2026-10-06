"""my-jizura: end-to-end check of the 素材込み file .jizura.zip (Phase 4-1) on the BUILT app (index.html).
usage: python3 build.py && python3 dev/bundle_e2e.py [--browser chromium]
Serves the repository root on :8771. Page A gets two pictures, a video clip, a song, an imported font and a picture placed over
the lyrics, then 「素材込みで保存」. Each check below opens a .zip in a NEW browser context (empty IndexedDB / localStorage, like
another PC):
  everything comes back (pictures, clip, font, song) and frames render the same as on page A · an MP4 can be exported ·
  a picture this browser did not have is reported when saving and after opening · a picture whose bytes do not match its id
  is left out · a .zip someone re-compressed (deflate) still opens.
Exit code 0 = all checks passed."""
import asyncio, base64, functools, hashlib, http.server, io, json, math, os, struct, sys, tempfile, threading, wave, zipfile
from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BROWSER = sys.argv[sys.argv.index('--browser') + 1] if '--browser' in sys.argv else 'chromium'
PORT = 8771
FONT = next((p for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf',
                         '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf') if os.path.isfile(p)), None)
LYRICS = '[00:00.50]夜明けの色を覚えてる\n[00:02.50]ほどけた声が遠くで鳴った\n[00:04.50]名前のない明日へ'

PNG = r"""async ([r, g, b]) => {
  const c = new OffscreenCanvas(640, 360), x = c.getContext('2d');
  x.fillStyle = `rgb(${r},${g},${b})`; x.fillRect(0, 0, 640, 360); x.fillStyle = '#fff'; x.fillRect(40, 40, 120, 80);
  const u8 = new Uint8Array(await (await c.convertToBlob({ type: 'image/png' })).arrayBuffer());
  let s = ''; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000)); return btoa(s);
}"""
CLIP = r"""async () => {
  const W = 320, H = 180, fps = 30;
  const muxer = new Mp4Muxer.Muxer({ target: new Mp4Muxer.ArrayBufferTarget(), video: { codec: 'vp9', width: W, height: H, frameRate: fps }, fastStart: 'in-memory' });
  const enc = new VideoEncoder({ output: (c, m) => muxer.addVideoChunk(c, m), error: e => { throw e; } });
  enc.configure({ codec: 'vp09.00.10.08', width: W, height: H, bitrate: 1e6, framerate: fps });
  const cv = new OffscreenCanvas(W, H), x = cv.getContext('2d');
  for (let i = 0; i < fps * 3; i++) {
    x.fillStyle = `rgb(${30 + 60 * Math.floor(i / fps)},${(i % fps) * 8},200)`; x.fillRect(0, 0, W, H);
    const f = new VideoFrame(cv, { timestamp: Math.round(i * 1e6 / fps), duration: Math.round(1e6 / fps) });
    enc.encode(f, { keyFrame: i % fps === 0 }); f.close();
  }
  await enc.flush(); muxer.finalize();
  const u8 = new Uint8Array(muxer.target.buffer); let s = ''; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(s);
}"""
# frames as the export draws them (clips at their exact time), hashed. Without the screen effects: their grain textures are made
# once per page with Math.random() in 09_render.js (upstream), so they differ from one page load to the next
FRAMES = r"""async (ts) => {
  const P = J.ui.plan, c = document.createElement('canvas'); c.width = 320; c.height = Math.round(320 * P.H / P.W);
  const x = c.getContext('2d', { willReadFrequently: true }), out = [];
  for (const t of ts) {
    await J.media.prepareFrame(P, t);
    x.setTransform(1, 0, 0, 1, 0, 0); x.clearRect(0, 0, c.width, c.height);
    new J.Renderer().frame(x, P, t, { scale: 320 / P.W, noHud: true, noPost: true });
    const d = x.getImageData(0, 0, c.width, c.height).data; let h = 0;
    for (let i = 0; i < d.length; i += 4) h = (Math.imul(h, 31) + d[i] + d[i + 1] * 3 + d[i + 2] * 7) | 0;
    out.push(h);
  }
  J.media.releaseVideos();
  return out;
}"""
STATE = r"""() => { const S = J.ui, p = S.project, keys = (p.userFonts || []).map(u => u.key);
  return { title: p.title, assets: p.media.assets.map(a => [a.id, a.type]), loaded: [...J.mediaAssets.keys()].sort(),
    fonts: keys.map(k => !!(J.FONTS[k] && J.FONTS[k].loaded)), display: p.fonts && p.fonts.display, audioName: p.audioName || null,
    audio: !!S.audio, duration: +(S.plan.duration || 0).toFixed(2), front: p.media.tracks.front.cuts.map(c => [c.assetId, c.rect && c.rect.x]),
    busy: J.mediaBundle.busy(), note: (document.getElementById('mediaNote') || {}).textContent || '' }; }"""


def wav(path, secs=6.0, rate=22050):
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b''.join(struct.pack('<h', int(9000 * math.sin(2 * math.pi * 440 * i / rate) * (1 if (i // (rate // 2)) % 2 == 0 else 0.3)))
                               for i in range(int(secs * rate))))


def serve():
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT); h.log_message = lambda *a: None
    s = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), h); threading.Thread(target=s.serve_forever, daemon=True).start(); return s


async def main():
    srv = serve(); fails, errors = [], []
    def ok(cond, msg): print(('  ok   ' if cond else '  FAIL ') + msg); cond or fails.append(msg)
    async with async_playwright() as p:
        b = await getattr(p, BROWSER).launch()

        async def page():
            ctx = await b.new_context(viewport={'width': 1400, 'height': 900}, accept_downloads=True)
            await ctx.add_init_script("try { localStorage.setItem('jizura.tourDone', '1'); } catch (e) {}")
            pg = await ctx.new_page()
            pg.on('pageerror', lambda e: errors.append(str(e)))
            pg.on('dialog', lambda dl: asyncio.ensure_future(dl.accept()))
            await pg.goto(f'http://127.0.0.1:{PORT}/index.html')
            await pg.wait_for_function('window.J && J.ui && J.ui.plan && J.mediaUI && J.mediaBundle')
            return ctx, pg

        async def open_zip(path):
            ctx, pg = await page()
            await pg.evaluate('() => { window.__old = J.ui.project; }')
            await pg.set_input_files('#fileProject', path)
            await pg.wait_for_function('J.ui.project !== window.__old && !J.mediaBundle.busy()', timeout=30000)
            await pg.wait_for_timeout(300)
            return ctx, pg

        with tempfile.TemporaryDirectory() as d:
            print('page A: pictures, a clip, a song, a font, a placement')
            ctxA, A = await page()
            files = []
            for k, rgb in enumerate([(200, 40, 40), (40, 160, 60)]):
                pth = os.path.join(d, f'pic{k + 1}.png'); open(pth, 'wb').write(base64.b64decode(await A.evaluate(PNG, list(rgb)))); files.append(pth)
            clip = os.path.join(d, 'clip.mp4'); open(clip, 'wb').write(base64.b64decode(await A.evaluate(CLIP))); files.append(clip)
            await A.evaluate("""(lyr) => { const P = J.ui.project; P.title = 'bundle test'; P.lyrics = lyr; P.timing.snap = false;
              document.getElementById('lyrics').value = lyr; J.uiApi.replan(); }""", LYRICS)
            await A.set_input_files('#mediaFiles', files)
            await A.wait_for_function('J.ui.project.media.assets.length === 3', timeout=60000)
            song = os.path.join(d, 'song.wav'); wav(song)
            await A.set_input_files('#audioFile', song)
            await A.wait_for_function("J.ui.audio && J.ui.project.audioName === 'song.wav'", timeout=30000)
            font_key = None
            if FONT:
                await A.set_input_files('#fontFile', FONT)
                await A.wait_for_function("(J.ui.project.userFonts || []).some(u => /^user_/.test(u.key))", timeout=20000)
                font_key = await A.evaluate("() => J.ui.project.userFonts.find(u => /^user_/.test(u.key)).key")
            else: print('  (no font file on this machine: the font part is skipped)')
            await A.evaluate("""() => { const S = J.ui, m = S.project.media, id = m.assets[1].id;
              m.tracks.front.cuts = [{ id: 'f1', assetId: id, lineRef: null, start: 0, end: null, rect: { x: 0.25, y: -0.2, w: 0.3, rot: 8 } }];
              S.project.media = J.media.normalize(m); J.uiApi.replan(); J.uiApi.flushSave(); }""")
            TS = [0.8, 2.9, 4.6]
            frames_a = await A.evaluate(FRAMES, TS)
            st_a = await A.evaluate(STATE)
            async with A.expect_download() as dl:
                await A.click('#btnSaveBundle')
            full = os.path.join(d, 'full.jizura.zip'); await (await dl.value).save_as(full)
            ok((await dl.value).suggested_filename == 'bundle test.jizura.zip', f'the file is named after the title ({(await dl.value).suggested_filename})')
            with zipfile.ZipFile(full) as z:
                names = sorted(z.namelist()); stored = all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist())
                man = json.loads(z.read('bundle.json')); proj = json.loads(z.read('project.json'))
            ok('project.json' in names and sum(n.startswith('assets/') for n in names) == 3 and any(n.startswith('song/') for n in names)
               and (not FONT or any(n.startswith('fonts/') for n in names)) and stored, f'the zip holds the project, 3 media files, the song{" and the font" if FONT else ""} (stored) {names}')
            ok(proj['media']['assets'] == json.loads(json.dumps(await A.evaluate('() => J.ui.project.media.assets'))) and proj.get('appVersion'),
               'project.json is the project as 「保存」 writes it')

            print('another browser: open the .zip')
            ctxB, B = await open_zip(full)
            if font_key: await B.wait_for_function('(k) => J.FONTS[k] && J.FONTS[k].loaded', arg=font_key, timeout=20000)
            await B.wait_for_function('J.ui.audio && J.mediaAssets.size === 3', timeout=30000)
            st_b = await B.evaluate(STATE)
            same = {k: st_a[k] == st_b[k] for k in ('title', 'assets', 'loaded', 'fonts', 'display', 'audioName', 'audio', 'duration', 'front')}
            ok(all(same.values()), f'pictures, clip, font, song and placement come back {[k for k, v in same.items() if not v] or ""}')
            frames_b = await B.evaluate(FRAMES, TS)
            ok(frames_a == frames_b, f'frames render the same as on the first browser ({frames_a} / {frames_b})')
            mp4 = await B.evaluate("""async () => { const S = J.ui; const r = await J.exportMP4({ plan: S.plan, project: Object.assign({}, S.project, { res: 720, includeAudio: true }),
                audio: S.audio, quality: 'normal', range: { t0: 1, t1: 2 } }); return { size: r.blob.size, codec: r.codec }; }""")
            ok(mp4['size'] > 10000, f'an MP4 can be exported there ({mp4})')
            await ctxB.close()

            print('a picture this browser does not have')
            await A.evaluate("""async () => { const id = J.ui.project.media.assets[0].id;
              await new Promise((res, rej) => { const r = indexedDB.open('jizura', 1); r.onsuccess = () => { const t = r.result.transaction('files', 'readwrite'); t.objectStore('files').delete('media:' + id); t.oncomplete = res; t.onerror = rej; }; }); }""")
            packed = await A.evaluate("async () => { const r = await J.mediaBundle.pack(J.ui.project, 'test'); window.__part = r.blob; return { assets: r.assets, missing: r.missing }; }")
            ok(packed['assets'] == 2 and packed['missing'] == ['pic1.png'], f'saving reports what is not included {packed}')
            part = os.path.join(d, 'part.jizura.zip')
            open(part, 'wb').write(base64.b64decode(await A.evaluate("async () => { const u8 = new Uint8Array(await window.__part.arrayBuffer()); let s = ''; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000)); return btoa(s); }")))
            ctxC, C = await open_zip(part)
            await C.wait_for_function("(document.getElementById('mediaNote') || {}).textContent.includes('pic1.png')", timeout=20000)
            st_c = await C.evaluate(STATE)
            ok(len(st_c['loaded']) == 2 and 'pic1.png' in st_c['note'], f'after opening, the missing picture is reported ({st_c["note"][:60]}…)')
            await ctxC.close()

            print('a picture whose bytes do not match')
            bad = os.path.join(d, 'bad.jizura.zip')
            with zipfile.ZipFile(full) as zi, zipfile.ZipFile(bad, 'w', zipfile.ZIP_STORED) as zo:
                victim = next(n for n in zi.namelist() if n.startswith('assets/') and n.endswith('.png'))
                for n in zi.namelist():
                    data = zi.read(n)
                    zo.writestr(n, data[:-8] + b'\x00' * 8 if n == victim else data)
            ctxD, D = await open_zip(bad)
            r = await D.evaluate('() => J.mediaBundle.last')
            await D.wait_for_timeout(500)
            st_d = await D.evaluate(STATE)
            ok(len(r['bad']) == 1 and r['assets'] == 2 and len(st_d['loaded']) == 2, f'it is left out (and reported as missing) {r}')
            await ctxD.close()

            print('a .zip re-compressed by another tool (deflate)')
            dfl = os.path.join(d, 'deflate.zip')
            with zipfile.ZipFile(full) as zi, zipfile.ZipFile(dfl, 'w', zipfile.ZIP_DEFLATED) as zo:
                for n in zi.namelist(): zo.writestr('my project/' + n, zi.read(n))
            ctxE, E = await open_zip(dfl)
            await E.wait_for_function('J.ui.audio && J.mediaAssets.size === 3', timeout=30000)
            st_e = await E.evaluate(STATE)
            ok(st_e['loaded'] == st_a['loaded'] and st_e['audio'] and st_e['front'] == st_a['front'], 'it opens (inside a folder too)')
            await ctxE.close()

            print('a .zip that is not a bundle')
            nb = os.path.join(d, 'photos.zip')
            with zipfile.ZipFile(nb, 'w') as zo: zo.writestr('a.txt', 'hello')
            ctxG, G = await page()
            before = await G.evaluate('() => J.ui.project.title')
            await G.set_input_files('#fileProject', nb)
            try:
                await G.wait_for_function("(document.getElementById('toast') || {}).textContent.includes('project.json')", timeout=10000); said = True
            except Exception: said = False
            ok(said and await G.evaluate('() => J.ui.project.title') == before and not await G.evaluate('() => J.mediaBundle.busy()'),
               'it is refused with the reason, and the open project stays')
            await ctxG.close()
            print('a .jizura.json still opens as before')
            js = os.path.join(d, 'plain.jizura.json'); open(js, 'w', encoding='utf-8').write(json.dumps(proj, ensure_ascii=False))
            ctxF, F = await open_zip(js)
            ok((await F.evaluate(STATE))['title'] == 'bundle test', 'the project opens (its media are reported as missing in that browser)')
            await ctxF.close()
            ok(not errors, f'no page errors {errors[:3]}')
        await b.close()
    srv.shutdown()
    print(f'FAILED: {len(fails)}' if fails else 'all bundle checks passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
