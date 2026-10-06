"""my-jizura: the placement editor (Phase 3b-3, src/11z_media_place.js) on the BUILT app, driven with the mouse like a person.
usage: python3 build.py && python3 dev/place_e2e.py [--browser chromium]
  「前」 on a picture puts it over the lyrics for the whole song (selected, with a frame on the preview) and takes it out of the
  automatic backgrounds · dragging the frame moves it, a corner resizes it, the knob turns it (Shift: 15° steps) — the preview
  shows it there · start / end / opacity in the list · スポイト: a click on the picture takes the colour under it as the key
  colour; a click beside it is refused; Esc stops it · 「中央に戻す」 · ✕ removes it · after a reload the placements and the
  list come back · an interrupted drag (pointercancel, Esc) keeps nothing · the eyedropper follows the motion of the picture ·
  no page errors.
Exit code 0 = all checks passed."""
import asyncio, os, sys, tempfile
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
from jizura_driver import Jizura

BROWSER = sys.argv[sys.argv.index('--browser') + 1] if '--browser' in sys.argv else 'auto'
MAG, BLUE, SCREEN, RED = (255, 0, 255), (40, 60, 200), (40, 180, 70), (220, 30, 30)
FRONT = "() => JSON.parse(JSON.stringify(J.ui.project.media.tracks.front.cuts))"
# the colour of the preview frame at a point of the page (the canvas as shown)
PIXEL = """async ([px, py]) => {
  const cv = document.getElementById('view'), r = cv.getBoundingClientRect(), plan = J.ui.plan;
  const w = 480, h = Math.round(480 * plan.H / plan.W), c = document.createElement('canvas'); c.width = w; c.height = h;
  (window.__plR || (window.__plR = new J.Renderer())).frame(c.getContext('2d'), plan, J.ui.t, { scale: w / plan.W });
  const d = c.getContext('2d').getImageData(Math.round((px - r.left) / r.width * (w - 1)), Math.round((py - r.top) / r.height * (h - 1)), 1, 1).data;
  return [d[0], d[1], d[2]];
}"""


def near(a, b, tol=40): return all(abs(int(x) - int(y)) <= tol for x, y in zip(a[:3], b[:3]))


def make(d):
    os.makedirs(d, exist_ok=True)
    Image.new('RGB', (1280, 720), BLUE).save(os.path.join(d, 'blue.png'))
    im = Image.new('RGBA', (300, 300), (0, 0, 0, 0)); ImageDraw.Draw(im).ellipse([10, 10, 290, 290], fill=MAG + (255,)); im.save(os.path.join(d, 'logo.png'))
    gs = Image.new('RGB', (400, 300), SCREEN); ImageDraw.Draw(gs).ellipse([150, 100, 250, 200], fill=(250, 250, 250)); gs.save(os.path.join(d, 'gscreen.png'))
    sp = Image.new('RGB', (400, 300), RED); ImageDraw.Draw(sp).rectangle([200, 0, 399, 299], fill=SCREEN); sp.save(os.path.join(d, 'split.png'))


async def main():
    fails = []
    ok = lambda cond, msg: (print(('  ok   ' if cond else '  FAIL ') + msg), None if cond else fails.append(msg))
    tmp = tempfile.mkdtemp(); pics = os.path.join(tmp, 'pics'); make(pics)
    async with Jizura(browser=BROWSER, log=lambda m: None) as jz:
        pg, ev = jz.page, jz.page.evaluate
        await pg.set_viewport_size({'width': 1500, 'height': 950})
        await jz.new_project(lyrics='[00:01.00]夜明けの色を覚えてる\n[00:05.00]ほどけた声が遠くで鳴った\n[00:09.00]名前のない明日へ\n[00:13.00]おわり')
        await jz.add_media([pics]); await jz.set_media_options(dim=0)
        await ev("() => J.uiApi.seek(6.5)")
        names = await ev("() => J.ui.project.media.assets.map(a => a.name)")
        nth = lambda name: names.index(name) + 1
        print('「前」')
        await pg.hover(f'#mediaList li:nth-child({nth("logo.png")})'); await pg.click(f'#mediaList li:nth-child({nth("logo.png")}) .fr')
        await pg.wait_for_selector('#mediaBox:not([hidden])')
        f = await ev(FRONT)
        logo = await ev("() => J.ui.project.media.assets.find(a => a.name === 'logo.png').id")
        ok(len(f) == 1 and f[0]['start'] == 0 and f[0]['end'] is None and f[0]['rect'] == {'x': 0, 'y': 0, 'w': 0.4, 'rot': 0} and await ev("() => J.mediaPlace.selected()") == f[0]['id'],
           f'the picture goes over the lyrics for the whole song, selected ({f})')
        ok(await pg.locator('#mediaFront .mf-row.sel').count() == 1, 'its row is in the list, selected')
        ok(logo not in await ev("() => J.ui.plan.media.back.cuts.map(c => c.assetId)"), 'it is no longer one of the automatic backgrounds')
        print('move / resize / turn')
        b = await pg.locator('#mediaBox').bounding_box(); cx, cy = b['x'] + b['width'] / 2, b['y'] + b['height'] / 2
        k = await ev("() => document.getElementById('view').getBoundingClientRect().width / J.ui.plan.W")
        W, H = await ev("() => [J.ui.plan.W, J.ui.plan.H]")
        await pg.mouse.move(cx, cy); await pg.mouse.down(); await pg.mouse.move(cx + 150, cy - 60, steps=6); await pg.mouse.up()
        r = (await ev(FRONT))[0]['rect']
        ok(abs(r['x'] - 150 / k / W) < 0.01 and abs(r['y'] + 60 / k / H) < 0.01, f'dragging the frame moves it ({r})')
        b = await pg.locator('#mediaBox').bounding_box(); cx, cy = b['x'] + b['width'] / 2, b['y'] + b['height'] / 2
        px = await ev(PIXEL, [cx, cy])
        ok(near(px, MAG), f'the preview shows it at its new place ({px})')
        se = await pg.locator('#mediaBox i.se').bounding_box()
        await pg.mouse.move(se['x'] + 5, se['y'] + 5); await pg.mouse.down()
        await pg.mouse.move(cx + (se['x'] + 5 - cx) * 0.5, cy + (se['y'] + 5 - cy) * 0.5, steps=6); await pg.mouse.up()
        r2 = (await ev(FRONT))[0]['rect']
        ok(abs(r2['w'] - 0.2) < 0.02 and r2['x'] == r['x'], f'a corner resizes it around its centre ({r2})')
        rk = await pg.locator('#mediaBox i.rot').bounding_box()
        await pg.mouse.move(rk['x'] + 5, rk['y'] + 5); await pg.mouse.down()
        await pg.keyboard.down('Shift'); await pg.mouse.move(cx + 200, cy + 3, steps=6); await pg.mouse.up(); await pg.keyboard.up('Shift')
        r3 = (await ev(FRONT))[0]['rect']
        ok(r3['rot'] == 90, f'the knob turns it, in 15° steps with Shift ({r3})')
        print('an interrupted drag')
        b = await pg.locator('#mediaBox').bounding_box(); cx, cy = b['x'] + b['width'] / 2, b['y'] + b['height'] / 2
        await pg.mouse.move(cx, cy); await pg.mouse.down(); await pg.mouse.move(cx - 120, cy + 40, steps=4)
        await ev("() => document.getElementById('mediaBox').dispatchEvent(new PointerEvent('pointercancel', { pointerId: 1, bubbles: true }))")
        await pg.mouse.up()
        ok((await ev(FRONT))[0]['rect'] == r3 and await ev("() => J.ui.plan.media.front.cuts[0].rect.x") == r3['x'], f'pointercancel puts it back where it was ({(await ev(FRONT))[0]["rect"]})')
        await pg.mouse.move(cx, cy); await pg.mouse.down(); await pg.mouse.move(cx + 90, cy + 30, steps=4)
        await pg.keyboard.press('Escape'); await pg.mouse.up()
        ok((await ev(FRONT))[0]['rect'] == r3, 'Esc during a drag puts it back too')
        print('time / opacity in the list')
        row = pg.locator('#mediaFront .mf-row').first
        await row.locator('.st').fill('2'); await row.locator('.st').dispatch_event('change')
        await pg.locator('#mediaFront .mf-row').first.locator('.en').fill('8'); await pg.locator('#mediaFront .mf-row').first.locator('.en').dispatch_event('change')
        await ev("() => { const e = document.querySelector('#mediaFront .mf-row .op'); e.value = '0.5'; e.dispatchEvent(new Event('change')); }")
        f = (await ev(FRONT))[0]
        ok(f['start'] == 2 and f['end'] == 8 and f['opacity'] == 0.5, f"start / end / opacity ({f['start']}, {f['end']}, {f['opacity']})")
        ok(await ev("() => J.ui.plan.media.front.cuts.map(c => [c.start, c.end])") == [[2, 8]], 'the plan follows')
        print('スポイト')
        await pg.hover(f'#mediaList li:nth-child({nth("gscreen.png")})'); await pg.click(f'#mediaList li:nth-child({nth("gscreen.png")}) .fr')
        await pg.wait_for_timeout(200)
        g = (await ev(FRONT))[1]
        ok(await ev("() => J.mediaPlace.selected()") == g['id'], 'the new one is selected')
        row2 = pg.locator('#mediaFront .mf-row').nth(1)
        await row2.locator('.key').select_option('spoid')
        ok(await ev("() => document.getElementById('viewport').classList.contains('media-spoid')"), 'the eyedropper is on')
        vr = await pg.locator('#view').bounding_box()
        await pg.mouse.click(vr['x'] + 8, vr['y'] + 8)                       # far from the picture
        ok('chroma' not in (await ev(FRONT))[1], 'a click beside the picture takes no colour')
        b = await pg.locator('#mediaBox').bounding_box()
        await pg.mouse.click(b['x'] + b['width'] * 0.1, b['y'] + b['height'] * 0.1)   # the green screen near its corner
        g = (await ev(FRONT))[1]
        col = g.get('chroma', {}).get('color', '')
        ok(col and near(tuple(int(col[i:i + 2], 16) for i in (1, 3, 5)), SCREEN, 10) and not await ev("() => document.getElementById('viewport').classList.contains('media-spoid')"),
           f'a click on the picture takes the colour under it ({col})')
        px = await ev(PIXEL, [b['x'] + b['width'] * 0.1, b['y'] + b['height'] * 0.1])
        ok(not near(px, SCREEN), f'… and the green is gone there ({px})')
        await pg.locator('#mediaFront .mf-row').nth(1).locator('.key').select_option('spoid')
        await pg.keyboard.press('Escape')
        ok(not await ev("() => document.getElementById('viewport').classList.contains('media-spoid')"), 'Esc stops the eyedropper')
        await pg.locator('#mediaFront .mf-row').nth(1).locator('.fit').click()
        ok((await ev(FRONT))[1]['rect'] == {'x': 0, 'y': 0, 'w': 0.4, 'rot': 0}, '「中央に戻す」')
        print('スポイト through the motion')
        sid = (await jz.add_timed_media('split.png', 0, 10, track='front', size=0.4, hold='push'))['id']
        await ev(f"() => J.mediaPlace.select('{sid}')")
        await ev("() => J.uiApi.seek(9.4)"); await pg.wait_for_timeout(200)          # pushed in to about 1.2× its placed size
        z = await ev(f"() => {{ const c = J.ui.plan.media.front.cuts.find(c => c.id === '{sid}'); const a = J.ui.project.media.assets.find(x => x.id === c.assetId); return J.media.cutBox(J.ui.plan, c, 9.4, J.ui.plan.W, J.ui.plan.H, J.media.layerFx(c, 9.4), a.w, a.h).dw / (0.4 * J.ui.plan.W); }}")
        vr = await pg.locator('#view').bounding_box()
        hx, hy = vr['x'] + vr['width'] * (0.5 + 0.22), vr['y'] + vr['height'] * 0.5   # outside where it is placed, inside where it is drawn
        await ev(f"() => J.mediaPlace.select('{sid}')"); await ev("() => J.mediaPlace.spoid()")
        await pg.mouse.click(hx, hy)
        col2 = next(c for c in await ev(FRONT) if c['id'] == sid).get('chroma', {}).get('color', '')
        ok(z > 1.15 and col2 and near(tuple(int(col2[i:i + 2], 16) for i in (1, 3, 5)), SCREEN, 10),
           f'the eyedropper follows the picture as drawn (×{z:.2f}): a click on its pushed-out edge takes that colour ({col2})')
        await jz.remove_timed_media(sid)
        print('reload / remove')
        await ev("() => J.uiApi.flushSave()")
        await pg.reload(); await pg.wait_for_function('window.J && J.ui && J.ui.plan && J.mediaUI && J.mediaPlace')
        await pg.wait_for_function('J.mediaAssets.size >= 3', timeout=30000)
        f = await ev(FRONT)
        await pg.wait_for_timeout(300)
        ok(len(f) == 2 and f[0]['rect']['rot'] == 90 and f[1].get('chroma', {}).get('color') == col and await pg.locator('#mediaFront .mf-row').count() == 2,
           f'after a reload the placements and the list come back ({len(f)})')
        await pg.locator('#mediaFront .mf-row').first.locator('.del').click()
        ok(len(await ev(FRONT)) == 1, '✕ removes one')
        ok(not jz.errors, f'no page errors {jz.errors[:3]}')
    print('FAILED:', len(fails)) if fails else print('all placement checks passed')
    sys.exit(1 if fails else 0)


asyncio.run(main())
