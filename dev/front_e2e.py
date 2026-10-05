"""my-jizura: checks of the front track (Phase 3b-1: pictures over the lyrics, placed by hand) on the BUILT app, through tools/jizura_driver.py.
usage: python3 build.py && python3 dev/front_e2e.py [--browser chromium]
  a logo (PNG with transparency) placed at a corner keeps its transparency and sits over the background picture · a picture over
  the lyrics hides them (drawn after the lyrics) · front pictures overlap (each its own layer; one without an end stays to the end) ·
  rotation turns it around its centre · the transparent PNG layers: front only in 'front', back picture only in 'back' · green
  screen output draws no picture · get_plan lists them with their track and place · save → open keeps the place, a bad rect is
  clamped · remove_timed_media removes a front one · the same plan twice · an MP4 export shows the logo ·
  クロマキー: a green-screen picture with key='auto' loses its screen (the colour found round its edge) and keeps its subject and a
  grey patch, the same without WebGL, a clip frame is keyed the same way, a colour given by hand, refused keys, MP4.
Exit code 0 = all checks passed."""
import asyncio, json, os, sys, tempfile
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
from jizura_driver import Jizura

BROWSER = sys.argv[sys.argv.index('--browser') + 1] if '--browser' in sys.argv else 'auto'
MAG, CYAN, GREEN, BLUE, SCREEN = (255, 0, 255), (0, 220, 255), (40, 170, 60), (40, 60, 200), (40, 180, 70)
GD = tuple(int(v * 0.75) for v in GREEN)           # the background picture under the default 暗さ (0.25)

# pixels of a frame at time t, at points (x, y) given from the frame centre (fractions of the frame, as the rect uses)
PIX = """async ([t, opts, pts]) => {
  const plan = J.ui.plan, w = 320, h = Math.round(320 * plan.H / plan.W);
  const cv = document.createElement('canvas'); cv.width = w; cv.height = h;
  const R = window.__feR || (window.__feR = new J.Renderer());
  R.frame(cv.getContext('2d'), plan, t, Object.assign({ scale: w / plan.W }, opts));
  const d = cv.getContext('2d').getImageData(0, 0, w, h).data;
  return pts.map(([fx, fy]) => { const x = Math.round((0.5 + fx) * (w - 1)), y = Math.round((0.5 + fy) * (h - 1)), i = (y * w + x) * 4; return [d[i], d[i + 1], d[i + 2], d[i + 3]]; });
}"""


def near(a, b, tol=40): return all(abs(int(x) - int(y)) <= tol for x, y in zip(a[:3], b[:3]))


def make(d):
    os.makedirs(d, exist_ok=True)
    im = Image.new('RGBA', (200, 200), (0, 0, 0, 0)); ImageDraw.Draw(im).rectangle([50, 50, 149, 149], fill=MAG + (255,)); im.save(os.path.join(d, 'logo.png'))
    Image.new('RGB', (300, 100), CYAN).save(os.path.join(d, 'bar.png'))
    Image.new('RGB', (1280, 720), GREEN).save(os.path.join(d, 'green.png'))
    Image.new('RGB', (1280, 720), BLUE).save(os.path.join(d, 'blue.png'))
    gs = Image.new('RGB', (400, 300), SCREEN); dr = ImageDraw.Draw(gs)            # a green screen with a magenta subject and a grey one
    dr.ellipse([150, 100, 250, 200], fill=MAG); dr.rectangle([20, 230, 80, 290], fill=(128, 128, 128)); gs.save(os.path.join(d, 'gscreen.png'))


async def main():
    fails = []
    ok = lambda cond, msg: (print(('  ok   ' if cond else '  FAIL ') + msg), None if cond else fails.append(msg))
    tmp = tempfile.mkdtemp(); pics = os.path.join(tmp, 'pics'); make(pics)
    async with Jizura(browser=BROWSER, log=lambda m: None) as jz:
        ev = jz.page.evaluate
        lyr = '\n'.join(f'[00:{1 + 4 * i:02d}.00]{t}' for i, t in enumerate(['夜明けの色を覚えてる', 'ほどけた声が遠くで鳴った', '手を離す', 'ねえ、まだ間に合うかな', '名前のない明日へ', 'おわり']))
        await jz.new_project(lyrics=lyr); await jz.set_look(seed=3)
        await jz.add_media([pics]); await jz.set_media_options(auto=False)
        await jz.add_timed_media('green.png', 0)                                      # the background: one green picture
        r = await jz.add_timed_media('logo.png', 0, track='front', x=0.3, y=-0.3, size=0.2)
        logo = r['id']
        print('a logo at a corner')
        # the logo is 0.2 of the frame wide; its magenta square is the middle half, the rest of the PNG is transparent
        px = await ev(PIX, [6.5, {}, [[0.3, -0.3], [0.38, -0.3], [-0.3, 0.3]]])
        ok(near(px[0], MAG) and near(px[1], GD) and near(px[2], GD), f'the logo sits at its place, its transparent edge shows the background ({px})')
        p = await jz.get_plan()
        ok(any(x['id'] == logo and x['track'] == 'front' and x['x'] == 0.3 and x['size'] == 0.2 for x in p['timed']) and p['front'] and p['front'][0]['placed'],
           f"get_plan lists it with its track and place ({[x for x in p['timed'] if x['track'] == 'front']})")
        print('over the lyrics, overlapping, turned')
        await jz.add_timed_media('bar.png', 8, 12, track='front', size=0.6)              # a wide bar over the middle of the frame
        mid = await ev("() => { const c = J.ui.plan.cuts.find(c => c.utext != null && c.start <= 10 && c.end > 10); return c ? 10 : null; }")
        px = await ev(PIX, [10.0, {}, [[0, 0], [0.3, -0.3]]])
        ok(mid and near(px[0], CYAN) and near(px[1], MAG), f'a front picture covers the lyrics, and the logo still shows beside it ({px})')
        px = await ev(PIX, [13.0, {}, [[0, 0], [0.3, -0.3]]])
        ok(not near(px[0], CYAN) and near(px[1], MAG), f'after its end only the logo stays ({px})')
        await jz.add_timed_media('bar.png', 14.5, 18, track='front', size=0.3, rot=90)
        flat = await ev(PIX, [10.0, {}, [[0.2, 0], [0, -0.2]]])
        turned = await ev(PIX, [16.0, {}, [[0.12, 0], [0, -0.2]]])
        ok(near(flat[0], CYAN) and not near(flat[1], CYAN) and near(turned[1], CYAN) and not near(turned[0], CYAN), f'rot=90 stands the bar up ({flat} → {turned})')
        print('layers and green screen')
        back = await ev(PIX, [6.5, {'transparent': True, 'layer': 'back'}, [[0.3, -0.3], [-0.3, 0.3]]])
        front = await ev(PIX, [6.5, {'transparent': True, 'layer': 'front'}, [[0.3, -0.3], [-0.3, 0.3]]])
        ok(near(back[0], GD) and back[1][3] == 255 and near(front[0], MAG) and front[0][3] == 255 and front[1][3] == 0,
           f'transparent PNG: the logo only in the front layer, the background picture only in the back layer ({back} / {front})')
        key = await ev("""async (P) => { const S = J.ui, k = S.project.keyBg; S.project.keyBg = 'green'; J.uiApi.replan();
          const r = await (""" + PIX + """)([6.5, {}, [[0.3, -0.3]]]); S.project.keyBg = k; J.uiApi.replan(); return r; }""", None)
        ok(not near(key[0], MAG), f'green screen output draws no picture ({key})')
        same = await ev("() => JSON.stringify(J.plan(J.ui.project, null).media.front) === JSON.stringify(J.plan(J.ui.project, null).media.front)")
        ok(same, 'the same project gives the same front track')
        print('save / open / remove')
        pth = os.path.join(tmp, 'f.jizura.json'); await jz.save_project(pth)
        doc = json.load(open(pth, encoding='utf-8'))
        doc['media']['tracks']['front']['cuts'][0]['rect'] = {'x': 9, 'y': -0.3, 'w': 99, 'rot': 720}
        bad = os.path.join(tmp, 'bad.jizura.json'); json.dump(doc, open(bad, 'w', encoding='utf-8'), ensure_ascii=False)
        await jz.new_project(); await jz.open_project(pth); await jz.add_media([pics])
        px = await ev(PIX, [6.5, {}, [[0.3, -0.3]]])
        ok(near(px[0], MAG), f'save → open keeps the logo where it was ({px})')
        await jz.open_project(bad)
        rc = await ev("() => J.ui.project.media.tracks.front.cuts[0].rect")
        ok(rc == {'x': 1, 'y': -0.3, 'w': 4, 'rot': 180}, f'a rect out of range in a project file is clamped ({rc})')
        await jz.open_project(pth)
        r = await jz.remove_timed_media(logo)
        ok(r['removed'] == 1 and not any(x['id'] == logo for x in r['timed']), 'remove_timed_media removes a front picture')
        try: await jz.add_timed_media('logo.png', 0, track='top'); ok(False, 'an unknown track is refused')
        except Exception: ok(True, 'an unknown track is refused')
        print('export (short MP4)')
        await jz.add_timed_media('logo.png', 0, track='front', x=0.3, y=-0.3, size=0.2)
        res = await ev("""async () => {
          if (typeof VideoEncoder === 'undefined') return { skip: 'no WebCodecs' };
          const S = J.ui, P = Object.assign({}, S.project, { res: 720, includeAudio: false });
          let r; try { r = await J.exportMP4({ plan: S.plan, project: P, audio: null, quality: 'normal', range: { t0: 6.0, t1: 7.0 } }); } catch (e) { return { skip: String(e.message || e).slice(0, 200) }; }
          const v = document.createElement('video'); v.muted = true; v.src = URL.createObjectURL(r.blob);
          await new Promise((ok, no) => { v.onloadeddata = ok; v.onerror = () => no(new Error('video')); });
          v.currentTime = 0.5; await new Promise(ok => { v.onseeked = ok; });
          const c = document.createElement('canvas'); c.width = 320; c.height = 180; const x = c.getContext('2d'); x.drawImage(v, 0, 0, 320, 180);
          const at = (fx, fy) => { const d = x.getImageData(Math.round((0.5 + fx) * 319), Math.round((0.5 + fy) * 179), 1, 1).data; return [d[0], d[1], d[2]]; };
          return { codec: r.codec, logo: at(0.3, -0.3), back: at(-0.3, 0.3) }; }""")
        if 'skip' in res: print('  skip export:', res['skip'])
        else: ok(near(res['logo'], MAG, 60) and near(res['back'], GD, 60), f"MP4 ({res['codec']}) shows the logo over the background ({res})")
        print('クロマキー')
        await jz.new_project(lyrics=lyr); await jz.set_look(seed=3)
        await jz.add_media([pics]); await jz.set_media_options(auto=False, dim=0)
        await jz.add_timed_media('blue.png', 0)
        r = await jz.add_timed_media('gscreen.png', 0, track='front', size=0.5, key='auto')
        # the picture is half the frame wide (0.5 W × 0.375 W); its subject sits in the middle, the grey square at the bottom left
        pts = [[0, 0], [-0.2, -0.25], [0.2, 0.2], [-0.2, 0.28]]
        BL = BLUE
        px = await ev(PIX, [6.5, {}, pts])
        ok(near(px[0], MAG) and near(px[1], BL) and near(px[2], BL) and near(px[3], (128, 128, 128), 30),
           f'the green screen is taken out, the subject and a grey patch stay ({px})')
        info = await ev("() => J.media.chromaInfo()")
        tm = (await jz.get_plan())['timed']; fk = [x for x in tm if x['track'] == 'front'][0]
        ok(fk['key'].startswith('auto (#') and near(tuple(int(fk['key'][7 + 2 * i:9 + 2 * i], 16) for i in range(3)), SCREEN, 12),
           f"'auto' finds the screen colour round the edge ({fk['key']}, webgl {info['webgl']})")
        cpu = await ev("async (a) => { J.media.chromaCPU = true; const r = await (" + PIX + ")(a); J.media.chromaCPU = false; return r; }", [6.6, {}, pts])
        ok(near(cpu[0], MAG) and near(cpu[1], BL) and near(cpu[3], (128, 128, 128), 30), f'without WebGL the same picture keys the same way ({cpu})')
        clip = await ev("""() => { const cv = document.createElement('canvas'); cv.width = 64; cv.height = 36; const x = cv.getContext('2d');
          x.fillStyle = '#28b446'; x.fillRect(0, 0, 64, 36); x.fillStyle = '#ff00ff'; x.fillRect(24, 10, 16, 16);
          const out = J.media.keyed({ type: 'video', name: 'clip' }, cv, { chroma: { color: '#28b446', tol: 0.1, soft: 0.08, spill: 0.6 } }, 0);
          const d = out.getContext('2d').getImageData(0, 0, out.width, out.height).data, at = (px, py) => d[(py * out.width + px) * 4 + 3];
          return [at(32, 18), at(4, 4)]; }""")
        ok(clip[0] > 240 and clip[1] < 10, f'a clip frame is keyed the same way (alpha subject / screen {clip})')
        await jz.add_timed_media('gscreen.png', 10, 14, track='front', size=0.5, key='#ff00ff', key_tol=0.2)
        px = await ev(PIX, [12.0, {}, [[-0.2, -0.25]]])               # this one takes magenta out: its green screen stays
        ok(near(px[0], SCREEN), f'a colour given by hand takes that colour out, not the screen ({px})')
        same = await ev("() => JSON.stringify(J.plan(J.ui.project, null).media.front) === JSON.stringify(J.plan(J.ui.project, null).media.front)")
        ok(same, 'the same project gives the same keyed front track')
        try: await jz.add_timed_media('gscreen.png', 0, track='front', key='green'); ok(False, 'a key that is not auto / #rrggbb is refused')
        except Exception: ok(True, 'a key that is not auto / #rrggbb is refused')
        res = await ev("""async () => {
          if (typeof VideoEncoder === 'undefined') return { skip: 'no WebCodecs' };
          const S = J.ui, P = Object.assign({}, S.project, { res: 720, includeAudio: false });
          let r; try { r = await J.exportMP4({ plan: S.plan, project: P, audio: null, quality: 'normal', range: { t0: 6.0, t1: 7.0 } }); } catch (e) { return { skip: String(e.message || e).slice(0, 200) }; }
          const v = document.createElement('video'); v.muted = true; v.src = URL.createObjectURL(r.blob);
          await new Promise((ok, no) => { v.onloadeddata = ok; v.onerror = () => no(new Error('video')); });
          v.currentTime = 0.5; await new Promise(ok => { v.onseeked = ok; });
          const c = document.createElement('canvas'); c.width = 320; c.height = 180; const x = c.getContext('2d'); x.drawImage(v, 0, 0, 320, 180);
          const at = (fx, fy) => { const d = x.getImageData(Math.round((0.5 + fx) * 319), Math.round((0.5 + fy) * 179), 1, 1).data; return [d[0], d[1], d[2]]; };
          return { subject: at(0, 0), screen: at(-0.2, -0.25) }; }""")
        if 'skip' in res: print('  skip export:', res['skip'])
        else: ok(near(res['subject'], MAG, 60) and near(res['screen'], BL, 60), f"MP4: the subject over the background, no green ({res})")
        ok(not jz.errors, f'no page errors {jz.errors[:3]}')
    print('FAILED:', len(fails)) if fails else print('all front checks passed')
    sys.exit(1 if fails else 0)


asyncio.run(main())
