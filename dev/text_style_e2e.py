"""my-jizura: checks of lyric lines set by hand (src/08m_media_text.js, set_line_style) on the BUILT app, through tools/jizura_driver.py.
usage: python3 build.py && python3 dev/text_style_e2e.py [--browser chromium]
  the interlude title switch also clears the interlude the planner puts into a long gap between lines · a coloured line keeps its own
  colour scheme (background, accents) in a style with several schemes, also after it is locked · one cut takes its own background
  and decoration · single=False and 'auto' clear what they set · x / y / size move the lyric (the 'place' camera) · same plan twice.
Exit code 0 = all checks passed."""
import asyncio, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
from jizura_driver import Jizura

BROWSER = sys.argv[sys.argv.index('--browser') + 1] if '--browser' in sys.argv else 'auto'


async def main():
    fails = []
    ok = lambda cond, msg: (print(('  ok   ' if cond else '  FAIL ') + msg), None if cond else fails.append(msg))
    async with Jizura(browser=BROWSER, log=lambda m: None) as jz:
        ev = jz.page.evaluate
        print('interlude title')
        await jz.new_project(title='あの日の青', artist='テスト', lyrics='[00:01.00]なんなんですかね\n[00:12.00]この、やけに重たい感情\n[00:16.00][間奏 8]\n[00:24.00]西日を飲んだ')
        INTER = "() => J.ui.plan.cuts.filter(c => c.layout === 'interlude').map(c => [c.utext == null && c.text ? c.text : null, !!(c.params && c.params.showTitle)])"
        before = await ev(INTER)
        ok(any(t for t, _ in before) and any(s for _, s in before), f'a gap interlude carries the title and the [間奏] line shows it ({before})')
        await jz.set_text_options(interlude_title=False)
        after = await ev(INTER)
        ok(all((t or '').strip() == '' and not s for t, s in after), f'with the title off neither shows it ({after})')
        ok((await jz.get_plan())['title'] == 'あの日の青', 'the title stays in the project')
        print('colour on a style with several colour schemes')
        style = await ev("() => J.STYLE_ORDER.find(k => J.resolveStyle({ style: k, colors: {} }).schemes.length >= 3)")
        found = None
        for seed in range(1, 40):
            await jz.set_look(style=style, seed=seed)
            hit = await ev("() => { const P = J.ui.plan; const c = P.cuts.find(c => c.utext != null && c.scheme > 0); return c ? [c.line, c.scheme, P.style.schemes[c.scheme].bg] : null; }")
            if hit: found = hit; break
        ok(found is not None, f'a line on another colour scheme ({style}: {found})')
        if found:
            li, sch, bg = found
            r = await jz.set_line_style(li + 1, color='#ff3366')
            got = await ev(f"() => J.media.lineCuts(J.ui.plan, {li}).map(c => [c.scheme % {await ev('() => J.resolveStyle(J.ui.project).schemes.length')}, J.ui.plan.style.schemes[c.scheme].bg, J.ui.plan.style.schemes[c.scheme].fg])")
            ok(any(g[1] == bg for g in got) and all(g[2] == '#ff3366' for g in got), f'the colour keeps the scheme of the cut ({got})')
            await jz.set_line_style(li + 1, lock=True)
            again = await ev(f"() => J.media.lineCuts(J.ui.plan, {li}).map(c => [J.ui.plan.style.schemes[c.scheme].bg, J.ui.plan.style.schemes[c.scheme].fg])")
            ok([g[1:] for g in got] == again, f'… also after the line is locked ({again})')
            await jz.set_look(seed=999)
            again2 = await ev(f"() => J.media.lineCuts(J.ui.plan, {li}).map(c => [J.ui.plan.style.schemes[c.scheme].bg, J.ui.plan.style.schemes[c.scheme].fg])")
            ok(again2 == again, '… and when the other lines are laid out again')
        print('one cut / auto / single')
        await jz.new_project(lyrics='[00:01.00]この、やけに/重たい感情\n[00:06.00]西日を飲んだ/硝子の向こう')
        r = await jz.set_line_style(1, cut_times=[1.5])
        r = await jz.set_line_style(1, cut=2, bg='none', decor=[])
        ok(r['cuts'][1]['bg'] == 'none' and r['cuts'][1]['decor'] == [] and r['style']['cutTech'] == {'1': {'bg': 'none', 'decor': 'none'}},
           f"cut 2 takes its own background and no decoration {r['style'].get('cutTech')}")
        deco = await ev("() => J.DECOR_ORDER.find(k => !J.DECOR[k].special)")
        r = await jz.set_line_style(1, cut=1, decor=[deco])
        ok(r['cuts'][0]['decor'] == [deco], f'cut 1 takes one decoration ({deco})')
        try: await jz.set_line_style(1, cut=1, decor=[deco, deco]); ok(False, 'two decorations on one cut are refused')
        except Exception: ok(True, 'two decorations on one cut are refused')
        r = await jz.set_line_style(2, single=True); ok(r['style'].get('single') is True and len(r['cuts']) == 1, 'single=True: one cut')
        r = await jz.set_line_style(2, single=False); ok('single' not in r['style'], f"single=False clears it ({r['style']})")
        r = await jz.set_line_style(2, size=1.5, y=-0.2, decor=[]); ok(r['place'] == {'scale': 1.5, 'y': -0.2} and r['style'].get('decor') == [], 'size / y / no decorations')
        r = await jz.set_line_style(2, size='auto', y='auto', decor='auto'); ok(r['place'] == {} and 'decor' not in r['style'], "'auto' clears them")
        print('placement')
        await jz.set_line_style(2, x=0.25, size=0.5)
        cam = await ev("() => { const c = J.media.lineCuts(J.ui.plan, 1)[0]; return [c.cam, c.camP.x, c.camP.s, !!J.CAMERA[c.camP.base]]; }")
        ok(cam[0] == 'place' and cam[1] == 0.25 and cam[2] == 0.5 and cam[3], f'the lyric is moved by the place camera over its own camera ({cam})')
        same = await ev("() => { const a = JSON.stringify(J.plan(J.ui.project, null).cuts.map(c => [c.cam, c.camP, c.scheme])); const b = JSON.stringify(J.plan(J.ui.project, null).cuts.map(c => [c.cam, c.camP, c.scheme])); return a === b; }")
        ok(same, 'the same project gives the same plan')
        ok(not await ev("() => J.CAMERA_ORDER.includes('place')"), 'the place camera is never picked at random')
        ok(not jz.errors, f'no page errors {jz.errors[:3]}')
    print('FAILED:', len(fails)) if fails else print('all text style checks passed')
    sys.exit(1 if fails else 0)


asyncio.run(main())
