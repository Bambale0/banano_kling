#!/usr/bin/env bash
set -Eeuo pipefail
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
mkdir -p "$root/etc/apt/sources.list.d"
printf 'VERSION_CODENAME=noble\n' > "$root/etc/os-release"
printf 'http://azure.archive.ubuntu.com/ubuntu\nhttp://security.ubuntu.com/ubuntu\n' > "$root/etc/apt/apt-mirrors.txt"
printf 'URIs: mirror+file:/etc/apt/apt-mirrors.txt\n' > "$root/etc/apt/sources.list.d/ubuntu.sources"
printf 'deb https://archive.ubuntu.com/ubuntu noble main\n' > "$root/etc/apt/sources.list"
printf 'deb https://security.ubuntu.com/ubuntu noble-security main\n' > "$root/etc/apt/sources.list.d/security.list"
CI_APT_TEST_ROOT="$root" bash "$(dirname "$0")/prepare-ubuntu-apt.sh"
! grep -ER '(azure\.archive|archive\.ubuntu\.com|security\.ubuntu\.com)' "$root/etc/apt"
[[ $(grep -c 'https://mirrors.edge.kernel.org/ubuntu' "$root/etc/apt/apt-mirrors.txt") -eq 2 ]]
grep -q 'mirror+file:/etc/apt/apt-mirrors.txt' "$root/etc/apt/sources.list.d/ubuntu.sources"
grep -q 'https://mirrors.edge.kernel.org/ubuntu' "$root/etc/apt/sources.list.d/security.list"
CI_APT_TEST_ROOT="$root" bash "$(dirname "$0")/prepare-ubuntu-apt.sh"
echo 'Ubuntu apt mirror fallback source fixture PASS'
