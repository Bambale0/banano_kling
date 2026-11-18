#!/usr/bin/env bash
# Publish the mobile-first NEUROMIX landing at / without replacing /mini-app/.
# Called by the existing exact-SHA production deploy.
set -Eeuo pipefail
umask 027

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
EXPECTED_SHA="$1"
HOST="neuromixbot.com"
ROOT="/var/www/neuromix-landing"
LANDING="$PROJECT_DIR/web/landing"
NGINX="/etc/nginx/sites-available/$HOST.conf"
BACKUPS="/var/backups/banano-landing/$HOST"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$(printf '%.12s' "$EXPECTED_SHA")"
BACKUP="$BACKUPS/$STAMP"
CONFIG_CHANGED=0
VERIFIED=0
SMOKE=""

[[ -n "$EXPECTED_SHA" && "$(git -C "$PROJECT_DIR" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || {
  echo "[landing] Exact checked-out SHA does not match" >&2; exit 1;
}
[[ -f "$LANDING/index.html" && -f "$LANDING/robots.txt" && -f "$LANDING/sitemap.xml" && -f "$LANDING/grunge-collage.webp" ]] || {
  echo "[landing] Website assets missing" >&2; exit 1;
}
[[ -f "$NGINX" ]] || { echo "[landing] Expected Nginx vhost missing: $NGINX" >&2; exit 1; }

python3 - "$LANDING/index.html" <<'PY'
from html.parser import HTMLParser
from pathlib import Path
import sys

class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.headings = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self.links.append(attrs.get("href", ""))
        if tag == "h1":
            self.headings.append(tag)

p = Links()
p.feed(Path(sys.argv[1]).read_text(encoding="utf8"))
asset = Path(sys.argv[1]).parent / "grunge-collage.webp"
data = asset.read_bytes()
assert data[:4] == b"RIFF" and data[8:12] == b"WEBP", "Invalid hero artwork"
assert b'src="/grunge-collage.webp"' in Path(sys.argv[1]).read_bytes(), "Hero artwork not wired"
assert p.headings == ["h1"], "Landing must have one H1"
assert p.links.count("/mini-app/") >= 3, "Missing direct app entrypoints"
assert all(link.startswith(("/", "#")) for link in p.links), "Unexpected outbound link"
PY

[[ ! -L "$ROOT" ]] || { echo "[landing] Isolated landing root cannot be a symlink" >&2; exit 1; }
install -d -m 0755 "$ROOT"
install -d -m 0700 "$BACKUP"
cp -p -- "$NGINX" "$BACKUP/nginx.conf"
if [[ -f "$ROOT/index.html" ]]; then cp -p -- "$ROOT/index.html" "$BACKUP/index.html"; fi
for file in robots.txt sitemap.xml grunge-collage.webp; do
  if [[ -f "$ROOT/$file" ]]; then cp -p -- "$ROOT/$file" "$BACKUP/$file"; fi
done

rollback() {
  status=$?
  if [[ -n "$SMOKE" ]]; then rm -f -- "$SMOKE"; fi
  if [[ "$VERIFIED" != 1 && "$CONFIG_CHANGED" == 1 ]]; then
    echo "[landing] Activation failed; restoring Nginx config from $BACKUP" >&2
    cp -p -- "$BACKUP/nginx.conf" "$NGINX"
    if nginx -t; then systemctl reload nginx || true; fi
  fi
  if [[ "$VERIFIED" != 1 ]]; then
    if [[ -f "$BACKUP/index.html" ]]; then cp -p -- "$BACKUP/index.html" "$ROOT/index.html"; else rm -f -- "$ROOT/index.html"; fi
    for file in robots.txt sitemap.xml grunge-collage.webp; do
      if [[ -f "$BACKUP/$file" ]]; then cp -p -- "$BACKUP/$file" "$ROOT/$file"; else rm -f -- "$ROOT/$file"; fi
    done
  fi
  exit "$status"
}
trap rollback EXIT

for file in index.html robots.txt sitemap.xml grunge-collage.webp; do
  tmp="$(mktemp "$ROOT/.landing-$file.XXXXXX")"
  install -m 0644 "$LANDING/$file" "$tmp"
  mv -f -- "$tmp" "$ROOT/$file"
done

# Live vhost has emergency VK isolation absent from some tracked templates:
# modify only the exact root block and preserve other routes and headers.
python3 - "$NGINX" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
content = path.read_text(encoding="utf8")
old = """    location = / {
        return 302 /mini-app/;
    }
"""
new = """    # Public marketing entry; existing Mini App stays at /mini-app/.
    location = / {
        root /var/www/neuromix-landing;
        try_files /index.html =404;
        add_header Cache-Control "no-cache, max-age=0, must-revalidate" always;
    }

    location = /robots.txt {
        root /var/www/neuromix-landing;
        try_files /robots.txt =404;
        add_header Cache-Control "public, max-age=3600" always;
    }

    location = /sitemap.xml {
        root /var/www/neuromix-landing;
        try_files /sitemap.xml =404;
        add_header Cache-Control "public, max-age=3600" always;
    }
"""
if old in content:
    if content.count(old) != 1:
        raise SystemExit("Ambiguous root route; refusing mutation")
    content = content.replace(old, new, 1)
elif new in content:
    pass
else:
    raise SystemExit("Unknown Nginx root route; refusing mutation")
# Add this exact static route to already-live landing configs without
# overwriting emergency Nginx edits or existing Mini App routes.
artwork_block = """    # Cacheable static collage from the isolated marketing root; never the Mini App root.
    location = /grunge-collage.webp {
        root /var/www/neuromix-landing;
        try_files /grunge-collage.webp =404;
        add_header Cache-Control "public, max-age=86400" always;
    }
"""
if artwork_block not in content:
    if "location = /grunge-collage.webp {" in content:
        raise SystemExit("Unexpected artwork route; refusing mutation")
    anchor = """    location = /sitemap.xml {
        root /var/www/neuromix-landing;
        try_files /sitemap.xml =404;
        add_header Cache-Control "public, max-age=3600" always;
    }
"""
    if content.count(anchor) != 1:
        raise SystemExit("Unexpected sitemap route; refusing mutation")
    content = content.replace(anchor, anchor + "\n" + artwork_block, 1)
if content.count("location = / {") != 1:
    raise SystemExit("Unexpected HTTPS root location count")
tmp = path.with_suffix(path.suffix + ".landing-tmp")
tmp.write_text(content, encoding="utf8")
tmp.chmod(path.stat().st_mode & 0o777)
tmp.replace(path)
PY

CONFIG_CHANGED=1
nginx -t
systemctl reload nginx

SMOKE="$(mktemp)"
# Nginx reload is asynchronous: a still-active worker can briefly return the
# previous 302. Verify both origin and public Cloudflare route with a bounded
# retry loop; never treat a 302 as success, even if curl exits with status 0.
for mode in origin public; do
  args=()
  if [[ "$mode" == origin ]]; then args=(--resolve "$HOST:443:127.0.0.1"); fi
  status=""
  for (( attempt=1; attempt<=30; attempt++ )); do
    status="$(curl -sS --connect-timeout 5 --max-time 15 "${args[@]}" -o "$SMOKE" -w '%{http_code}' "https://$HOST/" || true)"
    if [[ "$status" == 200 ]] && grep -q 'id="hero-title"' "$SMOKE" && grep -q 'href="/mini-app/"' "$SMOKE"; then
      break
    fi
    sleep 1
  done
  [[ "$status" == 200 ]] || { echo "[landing] $mode root returned $status, expected 200" >&2; exit 1; }
  grep -q 'id="hero-title"' "$SMOKE" || { echo "[landing] $mode root does not serve landing" >&2; exit 1; }
  grep -q 'href="/mini-app/"' "$SMOKE" || { echo "[landing] $mode root missing app entry" >&2; exit 1; }
done
for file in robots.txt sitemap.xml; do
  code="$(curl -sS --max-time 15 --resolve "$HOST:443:127.0.0.1" -o /dev/null -w '%{http_code}' "https://$HOST/$file")"
  [[ "$code" == 200 ]] || { echo "[landing] /$file returned $code" >&2; exit 1; }
done
# Verify real WebP bytes from the exact git release at origin and public edge.
for mode in origin public; do
  args=()
  if [[ "$mode" == origin ]]; then args=(--resolve "$HOST:443:127.0.0.1"); fi
  status="$(curl -sS --connect-timeout 5 --max-time 20 "${args[@]}" -o "$SMOKE" -w '%{http_code}' "https://$HOST/grunge-collage.webp")"
  [[ "$status" == 200 ]] || { echo "[landing] $mode artwork returned $status" >&2; exit 1; }
  cmp -s "$LANDING/grunge-collage.webp" "$SMOKE" || { echo "[landing] $mode artwork hash mismatch" >&2; exit 1; }
done
miniapp_revision="$(curl -fsS --max-time 20 --resolve "$HOST:443:127.0.0.1" "https://$HOST/mini-app/revision.txt")"
[[ "$miniapp_revision" == "$EXPECTED_SHA" ]] || { echo "[landing] Existing Mini App revision mismatch" >&2; exit 1; }

VERIFIED=1
printf '[landing] LIVE_OK https://%s/ root=200 miniapp_revision=%s backup=%s\n' "$HOST" "$miniapp_revision" "$BACKUP"
