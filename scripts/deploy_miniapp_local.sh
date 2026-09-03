#!/usr/bin/env bash
# Build and publish the Tanya Mini App on the production server itself.
# This script intentionally does not configure DNS, TLS or Nginx. It only
# refreshes the already configured static Mini App web root for the exact
# checked-out production commit.

set -Eeuo pipefail
IFS=$'\n\t'
umask 027

# This script can run inside a streamed SSH deployment. npm and its child
# processes must never inherit the caller's script stream as stdin.
exec </dev/null

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
EXPECTED_SHA="${1:-$(git -C "$PROJECT_DIR" rev-parse HEAD)}"
DEFAULT_FRONTEND_DOMAIN="tanyapp.xn--e1aikcel5c5a.online"
FRONTEND_DOMAIN="${MINIAPP_FRONTEND_DOMAIN:-$DEFAULT_FRONTEND_DOMAIN}"
PROFILE_FILE="/etc/banano-miniapp/profiles/${FRONTEND_DOMAIN}.env"
WEB_ROOT="/var/www/${FRONTEND_DOMAIN}"
MINIAPP_ROOT="${WEB_ROOT}/mini-app"
BACKUP_ROOT="/var/backups/banano-miniapp/${FRONTEND_DOMAIN}"
KEEP_BACKUPS="${KEEP_BACKUPS:-7}"
RUN_NPM_AUDIT="${RUN_NPM_AUDIT:-1}"

log() {
  printf '[miniapp-local] %s\n' "$*"
}

die() {
  printf '[miniapp-local] ERROR: %s\n' "$*" >&2
  exit 1
}

run_npm_audit() {
  local audit_json audit_status
  audit_json="$(mktemp)"
  audit_status=0

  set +e
  npm audit --omit=dev --audit-level=moderate --json >"$audit_json"
  audit_status=$?
  set -e

  if [[ "$audit_status" -eq 0 ]]; then
    rm -f "$audit_json"
    return 0
  fi

  # Browserslist <=4.28.6 currently has two reviewed advisories. In this app it
  # is used only while compiling the static export on our trusted production
  # host; it is not a runtime dependency served to users. Keep this exception
  # narrowly scoped to the two known advisory URLs so any new npm finding still
  # blocks deployment. Remove the exception when package-lock is refreshed to
  # browserslist >=4.28.7.
  if python3 - "$audit_json" <<'PY'
import json
import sys
from pathlib import Path

allowed_urls = {
    "https://github.com/advisories/GHSA-c83g-rgw3-j3cx",
    "https://github.com/advisories/GHSA-73wf-gq98-2v4g",
}

try:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)

vulnerabilities = payload.get("vulnerabilities")
if not isinstance(vulnerabilities, dict) or not vulnerabilities:
    raise SystemExit(1)

browserslist = vulnerabilities.get("browserslist")
if not isinstance(browserslist, dict):
    raise SystemExit(1)

seen_direct_urls: set[str] = set()
for package_name, details in vulnerabilities.items():
    if not isinstance(details, dict):
        raise SystemExit(1)
    via = details.get("via") or []
    string_via = {item for item in via if isinstance(item, str)}
    advisory_urls = {
        str(item.get("url") or "")
        for item in via
        if isinstance(item, dict) and item.get("url")
    }

    if advisory_urls - allowed_urls:
        raise SystemExit(1)
    if package_name == "browserslist":
        if string_via:
            raise SystemExit(1)
        seen_direct_urls.update(advisory_urls)
        continue
    if string_via - {"browserslist"}:
        raise SystemExit(1)
    if not string_via and not advisory_urls:
        raise SystemExit(1)

if not seen_direct_urls or not seen_direct_urls.issubset(allowed_urls):
    raise SystemExit(1)
PY
  then
    log "npm audit: allowing only the known build-time Browserslist advisories; all other findings remain blocking"
    rm -f "$audit_json"
    return 0
  fi

  cat "$audit_json" >&2
  rm -f "$audit_json"
  return "$audit_status"
}

if [[ -f "$PROFILE_FILE" ]]; then
  # Existing production profile owns only filesystem/runtime details. The
  # public domain stays pinned above to prevent deploying a stale remote host.
  # shellcheck disable=SC1090
  source "$PROFILE_FILE"
  WEB_ROOT="${WEB_ROOT:-/var/www/${FRONTEND_DOMAIN}}"
  MINIAPP_ROOT="${MINIAPP_ROOT:-${WEB_ROOT}/mini-app}"
  BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/banano-miniapp/${FRONTEND_DOMAIN}}"
  KEEP_BACKUPS="${KEEP_BACKUPS:-7}"
  RUN_NPM_AUDIT="${RUN_NPM_AUDIT:-1}"
fi

command -v git >/dev/null || die "git is required"
command -v node >/dev/null || die "node is required"
command -v npm >/dev/null || die "npm is required"
command -v rsync >/dev/null || die "rsync is required"
command -v curl >/dev/null || die "curl is required"
command -v python3 >/dev/null || die "python3 is required"

ACTUAL_SHA="$(git -C "$PROJECT_DIR" rev-parse HEAD)"
[[ "$ACTUAL_SHA" == "$EXPECTED_SHA" ]] \
  || die "checked-out commit mismatch: expected=$EXPECTED_SHA actual=$ACTUAL_SHA"

FRONTEND_DIR="${PROJECT_DIR}/frontend/miniapp-v0"
OUT_DIR="${FRONTEND_DIR}/out"
[[ -f "${FRONTEND_DIR}/package-lock.json" ]] || die "package-lock.json is missing"

node_major="$(node -p 'process.versions.node.split(".")[0]')"
[[ "$node_major" =~ ^[0-9]+$ ]] || die "could not determine Node.js version"
(( node_major >= 20 )) || die "Node.js 20+ is required; found $(node -v)"

log "Building exact commit ${EXPECTED_SHA} on $(hostname)"
cd "$FRONTEND_DIR"
npm ci

if [[ "$RUN_NPM_AUDIT" == "1" ]]; then
  run_npm_audit
fi

npm run lint
rm -rf .next out
npm run build
[[ -s "${OUT_DIR}/index.html" ]] || die "static export did not create out/index.html"
[[ -d "${OUT_DIR}/_next/static" ]] || die "static export is missing _next/static"

install -d -m 0755 "$MINIAPP_ROOT"
install -d -m 0700 "$BACKUP_ROOT"

if [[ -f "${MINIAPP_ROOT}/index.html" ]]; then
  stamp="$(date '+%Y%m%d-%H%M%S')"
  backup_dir="${BACKUP_ROOT}/${stamp}"
  log "Backing up current Mini App to ${backup_dir}"
  mkdir -p "$backup_dir"
  cp -al "${MINIAPP_ROOT}/." "$backup_dir/"

  mapfile -t old_backups < <(
    find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
      | sort -nr \
      | awk '{print $2}'
  )
  if (( ${#old_backups[@]} > KEEP_BACKUPS )); then
    for ((i=KEEP_BACKUPS; i<${#old_backups[@]}; i++)); do
      rm -rf -- "${old_backups[$i]}"
    done
  fi
fi

log "Publishing static export to ${MINIAPP_ROOT}"
# Keep older hashed chunks for in-flight Telegram WebViews while replacing the
# entrypoint and all current assets atomically enough for static Nginx serving.
rsync -a --chmod=D755,F644 "${OUT_DIR}/" "${MINIAPP_ROOT}/"
printf '%s\n' "$EXPECTED_SHA" > "${MINIAPP_ROOT}/revision.txt"
chmod 0644 "${MINIAPP_ROOT}/revision.txt"
chown -R root:root "$WEB_ROOT"

BASE_URL="https://${FRONTEND_DOMAIN}/mini-app"
work="$(mktemp -d)"
cleanup() { rm -rf "$work"; }
trap cleanup EXIT

live_revision="$(
  curl -fsS --retry 8 --retry-delay 2 --retry-all-errors \
    -H 'Cache-Control: no-cache' \
    "${BASE_URL}/revision.txt?revision=${EXPECTED_SHA}"
)"
[[ "$live_revision" == "$EXPECTED_SHA" ]] \
  || die "live revision mismatch: expected=$EXPECTED_SHA actual=$live_revision"

curl -fsS --retry 8 --retry-delay 2 --retry-all-errors \
  -H 'Cache-Control: no-cache' \
  "${BASE_URL}/?revision=${EXPECTED_SHA}" > "$work/index.html"
grep -q '_next/static' "$work/index.html" || die "live HTML has no Next.js static assets"
grep -oE '/mini-app/_next/static/[^" ]+\.js' "$work/index.html" \
  | sort -u > "$work/assets.txt"
[[ -s "$work/assets.txt" ]] || die "live HTML did not expose JavaScript assets"

while IFS= read -r asset; do
  curl -fsSI --retry 5 --retry-delay 2 --retry-all-errors \
    "https://${FRONTEND_DOMAIN}${asset}?revision=${EXPECTED_SHA}" >/dev/null
done < "$work/assets.txt"

log "LIVE_OK ${BASE_URL}/ revision=${EXPECTED_SHA}"
