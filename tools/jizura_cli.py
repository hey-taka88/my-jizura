"""my-jizura: 文字PV をコマンドで作る（見えないブラウザでビルド済みの index.html を動かす）

  python3 tools/jizura_cli.py render --lyrics song.json --song song.mp3 --media pics/ --aspect 16:9 --aspect 9:16 --theme ballad --out mv.mp4
  python3 tools/jizura_cli.py preview --lyrics song.lrc --media pics/ --count 6 --out-dir shots/
  python3 tools/jizura_cli.py plan --project mv.jizura.json --media pics/        # 行・時刻・画像の一覧（JSON）
  python3 tools/jizura_cli.py info                                                # 選べる値とブラウザの対応状況（JSON）

先に python3 build.py（index.html を作る）。必要なもの：pip install -r dev/requirements.txt と python3 -m playwright install chromium。
H.264 の MP4（AI 動画の多く）を読むには Google Chrome か Edge が入っていること（自動で使います）。
既存のファイルは上書きしません（--force で上書き）。
"""
import argparse, asyncio, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jizura_driver import Jizura, JizuraError, ASPECTS, RES, FPS, QUALITY, MEDIA_ORDER, MEDIA_HOLD, MEDIA_FIT, MEDIA_ENTER, MEDIA_TREAT, MEDIA_SCRIM, VIDEO_EXTEND, VIDEO_RATES, VIDEO_BEATS


def log(msg): print(msg, file=sys.stderr, flush=True)


def common(p):
    g = p.add_argument_group('入力')
    g.add_argument('--project', help='保存したプロジェクト（.jizura.json）から始める')
    g.add_argument('--lyrics', help='歌詞：LRC / SRT / VTT / Whisper・Suno の JSON / テキスト')
    g.add_argument('--song', help='曲（mp3・wav・m4a、動画ファイルの音声も可）')
    g.add_argument('--media', action='append', default=[], help='画像・動画のファイルかフォルダ（何度でも。フォルダは名前順）')
    g.add_argument('--title', help='曲名'); g.add_argument('--artist', help='アーティスト名')
    g = p.add_argument_group('見た目')
    g.add_argument('--theme', help='おまかせのテーマ（info で一覧。例 ballad）')
    g.add_argument('--variation', type=int, help='おまかせの案の番号（同じ番号なら同じ見た目）')
    g.add_argument('--style', help='スタイルを固定（例 noir）'); g.add_argument('--mood', help='雰囲気を固定（例 calm）')
    g.add_argument('--seed', type=int, help='カット割りのシード')
    g = p.add_argument_group('画像・動画')
    g.add_argument('--order', choices=MEDIA_ORDER); g.add_argument('--hold', choices=MEDIA_HOLD, help='動き：kenburns = ゆっくり寄る、pan = 横に流す、push = ぐっと寄る、drift = 漂う、beatPulse = 拍で脈打つ')
    g.add_argument('--trans', help='つなぎ：fade / cut / mix / 切り替え効果の名前（info で一覧）')
    g.add_argument('--enter', choices=MEDIA_ENTER, help='登場・退場（前後に画像が無いとき）'); g.add_argument('--treat', choices=MEDIA_TREAT, help='加工')
    g.add_argument('--scrim', choices=MEDIA_SCRIM, help='文字の下の暗幕'); g.add_argument('--media-omakase', action='store_true', help='メディアのおまかせ（動き・つなぎ・加工などをまとめて決める）')
    g.add_argument('--fit', choices=MEDIA_FIT); g.add_argument('--dim', type=float, help='暗さ 0〜0.9（文字を読みやすく）')
    g.add_argument('--lyric-bg', action='store_true', help='歌詞側の背景グラフィックも重ねる')
    g.add_argument('--shuffle', type=int, help='並びのシード（order=random のとき）')
    g.add_argument('--extend', choices=VIDEO_EXTEND, help='動画が行より短いとき')
    g.add_argument('--rate', type=float, choices=VIDEO_RATES); g.add_argument('--beats', type=int, choices=VIDEO_BEATS)
    g.add_argument('--line-media', action='append', default=[], metavar='行=画像', help='行ごとの画像（例 3=sunset.jpg、5=none）。何度でも')
    g = p.add_argument_group('出力')
    g.add_argument('--aspect', action='append', choices=ASPECTS, help='画面比（何度でも。2 つ以上なら比率ごとにファイル）')
    g.add_argument('--res', type=int, choices=RES); g.add_argument('--fps', type=int, choices=FPS)
    g.add_argument('--browser', default='auto', choices=['auto', 'chrome', 'msedge', 'chromium'])
    g.add_argument('--app', help='アプリの場所（既定はこのリポジトリの index.html。URL も可）')
    g.add_argument('--force', action='store_true', help='既存のファイルを上書きする')


async def setup(jz, a, aspect):
    if a.project: await jz.open_project(a.project)
    else: await jz.new_project(title=a.title or '', artist=a.artist or '', aspect=aspect or '16:9')
    if a.project and (a.title or a.artist):
        await jz.page.evaluate('(o) => { const P = J.ui.project; if (o.t) P.title = o.t; if (o.a) P.artist = o.a; J.uiApi.replan(); }', {'t': a.title, 'a': a.artist})
    if a.lyrics:
        r = await jz.set_lyrics(path=a.lyrics); log(f'歌詞: {r["lines"]} 行（時刻付き {r["timed"]} 行・{r["kind"]}）')
    if a.song:
        r = await jz.load_song(a.song); log(f'曲: {r["name"]}（{r["duration"]:.1f} 秒・約 {r["bpm"]} BPM）')
    if a.media:
        r = await jz.add_media(a.media); log(f'画像・動画: {len(r["added"])} 件追加（全 {r["total"]} 件）')
        for e in r['errors']: log(f'  読み込めません: {e["name"]}（{e["reason"]}）')
    if a.theme or a.variation is not None or a.style or a.mood or a.seed is not None:
        r = await jz.set_look(theme=a.theme, style=a.style, mood=a.mood, variation=a.variation, seed=a.seed)
        log(f'見た目: {r["styleName"]}・{r["mood"]}' + (f'（テーマ {r["theme"]}）' if r['theme'] else ''))
    if a.media_omakase: r = await jz.media_omakase(); log(f'メディアのおまかせ: {r["summary"]}')
    mo = dict(order=a.order, hold=a.hold, fit=a.fit, dim=a.dim, lyric_bg=True if a.lyric_bg else None, shuffle=a.shuffle, extend=a.extend, rate=a.rate, beats=a.beats,
              trans=a.trans, enter=a.enter, exit=a.enter, treat=a.treat, scrim=a.scrim)
    if any(v is not None for v in mo.values()): await jz.set_media_options(**mo)
    for s in a.line_media:
        k, _, v = s.partition('=')
        if not k.strip().isdigit() or not v: raise JizuraError(f'--line-media は 行=画像 の形で: {s}')
        await jz.set_line_media(int(k), v.strip())
    if aspect and a.project: await jz.set_output(aspect=aspect)
    if a.res or a.fps: await jz.set_output(res=a.res, fps=a.fps)


def target(path, force):
    path = os.path.abspath(path)
    if os.path.exists(path) and not force: raise JizuraError(f'すでにあります（上書きは --force）: {path}')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def per_aspect(out, aspect, many):
    if not many: return out
    b, e = os.path.splitext(out)
    if b.endswith('.jizura'): b, e = b[:-7], '.jizura' + e
    return f'{b}_{aspect.replace(":", "x")}{e}'


async def run(a):
    aspects = getattr(a, 'aspect', None) or [None]
    async with Jizura(app=a.app, browser=a.browser, log=log) as jz:
        if a.cmd == 'info':
            print(json.dumps({'status': await jz.status(), 'options': await jz.options()}, ensure_ascii=False, indent=1)); return
        await setup(jz, a, aspects[0])
        many = len(aspects) > 1
        for k, asp in enumerate(aspects):
            if k: await jz.set_output(aspect=asp); log(f'画面比: {asp}')
            if a.cmd == 'plan':
                print(json.dumps(await jz.get_plan(), ensure_ascii=False, indent=1))
            elif a.cmd == 'preview':
                d = per_aspect(a.out_dir, asp, many) if many else a.out_dir
                times = [float(x) for x in a.at.split(',')] if a.at else None
                os.makedirs(d, exist_ok=True)
                for t, text, png in await jz.preview(times=times, count=a.count, width=a.width):
                    p = target(os.path.join(d, f'frame_{t:07.2f}.png'), a.force)
                    open(p, 'wb').write(png); log(f'{p}  {text}')
            else:
                out = target(per_aspect(a.out, asp or 'x', many), a.force)
                if a.save_project: await jz.save_project(target(per_aspect(a.save_project, asp or 'x', many), a.force))
                t0, t1 = None, None
                if a.range:
                    s, _, e = a.range.partition('-'); t0 = float(s) if s else None; t1 = float(e) if e else None
                log(f'書き出し中: {out}')
                r = await jz.export_mp4(out, t0=t0, t1=t1, audio=not a.no_audio, quality=a.quality)
                log(f'できました: {out}（{r["width"]}×{r["height"]}・{r["codec"]}・{r["duration"]:.1f} 秒・{r["size"] / 1e6:.1f}MB'
                    + (f'・音声 {r["audio"]}' if r['audio'] else '・音声なし') + '）' + (f'  ※{r["note"]}' if r.get('note') else ''))
        if jz.errors: log('ページのエラー: ' + ' / '.join(jz.errors[:3]))


def main():
    ap = argparse.ArgumentParser(prog='jizura_cli.py', description=__doc__.split('\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('render', help='MP4 を書き出す'); common(r)
    r.add_argument('--out', required=True, help='出力する MP4（画面比が 2 つ以上なら _16x9 などが付く）')
    r.add_argument('--range', help='秒の範囲だけ書き出す（例 30-45）')
    r.add_argument('--quality', choices=QUALITY); r.add_argument('--no-audio', action='store_true')
    r.add_argument('--save-project', help='プロジェクトも保存する（.jizura.json）')
    p = sub.add_parser('preview', help='フレームを PNG で保存'); common(p)
    p.add_argument('--out-dir', required=True); p.add_argument('--at', help='秒（カンマ区切り。例 12.5,40）')
    p.add_argument('--count', type=int, default=6, help='--at が無いとき、歌詞の行から均等に何枚'); p.add_argument('--width', type=int, default=960)
    q = sub.add_parser('plan', help='行・時刻・画像の一覧を JSON で'); common(q)
    i = sub.add_parser('info', help='選べる値とブラウザの対応状況'); i.add_argument('--browser', default='auto', choices=['auto', 'chrome', 'msedge', 'chromium']); i.add_argument('--app')
    a = ap.parse_args()
    try: asyncio.run(run(a))
    except JizuraError as e: log(f'エラー: {e}'); sys.exit(2)
    except KeyboardInterrupt: sys.exit(130)


if __name__ == '__main__':
    main()
