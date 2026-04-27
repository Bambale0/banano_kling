#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

cat > miniapp_static_diagnose.txt <<'EOF'
Mini App static fix started
EOF

python3 - <<'PY'
from pathlib import Path

p = Path('bot/miniapp.py')
s = p.read_text(encoding='utf-8')

static_block = '''
    # miniapp_static_mount_v1
    from pathlib import Path as _MiniAppPath
    miniapp_out_dir = _MiniAppPath(__file__).resolve().parent.parent / "frontend" / "miniapp-v0" / "out"
    miniapp_next_static_dir = miniapp_out_dir / "_next" / "static"
    if miniapp_next_static_dir.exists():
        app.router.add_static("/mini-app/_next/static/", path=str(miniapp_next_static_dir), name="miniapp_next_static")
    if miniapp_out_dir.exists():
        app.router.add_static("/mini-app/", path=str(miniapp_out_dir), name="miniapp_static", show_index=False)
'''

if 'miniapp_static_mount_v1' not in s:
    app_marker = 'app = web.Application()\n'
    pos = s.find(app_marker)
    if pos != -1:
        insert_at = pos + len(app_marker)
        s = s[:insert_at] + static_block + s[insert_at:]
    else:
        router_marker = 'app.router.add_'
        pos = s.find(router_marker)
        if pos == -1:
            raise SystemExit('Could not find aiohttp app/router mount point in bot/miniapp.py')
        line_start = s.rfind('\n', 0, pos) + 1
        s = s[:line_start] + static_block + s[line_start:]

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
