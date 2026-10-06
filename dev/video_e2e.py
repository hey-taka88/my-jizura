"""my-jizura: end-to-end check of video clips (Phase 2) on the BUILT app (index.html).
usage: python3 build.py && python3 dev/video_e2e.py
Serves the repository root on :8769. In the page it encodes four 4-second clips (VP9 in MP4, 30 fps) whose every frame
carries its own clip time in its colour (red = whole second, green = frame in the second, blue = which clip), adds
them with 「追加」, puts a 10-second line over a clip and checks:
  preview frame = the clip time the song time maps to · exported MP4 frames for loop / ping-pong / hold / restart
  every bar (incl. the cross-fade at the loop seam) · at most 3 clips hold a decoder while scrubbing ·
  a clip placed at a time of the song runs straight through lyric lines (also around a line with its own clip, and when exported) ·
  clips come back after a reload · PNG export runs with clips · a video file is accepted as the song.
Exit code 0 = all checks passed."""
import asyncio, base64, functools, http.server, os, sys, tempfile, threading
from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FPS, SECS = 30, 4
BLUES = [40, 100, 160, 220]

MAKE = r"""async ([blue, fps, secs]) => {
  const W = 320, H = 180, chunks = [];
  const muxer = new Mp4Muxer.Muxer({ target: new Mp4Muxer.ArrayBufferTarget(), video: { codec: 'vp9', width: W, height: H, frameRate: fps }, fastStart: 'in-memory' });
  const enc = new VideoEncoder({ output: (c, m) => muxer.addVideoChunk(c, m), error: e => { throw e; } });
  enc.configure({ codec: 'vp09.00.10.08', width: W, height: H, bitrate: 2e6, framerate: fps });
  const cv = new OffscreenCanvas(W, H), x = cv.getContext('2d');
  for (let i = 0; i < fps * secs; i++) {
    x.fillStyle = `rgb(${30 + 50 * Math.floor(i / fps)},${(i % fps) * 8},${blue})`; x.fillRect(0, 0, W, H);
    const f = new VideoFrame(cv, { timestamp: Math.round(i * 1e6 / fps), duration: Math.round(1e6 / fps) });
    enc.encode(f, { keyFrame: i % fps === 0 }); f.close();
  }
  await enc.flush(); muxer.finalize();
  const u8 = new Uint8Array(muxer.target.buffer); let s = ''; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(s);
}"""
# clip time read back from a colour (median of a frame)
def clip_time(rgb):
    r, g = rgb[0], rgb[1]
    return round((r - 30) / 50) + round(g / 8) / FPS

MEDIAN = r"""async ([src, t]) => {   // src: 'render' (the app's renderer at song time t) or a blob URL + seconds (an exported video)
  const c = document.createElement('canvas'); c.width = 96; c.height = 54; const x = c.getContext('2d');
  if (src === 'render') new J.Renderer().frame(x, J.ui.plan, t, { scale: 96 / J.ui.plan.W });
  else { const v = window.__ev || (window.__ev = document.createElement('video')); if (v.src !== src) { v.muted = true; v.src = src; await new Promise(r => { v.onloadeddata = r; }); }
         // Wait for the requested export frame to be presented (within one output frame), not just a seek event.
         const frame = new Promise((resolve, reject) => {
           let cb = 0;
           const timer = setTimeout(() => { v.cancelVideoFrameCallback(cb); reject(new Error('frame not presented: ' + JSON.stringify(window.__lastVideoRead))); }, 10000);
           const ready = (now, meta) => {
             window.__lastVideoRead = { requested: t, mediaTime: meta.mediaTime, currentTime: v.currentTime, readyState: v.readyState };
             if (Math.abs(meta.mediaTime - t) > 1 / J.ui.plan.fps + .005) { cb = v.requestVideoFrameCallback(ready); return; }
             clearTimeout(timer); resolve();
           };
           cb = v.requestVideoFrameCallback(ready);
         });
         const sought = new Promise(r => { v.onseeked = r; }); v.currentTime = t;
         await Promise.all([sought, frame]); x.drawImage(v, 0, 0, 96, 54); }
  const d = x.getImageData(0, 0, 96, 54).data, ch = [[], [], []];
  for (let i = 0; i < d.length; i += 4) for (let k = 0; k < 3; k++) ch[k].push(d[i + k]);
  return ch.map(a => { a.sort((p, q) => p - q); return a[a.length >> 1]; });
}"""

def serve():
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT); h.log_message = lambda *a: None
    s = http.server.ThreadingHTTPServer(('127.0.0.1', 8769), h); threading.Thread(target=s.serve_forever, daemon=True).start(); return s

async def main():
    srv = serve(); fails = []
    def ok(cond, msg): print(('  ok   ' if cond else '  FAIL ') + msg); cond or fails.append(msg)
    with tempfile.TemporaryDirectory() as d:
        async with async_playwright() as p:
            b = await p.chromium.launch(); ctx = await b.new_context(viewport={'width': 1500, 'height': 950})
            await ctx.add_init_script("try { localStorage.setItem('jizura.tourDone', '1'); } catch (e) {}")
            pg = await ctx.new_page(); errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
            pg.on('dialog', lambda dl: asyncio.ensure_future(dl.accept()))
            await pg.goto('http://127.0.0.1:8769/index.html'); await pg.wait_for_function('window.J && J.ui && J.ui.plan && J.mediaUI')
            print('make clips')
            paths = []
            for k, blue in enumerate(BLUES):
                data = await pg.evaluate(MAKE, [blue, FPS, SECS])
                pth = os.path.join(d, f'clip{k + 1}.mp4'); open(pth, 'wb').write(base64.b64decode(data)); paths.append(pth)
            # lyrics: three 10-second lines, no snapping; 120 BPM → a bar of 4 beats = 2 s
            await pg.evaluate("""() => { const P = J.ui.project; P.lyrics = '[00:00.00]いち\\n[00:10.00]に\\n[00:20.00]さん\\n[00:30.00]よん\\n[00:40.00]ご'; P.timing.snap = false; P.timing.bpm = 120; P.title = '';
              P.media.tracks.back.dim = 0; P.media.scrim = { mode: 'off', amount: 0 };   // the clip colours are read back: no veil, no plate
              document.getElementById('lyrics').value = P.lyrics; J.uiApi.replan(); }""")
            print('add clips')
            await pg.set_input_files('#mediaFiles', paths)
            await pg.wait_for_function('J.ui.project.media.assets.length === 4', timeout=60000)
            info = await pg.evaluate("() => ({ a: J.ui.project.media.assets.map(a => [a.type, a.w, a.h, a.duration]), cuts: J.ui.plan.media.back.cuts.map(c => [c.type, c.start, c.end, c.hold, c.v && c.v.extend]), ui: !document.getElementById('mediaVideo').hidden, acc: document.getElementById('audioFile').accept })")
            ok(all(a[0] == 'video' and a[1] == 320 and abs(a[3] - SECS) < 0.1 for a in info['a']), f"4 clips added as video, 320×180, {SECS} s: {info['a'][0]}")
            ok(len(info['cuts']) == 5 and info['cuts'][0][3] == 'still' and info['cuts'][0][4] == 'loop', f"one clip per line, no slow zoom on clips, loop by default: {info['cuts'][:2]}")
            ok(info['ui'], 'the clip settings appear in the panel')
            ok('video' in info['acc'], 'a video file is accepted as the song')
            print('preview (paused, scrubbing)')
            for t in [1.5, 5.25, 8.9]:
                await pg.evaluate(f"() => J.uiApi.seek({t})")
                await pg.wait_for_function(f"() => {{ const c = J.media.cutAt(J.ui.plan, {t}, 'back'), a = J.mediaAssets.get(c.assetId), vt = J.media.videoTimes(J.ui.plan, c, {t}); const tg = vt.alt != null && vt.k > .5 ? vt.alt : vt.main; return a.el && !a.el.seeking && a.el.readyState >= 2 && Math.abs(a.el.currentTime - tg) < 0.03; }}", timeout=15000)
                await pg.wait_for_timeout(120)
                exp = await pg.evaluate(f"() => {{ const c = J.media.cutAt(J.ui.plan, {t}, 'back'), vt = J.media.videoTimes(J.ui.plan, c, {t}); return vt.alt != null && vt.k > .5 ? vt.alt : vt.main; }}")
                m = await pg.evaluate(MEDIAN, ['render', t])
                ok(abs(clip_time(m) - exp) <= 0.07, f'preview at {t}s shows clip time {clip_time(m):.2f} (expected {exp:.2f})')
            print('scrub across all lines')
            for t in [1, 11, 21, 31, 41, 2, 12, 22, 32, 42]:
                await pg.evaluate(f"() => J.uiApi.seek({t})"); await pg.wait_for_timeout(150)
            live = await pg.evaluate("() => J.media.liveVideos()")
            ok(live <= 3, f'at most 3 clips hold a decoder ({live})')
            print('preview (playing)')
            await pg.evaluate("() => { J.uiApi.seek(0.2); }")
            await pg.evaluate("""() => { window.__seeks = 0; for (const a of J.mediaAssets.values()) if (a.el) a.el.addEventListener('seeking', () => window.__seeks++); document.getElementById('btnPlay').click(); }""")
            await pg.wait_for_timeout(2500)
            st = await pg.evaluate("""() => { const S = J.ui, t = S.t, c = J.media.cutAt(S.plan, t, 'back'), a = J.mediaAssets.get(c.assetId), vt = J.media.videoTimes(S.plan, c, t);
              const r = { playing: S.playing, t: +t.toFixed(2), drift: +Math.abs(a.el.currentTime - vt.main).toFixed(3), paused: a.el.paused, seeks: window.__seeks }; document.getElementById('btnPlay').click(); return r; }""")
            ok(st['playing'] and not st['paused'] and st['drift'] < 0.15 and st['seeks'] <= 3, f"while playing the clip plays along (drift {st['drift']}s, {st['seeks']} seeks in 2.5 s)")
            print('export (MP4 frames vs. expected clip time)')
            for mode, r0, r1 in [('loop', 2.5, 5.5), ('pingpong', 3.0, 6.0), ('hold', 3.0, 6.0), ('beat', 0.5, 4.5)]:
                res = await pg.evaluate("""async ([mode, r0, r1]) => {
                  const S = J.ui; S.project.media.autoFill.back.video = { extend: mode, rate: 1, beats: 4 }; J.uiApi.replan();
                  const t0 = performance.now(); const r = await J.exportMP4({ plan: S.plan, project: Object.assign({}, S.project, { res: 720, includeAudio: false }), audio: null, quality: 'normal', range: { t0: r0, t1: r1 } });
                  return { url: URL.createObjectURL(r.blob), codec: r.codec, ms: (performance.now() - t0) / ((r1 - r0) * S.plan.fps) }; }""", [mode, r0, r1])
                print(f"  ({mode}: {res['codec']}, {res['ms']:.0f} ms per frame at 720p)")
                worst, bad = 0, []
                for off in [0.15, 0.6, 1.05, 1.4, 1.75, 2.2, 2.65]:
                    t = r0 + off
                    if t >= r1 - 0.05: continue
                    vt = await pg.evaluate(f"() => {{ const c = J.media.cutAt(J.ui.plan, {t}, 'back'); return J.media.videoTimes(J.ui.plan, c, {t}); }}")
                    m = await pg.evaluate(MEDIAN, [res['url'], off + 0.5 / 30])
                    got = clip_time(m)
                    if vt.get('alt') is not None: continue           # seam frames are a blend; checked below
                    err = abs(got - vt['main']); worst = max(worst, err)
                    if err > 0.1: bad.append((round(t, 2), round(vt['main'], 2), round(got, 2)))
                ok(not bad, f'{mode}: exported frames follow the clip time (worst error {worst:.3f}s) {bad[:3]}')
            # the loop seam: frames inside the last 0.3 s of a pass mix the end and the start of the clip
            await pg.evaluate("() => { J.ui.project.media.autoFill.back.video = { extend: 'loop', rate: 1, beats: 4 }; J.uiApi.replan(); }")
            # Alternate end/start seeks repeatedly; inspect capture pixels before encoding to distinguish capture and readback failures.
            captures = await pg.evaluate("""async () => {
              const P=J.ui.plan,out=[],cv=document.createElement('canvas');cv.width=cv.height=1;const x=cv.getContext('2d');
              for(let pass=0;pass<4;pass++) for(const t of [3.72,3.80,3.88]) {
                await J.media.prepareFrame(P,t);const c=J.media.cutAt(P,t,'back'),a=J.mediaAssets.get(c.assetId),vt=J.media.videoTimes(P,c,t);
                const red=time=>{const src=J.media.videoCap(a,time);if(!src)return null;x.drawImage(src,0,0,1,1);return x.getImageData(0,0,1,1).data[0];};
                out.push({t,main:red(vt.main),alt:red(vt.alt),k:vt.k});
              }return out;
            }""")
            bad=[c for c in captures if c['main'] is None or c['alt'] is None or abs(c['main']-180)>3 or abs(c['alt']-30)>3]
            ok(not bad, f'loop seam prepares both distinct source frames across 12 alternating seeks {bad[:3]}')
            res = await pg.evaluate("""async () => { const S = J.ui; const r = await J.exportMP4({ plan: S.plan, project: Object.assign({}, S.project, { res: 720, includeAudio: false }), audio: null, quality: 'normal', range: { t0: 3.5, t1: 4.5 } }); return URL.createObjectURL(r.blob); }""")
            m = await pg.evaluate(MEDIAN, [res, 0.38])                # song 3.88 s: end of the clip (3.88) with the start (0.18) fading in at 60 %
            readback=await pg.evaluate('() => window.__lastVideoRead')
            ok(80 < m[0] < 175, f'the loop seam is a cross-fade, not a jump (red {m[0]} between the end and the start of the clip; decoded {readback})')
            print('a clip placed at a time (under the whole song, on the song clock)')
            await pg.evaluate("""() => { const S = J.ui, m = S.project.media, ids = m.assets.map(a => a.id);
              m.autoFill.back.video = { extend: 'loop', rate: 1, beats: 4 };
              m.tracks.back.cuts = [{ id: 't1', assetId: ids[0], lineRef: null, start: 0, end: null }, { id: 'l2', assetId: ids[2], lineRef: { line: 2 } }];
              S.project.media = J.media.normalize(m); J.uiApi.replan(); }""")
            cuts = await pg.evaluate("() => { const id0 = J.ui.project.media.assets[0].id; return J.ui.plan.media.back.cuts.map(c => [c.assetId === id0 ? 'bg' : 'line', +c.start.toFixed(2), c.anchor]); }")
            ok([c[0] for c in cuts] == ['bg', 'line', 'bg'] and [c[1] for c in cuts] == [0, 20, 30] and cuts[2][2] == 0,
               f'it covers the automatic per-line clips, a clip chosen for line 3 still shows, and it resumes on its own clock: {cuts}')
            VT = """(ts) => ts.map(t => { const P = J.ui.plan, c = J.media.cutAt(P, t, 'back'); return J.media.videoTimes(P, c, t).main; })"""
            a_, b_ = await pg.evaluate(VT, [9.95, 10.05])
            ok(abs((b_ - a_) - 0.1) < 0.02, f'no restart at the lyric line at 10 s (clip time {a_:.2f} → {b_:.2f})')
            same = await pg.evaluate("""() => { const P = J.ui.plan, c0 = P.media.back.cuts[0], c2 = P.media.back.cuts[2];
              return [J.media.videoTimes(P, c2, 30.05).main, J.media.videoTimes(P, c0, 30.05).main]; }""")
            ok(abs(same[0] - same[1]) < 1e-6, f'after line 3 the clip is where it would have been without it ({same[0]:.2f})')
            res = await pg.evaluate("""async () => { const S = J.ui; const r = await J.exportMP4({ plan: S.plan, project: Object.assign({}, S.project, { res: 720, includeAudio: false }), audio: null, quality: 'normal', range: { t0: 9.4, t1: 10.6 } }); return URL.createObjectURL(r.blob); }""")
            bad = []
            for off in [0.2, 0.55, 0.65, 1.0]:
                exp = (await pg.evaluate(VT, [9.4 + off]))[0]
                got = clip_time(await pg.evaluate(MEDIAN, [res, off + 0.5 / 30]))
                if abs(got - exp) > 0.1: bad.append((round(9.4 + off, 2), round(exp, 2), round(got, 2)))
            ok(not bad, f'the exported frames run straight through the lyric line {bad}')
            for t in [12.3, 31.7]:
                await pg.evaluate(f"() => J.uiApi.seek({t})")
                await pg.wait_for_function(f"() => {{ const c = J.media.cutAt(J.ui.plan, {t}, 'back'), a = J.mediaAssets.get(c.assetId), vt = J.media.videoTimes(J.ui.plan, c, {t}); return a.el && !a.el.seeking && a.el.readyState >= 2 && Math.abs(a.el.currentTime - vt.main) < 0.03; }}", timeout=15000)
                await pg.wait_for_timeout(120)
                exp = (await pg.evaluate(VT, [t]))[0]; got = clip_time(await pg.evaluate(MEDIAN, ['render', t]))
                ok(abs(got - exp) <= 0.07, f'a seek to {t}s shows the same clip time as the export would ({got:.2f} / {exp:.2f})')
            await pg.evaluate("() => { const m = J.ui.project.media; m.tracks.back.cuts = []; J.uiApi.replan(); }")
            print('PNG export with clips')
            n = await pg.evaluate("""async () => { const S = J.ui; const r = await J.exportPNGZip({ plan: S.plan, project: Object.assign({}, S.project, { res: 720 }), range: { t0: 10.5, t1: 11.0 } }); return r && (r.size || r.byteLength || (r.blob && r.blob.size)) || 0; }""")
            ok(bool(n), f'PNG export runs with clips ({n})')
            print('reload')
            await pg.evaluate("() => J.uiApi.flushSave()")
            await pg.reload(); await pg.wait_for_function('window.J && J.ui && J.ui.plan && J.mediaUI')
            await pg.wait_for_function("() => [...J.mediaAssets.values()].filter(a => a.type === 'video').length === 4", timeout=60000)
            th = await pg.evaluate("() => [...J.mediaAssets.values()].every(a => a.thumb && a.thumb.width === 160) && document.querySelectorAll('#mediaList .dur').length")
            ok(th == 4, f'clips are back after a reload, with thumbnails and their length shown ({th})')
            ok(not errs, f'no page errors {errs[:3]}')
            await b.close()
    srv.shutdown()
    print('FAILED: %d' % len(fails) if fails else 'all video checks passed')
    sys.exit(1 if fails else 0)

asyncio.run(main())
