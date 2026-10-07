"""my-jizura: 「ダンス動画を重ねる」 in the かんたん panel (11z_media_easy.js) on the BUILT app, through tools/jizura_driver.py.
usage: python3 build.py && python3 dev/easy_dance_e2e.py [--browser chromium]
  the section is in the かんたん panel · a green-screen clip (made in the page: VP9 in MP4, a magenta dancer on a green screen)
  chosen with its button goes over the lyrics for the whole song, standing on the bottom, 0.9 of the frame tall, its screen taken
  out (the background picture shows through), the lyrics split to the sides · it is not one of the automatic backgrounds ·
  位置 / 大きさ keep it on the bottom · 背景 「抜かない」 shows the screen again · another 画面比 keeps its height and its feet on
  the bottom · 差し替え with a transparent PNG keeps its place and drops the key, the clip it replaced leaves the list (never a
  background, also when it is taken off in 詳細's list) · what is found: alpha (also a clip's thumbnail with transparency), green, blue, plain · ✕ takes it off (its clips stay in
  the list, marked, never a background) · a clip read while another project was opened is dropped and not kept · a broken file named like a clip in the list is refused · the same clip under another name is the one in the
  list · the same project gives the same plan · スマホ: a picture's buttons show and work, the frame's handles are big enough.
Exit code 0 = all checks passed."""
import asyncio, base64, os, sys, tempfile
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
from jizura_driver import Jizura

BROWSER = sys.argv[sys.argv.index('--browser') + 1] if '--browser' in sys.argv else 'auto'
MAG, SCREEN, BLUE, BSCREEN = (255, 0, 255), (40, 180, 70), (40, 60, 200), (30, 60, 220)
BD = tuple(int(v * 0.75) for v in BLUE)              # the background picture under the default 暗さ (0.25)

# a portrait clip: a green screen with a magenta dancer standing on its bottom (x 60..120, y 100..320 of 180 × 320)
MAKE = r"""async ([secs]) => {
  const W = 180, H = 320, fps = 30;
  const muxer = new Mp4Muxer.Muxer({ target: new Mp4Muxer.ArrayBufferTarget(), video: { codec: 'vp9', width: W, height: H, frameRate: fps }, fastStart: 'in-memory' });
  const enc = new VideoEncoder({ output: (c, m) => muxer.addVideoChunk(c, m), error: e => { throw e; } });
  enc.configure({ codec: 'vp09.00.10.08', width: W, height: H, bitrate: 1e6, framerate: fps });
  const cv = new OffscreenCanvas(W, H), x = cv.getContext('2d');
  for (let i = 0; i < fps * secs; i++) {
    x.fillStyle = 'rgb(40,180,70)'; x.fillRect(0, 0, W, H);
    x.fillStyle = '#ff00ff'; x.fillRect(60, 100, 60, 220);
    const f = new VideoFrame(cv, { timestamp: Math.round(i * 1e6 / fps), duration: Math.round(1e6 / fps) });
    enc.encode(f, { keyFrame: i % fps === 0 }); f.close();
  }
  await enc.flush(); muxer.finalize();
  const u8 = new Uint8Array(muxer.target.buffer); let s = ''; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(s);
}"""

# pixels of a frame at time t (clips at their exact frame, as an export), at points given from the frame centre (fractions)
PIX = """async ([t, pts]) => {
  const plan = J.ui.plan, w = 320, h = Math.round(320 * plan.H / plan.W);
  const cv = document.createElement('canvas'); cv.width = w; cv.height = h;
  const R = window.__edR || (window.__edR = new J.Renderer());
  if (plan.media) await J.media.prepareFrame(plan, t);
  R.frame(cv.getContext('2d'), plan, t, { scale: w / plan.W, noPost: true });
  J.media.releaseVideos();
  const d = cv.getContext('2d').getImageData(0, 0, w, h).data;
  return pts.map(([fx, fy]) => { const x = Math.round((0.5 + fx) * (w - 1)), y = Math.round((0.5 + fy) * (h - 1)), i = (y * w + x) * 4; return [d[i], d[i + 1], d[i + 2]]; });
}"""


def near(a, b, tol=45): return all(abs(int(x) - int(y)) <= tol for x, y in zip(a[:3], b[:3]))


def make(d):
    os.makedirs(d, exist_ok=True)
    Image.new('RGB', (1280, 720), BLUE).save(os.path.join(d, 'blue.png'))
    Image.new('RGB', (100, 100), (0, 220, 255)).save(os.path.join(d, 'logo.png'))
    im = Image.new('RGBA', (300, 600), (0, 0, 0, 0)); ImageDraw.Draw(im).rectangle([100, 150, 199, 599], fill=MAG + (255,)); im.save(os.path.join(d, 'figure.png'))
    bs = Image.new('RGB', (400, 600), BSCREEN); ImageDraw.Draw(bs).rectangle([150, 200, 249, 599], fill=MAG); bs.save(os.path.join(d, 'bluescreen.png'))
    ph = Image.new('RGB', (400, 300)); dr = ImageDraw.Draw(ph)                    # a photo-like picture: no screen round its edge
    for y in range(300): dr.line([(0, y), (399, y)], fill=(200 - y // 2, 120 + y // 4, 60 + y // 3))
    dr.rectangle([0, 0, 60, 299], fill=(230, 220, 40)); ph.save(os.path.join(d, 'photo.png'))


async def main():
    fails = []
    ok = lambda cond, msg: (print(('  ok   ' if cond else '  FAIL ') + msg), None if cond else fails.append(msg))
    tmp = tempfile.mkdtemp(); pics = os.path.join(tmp, 'pics'); make(pics)
    async with Jizura(browser=BROWSER, log=lambda m: None) as jz:
        pg = jz.page; ev = pg.evaluate
        lyr = '\n'.join(f'[00:{1 + 4 * i:02d}.00]{t}' for i, t in enumerate(['夜明けの色を覚えてる', 'ほどけた声が遠くで鳴った', '手を離す', 'ねえ、まだ間に合うかな', '名前のない明日へ', 'おわり']))
        await jz.new_project(lyrics=lyr); await jz.set_look(seed=3)
        await jz.add_media([os.path.join(pics, 'blue.png')])                           # the automatic background: blue under every line
        await jz.add_media([os.path.join(pics, 'logo.png')])
        logo = (await jz.add_timed_media('logo.png', 0, track='front', x=-0.4, y=-0.4, size=0.1))['id']   # a logo placed in 詳細
        LOGO = "(id) => JSON.stringify(J.ui.project.media.tracks.front.cuts.find(c => c.id === id))"
        logo0 = await ev(LOGO, logo)
        clip = os.path.join(tmp, 'dance_gb.mp4')
        with open(clip, 'wb') as f: f.write(base64.b64decode(await ev(MAKE, [2])))
        print('the section')
        await pg.click('#modeEasy')
        vis = await ev("() => { const s = document.getElementById('easyDance'); return !!s && s.offsetParent !== null && /ダンス動画/.test(s.textContent) && !!s.querySelector('.dz-file'); }")
        ok(vis, 'かんたん shows 「ダンス動画を重ねる」 with a button to choose a clip (a logo placed in 詳細 is not its dancer)')
        plan0 = await ev("() => JSON.stringify(J.ui.plan.cuts.map(c => [c.start, c.layout]))")
        print('a green-screen clip')
        await pg.set_input_files('#easyDance .dz-file', clip)
        await pg.wait_for_function("() => { const c = J.mediaEasy.dancer(); return !!c && !!c.chroma; }", timeout=30000)
        d = await ev("() => J.mediaEasy.dancer()")
        R = d['rect']
        ok(d['start'] == 0 and d['end'] is None and d['chroma']['color'] == 'auto', f"it goes over the lyrics for the whole song, its screen keyed 'auto' ({d['start']}–{d['end']}, {d['chroma']})")
        ok(abs(R['x']) < 1e-6 and abs(R['y'] - 0.05) < 0.002 and abs(R['w'] - 0.9 * 1080 * 180 / (320 * 1920)) < 0.002,
           f'in the middle, standing on the bottom, 0.9 of the frame tall ({R})')
        st = await ev("() => ({ center: !!J.ui.project.centerFree, eCenter: document.getElementById('eCenter').checked, dz: document.querySelector('#easyDance .dz-center').checked, found: document.querySelector('#easyDance .found').textContent })")
        ok(st['center'] and st['eCenter'] and st['dz'], f'the lyrics go to its sides (中央を空ける turned on, both boxes ticked: {st})')
        ok('グリーンバック' in st['found'], f"the panel says what it found ({st['found']})")
        back = await ev("() => J.ui.plan.media.back.cuts.map(c => c.assetId)")
        did = d['assetId']
        ok(back and did not in back, f'the clip is not one of the automatic backgrounds ({len(back)} back cuts)')
        # the clip is 0.285 of the frame wide (±0.142); its dancer the middle third (±0.047), from y -0.12 down to the bottom
        px = await ev(PIX, [6.5, [[0, 0.3], [0.11, -0.25], [0.35, -0.3]]])
        ok(near(px[0], MAG), f'the dancer shows ({px[0]})')
        ok(near(px[1], BD) and not near(px[1], SCREEN), f'its green screen is taken out: the background picture shows through ({px[1]})')
        ok(near(px[2], BD), f'outside the clip: the background picture ({px[2]})')
        print('position, size, background')
        await pg.click('#easyDance .dz-pos[data-pos="right"]')
        R = (await ev("() => J.mediaEasy.dancer()"))['rect']
        pressed = await ev("() => document.querySelector('#easyDance .dz-pos[data-pos=\"right\"]').getAttribute('aria-pressed')")
        px = await ev(PIX, [6.5, [[0.25, 0.3], [0, 0.3]]])
        ok(abs(R['x'] - 0.25) < 1e-6 and pressed == 'true' and near(px[0], MAG) and not near(px[1], MAG), f'右 moves it to the right ({R}, {px})')
        await pg.eval_on_selector('#easyDance .dz-size', "(el) => { el.value = '0.6'; el.dispatchEvent(new Event('change')); }")
        R = (await ev("() => J.mediaEasy.dancer()"))['rect']
        h = R['w'] * 1920 * 320 / (180 * 1080)
        ok(abs(h - 0.6) < 0.01 and abs(R['y'] + h / 2 - 0.5) < 0.003 and abs(R['x'] - 0.25) < 1e-6, f'大きさ 60% keeps it on the bottom and on the right ({R}, height {h:.3f})')
        await pg.select_option('#easyDance .dz-key', 'none')
        d = await ev("() => J.mediaEasy.dancer()")
        px = await ev(PIX, [6.5, [[0.25 + 0.07, 0.1]]])
        ok('chroma' not in d and near(px[0], SCREEN), f'「抜かない」 shows its screen again ({px})')
        await pg.select_option('#easyDance .dz-key', 'auto')
        await pg.wait_for_selector('#easyDance .dz-tol')
        await pg.eval_on_selector('#easyDance .dz-tol', "(el) => { el.value = '0.2'; el.dispatchEvent(new Event('change')); }")
        d = await ev("() => J.mediaEasy.dancer()")
        ok(d['chroma']['color'] == 'auto' and abs(d['chroma']['tol'] - 0.2) < 1e-6, f"「背景の色を抜く」 and 抜く範囲 ({d['chroma']})")
        print('another 画面比')
        await jz.set_output(aspect='9:16')
        R = (await ev("() => J.mediaEasy.dancer()"))['rect']; h = R['w'] * 1080 * 320 / (180 * 1920)
        ok(abs(h - 0.6) < 0.01 and abs(R['y'] + h / 2 - 0.5) < 0.003 and abs(R['x'] - 0.25) < 1e-6, f'9:16 keeps its height and its feet on the bottom ({R}, height {h:.3f})')
        await jz.set_output(aspect='16:9')
        R = (await ev("() => J.mediaEasy.dancer()"))['rect']; h = R['w'] * 1920 * 320 / (180 * 1080)
        ok(abs(h - 0.6) < 0.01 and abs(R['y'] + h / 2 - 0.5) < 0.003, f'and back to 16:9 ({R}, height {h:.3f})')
        ok(await ev(LOGO, logo) == logo0, 'the logo placed in 詳細 keeps its own rect through both')
        await ev("() => J.uiApi.flushSave()")
        await pg.reload(); await pg.wait_for_function("(id) => window.J && J.ui && J.ui.plan && J.mediaEasy && J.mediaAssets.has(id)", arg=did, timeout=30000)
        await ev("""() => { const i = document.createElement('input'); i.type = 'file'; i.multiple = true; i.id = 'jzDriverFiles';
          i.style.display = 'none'; document.body.appendChild(i); }""")                   # the driver's file field (as Jizura.start)
        await jz.set_output(aspect='9:16')                                               # the first change after a reload
        R = (await ev("() => J.mediaEasy.dancer()"))['rect']; h = R['w'] * 1080 * 320 / (180 * 1920)
        ok(abs(h - 0.6) < 0.01 and abs(R['y'] + h / 2 - 0.5) < 0.003, f'after a reload, the first 9:16 keeps it too ({R}, height {h:.3f})')
        await jz.set_output(aspect='16:9')
        print('replace, and what is found')
        BACK = "() => J.ui.plan.media.back.cuts.map(c => c.assetId)"
        found = await ev("""(did) => {
          const th = document.createElement('canvas'); th.width = 160; th.height = 90;
          const x = th.getContext('2d'); x.fillStyle = '#ff00ff'; x.fillRect(60, 10, 40, 80);       // a clip with transparency round its dancer
          J.mediaAssets.set('fakealpha', { type: 'video', thumb: th, w: 160, h: 90 });
          const out = { clip: J.mediaEasy.detect(did).kind, alphaClip: J.mediaEasy.detect('fakealpha').kind };
          J.mediaAssets.delete('fakealpha');
          return out;
        }""", did)
        await pg.set_input_files('#easyDance .dz-file', os.path.join(pics, 'figure.png'))
        await pg.wait_for_function("(id) => { const c = J.mediaEasy.dancer(); return !!c && c.assetId !== id; }", arg=did, timeout=15000)
        d = await ev("() => J.mediaEasy.dancer()")
        R = d['rect']; h = R['w'] * 1920 * 600 / (300 * 1080)
        ok('chroma' not in d and abs(R['x'] - 0.25) < 1e-6 and abs(h - 0.6) < 0.01 and abs(R['y'] + h / 2 - 0.5) < 0.003,
           f'差し替え with a transparent PNG: same place and height, no key ({R})')
        names = await ev("() => J.ui.project.media.assets.map(a => a.name)")
        back = await ev(BACK)
        ok(len(await ev("() => J.ui.project.media.tracks.front.cuts")) == 2 and names == ['blue.png', 'logo.png', 'dance_gb.mp4', 'figure.png'] and did not in back and back,
           f'still one picture over the lyrics; the green clip it replaced stays in the list but never becomes a background ({names}, back {back})')
        await jz.add_media([os.path.join(pics, 'bluescreen.png'), os.path.join(pics, 'photo.png')])
        ids = await ev("() => Object.fromEntries(J.ui.project.media.assets.map(a => [a.name, a.id]))")
        found.update(await ev("(ids) => ({ figure: J.mediaEasy.detect(ids['figure.png']).kind, blue: J.mediaEasy.detect(ids['bluescreen.png']).kind, photo: J.mediaEasy.detect(ids['photo.png']).kind })", ids))
        ok(found == {'clip': 'green', 'figure': 'alpha', 'alphaClip': 'alpha', 'blue': 'blue', 'photo': 'plain'}, f'found: {found}')
        await ev("(id) => J.mediaEasy.use(id)", ids['bluescreen.png'])
        d = await ev("() => J.mediaEasy.dancer()")
        await ev("(id) => J.mediaEasy.use(id)", ids['photo.png'])
        d2 = await ev("() => J.mediaEasy.dancer()")
        ok(d['chroma'] and d['chroma']['color'] == 'auto' and 'chroma' not in d2, f"a blue screen is keyed, a photo is not ({d.get('chroma')}, {d2.get('chroma')})")
        same = await ev("() => JSON.stringify(J.plan(J.ui.project, null).media) === JSON.stringify(J.plan(J.ui.project, null).media)")
        ok(same, 'the same project gives the same plan')
        print('remove')
        await ev("(id) => document.querySelector(`#mediaFront .mf-row[data-id=\"${id}\"] .del`).click()", d2['id'])   # ✕ in 詳細's list
        back = await ev(BACK)
        ok(await ev("() => J.mediaEasy.dancer()") is None and set(back) == {ids['blue.png']}, f"✕ in 詳細's list: the clip that was the dancer is still no background ({back})")
        await ev("(id) => J.mediaEasy.use(id)", ids['figure.png'])
        await pg.click('#easyDance .dz-del')
        left = await ev("() => ({ front: J.ui.project.media.tracks.front.cuts.length, assets: J.ui.project.media.assets.map(a => a.name), pick: /動画を選ぶ/.test(document.getElementById('easyDance').textContent) })")
        back = await ev(BACK)
        ok(left == {'front': 1, 'assets': ['blue.png', 'logo.png', 'dance_gb.mp4', 'figure.png', 'bluescreen.png', 'photo.png'], 'pick': True}
           and set(back) == {ids['blue.png']} and await ev(LOGO, logo) == logo0,
           f'✕ takes it off, its clips stay in the list but none is a background, the logo stays, the button comes back ({left}, back {back})')
        saved = await ev("() => J.media.normalize(JSON.parse(JSON.stringify(J.ui.project.media))).assets.filter(a => a.role === 'dancer').map(a => a.name)")
        ok(saved == ['dance_gb.mp4', 'figure.png', 'bluescreen.png', 'photo.png'], f'that is kept in the project ({saved})')
        print('a clip already in the list')
        await jz.add_media([clip])                                                      # the green clip as one of the pictures
        await pg.set_input_files('#easyDance .dz-file', os.path.join(pics, 'figure.png'))
        await pg.wait_for_function("() => !!J.mediaEasy.dancer()", timeout=15000)
        fig = (await ev("() => J.mediaEasy.dancer()"))['assetId']
        bad = os.path.join(tmp, 'bad'); os.makedirs(bad, exist_ok=True)
        with open(os.path.join(bad, 'dance_gb.mp4'), 'wb') as f: f.write(os.urandom(4096))     # the same name, not a clip
        await pg.set_input_files('#easyDance .dz-file', os.path.join(bad, 'dance_gb.mp4'))
        await pg.wait_for_function("() => /再生でき|読み込めません/.test(document.getElementById('toast').textContent)", timeout=30000)
        d = await ev("() => ({ c: J.mediaEasy.dancer(), toast: document.getElementById('toast').textContent })")
        ok(d['c']['assetId'] == fig and '再生できません' in d['toast'], f"a broken file with the name of a clip in the list is refused, the dancer stays ({d['c']['assetId']} / {fig}, {d['toast']!r})")
        import shutil; again = os.path.join(tmp, 'renamed.mp4'); shutil.copy(clip, again)
        await pg.set_input_files('#easyDance .dz-file', again)
        await pg.wait_for_function("(id) => J.mediaEasy.dancer().assetId === id", arg=did, timeout=15000)
        n = await ev("() => J.ui.project.media.assets.map(a => a.name)")
        ok(len(n) == 6, f"the same clip under another name uses the one in the list ({n})")
        await ev("() => J.mediaEasy.remove()")
        await ev("() => { const el = document.getElementById('eCenter'); el.checked = false; el.dispatchEvent(new Event('change')); }")
        plan1 = await ev("() => JSON.stringify(J.ui.plan.cuts.map(c => [c.start, c.layout]))")
        ok(plan0 == plan1, 'without it (and 中央を空ける off again) the lyrics are planned as before')
        print('another project opened while a clip loads')
        await ev("""() => { const orig = J.mediaUI.addFiles; let go; window.__gate = new Promise(r => { go = r; }); window.__go = go;
          J.mediaUI.addFiles = async files => { J.mediaUI.addFiles = orig; const r = await orig(files); await window.__gate; return r; };
          const cv = document.createElement('canvas'); cv.width = 40; cv.height = 30; cv.getContext('2d').fillRect(0, 0, 20, 30);
          return new Promise(res => cv.toBlob(async b => { const buf = await b.arrayBuffer(); window.__lateId = await J.media.hashBytes(buf);
            window.__late = J.mediaEasy.add([new File([buf], 'late.png', { type: 'image/png' })]); res(); }, 'image/png')); }""")
        await jz.new_project(lyrics=lyr)
        await jz.add_media([os.path.join(pics, 'photo.png')])
        r = await ev("async () => { window.__go(); const id = await window.__late; return { id, front: J.ui.project.media.tracks.front.cuts.length, assets: J.ui.project.media.assets.map(a => a.name) }; }")
        ok(r == {'id': None, 'front': 0, 'assets': ['photo.png']}, f'the late result is dropped: the project opened meanwhile is untouched ({r})')
        LATE = "async () => ({ id: window.__lateId, live: J.mediaAssets.has(window.__lateId), stored: !!(await J.media.storedFile(window.__lateId)) })"
        for _ in range(50):
            late = await ev(LATE)
            if not late['live'] and not late['stored']: break
            await pg.wait_for_timeout(200)
        ok(late['id'] and not late['live'] and not late['stored'], f'and the picture read for the closed project is not kept in this browser ({late})')
        print('スマホ')
        await pg.set_viewport_size({'width': 390, 'height': 844})
        await pg.evaluate("() => document.getElementById('modeMobile').click()"); await pg.wait_for_timeout(300)
        acts = await ev("() => [...document.querySelectorAll('#mediaList .acts')].map(a => getComputedStyle(a).display !== 'none' && a.getBoundingClientRect().width > 0)")
        ok(acts and all(acts), f"a picture's buttons (前 / ← / ✕) show on a phone too ({acts})")
        await pg.click('#mediaList li .acts .fr')
        n = await ev("() => J.ui.project.media.tracks.front.cuts.length")
        hs = await ev("() => { const i = document.querySelector('#mediaBox i.se').getBoundingClientRect(); return [i.width, i.height]; }")
        ok(n == 1 and min(hs) >= 22, f'「前」 with a finger puts it over the lyrics, its frame has handles for a finger ({n} front, handle {hs})')
        errs = list(jz.errors)
        ok(not errs, f'no page errors ({errs[:3]})')
    print('\n' + ('ALL OK' if not fails else f'{len(fails)} FAILED'))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
