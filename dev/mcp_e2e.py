"""my-jizura: end-to-end check of the MCP server (tools/jizura_mcp.py) through a real MCP client over stdio.
usage: python3 build.py && python3 dev/mcp_e2e.py [--browser chromium] [--keep DIR]
Makes a working folder with a generated song (WAV), Suno-style timed lyrics and three pictures, starts the server on it, then:
  lists the tools · list_files · new_project → set_lyrics → load_song → add_media · a path outside the folder is refused ·
  set_line_media 'none' · set_look (theme) · set_media_options · preview returns PNG images · export_mp4 twice (the second gets a
  new name, nothing is overwritten; the lengths are reported) · save_project → open_project keeps the lines and the per-line choice ·
  saving under the same name twice: a new name (returned as `saved`), or replace=true for a file this server wrote; never a file
  that was there before · add_timed_media: one picture under the whole song covers the automatic ones, a line's own choice still
  shows, it comes back after save → open · open_project names the pictures that are not loaded · set_output 9:16 ·
  set_line_style: a phrase starts at its own time, a big centred line / a line moved up / a short vertical line come back the same
  (get_line and the same preview image) after save → open, a locked line survives set_look · relink_media in a fresh project ·
  the interlude title can be left out while the title stays · get_motion_plan changes nothing · lock_motion_palette keeps a range
  (cut times included) through set_look, its colours are reported as the project's, lock=false lets it go · set_word_times from
  a timing sheet (lines with words) moves a phrase to its sung time without touching the lyrics · 制作の記録: run.json / calls.jsonl / previews / projects match what
  happened (inputs and outputs with their sha256, time in and between tools, notes, refused calls).
Exit code 0 = all checks passed. Needs: pip install mcp (1.x or 2.x)."""
import asyncio, base64, datetime, inspect, io, json, math, os, struct, sys, tempfile, wave
from PIL import Image, ImageDraw
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BROWSER = sys.argv[sys.argv.index('--browser') + 1] if '--browser' in sys.argv else 'auto'
KEEP = sys.argv[sys.argv.index('--keep') + 1] if '--keep' in sys.argv else None
TOOLS = {'list_files', 'status', 'options', 'new_project', 'open_project', 'save_project', 'set_lyrics', 'load_song', 'add_media', 'remove_media',
         'set_line_media', 'set_look', 'set_media_options', 'media_omakase', 'set_output', 'get_plan', 'preview', 'export_mp4',
         'add_timed_media', 'remove_timed_media', 'get_line', 'set_line_style', 'set_text_options', 'relink_media',
         'log_note', 'run_info', 'start_run', 'get_motion_plan', 'lock_motion_palette', 'set_word_times'}
LINES = ['夜明けの色を覚えてる', 'ほどけた声が遠くで鳴った', 'ねえ、まだ間に合うかな', '名前のない明日へ']


def make_inputs(d):
    os.makedirs(os.path.join(d, 'pics'))
    for i, col in enumerate([(200, 60, 60), (50, 150, 70), (50, 110, 210)]):
        im = Image.new('RGB', (1280, 720), col); ImageDraw.Draw(im).ellipse([540, 260, 740, 460], fill=(255, 255, 255))
        im.save(os.path.join(d, 'pics', f'{i + 1:02d}.png'))
    sr, dur = 22050, 20.0                                   # 20 s, 120 BPM clicks over a soft tone
    with wave.open(os.path.join(d, 'song.wav'), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        fr = bytearray()
        for n in range(int(sr * dur)):
            t = n / sr; b = t % 0.5
            v = 0.15 * math.sin(2 * math.pi * 220 * t) + (0.7 * math.sin(2 * math.pi * 1000 * t) * math.exp(-b * 40) if b < 0.08 else 0)
            fr += struct.pack('<h', int(max(-1, min(1, v)) * 30000))
        w.writeframes(bytes(fr))
    words = []
    for i, line in enumerate(LINES):
        t0 = 2 + i * 4
        for k, ch in enumerate([line[:len(line) // 2], line[len(line) // 2:] + '\n']):
            words.append({'word': ch, 'start_s': t0 + k * 1.2, 'end_s': t0 + k * 1.2 + 1.1})
    json.dump({'aligned_words': words}, open(os.path.join(d, 'suno.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    # a timing sheet: lines that carry their own words (as a forced-alignment tool writes them)
    sheet = {'lines': [{'text': '西日を飲んだ/硝子の向こう', 'start': 17.0, 'end': 21.0, 'words': [
        {'word': '西日を', 'start': 17.0, 'end': 17.5, 'probability': 0.9}, {'word': '飲んだ', 'start': 17.6, 'end': 18.2, 'probability': 0.8},
        {'word': '硝子の', 'start': 18.0, 'end': 18.6, 'probability': 0.85}, {'word': '向こう', 'start': 18.7, 'end': 20.6, 'probability': 0.05}]}]}
    json.dump(sheet, open(os.path.join(d, 'timing_master.json'), 'w', encoding='utf-8'), ensure_ascii=False)


async def main():
    fails = []
    ok = lambda cond, msg: (print(('  ok   ' if cond else '  FAIL ') + msg), None if cond else fails.append(msg))
    tmp = tempfile.TemporaryDirectory(); d = KEEP or tmp.name
    os.makedirs(d, exist_ok=True); make_inputs(d)
    params = StdioServerParameters(command=sys.executable, args=[os.path.join(ROOT, 'tools', 'jizura_mcp.py'), '--workdir', d, '--browser', BROWSER], env=dict(os.environ))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()

            async def call(name, args=None, expect_error=False):
                to = 600 if not str(inspect.signature(s.call_tool).parameters['read_timeout_seconds'].annotation).count('timedelta') else datetime.timedelta(seconds=600)
                res = await s.call_tool(name, args or {}, read_timeout_seconds=to)         # (mcp 1.x takes a timedelta)
                err = getattr(res, 'isError', None)
                if err is None: err = getattr(res, 'is_error', False)
                if err and not expect_error: raise RuntimeError(f'{name}: ' + ' '.join(getattr(c, 'text', '') for c in res.content))
                if expect_error: return err, ' '.join(getattr(c, 'text', '') for c in res.content)
                sc = getattr(res, 'structuredContent', None) or getattr(res, 'structured_content', None)
                if isinstance(sc, dict) and set(sc) == {'result'}: sc = sc['result']
                if sc is not None and not isinstance(sc, list): return sc
                if len(res.content) == 1 and getattr(res.content[0], 'type', '') == 'text':      # a dict sent as JSON text
                    try: return json.loads(res.content[0].text)
                    except ValueError: pass
                return res.content

            names = {t.name for t in (await s.list_tools()).tools}
            ok(TOOLS <= names, f'all tools are listed ({len(names)}; missing {sorted(TOOLS - names)})')
            st = await call('status'); print('  browser:', st['browser'], '· H.264 encode', st['h264Encode'], '· decode', st['h264Decode'])
            f = await call('list_files')
            ok(f['songs'] == ['song.wav'] and f['lyrics'] == ['suno.json', 'timing_master.json'] and f['folders'] == ['pics'], f'list_files: {f}')
            await call('new_project', {'title': 'テスト', 'artist': 'me'})
            r = await call('set_lyrics', {'path': 'suno.json'})
            ok(r['lines'] == 4 and r['timed'] == 4 and r['kind'] == 'words', f'Suno words → 4 timed lines ({r})')
            r = await call('load_song', {'path': 'song.wav'})
            ok(abs(r['duration'] - 20) < 0.1 and r['bpm'] in (119, 120, 121, 60, 240), f'song: {r}')
            r = await call('add_media', {'paths': ['pics']})
            ok(r['added'] == ['01.png', '02.png', '03.png'] and r['total'] == 3, f'add_media: {r}')
            err, msg = await call('add_media', {'paths': ['../']}, expect_error=True)
            ok(err and '外' in msg, f'a path outside the working folder is refused ({msg[:60]})')
            err, msg = await call('set_look', {'theme': 'nope'}, expect_error=True)
            ok(err and 'theme' in msg, 'an unknown theme is refused')
            r = await call('set_line_media', {'line': 2, 'media': 'none'})
            ok(r['line']['media'] is None and r['line']['choice'] == 'none', f'line 2 → no picture ({r})')
            r = await call('set_look', {'theme': 'ballad', 'variation': 2})
            ok(r['theme'] == 'ballad' and r['mood'] in ('calm', 'emotional'), f'look: {r}')
            r = await call('set_media_options', {'dim': 0.5, 'hold': 'still', 'trans': 'wipe', 'treat': 'mono', 'scrim': 'always'})
            ok(r['dim'] == 0.5 and r['hold'] == 'still' and r['trans'] == 'wipe' and r['treat'] == 'mono' and r['scrim'] == 'always', f'media options: {r}')
            err, msg = await call('set_media_options', {'trans': 'nope'}, expect_error=True)
            ok(err and 'trans' in msg, 'an unknown transition is refused')
            r = await call('media_omakase')
            ok(bool(r.get('summary')), f"media_omakase: {r.get('summary')}")
            await call('set_media_options', {'dim': 0.5, 'hold': 'still', 'trans': 'fade', 'treat': 'none', 'scrim': 'off', 'order': 'sequential'})
            p = await call('get_plan')
            ok([l['text'] for l in p['lines']] == LINES and p['lines'][0]['start'] == 2, 'plan: the lines and their times')
            ok([l['media'] for l in p['lines']] == ['01.png', None, '02.png', '03.png'], f"plan: pictures by line {[l['media'] for l in p['lines']]}")
            shots = await call('preview', {'times': [4, 8.5], 'width': 480})
            imgs = [c for c in shots if getattr(c, 'type', '') == 'image']; txt = [c.text for c in shots if getattr(c, 'type', '') == 'text']
            sizes = [Image.open(io.BytesIO(base64.b64decode(c.data))).size for c in imgs]
            ok(len(imgs) == 2 and sizes[0] == (480, 270), f'preview: 2 PNG images {sizes}, captions {txt}')
            ok(len(txt) == 2 and LINES[0] in txt[0], 'preview captions name the line')
            im = Image.open(io.BytesIO(base64.b64decode(imgs[0].data))).convert('RGB').resize((48, 27))
            px = sorted(im.getpixel((x, y)) for x in range(48) for y in range(27))
            med = px[len(px) // 2]
            ok(med[0] > med[1] + 20 and med[0] > med[2] + 20, f'the frame at 4 s shows the red picture (median {med})')
            for k in range(2):
                r = await call('export_mp4', {'path': 'out/clip.mp4', 'start': 1, 'end': 3, 'res': 720})
                ok(r['path'] == os.path.join('out', 'clip.mp4' if k == 0 else 'clip-2.mp4') and r['size'] > 10000 and r['width'] == 1280,
                   f"export {k + 1}: {r['path']} {r['width']}×{r['height']} {r['codec']} audio {r['audio']} {r['size']} bytes")
            ok(all(os.path.getsize(os.path.join(d, 'out', n)) > 10000 for n in ('clip.mp4', 'clip-2.mp4')), 'both files are in the working folder')
            ok(r['frames'] == 48 and abs(r['videoDuration'] - 2) < 1e-6 and r['collision'] == 'renamed' and r['saved'] == r['path'],
               f"export reports frames {r['frames']}, video {r['videoDuration']} s, audio {r['audioDuration']} s, {r['collision']}")
            r = await call('save_project', {'path': 'mv.jizura.json'})
            ok(r['saved'] == 'mv.jizura.json' and r['collision'] == 'new' and os.path.isfile(os.path.join(d, 'mv.jizura.json')), f'saved: {r}')
            await call('new_project', {})
            p2 = await call('open_project', {'path': 'mv.jizura.json'})
            ok([l['text'] for l in p2['lines']] == LINES and p2['lines'][1]['choice'] == 'none' and p2['look']['theme'] == 'ballad',
               'open_project brings back the lines, the per-line choice and the look')
            print('save under the same name again')
            await call('set_look', {'style': 'noir'})                          # change B
            r = await call('save_project', {'path': 'mv.jizura.json'})
            ok(r == {'requested': 'mv.jizura.json', 'saved': 'mv-2.jizura.json', 'collision': 'renamed'}, f'without replace: a new name, and it says so ({r})')
            p3 = await call('open_project', {'path': r['saved']})
            ok(p3['look']['style'] == 'noir', 'opening the returned path gives the latest content')
            await call('set_look', {'style': 'paper'})
            r = await call('save_project', {'path': 'mv.jizura.json', 'replace': True})
            ok(r['saved'] == 'mv.jizura.json' and r['collision'] == 'replaced', f'replace=true writes over a file this server saved ({r})')
            p3 = await call('open_project', {'path': 'mv.jizura.json'})
            ok(p3['look']['style'] == 'paper', 'and opening it right after gives that content')
            open(os.path.join(d, 'mine.jizura.json'), 'w').write('{}')
            err, msg = await call('save_project', {'path': 'mine.jizura.json', 'replace': True}, expect_error=True)
            ok(err and '置き換えません' in msg and open(os.path.join(d, 'mine.jizura.json')).read() == '{}', 'a file that was there before is never replaced')
            print('a picture placed at a time')
            r = await call('add_timed_media', {'media': '03.png', 'start': 0})
            p4 = await call('get_plan')
            ok(r['id'] and len(p4['timed']) == 1 and p4['timed'][0]['start'] == 0, f"add_timed_media: {r['id']} {p4['timed']}")
            ok([l['media'] for l in p4['lines']] == ['03.png', None, '03.png', '03.png'], f"it covers the automatic pictures, line 2 keeps its 「なし」 {[l['media'] for l in p4['lines']]}")
            ok([c['media'] for c in p4['cuts']] == ['03.png', '03.png'] and p4['cuts'][1]['timed'], f"two pieces around line 2 {p4['cuts']}")
            r = await call('save_project', {'path': 'timed.jizura.json'})
            await call('new_project', {})
            p5 = await call('open_project', {'path': r['saved']})
            ok(len(p5['timed']) == 1 and [l['media'] for l in p5['lines']] == ['03.png', None, '03.png', '03.png'] and not p5['missing'],
               'it comes back after save → open')
            r = await call('remove_timed_media', {'id': 'all'})
            ok(r['removed'] == 1 and not r['timed'], 'remove_timed_media')
            err, msg = await call('add_timed_media', {'media': 'nope.png'}, expect_error=True)
            ok(err, 'an unknown picture is refused')
            print('lyric lines set by hand')
            import hashlib
            md5 = lambda c: hashlib.md5(base64.b64decode([x for x in c if getattr(x, 'type', '') == 'image'][0].data)).hexdigest()
            text = '[00:01.00]なんなんですかね\n[00:05.00]この、やけに/重たい感情\n[00:09.00][間奏 8]\n[00:17.00]西日を飲んだ/硝子の向こう\n[00:21.00]紙の値札'
            await call('new_project', {'title': 'あの日の青', 'artist': 'テスト', 'lyrics': text})
            await call('add_media', {'paths': ['pics']})
            r = await call('set_line_style', {'line': 2, 'cut_times': [1.6]})
            ok([(c['text'], c['start']) for c in r['cuts']] == [('この、やけに', 5), ('重たい感情', 6.6)], f"the second phrase starts at its own time {[(c['text'], c['start']) for c in r['cuts']]}")
            r = await call('set_line_style', {'line': 1, 'layout': 'center', 'size': 1.6, 'decor': [], 'bg': 'none'})
            ok(r['cuts'][0]['layout'] == 'center' and r['cuts'][0]['decor'] == [] and r['place'] == {'scale': 1.6}, f"line 1: big and centred, no decorations {r['place']}")
            r = await call('set_line_style', {'line': 4, 'y': -0.3, 'color': '#ffcc33'})
            ok(r['place'] == {'y': -0.3, 'color': '#ffcc33'} and all(c['color'] == '#ffcc33' for c in r['cuts']), f"line 4: moved up, its own colour {r['place']}")
            r = await call('set_line_style', {'line': 5, 'layout': 'vcols', 'single': True})
            ok(len(r['cuts']) == 1 and r['cuts'][0]['layout'] == 'vcols', 'line 5: one short vertical cut')
            err, msg = await call('set_line_style', {'line': 1, 'layout': 'nope'}, expect_error=True)
            ok(err and 'layout' in msg, 'an unknown layout is refused')
            before = {t: md5(await call('preview', {'times': [t], 'width': 320})) for t in (3.0, 7.0, 19.0, 22.0)}
            lines_before = [await call('get_line', {'line': n}) for n in (1, 2, 4, 5)]
            r = await call('save_project', {'path': 'styled.jizura.json'})
            await call('new_project', {})
            await call('open_project', {'path': r['saved']})
            lines_after = [await call('get_line', {'line': n}) for n in (1, 2, 4, 5)]
            after = {t: md5(await call('preview', {'times': [t], 'width': 320})) for t in (3.0, 7.0, 19.0, 22.0)}
            ok(lines_after == lines_before, 'save → open gives the same lines, cuts and settings')
            ok(after == before, f'… and the same frames ({sum(after[t] == before[t] for t in after)}/4 identical)')
            p6 = await call('get_plan')
            ok([l['text'] for l in p6['lines']] == ['なんなんですかね', 'この、やけに/重たい感情', '', '西日を飲んだ/硝子の向こう', '紙の値札']
               or [l['text'].replace('/', '') for l in p6['lines']] == ['なんなんですかね', 'この、やけに重たい感情', '', '西日を飲んだ硝子の向こう', '紙の値札'],
               f"the lyric text itself is unchanged {[l['text'] for l in p6['lines']]}")
            r = await call('set_line_style', {'line': 4, 'lock': True})
            locked = [(c['layout'], c['enter']) for c in r['cuts']]
            await call('set_look', {'variation': 7})
            r = await call('get_line', {'line': 4})
            ok([(c['layout'], c['enter']) for c in r['cuts']] == locked and r['place'] == {'y': -0.3, 'color': '#ffcc33'}, f'a locked line keeps its look when set_look runs {locked}')
            r = await call('set_line_style', {'line': 1, 'decor': 'auto', 'size': 'auto', 'cuts': 'auto', 'cut_times': 'auto'})
            ok(r['place'] == {} and 'decor' not in r['style'], f"'auto' passes the MCP schema and clears decor / size ({r['place']}, {r['style']})")
            print('motion plan / lock / word times')
            KEEPK = ['line', 'cut', 'start', 'end', 'text', 'layout', 'enter', 'exit', 'hold', 'treat', 'cam', 'inDur', 'outDur']
            pick = lambda m: [{k: c[k] for k in KEEPK} for c in m['cuts'] if not c['interlude']]
            plan0 = await call('get_plan')
            m0 = await call('get_motion_plan', {'start': 0, 'end': 30})
            ok(await call('get_plan') == plan0 and m0['cutCount'] == len(m0['cuts']) > 4 and m0['inventory']['layout'] and min(c['line'] for c in m0['cuts']) == 1,
               f"get_motion_plan reads the cuts (lines from 1) and changes nothing ({m0['cutCount']} cuts)")
            err, msg = await call('get_motion_plan', {'start': 5, 'end': 2}, expect_error=True)
            ok(err, 'a backwards range is refused')
            await call('set_line_style', {'line': 4, 'lock': False})        # (locked above: a locked line keeps its cut times)
            r = await call('set_word_times', {'path': 'timing_master.json'})
            l4 = await call('get_line', {'line': 4})
            ok(r['wordTimed'] == 1 and dict((c['text'], c['start']) for c in l4['cuts']).get('硝子の向こう') == 18.0 and l4['cutTimes'] == 'words'
               and [w['used'] for w in l4['words']] == [True, True, True, False] and r['weak'][0]['unused'] == 1,
               f"set_word_times: the phrase starts when it is sung, a word below 0.1 is not used {[(c['text'], c['start']) for c in l4['cuts']]}")
            ok([l['text'] for l in (await call('get_plan'))['lines']] == [l['text'] for l in plan0['lines']], '… and the lyrics are not touched')
            m1 = await call('get_motion_plan', {'start': 0, 'end': 30})
            r = await call('lock_motion_palette', {'start': 0, 'end': 30, 'text_color': '#223344', 'chroma': 0.2})
            ok(r['lines'] == [1, 2, 4, 5] and r['scheme'] == 0 and set(r['global']) == {'fg', 'chroma'} and r['colors']['fg'] == '#223344',
               f"lock_motion_palette locks the lines of the range; colours / chroma are reported as the project's {r}")
            await call('set_look', {'variation': 3})
            m2 = await call('get_motion_plan', {'start': 0, 'end': 30})
            ok(pick(m2) == pick(m1) and all(c['locked'] for c in m2['cuts'] if not c['interlude']), 'the locked range keeps its cuts, motion and cut times through set_look'
               + ''.join(f"\n        {a} → {b}" for a, b in zip(pick(m1), pick(m2)) if a != b))
            l4 = await call('get_line', {'line': 4})
            ok(l4['cutTimes'] == 'by hand' or l4['cutTimes'] == 'locked', f"a locked line reports its cut times as kept ({l4['cutTimes']})")
            await call('lock_motion_palette', {'start': 0, 'end': 30, 'lock': False})
            l4 = await call('get_line', {'line': 4})
            ok('lock' not in l4['style'] and l4['cutTimes'] == 'words', f"lock=false lets the range go (word times again: {l4['cutTimes']})")
            print('interlude title')
            ok(p6['title'] == 'あの日の青', 'the title is in the project')
            t_on = md5(await call('preview', {'times': [13.0], 'width': 320}))
            r = await call('set_text_options', {'interlude_title': False})
            t_off = md5(await call('preview', {'times': [13.0], 'width': 320}))
            p7 = await call('get_plan')
            ok(r == {'interludeTitle': False} and t_on != t_off and p7['title'] == 'あの日の青' and len(p7['lines']) == 5,
               'the interlude can leave the title out; the title and every line stay')
            print('relink')
            r = await call('save_project', {'path': 'relink.jizura.json'})
            async with stdio_client(params) as (r2, w2):                     # a fresh server: nothing loaded yet
                async with ClientSession(r2, w2) as s2:
                    await s2.initialize()
                    async def call2(name, args=None):
                        to2 = 600 if not str(inspect.signature(s2.call_tool).parameters['read_timeout_seconds'].annotation).count('timedelta') else datetime.timedelta(seconds=600)
                        res = await s2.call_tool(name, args or {}, read_timeout_seconds=to2)
                        sc = getattr(res, 'structuredContent', None) or getattr(res, 'structured_content', None)
                        return sc if isinstance(sc, dict) else json.loads(res.content[0].text)
                    p8 = await call2('open_project', {'path': r['saved']})
                    ok(sorted(p8['missing']) == ['01.png', '02.png', '03.png'], f"a fresh session names the missing pictures {p8['missing']}")
                    os.rename(os.path.join(d, 'pics', '02.png'), os.path.join(d, 'pics', 'renamed.png'))
                    r9 = await call2('relink_media', {'paths': ['pics']})
                    ok(sorted(r9['relinked']) == ['01.png', '02.png', '03.png'] and not r9['missing'] and 'renamed.png' in r9['files'],
                       f"relink_media finds them by content, a renamed file too {r9}")
            r = await call('set_output', {'aspect': '9:16'})
            ok(r['aspect'] == '9:16' and r['size'] == [1080, 1920], f'set_output: {r}')
            print('制作の記録')
            n = await call('log_note', {'text': '12 秒で文字が上で切れた', 'kind': 'issue', 'time': 12, 'line': 3})
            ok(n['kind'] == 'issue' and n['time'] == 12, f'log_note ({n})')
            info = await call('run_info')
            rd = os.path.join(d, info['dir'])
            run = json.load(open(os.path.join(rd, 'run.json'), encoding='utf-8'))
            calls = [json.loads(l) for l in open(os.path.join(rd, 'calls.jsonl'), encoding='utf-8')]
            ok(info['dir'].startswith('jizura_runs' + os.sep) and len(calls) == run['timing']['calls'] >= 40, f"the record is in the working folder ({info['dir']}, {len(calls)} calls)")
            ok(run['env']['app']['version'] and run['env']['app']['pageSha256'] and run['env']['browser']['browser'], f"environment: app {run['env']['app']['version']} {str(run['env']['app']['git'].get('commit'))[:8]}, {run['env']['browser']['browser']}")
            t = run['timing']; ok(t['toolMs'] > 0 and t['betweenToolsMs'] > 0 and t['wallMs'] >= t['toolMs'] and set(t['byPhase']) >= {'setup', 'edit', 'check', 'output'},
                                  f"time: {t['toolMs']} ms in tools, {t['betweenToolsMs']} ms between, phases {sorted(t['byPhase'])}")
            import hashlib as _h
            sha = lambda f: _h.sha256(open(f, 'rb').read()).hexdigest()
            ins = {i['path']: i['sha256'] for i in run['inputs']}
            ok(ins.get('suno.json') == sha(os.path.join(d, 'suno.json')) and ins.get('song.wav') == sha(os.path.join(d, 'song.wav')) and os.path.join('pics', '01.png') in ins,
               f"inputs with their content hash ({len(ins)})")
            outs = run['outputs']
            mp4 = [o for o in outs if o['tool'] == 'export_mp4']
            ok(len(mp4) == 2 and all(o['sha256'] == sha(os.path.join(d, o['path'])) for o in mp4) and mp4[0]['facts']['frames'] == 48 and mp4[1]['collision'] == 'renamed',
               f"exports with hash, frames and how the name was chosen ({[o['path'] for o in mp4]})")
            ok(any(o['tool'] == 'save_project' and o['collision'] == 'replaced' for o in outs), 'saves are listed (also the replaced one)')
            pv = [c for c in calls if c['tool'] == 'preview']
            files = [f for c in pv for f in c.get('previews', [])]
            ok(pv and files and all(os.path.isfile(os.path.join(d, f)) for f in files) and len(files) == sum(len([x for x in c['result'] if isinstance(x, str)]) for c in pv),
               f'every preview image is kept ({len(files)})')
            ok(all(c.get('project') for c in pv) and all(os.path.isfile(os.path.join(d, P['file'])) for P in run['projects'] if P['file']) and any(P['file'] for P in run['projects']),
               f"previews and exports name the project state they came from ({len(run['projects'])} states)")
            ok(any(e['tool'] == 'set_line_style' for e in run['errors']) and run['notes'][-1]['text'] == '12 秒で文字が上で切れた', 'refused calls and notes are in it')
            ph = {c['tool']: c['phase'] for c in calls}
            ok(ph.get('get_motion_plan') == 'check' and ph.get('lock_motion_palette') == 'edit' and ph.get('set_word_times') == 'edit' and 'timing_master.json' in ins,
               f"the new tools are recorded in their phase {[(k, ph.get(k)) for k in ('get_motion_plan', 'lock_motion_palette', 'set_word_times')]}")
            r = await call('start_run', {'title': '次の曲'})
            ok(r['dir'] != info['dir'] and '次の曲' in r['dir'] and os.path.isfile(os.path.join(d, r['dir'], 'run.json')), f"start_run opens a new record ({r['dir']})")
            st = await call('status')
            ok(not st['pageErrors'], f"no page errors {st['pageErrors']}")
    tmp.cleanup()
    print('FAILED:', len(fails)) if fails else print('all MCP checks passed')
    sys.exit(1 if fails else 0)


asyncio.run(main())
