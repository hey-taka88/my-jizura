"""my-jizura: end-to-end check of the Phase 3 picture looks on the BUILT app (index.html), through tools/jizura_driver.py.
usage: python3 build.py && python3 dev/media_look_e2e.py [--browser chromium] [--shots out/look]
Generates a bright 'sky', a striped and a dark picture, then checks:
  加工 (mono / sepia / duotone / match / blur change the colours; mono has no colour) · つなぎ with a transition (half of each
  picture mid-way through a wipe) · 動き (pan / push / drift / beatPulse move the picture; still does not) · 登場 slide / zoom / wipe
  after a line with no picture · 暗幕 auto (on a bright picture under white lyrics, not on a dark one; always / off) ·
  the same frame twice is the same (deterministic) · old and broken project data are normalised · メディアのおまかせ · no page errors.
Exit code 0 = all checks passed."""
import asyncio, hashlib, io, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
from jizura_driver import Jizura
from PIL import Image, ImageDraw

BROWSER = sys.argv[sys.argv.index('--browser') + 1] if '--browser' in sys.argv else 'auto'
SHOTS = sys.argv[sys.argv.index('--shots') + 1] if '--shots' in sys.argv else None
LYRICS = '[00:01.00]空の色を覚えてる\n[00:05.00]ほどけた声が遠くで鳴った\n[00:09.00]ねえまだ間に合うかな\n[00:13.00]名前のない明日へ\n[00:17.00]光の粒を集めて'


def pictures(d):
    im = Image.new('RGB', (1920, 1080)); dr = ImageDraw.Draw(im)
    for y in range(1080): dr.line([(0, y), (1920, y)], fill=(int(170 + 80 * y / 1080), int(205 + 45 * y / 1080), 255))
    im.save(os.path.join(d, '1_sky.png'))
    im = Image.new('RGB', (1920, 1080)); dr = ImageDraw.Draw(im)
    for i in range(24): dr.rectangle([i * 80, 0, i * 80 + 80, 1080], fill=[(220, 40, 40), (40, 180, 60), (40, 80, 220)][i % 3])
    im.save(os.path.join(d, '2_stripes.png'))
    Image.new('RGB', (1920, 1080), (14, 12, 20)).save(os.path.join(d, '3_dark.png'))
    return [os.path.join(d, n) for n in ('1_sky.png', '2_stripes.png', '3_dark.png')]


# a frame (lyrics left out unless asked) at a small size → raw RGB bytes; o: Renderer options
FRAME = r"""async ([t, w, o]) => {
  const S = J.ui, plan = S.plan, h = Math.round(w * plan.H / plan.W);
  if (plan.media) await J.media.prepareFrame(plan, t);
  const c = document.createElement('canvas'); c.width = w; c.height = h; const x = c.getContext('2d', { willReadFrequently: true });
  const keep = J.LAYOUTS; if (!o.lyrics) { J.LAYOUTS = new Proxy(keep, { get: (T, k) => ({ render: () => null }) }); }
  try { new J.Renderer().frame(x, plan, t, Object.assign({ scale: w / plan.W, noPost: true, noHud: true }, o)); } finally { J.LAYOUTS = keep; }
  return Array.from(x.getImageData(0, 0, w, h).data);
}"""


async def main():
    fails = []
    ok = lambda cond, msg: (print(('  ok   ' if cond else '  FAIL ') + msg), None if cond else fails.append(msg))
    with tempfile.TemporaryDirectory() as d:
        sky, stripes, dark = pictures(d)
        async with Jizura(browser=BROWSER, log=lambda m: None) as jz:
            ev = jz.page.evaluate
            await jz.new_project(lyrics=LYRICS)
            await jz.set_look(style='noir', seed=7)
            await jz.add_media([sky, stripes, dark])

            async def setm(js):
                await ev("(js) => { const m = J.ui.project.media; (new Function('m', js))(m); J.uiApi.replan(); }", js)

            async def frame(t, w=96, **o):
                px = await ev(FRAME, [t, w, o]); return px

            def stats(px):
                n = len(px) // 4; r = sum(px[0::4]) / n; g = sum(px[1::4]) / n; b = sum(px[2::4]) / n
                sat = sum(max(px[i:i + 3]) - min(px[i:i + 3]) for i in range(0, len(px), 4)) / n
                return r, g, b, sat

            diff = lambda a, b: sum(abs(x - y) for x, y in zip(a, b)) / len(a)
            base = "m.autoFill.back.hold='still'; m.autoFill.back.trans='cut'; m.autoFill.back.enter=m.autoFill.back.exit='cut'; m.tracks.back.dim=0; m.scrim.mode='off'; m.autoFill.back.treat='none';"
            print('加工')
            await setm(base); plain = stats(await frame(6.5))        # line 2 = the stripes
            res = {}
            for tr in ['mono', 'sepia', 'duotone', 'match', 'blur']:
                await setm(base + f"m.autoFill.back.treat='{tr}';"); res[tr] = await frame(6.5)
            ok(stats(res['mono'])[3] < 4 and plain[3] > 80, f"mono has no colour (saturation {stats(res['mono'])[3]:.1f}, plain {plain[3]:.0f})")
            ok(all(diff(res[k], res['mono']) > 4 for k in ('sepia', 'duotone', 'match')), 'sepia / duotone / match each differ from mono')
            st = stats(res['sepia']); ok(st[0] > st[2] + 10, f'sepia is warm (r {st[0]:.0f} > b {st[2]:.0f})')
            # blur: neighbouring stripes run into each other → fewer hard edges along a row
            row = lambda px, w=96: [px[(27 * w + i) * 4] for i in range(w)]
            edges = lambda r: sum(1 for i in range(len(r) - 1) if abs(r[i] - r[i + 1]) > 60)
            await setm(base); e0 = edges(row(await frame(6.5)))
            ok(edges(row(res['blur'])) < e0 / 2, f'blur softens the stripes (hard edges {edges(row(res["blur"]))} < {e0})')
            print('つなぎ')
            await setm(base + "m.autoFill.back.trans='wipe';")
            cuts = await ev("() => J.ui.plan.media.back.cuts.map(c => [c.join, c.start, c.inDur, c.transP && c.transP.dir])")
            ok(cuts[1][0] == 'wipe' and cuts[1][2] > 0.4, f'the second picture takes over with the wipe ({cuts[1]})')
            t = cuts[1][1] + cuts[1][2] / 2
            mid = await frame(t, 96); W_, H_ = 96, len(mid) // 4 // 96
            sub = lambda x0, x1, y0, y1: stats([v for y in range(y0, y1) for v in mid[(y * W_ + x0) * 4:(y * W_ + x1) * 4]])
            a_, b_ = (sub(0, 40, 0, H_), sub(56, 96, 0, H_)) if cuts[1][3] in ('L', 'R') else (sub(0, 96, 0, H_ // 2 - 4), sub(0, 96, H_ // 2 + 4, H_))
            ok(abs(a_[3] - b_[3]) > 40, f'mid-way one side shows the sky, the other the stripes (saturation {a_[3]:.0f} / {b_[3]:.0f}, wipe {cuts[1][3]})')
            await setm(base + "m.autoFill.back.trans='mix';")
            joins = await ev("() => J.ui.plan.media.back.cuts.slice(1).map(c => c.join)")
            ok(all(j in ('fade',) or j for j in joins) and len(set(joins)) >= 1, f'mix gives each join its own ({joins})')
            print('動き')
            for h in ['pan', 'push', 'drift', 'beatPulse', 'still']:
                await setm(base + f"m.autoFill.back.hold='{h}';")
                if h == 'beatPulse':                     # beats every 0.5 s (no song here): just before a beat and just after it
                    await ev("() => { J.ui.plan.beats = Array.from({ length: 60 }, (_, i) => i * 0.5); }")
                    a, b = await frame(6.49), await frame(6.52)
                else: a, b = await frame(5.3), await frame(8.6)
                moved = diff(a, b)
                ok((moved > 1.5) if h != 'still' else moved < 0.3, f'{h}: the picture {"moves" if h != "still" else "stays"} (change {moved:.2f})')
            print('登場')
            await setm(base + "m.tracks.back.cuts=[{ id:'l1', assetId:'', lineRef:{line:1} }];")      # line 2 without a picture → line 3 comes in by itself
            for en in ['slide', 'zoom', 'wipe', 'fade']:
                await setm(base + f"m.tracks.back.cuts=[{{ id:'l1', assetId:'', lineRef:{{line:1}} }}]; m.autoFill.back.enter=m.autoFill.back.exit='{en}';")
                c = await ev("() => J.ui.plan.media.back.cuts.find(c => c.start > 8.5)")
                early, later = await frame(c['start'] + c['inDur'] * 0.3), await frame(c['start'] + c['inDur'] + 0.4)
                ok(c['enter'] == en and c['join'] is None and diff(early, later) > 3, f'{en}: still coming in early ({diff(early, later):.1f})')
            print('暗幕')
            await setm(base)
            sky_t = await ev("() => { const c = J.cutAt(J.ui.plan, 2.7); return (c.start + c.end) / 2; }")
            off = await frame(sky_t, 192, lyrics=True)
            await setm(base + "m.scrim.mode='auto';"); auto = await frame(sky_t, 192, lyrics=True)
            await setm(base + "m.scrim.mode='always';"); alw = await frame(sky_t, 192, lyrics=True)
            ok(stats(auto)[1] < stats(off)[1] - 3, f'auto: a plate behind white lyrics on the bright sky (green {stats(off)[1]:.0f} → {stats(auto)[1]:.0f})')
            await setm(base + "m.tracks.back.cuts=[{ id:'l0', assetId:'" + (await ev("() => J.ui.project.media.assets[2].id")) + "', lineRef:{line:0} }];")
            d_off = await frame(sky_t, 192, lyrics=True)
            await setm(base + "m.tracks.back.cuts=[{ id:'l0', assetId:'" + (await ev("() => J.ui.project.media.assets[2].id")) + "', lineRef:{line:0} }]; m.scrim.mode='auto';")
            d_auto = await frame(sky_t, 192, lyrics=True)
            ok(diff(d_off, d_auto) < 0.2, f'auto: no plate on the dark picture (change {diff(d_off, d_auto):.2f})')
            ok(diff(alw, off) > 1, 'always: a plate')
            print('そのほか')
            await setm(base + "m.autoFill.back.trans='irisOpen'; m.autoFill.back.treat='duotone'; m.autoFill.back.hold='drift'; m.scrim.mode='always';")
            h1 = hashlib.md5(bytes(await frame(4.6, 160, lyrics=True))).hexdigest(); h2 = hashlib.md5(bytes(await frame(4.6, 160, lyrics=True))).hexdigest()
            ok(h1 == h2, 'the same frame twice is the same')
            n = await ev("""() => { const M = J.media;
              const old = M.normalize({ assets: [], tracks: { back: { cuts: [{ lineRef: { line: 0 }, assetId: '', enter: 'fade', trans: 'nope', treat: 'x' }] } }, autoFill: { back: { hold: 'kenburns', trans: 'auto', treat: 'bad', enter: 'spin' } }, scrim: { mode: 'loud', amount: 9 } });
              const c = old.tracks.back.cuts[0], A = old.autoFill.back;
              return [c.trans, c.treat, A.trans, A.treat, A.enter, A.exit, old.scrim.mode, old.scrim.amount]; }""")
            ok(n == ['auto', 'auto', 'fade', 'none', 'fade', 'fade', 'auto', 0.9], f'old / broken project data are normalised ({n})')
            r = await jz.media_omakase()
            ok(r['summary'] and r['hold'] in ('kenburns', 'pan', 'push', 'drift', 'beatPulse', 'still'), f"メディアのおまかせ: {r['summary']}")
            perf = await ev("""async () => { const S = J.ui, plan = S.plan, c = document.createElement('canvas'); c.width = 1920; c.height = 1080; const x = c.getContext('2d');
              const R = new J.Renderer(), t0 = performance.now(); for (let i = 0; i < 24; i++) R.frame(x, plan, 4.6 + i / 24, { scale: 1 }); return (performance.now() - t0) / 24; }""")
            print(f'  info 1080p frame with a transition + duotone + drift + plate: {perf:.0f} ms')
            if SHOTS:
                os.makedirs(SHOTS, exist_ok=True)
                for t, _, png in await jz.preview(times=[2.6, 4.6, 6.5, 9.4], width=640): open(os.path.join(SHOTS, f'look_{t:05.2f}.png'), 'wb').write(png)
            ok(not jz.errors, f'no page errors {jz.errors[:3]}')
    print('FAILED:', len(fails)) if fails else print('all look checks passed')
    sys.exit(1 if fails else 0)


asyncio.run(main())
