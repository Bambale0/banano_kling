#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

cat > miniapp_static_diagnose.txt <<'EOF'
Mini App static fix started
EOF

python3 - <<'PY'
from pathlib import Path
import re

p = Path('bot/miniapp.py')
s = p.read_text(encoding='utf-8')
orig = s

# Ensure both /mini-app and /mini-app/_next/static are served from the exported frontend.
# aiohttp route order matters: static assets must be mounted before catch-all /mini-app handlers.
static_block = '''
    # miniapp_static_mount_v1
    miniapp_out_dir = Path(__file__).resolve().parent.parent / "frontend" / "miniapp-v0" / "out"
    miniapp_next_static_dir = miniapp_out_dir / "_next" / "static"
    if miniapp_next_static_dir.exists():
        app.router.add_static("/mini-app/_next/static/", path=str(miniapp_next_static_dir), name="miniapp_next_static")
    if miniapp_out_dir.exists():
        app.router.add_static("/mini-app/", path=str(miniapp_out_dir), name="miniapp_static", show_index=False)
'''

if 'miniapp_static_mount_v1' not in s:
    # Prefer inserting right after app creation inside setup function.
    m = re.search(r'(app\s*=\s*web\.Application\([^\n]*\)\n)', s)
    if m:
        s = s[:m.end()] + static_block + s[m.end():]
    else:
        # Fallback: insert before first add_routes/add_static if present.
        m = re.search(r'(\s*app\.router\.add_', s)
        if not m:
            raise SystemExit('Could not find aiohttp app/router mount point in bot/miniapp.py')
        s = s[:m.start()] + static_block + s[m.start():]

p.write_text(s, encoding='utf-8')
PY

python3 -m py_compile bot/miniapp.py bot/main.py

echo "== Rebuild frontend =="
cd "$ROOT/frontend/miniapp-v0"
rm -rf .next out node_modules/.cache
npm install
npm run build

cd "$ROOT"
echo "== Verify built CSS/JS =="
find frontend/miniapp-v0/out/_next/static -maxdepth 3 -type f | head -50 || true

echo "== Restart =="
./restart.sh

echo "OK: miniapp static mount patched. Close Telegram WebView fully and open Mini App again."
