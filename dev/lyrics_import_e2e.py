"""my-jizura: end-to-end check of the lyric timing import (Phase 1.5) on the BUILT app (index.html).
usage: python3 build.py && python3 dev/lyrics_import_e2e.py
Serves the repository root on :8768 and loads SRT / VTT / Whisper JSON / Suno JSON / word-level JSON / enhanced LRC
through 「LRC を読み込む」, then checks the lyric lines and their start times. Exit code 0 = all checks passed."""
import asyncio, functools, http.server, json, os, sys, tempfile, threading
from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES = [
    ('song.srt', "1\n00:00:02,000 --> 00:00:04,000\n夜明けの色を\n\n2\n00:00:04,000 --> 00:00:05,000\n[Chorus]\n\n3\n00:00:06,500 --> 00:00:09,000\n<i>覚えてる</i>\n",
     [('夜明けの色を', 2.0), ('覚えてる', 6.5)]),
    ('song.vtt', "WEBVTT\n\n00:01.500 --> 00:03.000 align:start\nHello <c.yellow>world</c>\n\n00:04.250 --> 00:06.000\nsee you\n",
     [('Hello world', 1.5), ('see you', 4.25)]),
    ('whisper.json', json.dumps({'text': '…', 'segments': [{'start': 1.2, 'end': 3, 'text': ' ほどけた声が'}, {'start': 3.6, 'end': 6, 'text': ' 遠くで鳴った'}]}, ensure_ascii=False),
     [('ほどけた声が', 1.2), ('遠くで鳴った', 3.6)]),
    ('suno.json', json.dumps({'aligned_words': [{'word': '[Verse]\nWalking ', 'start_s': 1.0, 'end_s': 1.4}, {'word': 'down\n', 'start_s': 1.5, 'end_s': 1.9},
                                                {'word': '[Instrumental Break]\n', 'start_s': 3.0, 'end_s': 3.0}, {'word': 'la ', 'start_s': 9.0, 'end_s': 9.2}, {'word': 'la', 'start_s': 9.3, 'end_s': 9.6}]}),
     [('Walking down', 1.0), ('', 3.0), ('la la', 9.0)]),
    ('words.json', json.dumps({'segments': [{'start': 0, 'end': 9, 'text': '', 'words': [{'word': '夜', 'start': 0.5, 'end': 0.6}, {'word': '明け', 'start': 0.6, 'end': 0.9}, {'word': '色', 'start': 2.4, 'end': 2.6}]}]}, ensure_ascii=False),
     [('夜明け', 0.5), ('色', 2.4)]),
    ('enhanced.lrc', "[ti:Test]\n[00:01.00]<00:01.00>夜<00:01.30>明け\n[Verse 2]\n[00:05.00]\n[00:06.00][間奏 3]\n[00:09.00]終わり\n",
     [('夜明け', 1.0), ('', 6.0), ('終わり', 9.0)]),
]

def serve():
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT); h.log_message = lambda *a: None
    s = http.server.ThreadingHTTPServer(('127.0.0.1', 8768), h); threading.Thread(target=s.serve_forever, daemon=True).start(); return s

async def main():
    srv = serve(); fails = []
    def ok(cond, msg): print(('  ok   ' if cond else '  FAIL ') + msg); cond or fails.append(msg)
    with tempfile.TemporaryDirectory() as d:
        async with async_playwright() as p:
            b = await p.chromium.launch(); ctx = await b.new_context()
            await ctx.add_init_script("try { localStorage.setItem('jizura.tourDone', '1'); } catch (e) {}")
            pg = await ctx.new_page(); errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
            pg.on('dialog', lambda dl: asyncio.ensure_future(dl.accept()))
            await pg.goto('http://127.0.0.1:8768/index.html'); await pg.wait_for_function('window.J && J.ui && J.ui.plan && J.lyricsImport')
            acc = await pg.get_attribute('#fileLrc', 'accept'); ok('.srt' in acc and '.json' in acc, f'the import accepts SRT / VTT / JSON ({acc})')
            for name, text, want in CASES:
                path = os.path.join(d, name); open(path, 'w', encoding='utf-8').write(text)
                await pg.evaluate("() => { J.ui.project.lyrics = 'old'; }")
                await pg.set_input_files('#fileLrc', path)
                await pg.wait_for_function("() => J.ui.project.lyrics !== 'old'", timeout=10000)
                got = await pg.evaluate("() => J.ui.plan.lines.map(l => [l.interlude ? '' : l.text, +l.start.toFixed(2), l.lrc])")
                pairs = [(g[0], g[1]) for g in got]
                ok(pairs == [(t, s) for t, s in want], f'{name}: {pairs}')
            ok(not errs, f'no page errors {errs[:3]}')
            await b.close()
    srv.shutdown()
    print('FAILED: %d' % len(fails) if fails else 'all lyric import checks passed')
    sys.exit(1 if fails else 0)

asyncio.run(main())
