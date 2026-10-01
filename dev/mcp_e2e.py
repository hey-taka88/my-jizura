"""my-jizura: end-to-end check of the MCP server (tools/jizura_mcp.py) through a real MCP client over stdio.
usage: python3 build.py && python3 dev/mcp_e2e.py [--browser chromium] [--keep DIR]
Makes a working folder with a generated song (WAV), Suno-style timed lyrics and three pictures, starts the server on it, then:
  lists the tools · list_files · new_project → set_lyrics → load_song → add_media · a path outside the folder is refused ·
  set_line_media 'none' · set_look (theme) · set_media_options · preview returns PNG images · export_mp4 twice (the second gets a
  new name, nothing is overwritten) · save_project → open_project keeps the lines and the per-line choice · set_output 9:16.
Exit code 0 = all checks passed. Needs: pip install mcp (1.x or 2.x)."""
import asyncio, base64, datetime, inspect, io, json, math, os, struct, sys, tempfile, wave
from PIL import Image, ImageDraw
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BROWSER = sys.argv[sys.argv.index('--browser') + 1] if '--browser' in sys.argv else 'auto'
KEEP = sys.argv[sys.argv.index('--keep') + 1] if '--keep' in sys.argv else None
TOOLS = {'list_files', 'status', 'options', 'new_project', 'open_project', 'save_project', 'set_lyrics', 'load_song', 'add_media', 'remove_media',
         'set_line_media', 'set_look', 'set_media_options', 'set_output', 'get_plan', 'preview', 'export_mp4'}
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
            ok(f['songs'] == ['song.wav'] and f['lyrics'] == ['suno.json'] and f['folders'] == ['pics'], f'list_files: {f}')
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
            r = await call('set_media_options', {'dim': 0.5, 'hold': 'still'})
            ok(r['dim'] == 0.5 and r['hold'] == 'still', f'media options: {r}')
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
            r = await call('save_project', {'path': 'mv.jizura.json'})
            ok(r['saved'] == 'mv.jizura.json' and os.path.isfile(os.path.join(d, 'mv.jizura.json')), f'saved: {r}')
            await call('new_project', {})
            p2 = await call('open_project', {'path': 'mv.jizura.json'})
            ok([l['text'] for l in p2['lines']] == LINES and p2['lines'][1]['choice'] == 'none' and p2['look']['theme'] == 'ballad',
               'open_project brings back the lines, the per-line choice and the look')
            r = await call('set_output', {'aspect': '9:16'})
            ok(r['aspect'] == '9:16' and r['size'] == [1080, 1920], f'set_output: {r}')
            st = await call('status')
            ok(not st['pageErrors'], f"no page errors {st['pageErrors']}")
    tmp.cleanup()
    print('FAILED:', len(fails)) if fails else print('all MCP checks passed')
    sys.exit(1 if fails else 0)


asyncio.run(main())
