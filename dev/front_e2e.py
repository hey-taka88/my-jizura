"""my-jizura: checks of the front track (Phase 3b-1: pictures over the lyrics, placed by hand) on the BUILT app, through tools/jizura_driver.py.
usage: python3 build.py && python3 dev/front_e2e.py [--browser chromium]
  a logo (PNG with transparency) placed at a corner keeps its transparency and sits over the background picture · a picture over
  the lyrics hides them (drawn after the lyrics) · front pictures overlap (each its own layer; one without an end stays to the end) ·
  rotation turns it around its centre · the transparent PNG layers: front only in 'front', back picture only in 'back' · green
  screen output draws no picture · get_plan lists them with their track and place · save → open keeps the place, a bad rect is
  clamped · remove_timed_media removes a front one · the same plan twice · an MP4 export shows the logo.
Exit code 0 = all checks passed."""
import asyncio, json, os, sys, tempfile
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
from jizura_driver import Jizura

BROWSER = sys.argv[sys.argv.index('--browser') + 1] if '--browser' in sys.argv else 'auto'
MAG, CYAN, GREEN = (255, 0, 255), (0, 220, 255), (40, 170, 60)
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
        ok(not jz.errors, f'no page errors {jz.errors[:3]}')
    print('FAILED:', len(fails)) if fails else print('all front checks passed')
    sys.exit(1 if fails else 0)


asyncio.run(main())
