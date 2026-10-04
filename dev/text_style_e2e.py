"""my-jizura: checks of lyric lines set by hand (src/08m_media_text.js, set_line_style) on the BUILT app, through tools/jizura_driver.py.
usage: python3 build.py && python3 dev/text_style_e2e.py [--browser chromium]
  the interlude title switch also clears the interlude the planner puts into a long gap between lines · a coloured line keeps its own
  colour scheme (background, accents) in a style with several schemes, also after it is locked · one cut takes its own background
  and decoration · single=False and 'auto' clear what they set · x / y / size move the lyric (the 'place' camera) · same plan twice ·
  語の時刻: word times from Suno words, enhanced LRC and the 「LRC を読み込む」 button make the cuts of a line change when their word is
  sung (a recap cut and cut times set by hand stay), the lowest alignment confidence is reported, save → open keeps them ·
  固定: a line with a recap cut keeps its cut times when locked (the app's lock alone moves them), through set_look and a restyle;
  unlocking in the app lets the kept times go, a cut time set by hand stays (also one changed after the lock) · colour / position /
  size on a locked line keep its cut times (also after new word times), a layout change re-lays it · Whisper segments keep their words.
Exit code 0 = all checks passed."""
import asyncio, json, os, sys, tempfile
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
        print('語の時刻')
        words = [{'word': 'この、', 'start_s': 5.0, 'end_s': 5.3, 'p_align': 0.9}, {'word': 'やけに', 'start_s': 5.4, 'end_s': 6.5, 'p_align': 0.8}, {'word': '重たい', 'start_s': 6.7, 'end_s': 7.2, 'p_align': 0.95},
                 {'word': '感情\n', 'start_s': 7.3, 'end_s': 8.4, 'p_align': 0.4}, {'word': '西日を', 'start_s': 11.0, 'end_s': 11.5}, {'word': '飲んだ', 'start_s': 11.6, 'end_s': 12.5},
                 {'word': '硝子の', 'start_s': 12.8, 'end_s': 13.2}, {'word': '向こう', 'start_s': 13.3, 'end_s': 14.5}]
        suno = json.dumps({'aligned_words': words}, ensure_ascii=False)
        await jz.new_project(); await jz.set_look(seed=4)
        r = await jz.set_lyrics(text=suno)
        ok(r['wordTimed'] == 2, f"both lines keep their word times ({r})")
        cuts = lambda l: [(c['text'], c['start']) for c in l['cuts']]
        l1, l2 = await jz.get_line(1), await jz.get_line(2)
        st1 = dict(cuts(l1)); st2 = dict(cuts(l2))
        ok(l1['cutTimes'] == 'words' and st1.get('重たい感情') == 6.7, f'line 1: 重たい感情 starts when it is sung (6.7) {cuts(l1)}')
        ok(st2.get('飲んだ') == 11.6 and st2.get('硝子の向こう') == 12.8, f'line 2 follows its words too {cuts(l2)}')
        ok(any(c['text'] == 'この、やけに重たい感情' for c in l1['cuts']), 'the recap cut (the whole line again) stays')
        ok(l1['confidence'] == 0.4 and l2['confidence'] is None and (await jz.get_plan())['lines'][0]['confidence'] == 0.4, 'the lowest alignment confidence is reported per line')
        base = await ev("""() => { const t = J.ui.project.media.text, W = t.words; t.words = []; J.uiApi.replan();
          const s = J.media.lineCuts(J.ui.plan, 0).filter(c => !c.recap).map(c => +c.start.toFixed(2)); t.words = W; J.uiApi.replan(); return s; }""")
        ok(len(base) >= 2 and base[1] != 6.7, f'without the word times the cut would start elsewhere ({base})')
        ok(dict(cuts(await jz.get_line(1))).get('重たい感情') == 6.7, '… and with them back it starts at 6.7 again')
        r = await jz.set_line_style(1, cut_times=[1.0])
        ok(r['cutTimes'] == 'by hand' and dict(cuts(r)).get('重たい感情') == 6.0, f'cut times set by hand win {cuts(r)}')
        await jz.set_line_style(1, cut_times='auto')
        d = tempfile.mkdtemp(); pth = os.path.join(d, 'w.jizura.json'); await jz.save_project(pth)
        await jz.new_project(); await jz.open_project(pth)
        ok(dict(cuts(await jz.get_line(1))).get('重たい感情') == 6.7, 'save → open keeps the word times')
        lrc = '[00:05.00]<00:05.00>この、<00:05.40>やけに<00:06.70>重たい<00:07.30>感情<00:08.40>\n[00:11.00]西日を飲んだ'
        await jz.new_project(); await jz.set_look(seed=4)
        r = await jz.set_lyrics(text=lrc)
        l1 = await jz.get_line(1)
        ok(r['wordTimed'] == 1 and dict(cuts(l1)).get('重たい感情') == 6.7 and [w['t'] for w in l1['words']] == [5, 5.4, 6.7, 7.3], f"enhanced LRC word tags give word times {[w['t'] for w in l1['words']]}")
        fp = os.path.join(d, 'suno.json'); open(fp, 'w', encoding='utf-8').write(suno)
        await jz.new_project(); await jz.set_look(seed=4)
        await jz.page.set_input_files('#fileLrc', fp)
        await jz.page.wait_for_function("() => J.ui.project.media.text.words.length === 2", timeout=10000)
        ok(dict(cuts(await jz.get_line(1))).get('重たい感情') == 6.7, 'the 「LRC を読み込む」 button keeps the word times as well')
        await jz.set_lyrics(text='[00:01.00]手で打った歌詞\n[00:04.00]時刻だけ')
        ok(await ev("() => J.ui.project.media.text.words.length") == 0, 'lyrics without word times drop the old ones')
        print('固定と句の時刻')
        await jz.new_project(lyrics='[00:01.00]この、やけに/重たい感情\n[00:06.00]西日を飲んだ/硝子の向こう\n[00:11.00]紙の値札')
        rl = None
        for seed in range(1, 60):
            await jz.set_look(seed=seed)
            rl = await ev("() => { const c = J.ui.plan.cuts.find(c => c.recap); return c ? c.line : null; }")
            if rl is not None: break
        ok(rl is not None, f'a line with a recap cut (seed {seed}, line {rl})')
        if rl is not None:
            ln = rl + 1
            t0 = [(c['text'], c['start'], c['end']) for c in (await jz.get_line(ln))['cuts']]
            old = await ev(f'''() => {{ const S = J.ui, P = S.project, li = {rl}, keep = JSON.stringify(P.overrides[li] || null);
              P.overrides[li] = Object.assign({{}}, P.overrides[li] || {{}}, {{ lock: true, lockedSeed: S.plan.lines[li].seed, lockedCuts: J.lineSnapshot(S.plan, li) }});
              J.uiApi.replan(); const r = J.media.lineCuts(S.plan, li).map(c => +c.start.toFixed(2));
              if (keep === 'null') delete P.overrides[li]; else P.overrides[li] = JSON.parse(keep); J.uiApi.replan(); return r; }}''')
            ok(old != [c[1] for c in t0], f'(the app\'s lock alone moves the cut starts of this line: {[c[1] for c in t0]} → {old})')
            r = await jz.set_line_style(ln, lock=True)
            ok([(c['text'], c['start'], c['end']) for c in r['cuts']] == t0 and r['cutTimes'] == 'locked', f"set_line_style(lock) keeps them {[(c['text'], c['start']) for c in r['cuts']]}")
            await jz.set_look(seed=seed + 100)
            ok([(c['text'], c['start'], c['end']) for c in (await jz.get_line(ln))['cuts']] == t0, '… also when the other lines are laid out again')
            r = await jz.set_line_style(ln, layout='center')
            ok(r['cutTimes'] == 'locked' and all(c['layout'] == 'center' for c in r['cuts'] if c['text'] != r['text'].replace('/', '')), f"a change re-locks with the times of the new look ({r['cutTimes']})")
            # the app's lock button (12_ui.js) turns the lock off: the times the lock kept go with it
            await ev(f"() => {{ const o = J.ui.project.overrides[{rl}]; delete o.lock; delete o.lockedSeed; delete o.lockedCuts; J.uiApi.replan(); }}")
            r = await jz.get_line(ln)
            ok('cutTime' not in r['style'] and r['cutTimes'] == 'auto' and not await ev(f"() => !!(J.ui.project.media.text.lines[{rl}] || {{}}).heldTimes"),
               f"unlocking in the app lets the kept cut times go ({r['style']})")
            await jz.set_line_style(ln, cut_times=[1.0], lock=True)
            r = await jz.set_line_style(ln, lock=False)
            ok(r['style'].get('cutTime', [None])[0] == 1.0 and r['cutTimes'] == 'by hand', f"a cut time set by hand stays after unlocking ({r['style'].get('cutTime')})")
        print('固定のあとの編集（Codex レビュー）')
        await jz.new_project(lyrics='[00:01.00]ああ/いい/うう\n[00:09.00]次の行'); await jz.set_look(seed=123)
        await jz.set_line_style(1, cuts=3, layout='center')
        await jz.lock_motion_palette(1, 8)
        st0 = [c['start'] for c in (await jz.get_line(1))['cuts']]
        # the 「カットの開始時刻」 field (12_ui.js) changes cut 2 of the locked line: the same model change
        await ev("() => { const P = J.ui.project, ov = P.overrides[0]; P.overrides[0] = Object.assign({}, ov, { cutTime: Object.assign({}, ov.cutTime, { 1: 2.5 }) }); J.uiApi.replan(); }")
        await jz.lock_motion_palette(1, 8, lock=False)
        r = await jz.get_line(1)
        ok(r['cuts'][1]['start'] == 3.5 and r['cutTimes'] == 'by hand' and 'lock' not in r['style'],
           f"a cut time changed after the lock stays when the lock goes ({st0} → {[c['start'] for c in r['cuts']]}, {r['cutTimes']})")
        await jz.set_line_style(1, cut_times='auto'); await jz.lock_motion_palette(1, 8)
        st1 = [c['start'] for c in (await jz.get_line(1))['cuts']]
        sheet = json.dumps({'lines': [{'text': 'ああ/いい/うう', 'start': 1.0, 'words': [{'word': 'ああ', 'start': 1.0}, {'word': 'いい', 'start': 4.5}, {'word': 'うう', 'start': 7.0}]}]}, ensure_ascii=False)
        await jz.set_word_times(text=sheet)
        ok([c['start'] for c in (await jz.get_line(1))['cuts']] == st1, 'word times do not move a locked line')
        r = await jz.set_line_style(1, color='#a34f60')
        ok([c['start'] for c in r['cuts']] == st1 and r['style'].get('lock') and r['cutTimes'] == 'locked' and all(c['color'] == '#a34f60' for c in r['cuts']),
           f"a colour on a locked line keeps its cut times and lock ({st1} → {[c['start'] for c in r['cuts']]})")
        lay = [(c['layout'], c['enter']) for c in r['cuts']]
        r = await jz.set_line_style(1, y=-0.2, size=1.3)
        cam = await ev("() => J.media.lineCuts(J.ui.plan, 0).map(c => c.cam)")
        ok([c['start'] for c in r['cuts']] == st1 and [(c['layout'], c['enter']) for c in r['cuts']] == lay and all(c == 'place' for c in cam), 'position / size on a locked line: same cuts, moved')
        r = await jz.set_line_style(1, y='auto', size='auto')
        cam = await ev("() => J.media.lineCuts(J.ui.plan, 0).map(c => c.cam)")
        ok(r['place'] == {'color': '#a34f60'} and 'place' not in cam and r['style'].get('lock'), f'… and back where it was laid out ({cam})')
        r = await jz.set_line_style(1, layout='vcols')
        ok(r['style'].get('lock') and all(c['layout'] == 'vcols' for c in r['cuts'] if c['text'] != 'ああいいうう') and r['cuts'][1]['start'] != st1[1],
           f"a layout change lays the line out again (with its word times) and re-locks it {[c['start'] for c in r['cuts']]}")
        print('Whisper segments with words')
        seg = json.dumps({'segments': [{'start': 2.0, 'end': 5.0, 'text': ' 夜明けの 色を', 'words': [{'word': ' 夜明けの', 'start': 2.0, 'probability': 0.9}, {'word': ' 色を', 'start': 3.4, 'probability': 0.8}]},
                                       {'start': 6.0, 'end': 8.0, 'text': ' 覚えてる', 'words': [{'word': ' 覚えてる', 'start': 6.1}]}]}, ensure_ascii=False)
        r = await jz.set_lyrics(text=seg)
        l1 = await jz.get_line(1)
        ok(r['wordTimed'] == 2 and [w['t'] for w in l1['words']] == [2, 3.4] and l1['confidence'] == 0.8, f"segments keep the words they carry ({r}, {[w['t'] for w in l1['words']]})")
        ok(not jz.errors, f'no page errors {jz.errors[:3]}')
    print('FAILED:', len(fails)) if fails else print('all text style checks passed')
    sys.exit(1 if fails else 0)


asyncio.run(main())
