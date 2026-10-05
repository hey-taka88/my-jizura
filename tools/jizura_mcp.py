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
from jizura_runlog import RunLog
import functools

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
ap.add_argument('--no-record', action='store_true', help='do not keep the run log (jizura_runs/ in the working folder; also JIZURA_RECORD=0)')
ARGS = ap.parse_args()
WORK = os.path.realpath(os.path.expanduser(ARGS.workdir))
if not os.path.isdir(WORK): sys.exit(f'jizura: workdir not found: {WORK}')

mcp = Server('jizura', instructions=(
    'JIZURA makes lyric motion videos (文字PV) for a song: animated lyrics over pictures and video clips. '
    f'All paths are relative to the working folder {WORK}. Typical flow: list_files → new_project → set_lyrics (LRC / SRT / VTT / '
    'Whisper or Suno JSON give timing) → load_song → add_media → set_look → preview (look at the frames: are the lyrics readable? '
    'raise dim or change the look if not) → export_mp4. get_plan shows every line with its time and picture. '
    'save_project / export_mp4 return the path actually written (`saved`): use that one afterwards. '
    'A background clip for the whole song: add_timed_media (it runs on the song clock, not per line). '
    'To fix how a line looks (layout, size, position, colour, motion, decorations, when its second phrase starts): set_line_style; '
    'get_line shows what a line became. After open_project, relink_media brings back the pictures listed in `missing`. '
    'Every call is recorded in jizura_runs/ (制作の記録): use log_note for what you see, decide or work around (with the song time / '
    'line), start_run for a new song, and run_info for where the record is.'))

_jz = None
_lock = asyncio.Lock()
# 制作の記録: every call, the files read and written, the project states behind previews and exports (tools/jizura_runlog.py)
RUN = RunLog(WORK, ARGS.app, enabled=not ARGS.no_record and os.environ.get('JIZURA_RECORD', '1') != '0',
             log=lambda m: print(m, file=sys.stderr, flush=True))


def log(msg): print(msg, file=sys.stderr, flush=True)


async def app():
    global _jz
    if _jz is None:
        jz = Jizura(app=ARGS.app, browser=ARGS.browser, log=log)
        await jz.start(); _jz = jz
        try: RUN.set_browser(await jz.status())
        except Exception: pass
    return _jz


def inside(rel, must_exist=True, record=True):
    """a path in the working folder (relative, or absolute but inside it)"""
    if not isinstance(rel, str) or not rel.strip() or '\0' in rel: raise ToolError('パスを指定してください')
    p = os.path.realpath(os.path.join(WORK, os.path.expanduser(rel)))
    if p != WORK and not p.startswith(WORK + os.sep): raise ToolError(f'作業フォルダの外は使えません: {rel}')
    if must_exist and not os.path.exists(p): raise ToolError(f'見つかりません: {rel}')
    if must_exist and record: RUN.input(p, MEDIA_EXT)             # what this call reads (content hash)
    return p


_written = set()       # files this server wrote in this session (only those may be replaced)


def target(rel_path, ext, replace=False):
    """where an output goes → (path, info). A new name: as asked. A name that exists: with replace, the same file again when
    this server wrote it in this session (a file that was there before is never replaced); otherwise the next free name
    (name-2, name-3 …). info = {requested, saved, collision: new | renamed | replaced}: use `saved` in the next calls."""
    if not rel_path.lower().endswith(ext): rel_path += ext
    req = inside(rel_path, must_exist=False)
    os.makedirs(os.path.dirname(req), exist_ok=True)
    if not os.path.exists(req): p, how = req, 'new'
    elif replace and req in _written: p, how = req, 'replaced'
    elif replace: raise ToolError(f'作業フォルダに前からあるファイルは置き換えません（置き換えられるのは、このサーバーが今回書いたファイルだけ）: {rel_path}')
    else:
        base, k, p = req[:-len(ext)], 2, req
        while os.path.exists(p): p = f'{base}-{k}{ext}'; k += 1
        how = 'renamed'
    return p, {'requested': os.path.relpath(req, WORK), 'saved': os.path.relpath(p, WORK), 'collision': how}


rel = lambda p: os.path.relpath(p, WORK)


def recorded(fn):
    """every tool call goes into the run log: arguments, time, result, the project state it leaves, the preview images"""
    @functools.wraps(fn)
    async def w(*a, **kw):
        rec = RUN.begin(fn.__name__, {k: v for k, v in kw.items() if k != 'ctx'})
        try: r = await fn(*a, **kw)
        except BaseException as e:
            if rec: RUN.end(rec, error=e, page_errors=_jz.errors if _jz else None)
            raise
        if rec:
            images, summary = [], r
            if isinstance(r, list):                          # preview: captions and images
                summary, sec = [], 0.0
                for x in r:
                    if isinstance(x, str):
                        summary.append(x)
                        try: sec = float(x.split('s', 1)[0])
                        except ValueError: pass
                    elif getattr(x, 'data', None): images.append((sec, x.data))
            project = None
            if _jz is not None and _jz.page is not None:
                try:
                    async with _lock:
                        project = (await _jz.page.evaluate('() => JSON.stringify(J.ui.project, null, 1)'), await _jz.get_plan())
                except Exception: project = None
            RUN.end(rec, result=summary, images=images, project=project, page_errors=_jz.errors if _jz else None)
        return r
    return w


async def call(fn):
    async with _lock:
        try: return await fn(await app())
        except JizuraError as e: raise ToolError(str(e)) from None


# ---------------------------------------------------------------- tools
@mcp.tool()
@recorded
async def log_note(text: str, kind: str = 'note', time: float | None = None, line: int | None = None) -> dict:
    """Write into this production's record (制作の記録): what you saw, decided or ran into, so it can be fixed later. kind: note |
    issue (something wrong or missing in the app / tools) | decision (a choice for this song) | workaround (done by hand or another tool
    because the tools could not) | phase (where you are, e.g. 'export'). time: seconds in the song it is about; line: lyric line (1 = first).
    Be concrete: what you asked for, what you got, which frame (preview it), what you did instead."""
    if kind not in ('note', 'issue', 'decision', 'workaround', 'phase'): raise ToolError(f'kind は note / issue / decision / workaround / phase: {kind}')
    n = RUN.note(text, kind=kind, time_s=time, line=line)
    if n is None: raise ToolError('記録はオフです（--no-record / JIZURA_RECORD=0）')
    return n


@mcp.tool()
@recorded
async def run_info() -> dict:
    """Where this production's record is (jizura_runs/… in the working folder: run.json, calls.jsonl, previews/, projects/) and its
    summary so far: calls, time in tools vs. between tools, per phase, files written, notes and errors. Mention the folder when you report."""
    if not RUN.enabled: return {'recording': False}
    s = RUN.summary()
    return {'dir': RUN.rel(RUN.dir), 'timing': s, 'outputs': [o['path'] for o in RUN.m['outputs']], 'notes': len(RUN.m['notes']),
            'errors': len(RUN.m['errors']), 'projects': len(RUN.m['projects'])}


@mcp.tool()
@recorded
async def start_run(title: str = '') -> dict:
    """Start a new record (a new jizura_runs/ folder), e.g. for the next song; the record so far stays as it is."""
    if not RUN.enabled: return {'recording': False}
    RUN.start(title)
    if _jz is not None:
        try: RUN.set_browser(await _jz.status())
        except Exception: pass
    return {'dir': RUN.rel(RUN.dir)}


@mcp.tool()
@recorded
async def list_files(folder: str = '.') -> dict:
    """Files in the working folder (or a sub-folder) that the tools can use, grouped: lyrics (lrc/srt/vtt/json/txt),
    songs, media (pictures and video clips), projects (.jizura.json), sub-folders, and records (jizura_runs: the production records)."""
    d = inside(folder, record=False)
    if not os.path.isdir(d): raise ToolError(f'フォルダではありません: {folder}')
    out = {'folder': rel(d), 'lyrics': [], 'songs': [], 'media': [], 'projects': [], 'folders': []}
    for n in sorted(os.listdir(d)):
        if n.startswith('.'): continue
        p = os.path.join(d, n); r = rel(p); low = n.lower()
        if os.path.isdir(p):
            if n == 'jizura_runs' and d == WORK: out['records'] = r            # 制作の記録 (not a folder of material)
            else: out['folders'].append(r)
        elif low.endswith('.jizura.json'): out['projects'].append(r)
        elif MEDIA_EXT.search(n): out['media'].append(r)
        elif low.endswith(SONG_EXT): out['songs'].append(r)
        elif low.endswith(LYRIC_EXT): out['lyrics'].append(r)
    return out


@mcp.tool()
@recorded
async def status() -> dict:
    """The browser in use and whether it can read / write H.264 MP4 (most AI video clips are H.264: they need Google Chrome or Edge;
    WebM clips work everywhere), the app version and the working folder."""
    async def f(jz): s = await jz.status(); s['workdir'] = WORK; return s
    return await call(f)


@mcp.tool()
@recorded
async def options() -> dict:
    """The values the other tools accept: themes, styles, moods (with their Japanese names), aspects, resolutions, fps, quality,
    and the picture / clip settings."""
    return await call(lambda jz: jz.options())


@mcp.tool()
@recorded
async def new_project(title: str = '', artist: str = '', aspect: str = '16:9', lyrics: str = '') -> dict:
    """Start a new, empty project (a song already loaded stays). lyrics: optional text, one phrase per line ([mm:ss.xx] tags allowed).
    Returns the plan (see get_plan)."""
    return await call(lambda jz: jz.new_project(title=title, artist=artist, aspect=aspect, lyrics=lyrics or None))


@mcp.tool()
@recorded
async def open_project(path: str) -> dict:
    """Open a saved .jizura.json from the working folder (use the `saved` path that save_project returned). Pictures and clips are
    not inside the file: the plan's `missing` lists the ones to add again with add_media (they are recognised by content, so every
    line and timed placement gets its picture back). Returns the plan."""
    p = inside(path)
    return await call(lambda jz: jz.open_project(p))


@mcp.tool()
@recorded
async def save_project(path: str = 'project.jizura.json', replace: bool = False) -> dict:
    """Save the project as .jizura.json in the working folder (it opens in the app in a browser too). When the name exists:
    replace=true writes over it if this server saved it earlier in this session (never over a file that was there before);
    otherwise a new name is chosen. Returns {requested, saved, collision: new | renamed | replaced} — open / use `saved`."""
    async def f(jz):
        p, info = target(path[:-12] if path.lower().endswith('.jizura.json') else path, '.jizura.json', replace)
        await jz.save_project(p); _written.add(p); RUN.output(p, 'save_project', info); return info
    return await call(f)


@mcp.tool()
@recorded
async def set_lyrics(path: str = '', text: str = '') -> dict:
    """Replace the lyrics, from a file in the working folder (LRC / SRT / VTT / Whisper JSON / Suno aligned-words JSON give each line
    its time; a .txt is one phrase per line) or from text. Per-line settings and pictures are reset. Returns line counts."""
    p = inside(path) if path else None
    if not p and not text: raise ToolError('path か text を指定してください')
    return await call(lambda jz: jz.set_lyrics(path=p) if p else jz.set_lyrics(text=text))


@mcp.tool()
@recorded
async def load_song(path: str) -> dict:
    """Load the song (mp3 / wav / m4a …, or the sound of a video file) from the working folder. Tempo and length are analysed;
    lines without times are spread over the song."""
    p = inside(path)
    return await call(lambda jz: jz.load_song(p))


@mcp.tool()
@recorded
async def add_media(paths: list[str]) -> dict:
    """Add pictures and video clips (files or folders in the working folder; a folder adds its files in name order).
    By default they change line by line, in the order added. Returns what was added and what could not be read
    (reason 'video' = this browser cannot play that clip: H.265/HEVC, or H.264 without Chrome)."""
    ps = [inside(x) for x in paths]
    return await call(lambda jz: jz.add_media(ps))


@mcp.tool()
@recorded
async def remove_media(media: str) -> dict:
    """Remove a picture / clip (by name, or its number in get_plan's media list)."""
    async def f(jz): return {'media': await jz.remove_media(media)}
    return await call(f)


@mcp.tool()
@recorded
async def add_timed_media(media: str, start: float = 0, end: float | None = None, clip_start: float | None = None, fit: str = '',
                          track: str = 'back', x: float | None = None, y: float | None = None, size: float | None = None,
                          rot: float | None = None, opacity: float | None = None, enter: str = '', exit: str = '', hold: str = '',
                          key: str = '', key_tol: float | None = None, key_soft: float | None = None, key_spill: float | None = None) -> dict:
    """Place a picture or clip at a time of the song (seconds) instead of per lyric line — e.g. one background clip under the whole
    song: start=0 and no end (end = the next timed placement, or the end of the song). It covers the automatic per-line pictures in
    that time; a picture chosen for a line (set_line_media) still shows over it, and a clip keeps running on the song's clock (it never
    jumps back to its start at a lyric line, and any seek shows the same frame). media: a name or number, or 'none' (no picture then).
    clip_start: where in the clip to begin. fit: cover | contain.
    track 'front' puts it OVER the lyrics (前景: a logo, a character, a PNG with transparency, a frame): front pictures may overlap
    (each its own layer, the later one on top), one without an end stays until the end of the song, each fades in and out by itself.
    x / y: its centre from the frame centre (-0.5 … 0.5 of the frame = the edges; y < 0 = up), size: its width as a fraction of the
    frame width (0.02 … 4), rot: degrees — any of these places it by hand instead of filling the frame (also on the back track).
    opacity 0 … 1. enter / exit (options()['mediaEnter']) and hold (options()['mediaHold']): its own motion.
    key: クロマキー — take a colour out of it, e.g. a green-screen clip of a singer over the lyrics: 'auto' (the colour round the
    picture's edge) or '#rrggbb'. key_tol (0 … 0.6, default 0.1): how close to that colour counts as it — raise it when the screen
    shows through, lower it when the subject gets holes; key_soft (0 … 0.6, 0.08): the soft edge; key_spill (0 … 1, 0.6): how much
    green fringe is taken out of the subject. Look at it with preview (get_plan's `timed` shows the colour 'auto' found).
    Check it with preview. Returns its id and every timed placement (with its track)."""
    return await call(lambda jz: jz.add_timed_media(media, start=start, end=end, clip_start=clip_start, fit=fit or None, track=track,
                                                    x=x, y=y, size=size, rot=rot, opacity=opacity, enter=enter or None,
                                                    exit=exit or None, hold=hold or None, key=key or None, key_tol=key_tol,
                                                    key_soft=key_soft, key_spill=key_spill))


@mcp.tool()
@recorded
async def remove_timed_media(id: str = 'all') -> dict:
    """Remove a picture placed at a time, on either track (its id from add_timed_media / get_plan's `timed`), or 'all' of them."""
    return await call(lambda jz: jz.remove_timed_media(id))


@mcp.tool()
@recorded
async def get_line(line: int) -> dict:
    """One lyric line (1 = first, as in get_plan): its text and time, its own settings (style = layout / motion / decorations / cut times
    set by hand, place = position / size / colour) and every cut it became, with the parts actually used (layout, enter, exit, hold,
    cam, bg, decor, treat, trans, text colour). words: its word times (t, the text from there, p = confidence, used = whether the
    time is used for cut starts); confidence: the lowest one; cutTimes: how the cut starts were decided —
    'by hand' (cut_times) > 'locked' (kept by a lock) > 'words' (word times) > 'auto' (by text length)."""
    return await call(lambda jz: jz.get_line(int(line)))


@mcp.tool()
@recorded
async def set_line_style(line: int, cut: int | None = None, layout: str = '', enter: str = '', exit: str = '', hold: str = '', cam: str = '',
                         trans: str = '', bg: str = '', decor: list[str] | str | None = None, treat: str = '', cuts: int | str | None = None,
                         cut_times: list[float] | str | None = None, single: bool | None = None, x: float | str | None = None,
                         y: float | str | None = None, size: float | str | None = None, color: str = '', lock: bool | None = None,
                         reset: bool = False) -> dict:
    """Fix how one lyric line looks (or only its cut `cut`, 1 = first) — independent of set_look's random picks, kept in the project.
    Parts by key from options()['lyric'] (layout e.g. center / huge / vcols / lowerThird …; enter / exit / hold motions; cam; treat; bg
    or 'none'; trans or 'none'); 'auto' returns one part to automatic (also for decor, cuts, cut_times, x, y, size, color).
    decor: list of decoration keys ([] or 'none' = none; one at most with `cut`). With `cut`, bg and decor apply to that cut. cuts: split the line
    into that many cuts; cut_times: when cuts 2, 3 … start, in seconds from the line start (e.g. the second phrase); single: one cut.
    x / y: move the lyric (-0.5 … 0.5 of the frame; y < 0 = up), size: 0.2 … 3 (1 = as laid out), color: '#rrggbb' text colour.
    lock: keep exactly this look (and its cut times) when other lines are changed or set_look runs. On a locked line x / y / size /
    color keep its cuts and cut times; the other parts lay the line out again and re-lock it. reset: clear everything set for the line.
    Empty = unchanged. Check the result with preview at a time inside the line. Returns the line as get_line."""
    return await call(lambda jz: jz.set_line_style(int(line), cut=cut, layout=layout or None, enter=enter or None, exit=exit or None,
                                                    hold=hold or None, cam=cam or None, trans=trans or None, bg=bg or None, decor=decor,
                                                    treat=treat or None, cuts=cuts, cut_times=cut_times, single=single, x=x, y=y, size=size,
                                                    color=color or None, lock=lock, reset=reset))


@mcp.tool()
@recorded
async def set_text_options(interlude_title: bool | None = None) -> dict:
    """interlude_title: show the song title / artist on long interludes (default true). The title stays in the project (and in
    get_plan) either way — this only decides whether the wordless interlude shows it."""
    return await call(lambda jz: jz.set_text_options(interlude_title=interlude_title))


@mcp.tool()
@recorded
async def get_motion_plan(start: float = 0, end: float | None = None) -> dict:
    """The cuts the app actually made in [start, end) seconds of the song (end empty = to the end), read-only: for each cut its
    line (1 = first, as in get_plan / get_line) and cut number in the line, time, text, recap (the whole line again), layout,
    enter / exit / hold, treat, cam, trans, bg, decor, params, colour scheme, inDur / outDur, seed and whether the line is locked;
    plus `inventory` (which layouts / motions / cameras the range uses). Use it to compare candidates (set_look variation / seed)
    and to check that a locked range did not change. Nothing in the project changes."""
    return await call(lambda jz: jz.get_motion_plan(start, end))


@mcp.tool()
@recorded
async def lock_motion_palette(start: float, end: float, lock: bool = True, scheme: int | None = None, bg_color: str = '',
                              text_color: str = '', sub_color: str = '', accent_color: str = '', ghost_a: str = '', ghost_b: str = '',
                              chroma: float | None = None) -> dict:
    """Keep an adopted range: every lyric line that plays in [start, end) seconds is locked (固定) with exactly the cuts, motion,
    decorations and cut times it shows now — later set_look / set_line_style on other lines does not change it (lock=false lets the
    range go again; cut times set by hand stay). Lines with word times keep the word-timed cut starts they show.
    scheme: pin the range's cuts to this colour scheme of the style (0 = main).
    Colours ('#rrggbb') and chroma (0-1) are the PROJECT's, for every line, as in the 配色 panel: bg_color / text_color / sub_color
    replace scheme 0 (given one, scheme defaults to 0 so the range shows them), accent_color / ghost_a / ghost_b apply to every scheme.
    Empty colours = unchanged. For one line's own text colour use set_line_style(color=…).
    Returns the lines (1 = first) and what changed project-wide (`global`)."""
    return await call(lambda jz: jz.lock_motion_palette(start, end, lock=lock, scheme=scheme, bg_color=bg_color or None,
                                                        text_color=text_color or None, sub_color=sub_color or None,
                                                        accent_color=accent_color or None, ghost_a=ghost_a or None, ghost_b=ghost_b or None,
                                                        chroma=chroma))


@mcp.tool()
@recorded
async def set_range_style(start: float, end: float, tone: str = '', layout: str = '', enter: str = '', exit: str = '', hold: str = '',
                          cam: str = '', size: float | str | None = None) -> dict:
    """How strongly the lyrics move in a part of the song: every lyric line that plays in [start, end) seconds gets
    tone 'quiet' — one cut, big and centred, soft blur in and out, a slow breath (a rest, e.g. a pre-chorus or bridge);
    'calm' — JIZURA's own layout and cuts, but soft in and out and a slow drift; both without decorations, camera hits and screen
    effects (shake / glitch / flash …); or 'normal' — back to automatic (also clears these parts set per line in the range).
    layout / enter / exit / hold / cam (keys from options()['lyric'], 'auto' = automatic) set one part for the whole range on top;
    size: 0.2 … 3 ('auto' = as laid out). Locked lines in the range are laid out again and locked again. Busy parts (a chorus) need
    nothing: leave them to JIZURA. Check with get_motion_plan / preview; one line can still be changed with set_line_style.
    Other lines may change too (JIZURA avoids repeating the parts used just before): lock_motion_palette the parts already adopted
    first. Returns the lines (1 = first) and othersChanged (lines outside the range whose cuts changed)."""
    return await call(lambda jz: jz.set_range_style(start, end, tone=tone or None, layout=layout or None, enter=enter or None,
                                                    exit=exit or None, hold=hold or None, cam=cam or None, size=size))


@mcp.tool()
@recorded
async def set_word_times(path: str) -> dict:
    """Add word times to the current lyrics without changing them (the lines, their settings and pictures stay): a file in the
    working folder with words and their times — Suno aligned_words JSON, WhisperX / Whisper words, enhanced LRC (<mm:ss.xx> tags) or
    JSON lines that carry their own words ({"lines": [{"text", "start", "words": [{"word", "start", "probability"}]}]}, e.g. a
    timing master). Each lyric line takes the entry with the same text that starts nearest to it; its cuts then change when their
    first word is sung (cut times set by hand or kept by a lock win). Words below confidence 0.1 or outside their line are not used.
    Returns wordTimed (lines with word times), without (lines with none), unmatched (entries no line took: text that differs from
    the lyrics) and weak (lines with unused words). Correct a time in the file and call again to apply it."""
    p = inside(path)
    return await call(lambda jz: jz.set_word_times(path=p))


@mcp.tool()
@recorded
async def relink_media(paths: list[str]) -> dict:
    """Bring back the pictures / clips an opened project names but has not loaded (get_plan's `missing`): give files or folders in
    the working folder; they are matched by content (a renamed file is found, a different file with the same name is not).
    Returns relinked names, the files used, and what is still missing."""
    ps = [inside(x) for x in paths]
    return await call(lambda jz: jz.relink_media(ps))


@mcp.tool()
@recorded
async def set_line_media(line: int, media: str) -> dict:
    """Choose the picture behind lyric line `line` (1 = first line, as in get_plan): a media name or number, 'none' (no picture:
    the lyrics' own background shows), or 'auto' (back to the automatic order)."""
    async def f(jz):
        await jz.set_line_media(int(line), media)
        p = await jz.get_plan(); return {'line': p['lines'][int(line) - 1]}
    return await call(f)


@mcp.tool()
@recorded
async def set_look(theme: str = '', variation: int | None = None, style: str = '', mood: str = '', seed: int | None = None) -> dict:
    """Change how the lyrics look. theme: おまかせ within a direction (lyricpv, kinetic, wa, horror, pop, ballad — see options);
    variation: おまかせ again with this number (the same number gives the same look; try 1, 2, 3 … for alternatives);
    style / mood: pin one (see options); seed: another cut layout with the same look. Empty = unchanged."""
    return await call(lambda jz: jz.set_look(theme=theme or None, variation=variation, style=style or None, mood=mood or None, seed=seed))


@mcp.tool()
@recorded
async def set_media_options(auto: bool | None = None, order: str = '', hold: str = '', fit: str = '', dim: float | None = None,
                            lyric_bg: bool | None = None, shuffle: int | None = None, trans: str = '', enter: str = '', exit: str = '',
                            treat: str = '', scrim: str = '', scrim_amount: float | None = None, extend: str = '', rate: float | None = None,
                            beats: int | None = None) -> dict:
    """How pictures and clips fill the song. auto: one per lyric line in turn; order: sequential | random; shuffle: a number for
    another random order; hold (motion): kenburns (slow zoom) | pan | push | drift | beatPulse | still; fit: cover | contain;
    dim: 0–0.9 dark veil over the pictures (default 0.25); lyric_bg: also draw the lyrics' background graphic over the pictures.
    trans (from one picture to the next): fade | cut | mix (a different transition each time) | a transition key (see options);
    enter / exit (where no picture touches): fade | slide | zoom | wipe | cut; treat: none | match (tint to the style's colours) |
    mono | sepia | duotone | blur; scrim (a soft plate behind the lyrics): auto (only where the picture makes them hard to read) |
    always | off, scrim_amount 0–0.9. Clips shorter than their line — extend: loop | pingpong | hold | beat (restart every `beats`
    beats: 1, 2, 4, 8, 16); rate: 0.5–2. Empty = unchanged. If the lyrics are hard to read in preview: raise dim or set scrim."""
    return await call(lambda jz: jz.set_media_options(auto=auto, order=order or None, hold=hold or None, fit=fit or None, dim=dim,
                                                       lyric_bg=lyric_bg, shuffle=shuffle, trans=trans or None, enter=enter or None,
                                                       exit=exit or None, treat=treat or None, scrim=scrim or None, scrim_amount=scrim_amount,
                                                       extend=extend or None, rate=rate, beats=beats))


@mcp.tool()
@recorded
async def media_omakase() -> dict:
    """メディアのおまかせ: pick the pictures' motion, transitions, in / out, treatment, darkness and order together at random
    (a new idea each call; preview to see it). Returns the settings chosen."""
    return await call(lambda jz: jz.media_omakase())


@mcp.tool()
@recorded
async def set_output(aspect: str = '', res: int | None = None, fps: int | None = None, quality: str = '', include_audio: bool | None = None) -> dict:
    """Video settings: aspect 16:9 | 9:16 | 4:3 | 3:4 | 1:1 | 4:5 | 21:9 (the layout is redone for the new shape);
    res 720 | 1080 | 1440 | 2160 (short side); fps 24 | 30 | 60; quality standard | high | max. Empty = unchanged."""
    return await call(lambda jz: jz.set_output(aspect=aspect or None, res=res, fps=fps, quality=quality or None, include_audio=include_audio))


@mcp.tool()
@recorded
async def get_plan() -> dict:
    """The project: title, look, song, output size and length, every lyric line (1-based) with start / end seconds, its text,
    the picture shown and whether it was chosen by hand, the pictures and clips, and the picture settings."""
    return await call(lambda jz: jz.get_plan())


@mcp.tool()
@recorded
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
@recorded
async def export_mp4(path: str = 'jizura.mp4', res: int | None = None, start: float | None = None, end: float | None = None,
                     audio: bool = True, quality: str = '', replace: bool = False, ctx: Context = None) -> dict:
    """Write the MP4 into the working folder. A name that exists: replace=true writes over it if this server wrote it earlier in this
    session, otherwise a new name is chosen (see `saved`). start / end: only that part (seconds). Takes a while: roughly as long as
    the song or several times longer, depending on the computer and resolution. Returns size, codec, audio, and the lengths:
    duration (planned), frames / videoDuration (whole frames written), audioDuration."""
    async def f(jz):
        p, info = target(path, '.mp4', replace)
        task = asyncio.ensure_future(jz.export_mp4(p, res=res, t0=start, t1=end, audio=audio, quality=quality or None))
        while not task.done():
            await asyncio.wait([task], timeout=5)
            if ctx is not None and jz.progress and not task.done():
                try: await ctx.report_progress(round(jz.progress[0] * 100, 1), 100, jz.progress[1])
                except Exception: pass
        r = task.result(); _written.add(p); r.update(info); r['path'] = info['saved']
        RUN.output(p, 'export_mp4', info, extra={k: r.get(k) for k in ('codec', 'width', 'height', 'fps', 'frames', 'videoDuration', 'audioDuration', 'audio', 'duration')})
        return r
    return await call(f)


if __name__ == '__main__':
    log(f'jizura MCP: workdir {WORK}')
    mcp.run('stdio')        # the browser goes when this process ends (Playwright closes it with its pipe)
