#!/usr/bin/env bash
# GitHub-hosted Ubuntu runners intermittently fail DNS resolution for
# archive.ubuntu.com/security.ubuntu.com. Use independently reachable Ubuntu
# mirrors, preserving apt's normal signed Release metadata verification.
set -Eeuo pipefail

if [[ ${CI_APT_TEST_ROOT:-} ]]; then
  root=${CI_APT_TEST_ROOT%/}
  sudo_cmd=()
else
  root=''
  sudo_cmd=(sudo)
fi

codename=${VERSION_CODENAME:-}
if [[ ! $codename && -f ${root}/etc/os-release ]]; then
  codename=$(sed -n 's/^VERSION_CODENAME=//p' "${root}/etc/os-release" | tr -d '"')
fi
if [[ ! $codename && -f /etc/os-release ]]; then
  codename=$(sed -n 's/^VERSION_CODENAME=//p' /etc/os-release | tr -d '"')
fi
[[ $codename =~ ^[a-z]+$ ]] || { echo 'Unsafe or absent Ubuntu codename' >&2; exit 2; }

apply_mirror() {
  local mirror=$1 file
  for file in \
    "${root}/etc/apt/apt-mirrors.txt" \
    "${root}/etc/apt/sources.list" \
    "${root}"/etc/apt/sources.list.d/*.sources \
    "${root}"/etc/apt/sources.list.d/*.list; do
    [[ -f $file ]] || continue
    "${sudo_cmd[@]}" sed -i -E \
      -e "s@https?://(azure\.)?archive\.ubuntu\.com/ubuntu@${mirror}@g" \
      -e "s@https?://security\.ubuntu\.com/ubuntu@${mirror}@g" \
      -e "s@https?://mirrors\.edge\.kernel\.org/ubuntu@${mirror}@g" \
      -e "s@https?://mirror\.hetzner\.com/ubuntu/packages@${mirror}@g" \
      "$file"
  done
}

# Fixture mode asserts correct rewriting without touching the host or apt.
if [[ ${CI_APT_TEST_ROOT:-} ]]; then
  apply_mirror 'https://mirrors.edge.kernel.org/ubuntu'
  exit 0
fi

# Only official/verified Ubuntu mirror paths; apt validates signed InRelease\n# metadata and package hashes. Try HTTPS and canonical HTTP in case 443 is\n# unreachable on a hosted runner; never disable apt signature verification.\n# The fixture test remains network-independent.
# Check their DNS reachability before waiting for apt retries. Never mark the
# CI dependency gate as passed if actual apt update or install fails.
for mirror in \
  'https://archive.ubuntu.com/ubuntu' \
  'http://archive.ubuntu.com/ubuntu' \
  'https://mirrors.edge.kernel.org/ubuntu' \
  'https://mirror.hetzner.com/ubuntu/packages'; do
  if ! curl -fsSL --connect-timeout 4 --max-time 10 -o /dev/null "${mirror}/dists/${codename}/InRelease" ||      ! curl -fsSL --connect-timeout 4 --max-time 10 -o /dev/null "${mirror}/dists/${codename}-security/InRelease"; then
    echo "Ubuntu mirror not reachable: $mirror" >&2
    continue
  fi
  apply_mirror "$mirror"
  if sudo timeout 105 apt-get -o APT::Update::Error-Mode=any -o Acquire::Retries=1 -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15 update; then
    echo "Ubuntu signed apt index ready from $mirror"
    exit 0
  fi
  echo "apt update failed for $mirror; trying next mirror" >&2
done

echo 'No usable signed Ubuntu apt mirror; refusing to skip dependencies' >&2
exit 1
