"""my-jizura: end-to-end check of おまかせ × pictures (Phase 4-4) on the BUILT app (index.html).
usage: python3 build.py && python3 dev/calm_e2e.py [--browser chromium]
Serves the repository root on :8772. With 「画像の上では歌詞を控えめに」 (project.media.calm) on, the lyrics' random layouts rarely
fill the screen over a background picture. Checks:
  without pictures nothing changes (calm on = off) · calm off (a project saved before the setting) plans exactly as without the
  setting · over pictures the screen-filling (busy) layouts become rare · a line set to 「なし」 is not made calmer, green-screen
  output keeps its layouts · a layout chosen by hand stays · new projects have it on, an old file has it off, save → open keeps it · the panel switch.
Exit code 0 = all checks passed."""
import asyncio, functools, http.server, json, os, sys
from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BROWSER = sys.argv[sys.argv.index('--browser') + 1] if '--browser' in sys.argv else 'chromium'
PORT = 8772

# plans of one project (40 lines, seeds 1–4) under variations of the media part; returns per seed the layouts of every cut
PLANS = r"""(o) => {
  const base = JSON.parse(JSON.stringify(J.ui.project));
  base.lyrics = Array.from({ length: 40 }, (_, i) => { const t = 2 + i * 4; return `[${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}.00]行${i} あいうえお かきくけこ`; }).join('\n');
  base.media = J.media.normalize(Object.assign(J.media.defaults(), o.media || {}));
  if (o.keyBg) base.keyBg = o.keyBg;
  if (o.overrides) base.overrides = o.overrides;
  const real = J.media.calmStyle;
  if (o.noHook) J.media.calmStyle = st => st;                     // the planner as before this change
  try {
    const out = [];
    for (let seed = 1; seed <= 4; seed++) {
      const p = J.plan(Object.assign({}, base, { seed }), null);
      out.push(p.cuts.map(c => [c.line, c.layout]));
    }
    return out;
  } finally { J.media.calmStyle = real; }
}"""
BUSY = "() => J.LAYOUT_ORDER.filter(k => J.LAYOUTS[k].busy)"
PICS = {'assets': [{'id': 'aaaaaaaaaaaa', 'type': 'image', 'name': 'a.png', 'w': 640, 'h': 360},
                   {'id': 'bbbbbbbbbbbb', 'type': 'image', 'name': 'b.png', 'w': 640, 'h': 360}]}


def serve():
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT); h.log_message = lambda *a: None
    s = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), h); threading_start(s); return s


def threading_start(s):
    import threading
    threading.Thread(target=s.serve_forever, daemon=True).start()


async def main():
    srv = serve(); fails, errors = [], []
    def ok(cond, msg): print(('  ok   ' if cond else '  FAIL ') + msg); cond or fails.append(msg)
    async with async_playwright() as p:
        b = await getattr(p, BROWSER).launch()
        ctx = await b.new_context(viewport={'width': 1400, 'height': 900}, accept_downloads=True)
        await ctx.add_init_script("try { localStorage.setItem('jizura.tourDone', '1'); } catch (e) {}")
        pg = await ctx.new_page()
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.on('dialog', lambda dl: asyncio.ensure_future(dl.accept()))
        await pg.goto(f'http://127.0.0.1:{PORT}/index.html')
        await pg.wait_for_function('window.J && J.ui && J.ui.plan && J.mediaUI && typeof J.media.calmStyle === "function"')
        busy = set(await pg.evaluate(BUSY))
        plans = lambda **o: pg.evaluate(PLANS, o)
        share = lambda ps: sum(1 for p in ps for _, l in p if l in busy) / max(1, sum(len(p) for p in ps))

        print('without pictures')
        ok(await plans(media={'calm': True}) == await plans(media={'calm': False}) == await plans(media={'calm': True}, noHook=True),
           'calm on, calm off and the planner without the hook give the same plans')
        print('pictures, calm off (a project saved before the setting)')
        before = await plans(media=dict(PICS, calm=False), noHook=True)
        ok(await plans(media=dict(PICS, calm=False)) == before, 'the plans are exactly as without this change')
        print('pictures, calm on')
        calm = await plans(media=dict(PICS, calm=True))
        ok(share(before) > 0.05 and share(calm) < share(before) / 3,
           f'screen-filling layouts become rare over pictures ({share(before):.1%} → {share(calm):.1%}, {len(busy)} busy layouts)')
        ok([len(p) for p in calm] == [len(p) for p in before], 'the number of cuts does not change')
        print('a line without a picture')
        # its own layouts may still differ (the layout picker avoids repeating recent layouts, and earlier lines did change);
        # what matters is that this line is not made calmer: nothing is under it
        under = await pg.evaluate("""(pics) => { const P = JSON.parse(JSON.stringify(J.ui.project));
          P.media = J.media.normalize(Object.assign(J.media.defaults(), pics, { calm: true, tracks: { back: { cuts: [{ id: 'n5', assetId: '', lineRef: { line: 5 } }] } } }));
          const st = { bias: { layout: {} } };
          return [4, 5].map(li => [J.media.backUnder(P, li, 20, 24), J.media.calmStyle(st, P, li, 20, 24) === st]); }""", PICS)
        ok(under == [[True, False], [False, True]], f'line 6 (「なし」) has nothing under it and is not made calmer; line 5 is ({under})')
        print('the same rule as what is shown (resolveTrack)')
        # for every lyric cut: is a picture under it? asked of M.backUnder, and read from the resolved plan
        AGREE = r"""(cfg) => {
          const P = JSON.parse(JSON.stringify(J.ui.project));
          P.lyrics = Array.from({ length: 12 }, (_, i) => { const t = 2 + i * 4; return `[00:${String(t).padStart(2, '0')}.00]行${i} あいうえお`; }).join('\n');
          P.media = J.media.normalize(Object.assign(J.media.defaults(), cfg));
          const plan = J.plan(P, null), bad = [];
          let n = 0;
          for (const c of plan.cuts) {
            if (c.line < 0 || !c.text) continue;
            n++;
            const shown = plan.media.back.cuts.some(m => m.assetId && m.start < c.end - 0.02 && m.end > c.start + 0.02);
            const said = J.media.backUnder(P, c.line, c.start, c.end);
            if (shown !== said) bad.push([c.line, +c.start.toFixed(2), +c.end.toFixed(2), shown, said]);
          }
          return { n, bad };
        }"""
        A, B = 'aaaaaaaaaaaa', 'bbbbbbbbbbbb'
        cfgs = {
            'a timed 「なし」 over the automatic pictures': dict(PICS, tracks={'back': {'cuts': [{'id': 't1', 'assetId': '', 'start': 9, 'end': 22}]}}),
            'a timed picture without an end, then a timed 「なし」': dict(PICS, autoFill={'back': {'mode': 'off'}}, tracks={'back': {'cuts': [
                {'id': 't1', 'assetId': A, 'start': 6, 'end': None}, {'id': 't2', 'assetId': '', 'start': 26, 'end': None}]}}),
            'timed pictures only (no automatic ones)': dict(PICS, autoFill={'back': {'mode': 'off'}}, tracks={'back': {'cuts': [{'id': 't1', 'assetId': B, 'start': 14, 'end': 30}]}}),
            'a line set to 「なし」 inside a timed picture': dict(PICS, tracks={'back': {'cuts': [{'id': 't1', 'assetId': A, 'start': 0, 'end': None},
                {'id': 'l3', 'assetId': '', 'lineRef': {'line': 3}}]}}),
            'every picture is placed over the lyrics': dict(PICS, tracks={'front': {'cuts': [{'id': 'f1', 'assetId': A, 'start': 0, 'end': None, 'rect': {'x': 0, 'y': 0, 'w': 0.3, 'rot': 0}},
                {'id': 'f2', 'assetId': B, 'start': 0, 'end': None, 'rect': {'x': 0.3, 'y': 0, 'w': 0.3, 'rot': 0}}]}}),
        }
        for name, cfg in cfgs.items():
            r = await pg.evaluate(AGREE, cfg)
            ok(r['n'] > 10 and not r['bad'], f"{name}: the rule agrees with what is shown for all {r['n']} cuts {r['bad'][:3]}")
        print('green screen output')
        ok(await plans(media=dict(PICS, calm=True), keyBg='green') == await plans(media=dict(PICS, calm=True), keyBg='green', noHook=True),
           'no pictures are drawn there, so nothing changes')
        print('a layout chosen by hand')
        hand = sorted(busy)[0]
        h = await plans(media=dict(PICS, calm=True), overrides={'3': {'layout': hand}})
        ok(all(l == hand for p in h for x, l in p if x == 3), f'line 4 keeps {hand}')
        print('saving and the panel')
        st = await pg.evaluate("""() => { const fresh = J.ui.project.media.calm; const old = J.media.normalize({ assets: [] }).calm;
          const sw = document.getElementById('mediaCalm'); return { fresh, old, sw: !!sw, checked: sw && sw.checked }; }""")
        ok(st['fresh'] is True and st['old'] is False and st['sw'] and st['checked'], f'new project: on; an old file: off; the switch shows it {st}')
        await pg.evaluate("() => { const sw = document.getElementById('mediaCalm'); sw.click(); }")
        ok(await pg.evaluate('() => J.ui.project.media.calm') is False, 'the switch turns it off')
        await pg.evaluate("() => J.uiApi.flushSave()")
        await pg.reload(); await pg.wait_for_function('window.J && J.ui && J.ui.plan && J.mediaUI')
        ok(await pg.evaluate("() => J.ui.project.media.calm === false && !document.getElementById('mediaCalm').checked"), 'it stays off after a reload')
        ok(not errors, f'no page errors {errors[:3]}')
        await b.close()
    srv.shutdown()
    print(f'FAILED: {len(fails)}' if fails else 'all calm checks passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
