#!/usr/bin/env bash
# Build and publish the Tanya Mini App on the production server itself.
# Refresh the static Mini App roots for the exact checked-out commit. The
# existing VK vhost also receives a validated, reversible media-route include;
# DNS, TLS and other provisioned Nginx settings remain operator-owned.

set -Eeuo pipefail
IFS=$'\n\t'
umask 027

# This script can run inside a streamed SSH deployment. npm and its child
# processes must never inherit the caller's script stream as stdin.
exec </dev/null

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
EXPECTED_SHA="${1:-$(git -C "$PROJECT_DIR" rev-parse HEAD)}"
DEFAULT_FRONTEND_DOMAIN="neuromixbot.com"
FRONTEND_DOMAIN="${MINIAPP_FRONTEND_DOMAIN:-$DEFAULT_FRONTEND_DOMAIN}"
PROFILE_FILE="/etc/banano-miniapp/profiles/${FRONTEND_DOMAIN}.env"
WEB_ROOT="/var/www/${FRONTEND_DOMAIN}"
MINIAPP_ROOT="${WEB_ROOT}/mini-app"
BACKUP_ROOT="/var/backups/banano-miniapp/${FRONTEND_DOMAIN}"
VK_FRONTEND_DOMAIN="${VK_MINIAPP_FRONTEND_DOMAIN:-vk.neuromixbot.com}"
VK_WEB_ROOT="${VK_MINIAPP_WEB_ROOT:-/var/www/${VK_FRONTEND_DOMAIN}}"
VK_RELEASE_ROOT="${VK_WEB_ROOT}/releases"
RUN_NPM_AUDIT="${RUN_NPM_AUDIT:-0}"

log() {
  printf '[miniapp-local] %s\n' "$*"
}

die() {
  printf '[miniapp-local] ERROR: %s\n' "$*" >&2
  exit 1
}

# A minimum free-space floor is a fail-closed preflight, not a prediction of
# build/backup size. Retained history still needs operator capacity monitoring.
require_disk_space() {
    local minimum="${DEPLOY_MIN_FREE_BYTES:-10737418240}"
    local target="${1:-$PROJECT_DIR}"
    local available=""
    [[ "$minimum" =~ ^[0-9]{1,18}$ ]] && (( 10#$minimum >= 10737418240 )) \
        || die "DEPLOY_MIN_FREE_BYTES must be at least 10737418240 (10 GiB)"
    # Check the existing ancestor before creating a new backup directory.
    while [ ! -e "$target" ]; do
        target="$(dirname -- "$target")"
    done
    available="$(df -PB1 -- "$target" | awk 'NR == 2 {print $4}')"
    [[ "$available" =~ ^[0-9]{1,18}$ ]] && (( 10#$available >= 10#$minimum )) \
        || die "Insufficient disk space at $target: available=${available:-unknown} required=$minimum; no backups deleted"
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
  RUN_NPM_AUDIT="${RUN_NPM_AUDIT:-0}"
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

# Fail before build/backup if either filesystem is below the configured floor.
# Increase DEPLOY_MIN_FREE_BYTES for larger builds; retained history is not pruned.
require_disk_space "$PROJECT_DIR"
require_disk_space "$BACKUP_ROOT"
require_disk_space "$VK_RELEASE_ROOT"

log "Building exact commit ${EXPECTED_SHA} on $(hostname)"
cd "$FRONTEND_DIR"
npm ci --no-audit --fund=false

if [[ "$RUN_NPM_AUDIT" == "1" ]]; then
  run_npm_audit
fi

build_work="$(mktemp -d)"
work=""
vk_stage=""
vk_current_link=""
cleanup() {
  rm -rf -- "$build_work"
  [[ -z "$work" ]] || rm -rf -- "$work"
  [[ -z "$vk_stage" ]] || rm -rf -- "$vk_stage"
  [[ -z "$vk_current_link" ]] || rm -f -- "$vk_current_link"
}
trap cleanup EXIT

npm run lint
rm -rf .next out
npm run build
[[ -s "${OUT_DIR}/index.html" ]] || die "static export did not create out/index.html"
[[ -d "${OUT_DIR}/_next/static" ]] || die "static export is missing _next/static"
install -d -m 0700 "$build_work/telegram"
rsync -a "${OUT_DIR}/" "$build_work/telegram/"

rm -rf .next out
npm run build:vk
[[ -s "${OUT_DIR}/index.html" ]] || die "VK static export did not create out/index.html"
[[ -d "${OUT_DIR}/_next/static" ]] || die "VK static export is missing _next/static"
grep -q '/_next/static/' "${OUT_DIR}/index.html" || die "VK export has no root static assets"
if grep -q '/mini-app/_next/static/' "${OUT_DIR}/index.html"; then
  die "VK export contains Telegram-prefixed assets"
fi
install -d -m 0700 "$build_work/vk"
rsync -a "${OUT_DIR}/" "$build_work/vk/"

install -d -m 0755 "$MINIAPP_ROOT"
install -d -m 0700 "$BACKUP_ROOT"
install -d -m 0755 "$VK_RELEASE_ROOT"

if [[ -f "${MINIAPP_ROOT}/index.html" ]]; then
  stamp="$(date '+%Y%m%d-%H%M%S')"
  backup_dir="${BACKUP_ROOT}/${stamp}"
  log "Backing up current Mini App to ${backup_dir}"
  mkdir -p "$backup_dir"
  cp -al "${MINIAPP_ROOT}/." "$backup_dir/"

  # Releases preserve every historical backup. Retention/deletion is a
  # separately reviewed maintenance operation, never a deployment side effect.
  log "Preserving all existing Mini App backups"
fi

# The VK root SPA must not answer saved /uploads/ media requests with HTML.
# Derive the upstream from its existing API proxy and preserve the vhost.
python3 "${PROJECT_DIR}/scripts/configure_vk_media_route.py" \
  --site "/etc/nginx/sites-enabled/${VK_FRONTEND_DOMAIN}.conf" \
  --snippet "/etc/nginx/snippets/banano-vk-media.conf"

log "Publishing static export to ${MINIAPP_ROOT}"
# Keep older hashed chunks for in-flight Telegram WebViews while replacing the
# entrypoint and all current assets atomically enough for static Nginx serving.
rsync -a --chmod=D755,F644 "$build_work/telegram/" "${MINIAPP_ROOT}/"
# Backups use hard links: replace the inode instead of truncating old revisions.
revision_file="$(mktemp "${MINIAPP_ROOT}/.revision-XXXXXX")"
printf '%s\n' "$EXPECTED_SHA" > "$revision_file"
chmod 0644 "$revision_file"
mv -f -- "$revision_file" "${MINIAPP_ROOT}/revision.txt"
chown -R root:root "$WEB_ROOT"

vk_release_name="$EXPECTED_SHA"
vk_release_dir="${VK_RELEASE_ROOT}/${vk_release_name}"
if [[ -e "$vk_release_dir" || -L "$vk_release_dir" ]]; then
  vk_release_name="${EXPECTED_SHA}-$(date '+%Y%m%d-%H%M%S')-$$"
  vk_release_dir="${VK_RELEASE_ROOT}/${vk_release_name}"
fi
vk_stage="$(mktemp -d "${VK_RELEASE_ROOT}/.${vk_release_name}.staging.XXXXXX")"
log "Publishing VK export to ${vk_release_dir}"
rsync -a --chmod=D755,F644 "$build_work/vk/" "$vk_stage/"
vk_revision_file="$(mktemp "$vk_stage/.revision-XXXXXX")"
printf '%s\n' "$EXPECTED_SHA" > "$vk_revision_file"
chmod 0644 "$vk_revision_file"
mv -f -- "$vk_revision_file" "$vk_stage/revision.txt"
chown -R root:root "$vk_stage"
chmod 0755 "$vk_stage"
mv -T -- "$vk_stage" "$vk_release_dir"
vk_stage=""

# Replace only the symlink. Existing releases remain available for rollback and
# in-flight clients that still request their hashed assets.
vk_current_link="${VK_WEB_ROOT}/.current-${EXPECTED_SHA}-$$"
ln -s -- "$vk_release_dir" "$vk_current_link"
mv -T -- "$vk_current_link" "${VK_WEB_ROOT}/current"
vk_current_link=""

BASE_URL="https://${FRONTEND_DOMAIN}/mini-app"
work="$(mktemp -d)"

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

VK_BASE_URL="https://${VK_FRONTEND_DOMAIN}"
vk_live_revision="$(
  curl -fsS --retry 8 --retry-delay 2 --retry-all-errors \
    -H 'Cache-Control: no-cache' \
    "${VK_BASE_URL}/revision.txt?revision=${EXPECTED_SHA}"
)"
[[ "$vk_live_revision" == "$EXPECTED_SHA" ]] \
  || die "VK live revision mismatch: expected=$EXPECTED_SHA actual=$vk_live_revision"

curl -fsS --retry 8 --retry-delay 2 --retry-all-errors \
  -H 'Cache-Control: no-cache' \
  "${VK_BASE_URL}/?revision=${EXPECTED_SHA}" > "$work/vk-index.html"
grep -q '/_next/static/' "$work/vk-index.html" || die "VK live HTML has no root static assets"
if grep -q '/mini-app/_next/static/\|telegram-web-app.js' "$work/vk-index.html"; then
  die "VK live HTML contains Telegram-only assets"
fi
grep -oE '/_next/static/[^" ]+\.js' "$work/vk-index.html" \
  | sort -u > "$work/vk-assets.txt"
[[ -s "$work/vk-assets.txt" ]] || die "VK live HTML did not expose JavaScript assets"
while IFS= read -r asset; do
  curl -fsSI --retry 5 --retry-delay 2 --retry-all-errors \
    "${VK_BASE_URL}${asset}?revision=${EXPECTED_SHA}" >/dev/null
done < "$work/vk-assets.txt"

log "LIVE_OK ${BASE_URL}/ revision=${EXPECTED_SHA}"
log "VK_LIVE_OK ${VK_BASE_URL}/ revision=${EXPECTED_SHA}"
