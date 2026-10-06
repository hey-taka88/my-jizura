"""my-jizura: 制作の記録 (run log) for the MCP server — what happened in one production, kept in the working folder.

  <workdir>/jizura_runs/<YYYYmmdd-HHMMSS>_<title>/
    report.md     the same in Japanese for a person (notes with the nearest preview, outputs, time, errors)
    run.json      the summary, rewritten after every call: environment (app version + git commit + sha256 of the page,
                  browser and its H.264 support, python / MCP versions), time (wall / in tools / between tools — the client's own
                  thinking and other work — per tool and per phase), files read and written (path, size, sha256), the project
                  states that previews and exports were made from (with their media), notes, errors, page errors
    calls.jsonl   one line per tool call: arguments, a summary of the result, time, the project state after it
    previews/     every frame preview returned, as PNG (<call>_<n>_<seconds>s.png)
    projects/     the project JSON a preview or an export was made from (<hash>.jizura.json; once per state)

Nothing here changes what the tools do; a failure to record is reported on stderr and never fails a tool.
"""
import datetime, hashlib, json, os, platform, re, subprocess, sys, time

PHASES = {   # what a tool is for (the summary adds time and calls up per phase)
    'setup': {'new_project', 'open_project', 'set_lyrics', 'load_song', 'add_media', 'remove_media', 'relink_media', 'set_output'},
    'edit': {'add_timed_media', 'remove_timed_media', 'set_line_style', 'set_text_options', 'set_line_media', 'set_look',
             'set_media_options', 'media_omakase', 'lock_motion_palette', 'set_word_times', 'set_range_style'},
    'check': {'get_plan', 'get_line', 'get_motion_plan', 'preview', 'status', 'options', 'list_files', 'run_info'},
    'output': {'save_project', 'save_bundle', 'export_mp4'},
    'record': {'log_note', 'start_run'},
}
PHASE_OF = {t: p for p, ts in PHASES.items() for t in ts}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds')


def _short(v, depth=0):
    """a result / argument made small enough for a log line (long text and lists are cut, images are left out)"""
    if depth > 6: return '…'
    if isinstance(v, str): return v if len(v) <= 2000 else v[:2000] + f'…(+{len(v) - 2000})'
    if isinstance(v, (int, float, bool)) or v is None: return v
    if isinstance(v, dict): return {str(k): _short(x, depth + 1) for k, x in list(v.items())[:200]}
    if isinstance(v, (list, tuple)):
        out = [_short(x, depth + 1) for x in list(v)[:200]]
        if len(v) > 200: out.append(f'…(+{len(v) - 200})')
        return out
    if hasattr(v, 'data') and isinstance(getattr(v, 'data'), (bytes, bytearray)): return {'image': len(v.data)}
    return str(v)[:200]


class RunLog:
    def __init__(self, workdir, app_path, enabled=True, log=None):
        self.work = workdir
        self.app_path = app_path
        self.enabled = enabled
        self.log = log or (lambda m: print(m, file=sys.stderr))
        self.dir = None
        self._hash_cache = {}
        self.env = None

    # ------------------------------------------------------------ the run
    def start(self, title=''):
        """a new run (a new folder); the next call starts one by itself when none is open"""
        if not self.enabled: return None
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        slug = re.sub(r'[^\w\-]+', '_', str(title or 'run')).strip('_')[:40] or 'run'
        base = os.path.join(self.work, 'jizura_runs', f'{stamp}_{slug}')
        d, k = base, 2
        while os.path.exists(d): d = f'{base}-{k}'; k += 1        # never into a folder that is there already
        os.makedirs(os.path.join(d, 'previews')); os.makedirs(os.path.join(d, 'projects'))
        self.dir = d
        self.t0 = time.time(); self.last_end = None; self.seq = 0
        self.m = {'run': {'title': str(title or ''), 'dir': self.rel(d), 'started': _now(), 'updated': _now()},
                  'env': self._env(), 'timing': {}, 'inputs': [], 'outputs': [], 'projects': [], 'notes': [], 'errors': [], 'pageErrors': []}
        self._calls = []
        self._previews = []                                       # (call, song seconds, path)
        self._inputs = {}
        self._project_files = set()
        self._write()
        self.log(f'jizura: 制作の記録 → {self.rel(d)}')
        return d

    def rel(self, p):
        return os.path.relpath(p, self.work)

    def _env(self):
        if self.env is None:
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            git = {}
            try:
                git['commit'] = subprocess.run(['git', '-C', root, 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=5).stdout.strip() or None
                git['dirty'] = bool(subprocess.run(['git', '-C', root, 'status', '--porcelain', '--', 'src', 'tools', 'index.html'], capture_output=True, text=True, timeout=5).stdout.strip())
            except Exception: pass
            try:
                import importlib.metadata as md; mcpv = md.version('mcp')
            except Exception: mcpv = None
            try: ver = open(os.path.join(root, 'VERSION'), encoding='utf-8').read().strip()
            except OSError: ver = None
            page = self.app_path if self.app_path and not re.match(r'https?://', self.app_path) else os.path.join(root, 'index.html')
            self.env = {'app': {'version': ver, 'git': git, 'page': self.app_path or 'index.html', 'pageSha256': self._sha(page) if os.path.isfile(page) else None},
                        'python': platform.python_version(), 'platform': platform.platform(), 'mcp': mcpv, 'browser': None}
        return self.env

    def set_browser(self, status):
        """the browser in use (once the page is open)"""
        if not self.enabled: return
        self._env()['browser'] = {k: status.get(k) for k in ('browser', 'userAgent', 'h264Encode', 'h264Decode', 'vp9Encode', 'vp9Decode', 'webcodecs')}
        if self.dir: self.m['env'] = self.env; self._write()

    # ------------------------------------------------------------ files
    def _sha(self, path):
        try:
            st = os.stat(path); key = (path, st.st_size, st.st_mtime_ns)
            if key not in self._hash_cache:
                h = hashlib.sha256()
                with open(path, 'rb') as f:
                    for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
                self._hash_cache[key] = h.hexdigest()
            return self._hash_cache[key]
        except OSError: return None

    def _info(self, path):
        st = os.stat(path)
        return {'path': self.rel(path), 'size': st.st_size, 'sha256': self._sha(path),
                'mtime': datetime.datetime.fromtimestamp(st.st_mtime, datetime.timezone.utc).isoformat(timespec='seconds')}

    def input(self, path, media_ext=None):
        """a file (or a folder of media files) a tool reads; its content hash, once per version of the file"""
        if not self.enabled or not self.dir: return
        try:
            files = [os.path.join(path, n) for n in sorted(os.listdir(path)) if media_ext and media_ext.search(n) and os.path.isfile(os.path.join(path, n))] if os.path.isdir(path) else [path]
            for f in files:
                info = self._info(f)
                key = (info['path'], info['sha256'])
                if key in self._inputs: continue
                info['firstCall'] = self.seq
                self._inputs[key] = info; self.m['inputs'].append(info)
        except Exception as e: self.log(f'jizura: 記録できませんでした（入力）: {e}')

    def output(self, path, tool, info=None, extra=None):
        """a file a tool wrote (with how its name was chosen, and what it says about itself)"""
        if not self.enabled or not self.dir: return
        try:
            o = self._info(path); o.update(call=self.seq, tool=tool)
            if info: o.update({k: info[k] for k in ('requested', 'collision') if k in info})
            if extra: o['facts'] = _short(extra)
            self.m['outputs'].append(o)
        except Exception as e: self.log(f'jizura: 記録できませんでした（出力）: {e}')

    # ------------------------------------------------------------ calls
    def begin(self, tool, args):
        if not self.enabled: return None
        if not self.dir: self.start()
        self.seq += 1
        now = time.time()
        return {'call': self.seq, 'tool': tool, 'phase': PHASE_OF.get(tool, 'other'), 'args': _short(args), 'started': _now(),
                'gapMs': round((now - self.last_end) * 1000) if self.last_end else round((now - self.t0) * 1000), '_t': now}

    def end(self, rec, result=None, error=None, project=None, images=None, page_errors=None):
        """the call is over: its time, a summary of its result, the project state it left (project = (json text, plan summary))"""
        if not rec: return
        try:
            t = time.time(); rec['ms'] = round((t - rec.pop('_t')) * 1000); self.last_end = t
            rec['ok'] = error is None
            if error is not None: rec['error'] = str(error)[:2000]; self.m['errors'].append({'call': rec['call'], 'tool': rec['tool'], 'error': rec['error']})
            if result is not None: rec['result'] = _short(result)
            if images:
                rec['previews'] = []
                for k, (sec, png) in enumerate(images):
                    p = os.path.join(self.dir, 'previews', f'{rec["call"]:04d}_{k + 1}_{sec:07.2f}s.png')
                    with open(p, 'wb') as f: f.write(png)
                    rec['previews'].append(self.rel(p)); self._previews.append((rec['call'], sec, self.rel(p)))
            if project:
                text, plan = project
                h = hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
                prev = self.m['projects'][-1]['hash'] if self.m['projects'] else None
                rec['project'] = h; rec['projectChanged'] = h != prev
                if h != prev:
                    self.m['projects'].append({'hash': h, 'firstCall': rec['call'], 'title': plan.get('title'), 'song': plan.get('song'),
                                               'duration': plan.get('duration'), 'look': plan.get('look'),
                                               'media': [{k: a.get(k) for k in ('name', 'id', 'type', 'loaded')} for a in plan.get('media', [])],
                                               'file': None})
                # the exact project behind a preview / an export / a save is kept (once per state)
                if rec['tool'] in ('preview', 'export_mp4', 'save_project', 'save_bundle') and h not in self._project_files:
                    p = os.path.join(self.dir, 'projects', f'{h}.jizura.json')
                    with open(p, 'w', encoding='utf-8') as f: f.write(text)
                    self._project_files.add(h)
                    for P in self.m['projects']:
                        if P['hash'] == h: P['file'] = self.rel(p)
            if page_errors: self.m['pageErrors'] = list(page_errors)[-20:]
            with open(os.path.join(self.dir, 'calls.jsonl'), 'a', encoding='utf-8') as f: f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            self._calls.append({k: rec.get(k) for k in ('tool', 'phase', 'ms', 'gapMs', 'ok')})
            self._write()
        except Exception as e: self.log(f'jizura: 記録できませんでした: {e}')

    def note(self, text, kind='note', time_s=None, line=None):
        if not self.enabled: return None
        if not self.dir: self.start()
        n = {'call': self.seq, 'at': _now(), 'kind': kind, 'text': str(text)[:4000]}
        if time_s is not None: n['time'] = float(time_s)
        if line is not None: n['line'] = int(line)
        # the frame it is about: the preview nearest to its song time (within 2 s), else the last preview before it
        pv = [x for x in self._previews if time_s is not None and abs(x[1] - float(time_s)) <= 2]
        pv = min(pv, key=lambda x: (abs(x[1] - float(time_s)), -x[0])) if pv else (self._previews[-1] if self._previews else None)
        if pv: n['preview'] = pv[2]
        self.m['notes'].append(n)
        self._write()
        return n

    # ------------------------------------------------------------ summary
    def summary(self):
        if not self.enabled: return {'recording': False}
        if not self.dir: self.start()
        C = self._calls
        by = lambda key: {k: {'calls': sum(1 for c in C if c[key] == k), 'ms': sum(c['ms'] or 0 for c in C if c[key] == k),
                              'errors': sum(1 for c in C if c[key] == k and not c['ok'])} for k in sorted({c[key] for c in C})}
        tool_ms = sum(c['ms'] or 0 for c in C); gap_ms = sum(c['gapMs'] or 0 for c in C)
        return {'calls': len(C), 'wallMs': round((time.time() - self.t0) * 1000), 'toolMs': tool_ms, 'betweenToolsMs': gap_ms,
                'byPhase': by('phase'), 'byTool': by('tool')}

    def _write(self):
        if not self.dir: return
        self.m['run']['updated'] = _now()
        self.m['timing'] = self.summary()
        p = os.path.join(self.dir, 'run.json')
        with open(p + '.tmp', 'w', encoding='utf-8') as f: json.dump(self.m, f, ensure_ascii=False, indent=1)
        os.replace(p + '.tmp', p)
        p = os.path.join(self.dir, 'report.md')
        with open(p + '.tmp', 'w', encoding='utf-8') as f: f.write(self.report())
        os.replace(p + '.tmp', p)

    def report(self):
        """the record in Japanese, for a person (and for the next round of fixes): links are relative to the run folder"""
        m, t = self.m, self.m['timing']
        sec = lambda ms: f'{(ms or 0) / 1000:.1f} 秒'
        up = lambda path: os.path.relpath(os.path.join(self.work, path), self.dir)   # a path of the working folder, seen from the run folder
        env, b = m['env'], (m['env'].get('browser') or {})
        yes = lambda v: '○' if v else '×'
        L = [f"# 制作の記録 {m['run']['title']}".rstrip(), '',
             f"- 期間：{m['run']['started']} 〜 {m['run']['updated']}（UTC）",
             f"- 呼び出し {t.get('calls', 0)} 回。全体 {sec(t.get('wallMs'))} のうち、ツールの処理 {sec(t.get('toolMs'))}、ツールとツールのあいだ {sec(t.get('betweenToolsMs'))}"
             '（クライアント側の考える時間・ほかの作業）',
             f"- アプリ {env['app'].get('version')}（commit {str((env['app'].get('git') or {}).get('commit') or '?')[:10]}"
             f"{'・未コミットの変更あり' if (env['app'].get('git') or {}).get('dirty') else ''}）・ページ sha256 {str(env['app'].get('pageSha256'))[:12]}",
             f"- ブラウザ {b.get('browser') or '?'}（H.264 読み {yes(b.get('h264Decode'))}・書き {yes(b.get('h264Encode'))}）・Python {env.get('python')}・MCP {env.get('mcp')}", '']
        kinds = {'issue': '問題', 'workaround': '回避', 'decision': '判断', 'phase': '段階', 'note': 'メモ'}
        L += ['## メモ', '']
        if not m['notes']: L.append('（なし。log_note で、見たこと・困ったこと・手で直したことを残せます）')
        for n in m['notes']:
            where = '・'.join(x for x in (f"{n['time']:.2f} 秒" if 'time' in n else '', f"{n['line']} 行目" if 'line' in n else '') if x)
            L.append(f"- **{kinds.get(n['kind'], n['kind'])}**{'（' + where + '）' if where else ''}：{n['text']}"
                     + (f"  [プレビュー]({up(n['preview'])})" if n.get('preview') else '')
                     + f"  <sub>呼び出し {n['call']} のあと</sub>")
        L += ['', '## 書き出したファイル', '']
        if not m['outputs']: L.append('（なし）')
        else:
            L += ['| ファイル | ツール | サイズ | sha256 | 名前 | 中身 |', '|---|---|---:|---|---|---|']
            for o in m['outputs']:
                f = o.get('facts') or {}
                facts = '・'.join(x for x in (f"{f.get('width')}×{f.get('height')}" if f.get('width') else '', f.get('codec') or '',
                                              f"{f.get('frames')} フレーム（{f.get('videoDuration'):.2f} 秒）" if f.get('frames') else '',
                                              f"音声 {f.get('audioDuration'):.2f} 秒" if f.get('audioDuration') else ('音声なし' if f and not f.get('audio') else '')) if x)
                name = {'new': '新規', 'renamed': f"別名（{o.get('requested')}）", 'replaced': '置き換え'}.get(o.get('collision'), '')
                L.append(f"| [{o['path']}]({up(o['path'])}) | {o['tool']} | {o['size']:,} | {o['sha256'][:12]} | {name} | {facts} |")
        L += ['', '## 段階ごとの時間', '', '| 段階 | 回数 | 時間 | エラー |', '|---|---:|---:|---:|']
        names = {'setup': '準備', 'edit': '編集', 'check': '確認', 'output': '出力', 'record': '記録', 'other': 'その他'}
        for k, v in (t.get('byPhase') or {}).items(): L.append(f"| {names.get(k, k)} | {v['calls']} | {sec(v['ms'])} | {v['errors']} |")
        L += ['', '## エラー（ツールが断ったもの）', '']
        L += [f"- 呼び出し {e['call']} `{e['tool']}`：{e['error']}" for e in m['errors']] or ['（なし）']
        if m.get('pageErrors'): L += ['', '## ページのエラー', ''] + [f'- {e}' for e in m['pageErrors']]
        L += ['', '## 読んだファイル', '', '| ファイル | サイズ | sha256 |', '|---|---:|---|']
        L += [f"| {i['path']} | {i['size']:,} | {i['sha256'][:12]} |" for i in m['inputs']]
        L += ['', '## プロジェクトの状態', '', f"変わった回数 {len(m['projects'])}。プレビュー・書き出し・保存に使った状態は projects/ にあります。", '']
        for P in m['projects']:
            if not P.get('file'): continue
            media = '、'.join(a['name'] + ('' if a.get('loaded') else '（未読み込み）') for a in P.get('media') or [])
            L.append(f"- [{P['hash']}]({os.path.relpath(os.path.join(self.work, P['file']), self.dir)})（呼び出し {P['firstCall']} から）{P.get('title') or ''}・{(P.get('look') or {}).get('styleName') or ''}"
                     + (f"・素材 {media}" if media else ''))
        L += ['', '詳しくは run.json（まとめ）と calls.jsonl（呼び出しごと）。', '']
        return '\n'.join(L)
