"""Chroma/treatment cache regressions on the built app, including fresh CPU image and clip processing.
usage: python3 build.py && python3 dev/chroma_e2e.py [--browser chromium]
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
from jizura_driver import Jizura

BROWSER = sys.argv[sys.argv.index('--browser') + 1] if '--browser' in sys.argv else 'chromium'
PROBE = """(cpu) => {
  const M = J.media, previous = M.chromaCPU;
  const proto = CanvasRenderingContext2D.prototype, put = proto.putImageData;
  let writes = 0;
  proto.putImageData = function(...args) { writes++; return put.apply(this, args); };
  const picture = (w = 256) => {
    const cv = document.createElement('canvas'); cv.width = w; cv.height = w / 2;
    const x = cv.getContext('2d');
    ['#28b446', '#60aa70', '#ff00ff', '#808080'].forEach((col, i) => {
      x.fillStyle = col; x.fillRect(i * w / 4, 0, w / 4, cv.height);
    });
    return cv;
  };
  const pixels = cv => Array.from(cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data);
  const alpha = cv => [0, 1, 2, 3].map(i => cv.getContext('2d').getImageData(
    Math.floor((i + 0.5) * cv.width / 4), cv.height / 2, 1, 1).data[3]);
  const base = { color: '#28b446', tol: 0.02, soft: 0.03, spill: 0 };
  const cases = [base, { ...base, color: '#ff00ff' }, base, { ...base, tol: 0.4 },
    { ...base, soft: 0.4 }, { ...base, spill: 1 }, base];
  try {
    M.chromaCPU = cpu;
    const webgl = M.chromaInfo().webgl, results = [];
    for (const treat of ['mono', 'sepia', 'duotone', 'match', 'blur']) {
      const src = picture(), asset = { type: 'image', source: src }, plan = J.ui.plan;
      let firstKeyed, firstTreated;
      const steps = cases.map(chroma => {
        const cut = { chroma, treat }, keyed = M.keyed(asset, src, cut);
        const treated = M.treated(asset, keyed, cut, plan), actual = pixels(treated);
        firstKeyed ||= keyed; firstTreated ||= treated;
        // An independently processed image is the oracle for this setting, regardless of the previous cut.
        const fresh = picture(), freshAsset = { type: 'image', source: fresh };
        const expected = pixels(M.treated(freshAsset, M.keyed(freshAsset, fresh, cut), cut, plan));
        const before = writes;
        const again = M.treated(asset, M.keyed(asset, src, cut), cut, plan);
        return { matchesFresh: actual.every((v, i) => v === expected[i]),
          reusesCanvases: keyed === firstKeyed && treated === firstTreated && again === treated,
          cachedCPU: writes === before, alpha: alpha(keyed) };
      });
      results.push({ treat, steps });
    }
    // Fresh sources are essential: toggling chromaCPU on an already cached image never runs the fallback.
    const fresh = picture(1280), before = writes;
    const im = M.keyed({ type: 'image', source: fresh }, fresh, { chroma: base });
    const imageWrites = writes - before;
    const clipBefore = writes, clipAsset = { type: 'video' }, clipSource = picture(1280);
    const clip = M.keyed(clipAsset, clipSource, { chroma: base });
    const clipAlpha = alpha(clip), clipWrites = writes - clipBefore;
    const sameClip = M.keyed(clipAsset, clipSource, { chroma: cases[1] });
    return { cpu, webgl, results, imageWrites, clipWrites, imageWidth: im.width, clipWidth: clip.width,
      imageAlpha: alpha(im), clipAlpha, changedClipAlpha: alpha(sameClip), sameClip: clip === sameClip };
  } finally { M.chromaCPU = previous; proto.putImageData = put; }
}"""


async def main():
    failures = []

    def ok(cond, msg):
        print(('  ok   ' if cond else '  FAIL ') + msg, flush=True)
        if not cond:
            failures.append(msg)

    async with Jizura(browser=BROWSER, log=lambda m: None) as jz:
        await jz.new_project(lyrics='[00:01.00]クロマキーの確認')
        for cpu in (False, True):
            r = await jz.page.evaluate(PROBE, cpu)
            mode = 'CPU' if cpu else 'WebGL'
            ok(r['webgl'] == (not cpu), f'{mode}: requested backend available')
            for result in r['results']:
                steps = result['steps']
                ok(all(s['matchesFresh'] for s in steps), f"{mode} {result['treat']}: colour / tolerance / softness / spill / A→B→A match fresh processing")
                ok(all(s['reusesCanvases'] and s['cachedCPU'] for s in steps), f"{mode} {result['treat']}: reuse bounded canvases and unchanged image cache")
                ok(steps[0]['alpha'][0] == 0 and steps[0]['alpha'][2] == 255 and
                   steps[1]['alpha'][0] == 255 and steps[1]['alpha'][2] == 0, f"{mode} {result['treat']}: swapping key colour swaps transparent regions")
            ok(r['imageAlpha'][0] == 0 and r['imageAlpha'][2:] == [255, 255] and
               r['clipAlpha'][0] == 0 and r['clipAlpha'][2:] == [255, 255], f'{mode}: fresh image and clip remove screen, retain subject and grey')
            ok(r['sameClip'] and r['changedClipAlpha'][0] == 255 and r['changedClipAlpha'][2] == 0,
               f'{mode}: next clip frame reuses canvas with updated key')
            if cpu:
                ok(r['imageWrites'] > 0 and r['clipWrites'] > 0 and r['imageWidth'] == r['clipWidth'] == 960,
                   f"CPU fallback executed for fresh image and clip at 960px (writes {r['imageWrites']}/{r['clipWrites']})")
            else:
                ok(r['imageWrites'] == r['clipWrites'] == 0 and r['imageWidth'] == r['clipWidth'] == 1280,
                   'WebGL processes fresh image and clip without CPU fallback')
        ok(not jz.errors, f'no page errors {jz.errors[:3]}')
    print(f'FAILED: {len(failures)}' if failures else 'all chroma checks passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
