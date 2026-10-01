"""my-jizura: MCP server — lets Claude (Claude Code / Claude Desktop) or Codex make lyric videos with the app.

  python3 tools/jizura_mcp.py --workdir ~/mv          (stdio; the client starts it)

Every tool works inside one working folder (--workdir or JIZURA_WORKDIR; default: the current folder):
inputs are read from it and outputs are written into it, never elsewhere, and an existing file is never overwritten
(a new name is chosen). The page reaches nothing on the network but Google Fonts.
One app page is kept open while the server runs, so the tools build up one project step by step.
Needs: pip install -r dev/requirements.txt mcp  ·  python3 -m playwright install chromium  ·  python3 build.py
Setup for each client: docs/MCP.md
"""
import argparse, asyncio, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jizura_driver import Jizura, JizuraError, MEDIA_EXT

try:                                                    # mcp 2.x
    from mcp.server.mcpserver import MCPServer as Server, Image, Context
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:                                     # mcp 1.x
    from mcp.server.fastmcp import FastMCP as Server, Image, Context
    from mcp.server.fastmcp.exceptions import ToolError

LYRIC_EXT = ('.lrc', '.srt', '.vtt', '.json', '.txt')
SONG_EXT = ('.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.opus')

ap = argparse.ArgumentParser(description='my-jizura MCP server (stdio)')
ap.add_argument('--workdir', default=os.environ.get('JIZURA_WORKDIR') or os.getcwd(), help='the only folder the tools read and write')
ap.add_argument('--browser', default=os.environ.get('JIZURA_BROWSER', 'auto'), choices=['auto', 'chrome', 'msedge', 'chromium'])
ap.add_argument('--app', default=os.environ.get('JIZURA_APP'), help='index.html of this fork (default: the built one in this repository)')
ARGS = ap.parse_args()
WORK = os.path.realpath(os.path.expanduser(ARGS.workdir))
if not os.path.isdir(WORK): sys.exit(f'jizura: workdir not found: {WORK}')

mcp = Server('jizura', instructions=(
    'JIZURA makes lyric motion videos (文字PV) for a song: animated lyrics over pictures and video clips. '
    f'All paths are relative to the working folder {WORK}. Typical flow: list_files → new_project → set_lyrics (LRC / SRT / VTT / '
    'Whisper or Suno JSON give timing) → load_song → add_media → set_look → preview (look at the frames: are the lyrics readable? '
    'raise dim or change the look if not) → export_mp4. get_plan shows every line with its time and picture.'))

_jz = None
_lock = asyncio.Lock()


def log(msg): print(msg, file=sys.stderr, flush=True)


async def app():
    global _jz
    if _jz is None:
        jz = Jizura(app=ARGS.app, browser=ARGS.browser, log=log)
        await jz.start(); _jz = jz
    return _jz


def inside(rel, must_exist=True):
    """a path in the working folder (relative, or absolute but inside it)"""
    if not isinstance(rel, str) or not rel.strip() or '\0' in rel: raise ToolError('パスを指定してください')
    p = os.path.realpath(os.path.join(WORK, os.path.expanduser(rel)))
    if p != WORK and not p.startswith(WORK + os.sep): raise ToolError(f'作業フォルダの外は使えません: {rel}')
    if must_exist and not os.path.exists(p): raise ToolError(f'見つかりません: {rel}')
    return p


def fresh(rel, ext):
    """an output path in the working folder that does not exist yet (name, name-2, name-3 …)"""
    if not rel.lower().endswith(ext): rel += ext
    p = inside(rel, must_exist=False)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    base, k = p[:-len(ext)], 2
    while os.path.exists(p): p = f'{base}-{k}{ext}'; k += 1
    return p


rel = lambda p: os.path.relpath(p, WORK)


async def call(fn):
    async with _lock:
        try: return await fn(await app())
        except JizuraError as e: raise ToolError(str(e)) from None


# ---------------------------------------------------------------- tools
@mcp.tool()
async def list_files(folder: str = '.') -> dict:
    """Files in the working folder (or a sub-folder) that the tools can use, grouped: lyrics (lrc/srt/vtt/json/txt),
    songs, media (pictures and video clips), projects (.jizura.json), videos already exported, sub-folders."""
    d = inside(folder)
    if not os.path.isdir(d): raise ToolError(f'フォルダではありません: {folder}')
    out = {'folder': rel(d), 'lyrics': [], 'songs': [], 'media': [], 'projects': [], 'folders': []}
    for n in sorted(os.listdir(d)):
        if n.startswith('.'): continue
        p = os.path.join(d, n); r = rel(p); low = n.lower()
        if os.path.isdir(p): out['folders'].append(r)
        elif low.endswith('.jizura.json'): out['projects'].append(r)
        elif MEDIA_EXT.search(n): out['media'].append(r)
        elif low.endswith(SONG_EXT): out['songs'].append(r)
        elif low.endswith(LYRIC_EXT): out['lyrics'].append(r)
    return out


@mcp.tool()
async def status() -> dict:
    """The browser in use and whether it can read / write H.264 MP4 (most AI video clips are H.264: they need Google Chrome or Edge;
    WebM clips work everywhere), the app version and the working folder."""
    async def f(jz): s = await jz.status(); s['workdir'] = WORK; return s
    return await call(f)


@mcp.tool()
async def options() -> dict:
    """The values the other tools accept: themes, styles, moods (with their Japanese names), aspects, resolutions, fps, quality,
    and the picture / clip settings."""
    return await call(lambda jz: jz.options())


@mcp.tool()
async def new_project(title: str = '', artist: str = '', aspect: str = '16:9', lyrics: str = '') -> dict:
    """Start a new, empty project (a song already loaded stays). lyrics: optional text, one phrase per line ([mm:ss.xx] tags allowed).
    Returns the plan (see get_plan)."""
    return await call(lambda jz: jz.new_project(title=title, artist=artist, aspect=aspect, lyrics=lyrics or None))


@mcp.tool()
async def open_project(path: str) -> dict:
    """Open a saved .jizura.json from the working folder. Pictures are not inside the file: add them again with add_media
    (they are recognised by content, so each line gets its picture back). Returns the plan."""
    p = inside(path)
    return await call(lambda jz: jz.open_project(p))


@mcp.tool()
async def save_project(path: str = 'project.jizura.json') -> dict:
    """Save the project as .jizura.json in the working folder (a new name if it exists). It can be opened in the app in a browser too."""
    async def f(jz):
        p = fresh(path[:-12] if path.lower().endswith('.jizura.json') else path, '.jizura.json')
        await jz.save_project(p); return {'saved': rel(p)}
    return await call(f)


@mcp.tool()
async def set_lyrics(path: str = '', text: str = '') -> dict:
    """Replace the lyrics, from a file in the working folder (LRC / SRT / VTT / Whisper JSON / Suno aligned-words JSON give each line
    its time; a .txt is one phrase per line) or from text. Per-line settings and pictures are reset. Returns line counts."""
    p = inside(path) if path else None
    if not p and not text: raise ToolError('path か text を指定してください')
    return await call(lambda jz: jz.set_lyrics(path=p) if p else jz.set_lyrics(text=text))


@mcp.tool()
async def load_song(path: str) -> dict:
    """Load the song (mp3 / wav / m4a …, or the sound of a video file) from the working folder. Tempo and length are analysed;
    lines without times are spread over the song."""
    p = inside(path)
    return await call(lambda jz: jz.load_song(p))


@mcp.tool()
async def add_media(paths: list[str]) -> dict:
    """Add pictures and video clips (files or folders in the working folder; a folder adds its files in name order).
    By default they change line by line, in the order added. Returns what was added and what could not be read
    (reason 'video' = this browser cannot play that clip: H.265/HEVC, or H.264 without Chrome)."""
    ps = [inside(x) for x in paths]
    return await call(lambda jz: jz.add_media(ps))


@mcp.tool()
async def remove_media(media: str) -> dict:
    """Remove a picture / clip (by name, or its number in get_plan's media list)."""
    async def f(jz): return {'media': await jz.remove_media(media)}
    return await call(f)


@mcp.tool()
async def set_line_media(line: int, media: str) -> dict:
    """Choose the picture behind lyric line `line` (1 = first line, as in get_plan): a media name or number, 'none' (no picture:
    the lyrics' own background shows), or 'auto' (back to the automatic order)."""
    async def f(jz):
        await jz.set_line_media(int(line), media)
        p = await jz.get_plan(); return {'line': p['lines'][int(line) - 1]}
    return await call(f)


@mcp.tool()
async def set_look(theme: str = '', variation: int | None = None, style: str = '', mood: str = '', seed: int | None = None) -> dict:
    """Change how the lyrics look. theme: おまかせ within a direction (lyricpv, kinetic, wa, horror, pop, ballad — see options);
    variation: おまかせ again with this number (the same number gives the same look; try 1, 2, 3 … for alternatives);
    style / mood: pin one (see options); seed: another cut layout with the same look. Empty = unchanged."""
    return await call(lambda jz: jz.set_look(theme=theme or None, variation=variation, style=style or None, mood=mood or None, seed=seed))


@mcp.tool()
async def set_media_options(auto: bool | None = None, order: str = '', hold: str = '', fit: str = '', dim: float | None = None,
                            lyric_bg: bool | None = None, shuffle: int | None = None, extend: str = '', rate: float | None = None,
                            beats: int | None = None) -> dict:
    """How pictures and clips fill the song. auto: one per lyric line in turn; order: sequential | random; shuffle: a number for
    another random order; hold: kenburns (slow zoom) | still; fit: cover | contain; dim: 0–0.9 dark veil over the pictures so the
    lyrics stay readable (default 0.25); lyric_bg: also draw the lyrics' background graphic over the pictures.
    Clips shorter than their line — extend: loop | pingpong | hold (stop on the last frame) | beat (restart every `beats` beats:
    1, 2, 4, 8, 16); rate: 0.5–2. Empty = unchanged."""
    return await call(lambda jz: jz.set_media_options(auto=auto, order=order or None, hold=hold or None, fit=fit or None, dim=dim,
                                                       lyric_bg=lyric_bg, shuffle=shuffle, extend=extend or None, rate=rate, beats=beats))


@mcp.tool()
async def set_output(aspect: str = '', res: int | None = None, fps: int | None = None, quality: str = '', include_audio: bool | None = None) -> dict:
    """Video settings: aspect 16:9 | 9:16 | 4:3 | 3:4 | 1:1 | 4:5 | 21:9 (the layout is redone for the new shape);
    res 720 | 1080 | 1440 | 2160 (short side); fps 24 | 30 | 60; quality standard | high | max. Empty = unchanged."""
    return await call(lambda jz: jz.set_output(aspect=aspect or None, res=res, fps=fps, quality=quality or None, include_audio=include_audio))


@mcp.tool()
async def get_plan() -> dict:
    """The project: title, look, song, output size and length, every lyric line (1-based) with start / end seconds, its text,
    the picture shown and whether it was chosen by hand, the pictures and clips, and the picture settings."""
    return await call(lambda jz: jz.get_plan())


@mcp.tool()
async def preview(times: list[float] | None = None, count: int = 4, width: int = 640) -> list:
    """Frames of the video as images, to check the look: are the lyrics readable over the pictures, does the style fit the song?
    times: seconds (max 12); without times, `count` frames spread over the lyric lines. width: pixels (max 1280)."""
    async def f(jz):
        shots = await jz.preview(times=(times or None) and times[:12], count=max(1, min(12, count)), width=max(160, min(1280, width)))
        out = []
        for t, text, png in shots:
            out.append(f'{t:.2f}s — {text or "（歌詞なし）"}'); out.append(Image(data=png, format='png'))
        return out
    return await call(f)


@mcp.tool()
async def export_mp4(path: str = 'jizura.mp4', res: int | None = None, start: float | None = None, end: float | None = None,
                     audio: bool = True, quality: str = '', ctx: Context = None) -> dict:
    """Write the MP4 into the working folder (a new name if it exists). start / end: only that part (seconds). Takes a while:
    roughly as long as the song or several times longer, depending on the computer and resolution. Returns size, codec, audio."""
    async def f(jz):
        p = fresh(path, '.mp4')
        task = asyncio.ensure_future(jz.export_mp4(p, res=res, t0=start, t1=end, audio=audio, quality=quality or None))
        while not task.done():
            await asyncio.wait([task], timeout=5)
            if ctx is not None and jz.progress and not task.done():
                try: await ctx.report_progress(round(jz.progress[0] * 100, 1), 100, jz.progress[1])
                except Exception: pass
        r = task.result(); r['path'] = rel(p); return r
    return await call(f)


if __name__ == '__main__':
    log(f'jizura MCP: workdir {WORK}')
    mcp.run('stdio')        # the browser goes when this process ends (Playwright closes it with its pipe)
