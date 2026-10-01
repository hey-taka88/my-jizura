#!/bin/bash
# SessionStart hook for Claude Code on the web: install the test tools so
# `python3 dev/smoke_all.py` (Playwright + Pillow) and `node dev/ae_test.js` (acorn) work.
set -euo pipefail

# Local sessions manage their own environment.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# Python: Playwright pinned to the preinstalled Chromium (see dev/requirements.txt), Pillow for contact sheets.
pip install --quiet --disable-pip-version-check -r dev/requirements.txt

# The MCP SDK for tools/jizura_mcp.py and dev/mcp_e2e.py (best effort: the image's Debian PyJWT cannot be upgraded in place).
pip install --quiet --disable-pip-version-check "mcp>=1.10" 2>/dev/null \
  || pip install --quiet --disable-pip-version-check --ignore-installed PyJWT "mcp>=1.10" 2>/dev/null \
  || echo "session-start: mcp not installed (dev/mcp_e2e.py needs it)" >&2

# Node: acorn for the After Effects panel mock (dev/ae_test.js, dev/ae_check.js).
if [ -f dev/package.json ]; then
  (cd dev && npm install --no-audit --no-fund --loglevel=error)
fi
