"""Run the PR checks locally or in Linux CI. Install dev/requirements.txt + Chromium first."""
import argparse
import ast
import functools
import http.server
from pathlib import Path
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
PAGES = ['index.html'] + [f'{lang}/index.html' for lang in ('en', 'zh-hant', 'zh-hans', 'ko', 'id', 'vi')]


def run(*args, timeout=300):
    print('+', *args, flush=True)
    subprocess.run(args, cwd=ROOT, check=True, timeout=timeout)


def static_checks():
    run(sys.executable, 'build.py')
    for path in sorted(ROOT.glob('src/*.js')) + sorted(ROOT.glob('app/*.js')):
        run('node', '--check', str(path.relative_to(ROOT)))
    for page in PAGES:
        run(sys.executable, 'tools/check_page_js.py', page)
    # Pages serves committed HTML. Ignore sitemap.xml here: build.py stamps today's date.
    run('git', 'diff', '--exit-code', 'HEAD', '--', *PAGES)
    for pattern in ('*.py', 'app/*.py', 'dev/*.py', 'tools/*.py'):
        for path in sorted(ROOT.glob(pattern)):
            ast.parse(path.read_text(encoding='utf-8'), filename=str(path.relative_to(ROOT)))
    print('Python syntax OK', flush=True)


def browser_checks():
    for script, args in (
        ('lyrics_import_e2e.py', []),
        ('text_style_e2e.py', ['--browser', 'chromium']),
        ('media_e2e.py', ['--require-export']),
        ('video_e2e.py', []),
        ('front_e2e.py', ['--browser', 'chromium', '--require-export']),
        ('chroma_e2e.py', ['--browser', 'chromium']),
        ('place_e2e.py', ['--browser', 'chromium']),
        ('place_regression_e2e.py', ['--browser', 'chromium']),
    ):
        run(sys.executable, f'dev/{script}', *args)
    run(sys.executable, 'dev/build_test.py', 'all', '--all-packs')
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / 'dev/www'))
    with http.server.ThreadingHTTPServer(('127.0.0.1', 8765), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            run(sys.executable, 'dev/smoke_all.py', 't_all', timeout=600)
        finally:
            server.shutdown()
            thread.join()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--static-only', action='store_true')
    mode.add_argument('--browser-only', action='store_true', help='Use pages already built by the static checks')
    args = parser.parse_args()
    if not args.browser_only:
        static_checks()
    if not args.static_only:
        browser_checks()


if __name__ == '__main__':
    main()
