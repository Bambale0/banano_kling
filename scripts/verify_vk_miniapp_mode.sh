#!/usr/bin/env bash
# Match the public VK host state without re-enabling an intentionally isolated app.
set -Eeuo pipefail

base_url="${1:?VK frontend base URL required}"
expected_sha="${2:?expected release SHA required}"
base_url="${base_url%/}"

http_status() {
  curl -sS --connect-timeout 5 --max-time 20 -o /dev/null -w '%{http_code}' "$1"
}

revision_url="${base_url}/revision.txt?revision=${expected_sha}"
root_url="${base_url}/?revision=${expected_sha}"
revision_status="$(http_status "$revision_url")"
root_status="$(http_status "$root_url")"

if [[ "$revision_status" == 410 && "$root_status" == 410 ]]; then
  printf 'disabled\n'
  exit 0
fi

if [[ "$revision_status" == 200 && "$root_status" == 200 ]]; then
  revision="$(curl -fsS --connect-timeout 5 --max-time 20 "$revision_url")"
  if [[ "$revision" == "$expected_sha" ]]; then
    printf 'enabled\n'
    exit 0
  fi
  echo "VK revision mismatch: expected exact release SHA" >&2
  exit 1
fi

echo "VK frontend mode inconsistent: revision_http=$revision_status root_http=$root_status (expected both 200 or both 410)" >&2
exit 1
