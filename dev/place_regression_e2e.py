"""Placement review regressions on the built app: rendered colour, video time, picker exit and saved cancellation.
usage: python3 build.py && python3 dev/place_regression_e2e.py [--browser chromium]
"""
import asyncio
import base64
import sys
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from jizura_driver import Jizura

BROWSER = sys.argv[sys.argv.index('--browser') + 1] if '--browser' in sys.argv else 'chromium'
LYRICS = '[00:01.00]夜明けの色を覚えてる\n[00:05.00]ほどけた声が遠くで鳴った\n[00:09.00]名前のない明日へ\n[00:13.00]おわり'
FRONT = '() => JSON.parse(JSON.stringify(J.ui.project.media.tracks.front.cuts))'
ARMED = "() => document.getElementById('viewport').classList.contains('media-spoid')"
MAKE_CLIP = """async () => {
  const mux = new Mp4Muxer.Muxer({target: new Mp4Muxer.ArrayBufferTarget(),
    video: {codec: 'vp9', width: 320, height: 180, frameRate: 30}, fastStart: 'in-memory'});
  const enc = new VideoEncoder({output: (c, m) => mux.addVideoChunk(c, m), error: e => {throw e;}});
  enc.configure({codec: 'vp09.00.10.08', width: 320, height: 180, bitrate: 2e6, framerate: 30});
  const cv = new OffscreenCanvas(320, 180), x = cv.getContext('2d');
  for (let i = 0; i < 120; i++) {
    x.fillStyle = `rgb(${30 + 50 * Math.floor(i / 30)},0,40)`; x.fillRect(0, 0, 320, 180);
    const f = new VideoFrame(cv, {timestamp: Math.round(i * 1e6 / 30), duration: Math.round(1e6 / 30)});
    enc.encode(f, {keyFrame: i % 30 === 0}); f.close();
  }
  await enc.flush(); enc.close(); mux.finalize();
  const u8 = new Uint8Array(mux.target.buffer); let s = '';
  for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode(...u8.subarray(i, i + 0x8000));
  return btoa(s);
}"""


async def main():
    failures = []

    def ok(cond, msg):
        print(('  ok   ' if cond else '  FAIL ') + msg, flush=True)
        if not cond:
            failures.append(msg)

    with tempfile.TemporaryDirectory() as tmp:
        pic = Path(tmp) / 'split.png'
        im = Image.new('RGB', (400, 300), (0, 220, 0))
        ImageDraw.Draw(im).rectangle((0, 0, 99, 299), fill=(240, 0, 0)); im.save(pic)
        async with Jizura(browser=BROWSER, log=lambda m: None) as jz:
            pg, ev = jz.page, jz.page.evaluate
            await pg.set_viewport_size({'width': 1500, 'height': 950})
            await jz.new_project(lyrics=LYRICS); await jz.add_media([str(pic)])
            await jz.set_media_options(auto=False, dim=0)
            cid = (await jz.add_timed_media('split.png', 0, track='front', size=0.6, hold='push', enter='cut', exit='cut'))['id']
            await ev('(id) => {J.mediaPlace.select(id); J.uiApi.seek(10);}', cid)
            await pg.wait_for_timeout(100)
            # Compare the actual drawn pixels to picked source colours; do not use cutBox as the test oracle.
            for aspect in ('16:9', '9:16'):
                await ev('(a) => {J.ui.project.aspect=a; J.uiApi.replan();}', aspect)
                await pg.wait_for_timeout(80)
                results = await ev("""() => {
                  const S=J.ui, c=S.project.media.tracks.front.cuts[0], out=[];
                  for (const [hold, enter, time, rot] of [['push','cut',10,0],['drift','cut',10,35],
                      ['kenburns','cut',10,-25],['pan','cut',10,15],['still','slide',0.5,20],['still','zoom',0.5,-15]]) {
                    Object.assign(c,{hold,enter}); c.rect.rot=rot; J.uiApi.replan(); S.t=time;
                    const P=S.plan, r=document.getElementById('view').getBoundingClientRect();
                    const cv=document.createElement('canvas'); cv.width=P.W/4; cv.height=P.H/4;
                    const x=cv.getContext('2d'); x.scale(cv.width/P.W,cv.width/P.W);
                    J.media.drawTrack(x,P,time,'front',{scale:cv.width/P.W});
                    let checked=0, wrong=0;
                    for(let yy=0.2; yy<0.81; yy+=0.05) for(let xx=0.2; xx<0.81; xx+=0.03) {
                      const px=Math.floor(xx*cv.width), py=Math.floor(yy*cv.height), d=x.getImageData(px,py,1,1).data;
                      // Compare flat interiors, excluding antialiased borders even during partly faded entrances.
                      if(d[3]<40 || !((d[0]>235&&d[1]<4)||(d[1]>215&&d[0]<4))) continue;
                      const near=x.getImageData(px-1,py-1,3,3).data;
                      if(near.some((v,i)=>Math.abs(v-d[i%4])>2)) continue;
                      const col=J.media.pickColor(c,r.left+(px+0.5)/cv.width*r.width,r.top+(py+0.5)/cv.height*r.height);
                      const rgb=col&&[1,3,5].map(i=>parseInt(col.slice(i,i+2),16)); checked++;
                      if(!rgb||rgb.some((v,i)=>Math.abs(v-d[i])>8)) wrong++;
                    }
                    out.push({hold,enter,rot,checked,wrong});
                  }
                  return out;
                }""")
                for r in results:
                    ok(r['checked'] > 0 and r['wrong'] == 0, f'{aspect}: picker matches rendered motion/rotation {r}')
            await ev("() => {const c=J.ui.project.media.tracks.front.cuts[0];Object.assign(c,{hold:'still',enter:'cut'});c.rect.rot=0;J.ui.project.aspect='16:9';J.uiApi.replan();J.uiApi.seek(6.5);}")
            await pg.wait_for_timeout(100)
            key = pg.locator('#mediaFront .key').first
            await key.select_option('auto'); await key.select_option('spoid'); await key.select_option('')
            ok(not await ev(ARMED), 'Off cancels the eyedropper')
            b=await pg.locator('#mediaBox').bounding_box()
            await pg.mouse.click(b['x']+b['width']*.6,b['y']+b['height']*.5)
            ok('chroma' not in (await ev(FRONT))[0], 'a later click does not re-enable the key')
            await key.select_option('spoid'); await ev('() => J.mediaPlace.select(null)')
            ok(not await ev(ARMED), 'deselecting cancels the eyedropper')
            await ev('(id) => J.mediaPlace.select(id)',cid)
            await key.select_option('spoid')
            b=await pg.locator('#mediaBox').bounding_box(); x,y=b['x']+b['width']/2,b['y']+b['height']/2
            before=(await ev(FRONT))[0]['rect']
            await pg.mouse.move(x,y);await pg.mouse.down();await pg.mouse.move(x+30,y+15,steps=3)
            await pg.keyboard.press('Escape');await pg.mouse.up()
            ok(not await ev(ARMED) and (await ev(FRONT))[0]['rect']==before, 'picker gesture + Escape neither moves nor keys the image')
            for existing, cancel in ((True,'pointercancel'),(False,'Escape')):
                await ev('(exists) => {const c=J.ui.project.media.tracks.front.cuts[0];if(exists)c.rect={x:0,y:0,w:.4,rot:0};else delete c.rect;J.uiApi.replan();}',existing)
                await pg.wait_for_timeout(80)
                before=(await ev(FRONT))[0].get('rect')
                b=await pg.locator('#mediaBox').bounding_box();x,y=b['x']+b['width']/2,b['y']+b['height']/2
                await pg.mouse.move(x,y);await pg.mouse.down();await pg.mouse.move(x+45,y+20,steps=3)
                await ev('() => J.uiApi.flushSave()')  # an autosave may fire while the pointer is still held
                if cancel=='Escape': await pg.keyboard.press('Escape')
                else: await pg.locator('#mediaBox').dispatch_event('pointercancel',{'pointerId':1,'pointerType':'mouse'})
                await pg.mouse.up()
                saved=await ev("() => JSON.parse(localStorage.getItem('jizura.project.v1')).media.tracks.front.cuts[0]")
                ok((await ev(FRONT))[0].get('rect')==before and saved.get('rect')==before,
                   f'{cancel} restores project and saved rect (original rect present: {existing})')
            # Two cuts use different frames of the same clip; its shared element stays on the last frame prepared.
            video=Path(tmp)/'clock.mp4';video.write_bytes(base64.b64decode(await ev(MAKE_CLIP)))
            await jz.new_project(lyrics=LYRICS);await jz.add_media([str(video)]);await jz.set_media_options(auto=False)
            for pos,start in ((-.25,0),(.25,1)):
                await jz.add_timed_media('clock.mp4',0,track='front',x=pos,size=.4,clip_start=start,enter='cut',exit='cut')
            await ev("() => {J.mediaPlace.select(J.ui.project.media.tracks.front.cuts[0].id);J.uiApi.seek(2);}")
            await pg.wait_for_timeout(100)
            r=await ev("""async () => {
              const S=J.ui;await J.media.prepareFrame(S.plan,2);
              const cv=document.createElement('canvas');cv.width=960;cv.height=540;
              new J.Renderer().frame(cv.getContext('2d'),S.plan,2,{scale:960/S.plan.W,noPost:true,noHud:true});
              const r=document.getElementById('view').getBoundingClientRect();
              return S.project.media.tracks.front.cuts.map(c=>({
                rendered:Array.from(cv.getContext('2d').getImageData(Math.round((.5+c.rect.x)*960),270,1,1).data).slice(0,3),
                picked:J.media.pickColor(c,r.left+r.width*(.5+c.rect.x),r.top+r.height*.5)}));
            }""")
            ok(abs(r[0]['rendered'][0]-r[1]['rendered'][0])>30, 'fixture renders two different clip times')
            for i,c in enumerate(r):
                rgb=[int(c['picked'][k:k+2],16) for k in (1,3,5)] if c['picked'] else []
                ok(len(rgb)==3 and all(abs(a-b)<=3 for a,b in zip(rgb,c['rendered'])),f'video cut {i+1}: picker uses its displayed frame {c}')
            await pg.locator('#mediaFront .key').first.select_option('spoid')
            b=await pg.locator('#mediaBox').bounding_box();await pg.mouse.click(b['x']+b['width']/2,b['y']+b['height']/2)
            key=(await ev(FRONT))[0].get('chroma',{}).get('color')
            expected='#'+''.join(f'{v:02x}' for v in r[0]['rendered'])
            ok(key==expected, f'actual video eyedropper click stores selected frame colour ({key}, expected {expected})')
            ok(not jz.errors,f'no page errors {jz.errors[:3]}')
    print(f'FAILED: {len(failures)}' if failures else 'all placement regression checks passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
