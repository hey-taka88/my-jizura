"""my-jizura: end-to-end check of the background-pictures layer (Phase 1) on the BUILT app (index.html).
usage: python3 build.py && python3 dev/media_e2e.py [--shots out/media] [--require-export]
Serves the repository root on :8766, drops five generated pictures (and one text file) into 「画像を追加」, then checks:
  every lyric line shows a picture in turn · 「画像なし」 on one line · keyBg (green) draws no picture ·
  transparent PNG layers (back has the picture, front has not) · the background graphic is left out unless 「重ねる」 ·
  the saved project holds no image bytes · pictures come back after a reload · removing a picture · a short MP4 export.
Exit code 0 = all checks passed."""
import asyncio, functools, http.server, os, sys, tempfile, threading
from playwright.async_api import async_playwright
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = sys.argv[sys.argv.index('--shots') + 1] if '--shots' in sys.argv else None
PICS = [('01_red.png', (210, 59, 59), (1920, 1080)), ('02_green.jpg', (47, 158, 68), (1920, 1080)), ('03_blue.png', (47, 111, 210), (1080, 1920)),
        ('04_gold.webp', (217, 164, 0), (6000, 4000)), ('05_purple.png', (155, 63, 210), (1600, 900))]

def make_pictures(d):
    paths = []
    for name, col, (w, h) in PICS:
        im = Image.new('RGB', (w, h), col); dr = ImageDraw.Draw(im)
        dr.rectangle([w // 2 - w // 12, h // 2 - h // 12, w // 2 + w // 12, h // 2 + h // 12], fill=(255, 255, 255))
        p = os.path.join(d, name); im.save(p, quality=92) if not name.endswith('.png') else im.save(p); paths.append(p)
    t = os.path.join(d, 'notes.txt'); open(t, 'w').write('not a picture'); paths.append(t)
    return paths

def serve():
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
    h.log_message = lambda *a: None
    s = http.server.ThreadingHTTPServer(('127.0.0.1', 8766), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s

# median colour of a frame rendered at time t (robust to the lyrics drawn on top); opts → Renderer.frame options
MEDIAN = r"""([t, opts]) => {
  const S = J.ui, c = document.createElement('canvas'); c.width = Math.round(S.plan.W / 6); c.height = Math.round(S.plan.H / 6);
  const x = c.getContext('2d'); new J.Renderer().frame(x, S.plan, t, Object.assign({ scale: c.width / S.plan.W }, opts || {}));
  const d = x.getImageData(0, 0, c.width, c.height).data, ch = [[], [], [], []];
  for (let i = 0; i < d.length; i += 4) for (let k = 0; k < 4; k++) ch[k].push(d[i + k]);
  return ch.map(a => { a.sort((p, q) => p - q); return a[a.length >> 1]; });
}"""
near = lambda a, b, tol=40: all(abs(a[i] - b[i]) <= tol for i in range(3))

async def main():
    srv = serve(); fails = []; ok = lambda cond, msg: (print(('  ok   ' if cond else '  FAIL ') + msg), None if cond else fails.append(msg))
    with tempfile.TemporaryDirectory() as d:
        files = make_pictures(d)
        async with async_playwright() as p:
            b = await p.chromium.launch(); ctx = await b.new_context(viewport={'width': 1600, 'height': 1000}); pg = await ctx.new_page()
            await ctx.add_init_script("try { localStorage.setItem('jizura.tourDone', '1'); } catch (e) {}")   # no first-visit tour
            errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
            pg.on('dialog', lambda dl: asyncio.ensure_future(dl.accept()))
            await pg.goto('http://127.0.0.1:8766/index.html'); await pg.wait_for_function('window.J && J.ui && J.ui.plan && J.mediaUI')
            print('add pictures')
            await pg.set_input_files('#mediaFiles', files)
            await pg.wait_for_function('J.ui.project.media.assets.length === 5 && J.mediaAssets.size >= 5', timeout=30000)
            note = await pg.inner_text('#mediaNote'); ok('1' in note and '読み込めません' in note, f'the text file is reported: {note!r}')
            info = await pg.evaluate("""() => { const S = J.ui; return { assets: S.project.media.assets.map(a => [a.name, a.w, a.h]), lines: S.plan.lines.map(l => [l.index, l.start, l.end]),
              cuts: S.plan.media.back.cuts.map(c => [c.assetId, c.start, c.end, c.line]), names: Object.fromEntries(S.project.media.assets.map(a => [a.id, a.name])),
              sels: document.querySelectorAll('select.media-sel').length, gold: [J.mediaAssets.get(S.project.media.assets[3].id).sw, J.mediaAssets.get(S.project.media.assets[3].id).sh] }; }""")
            ok([a[0] for a in info['assets']] == [n for n, _, _ in PICS], 'pictures are listed in the order added')
            ok(info['assets'][3][1:] == [6000, 4000] and max(info['gold']) <= 4096, f"a 6000×4000 picture is kept at {info['gold']} (≤ 4096)")
            ok(info['sels'] == len(info['lines']), f"every line has a picture selector ({info['sels']}/{len(info['lines'])})")
            ok(info['cuts'] and info['cuts'][0][1] == 0, 'the first picture starts at 0 (covers the intro)')
            seq = [info['names'][c[0]] for c in info['cuts']]
            ok(seq[:5] == [n for n, _, _ in PICS][:min(5, len(seq))], f'pictures change line by line in order: {seq[:6]}')
            # each cut shows its picture (darkened by 暗さ 25 %)
            await pg.evaluate("() => { J.ui.project.media.tracks.back.dim = 0; J.uiApi.replan(); }")
            col = {n: c for n, c, _ in PICS}
            for c in info['cuts'][:5]:
                t = (c[1] + c[2]) / 2 + 0.3
                m = await pg.evaluate(MEDIAN, [t, {}])
                ok(near(m, col[info['names'][c[0]]]), f"frame at {t:.1f}s shows {info['names'][c[0]]} (median {m[:3]})")
            print('one line set to 「画像なし」')
            li = info['lines'][1][0]
            await pg.select_option(f'#lineList li:nth-child({li + 1}) select.media-sel', 'none')
            gap = await pg.evaluate(f"() => J.ui.plan.media.back.cuts.some(c => c.start <= J.ui.plan.lines[{li}].start + 0.01 && c.end > J.ui.plan.lines[{li}].start + 0.01)")
            ok(not gap, 'that line has no picture in the plan')
            t_gap = info['lines'][1][1] + 0.8
            m = await pg.evaluate(MEDIAN, [t_gap, {}]); ok(not any(near(m, c) for _, c, _ in PICS), f'the frame there shows no picture (median {m[:3]})')
            print('outputs')
            t1 = (info['cuts'][0][1] + info['cuts'][0][2]) / 2 + 0.3
            await pg.evaluate("() => { J.ui.project.keyBg = 'green'; J.uiApi.replan(); }")
            m = await pg.evaluate(MEDIAN, [t1, {}]); ok(not near(m, col[PICS[0][0]]), f'green screen output draws no picture (median {m[:3]})')
            await pg.evaluate("() => { J.ui.project.keyBg = 'off'; J.uiApi.replan(); }")
            mb = await pg.evaluate(MEDIAN, [t1, {'transparent': True, 'layer': 'back'}]); mf = await pg.evaluate(MEDIAN, [t1, {'transparent': True, 'layer': 'front'}])
            mt = await pg.evaluate(MEDIAN, [t1, {'transparent': True}])
            ok(mb[3] == 255 and near(mb, col[PICS[0][0]]), f'transparent PNG back layer has the picture (median {mb})')
            ok(mf[3] == 0 and mt[3] == 0, f'front layer and plain transparent PNG stay see-through (alpha {mf[3]}, {mt[3]})')
            # background graphics (J.BG): left out under pictures unless 「重ねる」
            cnt = """(over) => { const S = J.ui; S.project.media.lyricBg = over ? 'over' : 'off'; S.project.overrides[0] = Object.assign({}, S.project.overrides[0], { bg: 'meshBlobs' }); J.uiApi.replan(); let n = 0; const saved = {};
              for (const k of Object.keys(J.BG)) { saved[k] = J.BG[k].draw; J.BG[k].draw = function () { n++; return saved[k].apply(this, arguments); }; }
              const c = document.createElement('canvas'); c.width = 96; c.height = 54; const r = new J.Renderer(), x = c.getContext('2d');
              for (const cut of S.plan.cuts) if (cut.bg && cut.bg !== 'none') r.frame(x, S.plan, (cut.start + cut.end) / 2, { scale: 96 / S.plan.W });
              for (const k of Object.keys(saved)) J.BG[k].draw = saved[k];
              return [n, S.plan.cuts.filter(c => c.bg && c.bg !== 'none' && J.media.hidesBg(S.plan, (c.start + c.end) / 2)).length, S.plan.cuts.filter(c => c.bg && c.bg !== 'none').length]; }"""
            off = await pg.evaluate(cnt, False); over = await pg.evaluate(cnt, True)
            ok(off[1] >= 1 and over[0] == over[2] and off[0] == off[2] - off[1], f'background graphics: {off[0]} drawn when off, {over[0]} when 重ねる (cuts with one: {off[2]}, under pictures: {off[1]})')
            await pg.evaluate("() => { J.ui.project.media.lyricBg = 'off'; J.ui.project.media.tracks.back.dim = 0.25; J.uiApi.replan(); J.uiApi.flushSave(); }")
            saved = await pg.evaluate("() => localStorage.getItem('jizura.project.v1')")
            ok('"assets"' in saved and 'data:' not in saved and len(saved) < 60000, f'saved project keeps only picture metadata ({len(saved)} chars)')
            if SHOTS:
                os.makedirs(SHOTS, exist_ok=True)
                await pg.evaluate(f"() => J.uiApi.seek({t1})"); await pg.wait_for_timeout(500)
                await pg.screenshot(path=os.path.join(SHOTS, 'editor.png'))
                await pg.locator('#mediaSec').screenshot(path=os.path.join(SHOTS, 'panel.png'))
            print('reload')
            await pg.reload(); await pg.wait_for_function('window.J && J.ui && J.ui.plan && J.mediaUI')
            await pg.wait_for_function('J.mediaAssets.size >= 5', timeout=30000)
            r = await pg.evaluate("() => [J.ui.project.media.assets.length, document.querySelectorAll('#mediaList li:not(.missing)').length, J.ui.project.media.tracks.back.cuts.length]")
            ok(r[0] == 5 and r[1] == 5 and r[2] == 1, f'after a reload: {r[0]} pictures, {r[1]} shown, the 「画像なし」 line kept ({r[2]})')
            print('remove one')
            await pg.click('#mediaList li:nth-child(5) .del')
            await pg.wait_for_function('J.ui.project.media.assets.length === 4')
            gone = await pg.evaluate("""async () => { const id = [...J.mediaAssets.keys()].find(k => !J.ui.project.media.assets.some(a => a.id === k));
              const d = await new Promise(r => { const q = indexedDB.open('jizura', 1); q.onsuccess = () => r(q.result); });
              const keys = await new Promise(r => { const q = d.transaction('files').objectStore('files').getAllKeys(); q.onsuccess = () => r(q.result); });
              return [id || null, keys.filter(k => String(k).startsWith('media:')).length]; }""")
            ok(gone[0] is None and gone[1] == 4, f'removed from memory and from this browser (stored: {gone[1]})')
            print('export (short MP4)')
            res = await pg.evaluate("""async (t1) => {
              if (typeof VideoEncoder === 'undefined') return { skip: 'no WebCodecs' };
              const S = J.ui, P = Object.assign({}, S.project, { res: 720, includeAudio: false });
              let r; try { r = await J.exportMP4({ plan: S.plan, project: P, audio: null, quality: 'normal', range: { t0: t1 - 0.5, t1: t1 + 0.5 } }); } catch (e) { return { skip: String(e.message || e).slice(0, 200) }; }
              const v = document.createElement('video'); v.muted = true; v.src = URL.createObjectURL(r.blob);
              await new Promise((ok, no) => { v.onloadeddata = ok; v.onerror = () => no(new Error('video')); });
              v.currentTime = 0.5; await new Promise(ok => { v.onseeked = ok; });
              const c = document.createElement('canvas'); c.width = 160; c.height = 90; const x = c.getContext('2d'); x.drawImage(v, 0, 0, 160, 90);
              const d = x.getImageData(0, 0, 160, 90).data, ch = [[], [], []];
              for (let i = 0; i < d.length; i += 4) for (let k = 0; k < 3; k++) ch[k].push(d[i + k]);
              return { codec: r.codec, size: r.size, median: ch.map(a => { a.sort((p, q) => p - q); return a[a.length >> 1]; }) }; }""", t1)
            if 'skip' in res:
                print('  skip export:', res['skip'])
                if '--require-export' in sys.argv: ok(False, 'MP4 export is required for CI')
            else: ok(near(res['median'], tuple(int(v * 0.75) for v in col[PICS[0][0]]), 45), f"MP4 ({res['codec']}, {res['size']} bytes) shows the picture (median {res['median']})")
            ok(not errs, f'no page errors {errs[:3]}')
            await b.close()
    srv.shutdown()
    print('FAILED:', len(fails)) if fails else print('all media checks passed')
    sys.exit(1 if fails else 0)

asyncio.run(main())
