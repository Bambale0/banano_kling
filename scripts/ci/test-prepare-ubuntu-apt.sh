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

# Exercise real mirror candidate selection with all network and apt calls mocked.
probe_root=$(mktemp -d)
backup_root=$(mktemp -d)
fail_root=$(mktemp -d)
trap 'rm -rf "$root" "$probe_root" "$backup_root" "$fail_root"' EXIT
cp -R "$root/etc" "$probe_root/"
cp -R "$root/etc" "$backup_root/"
cp -R "$root/etc" "$fail_root/"
mkdir -p "$probe_root/bin"
cat > "$probe_root/bin/curl" <<'MOCK'
#!/usr/bin/env bash
url=$(printf '%s\n' "$@" | tail -n 1)
printf '%s\n' "$url" >> "$CI_APT_TEST_CURL_LOG"
[[ "$CI_APT_TEST_FAIL_ALL" == 1 ]] && exit 28
if [[ "$CI_APT_TEST_BACKUP" == 1 ]]; then
 [[ "$url" == https://archive.ubuntu.com/ubuntu/* ]] && exit 0
else
 [[ "$url" == https://azure.archive.ubuntu.com/ubuntu/* ]] && exit 0
fi
exit 28
MOCK
cat > "$probe_root/bin/apt-get" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$CI_APT_TEST_APT_LOG"
exit 0
MOCK
chmod +x "$probe_root/bin/curl" "$probe_root/bin/apt-get"
CI_APT_TEST_ROOT="$probe_root" CI_APT_TEST_RUN_FULL=1 CI_APT_TEST_FAIL_ALL=0 CI_APT_TEST_BACKUP=0 \
CI_APT_TEST_CURL_LOG="$probe_root/curl.log" CI_APT_TEST_APT_LOG="$probe_root/apt.log" \
PATH="$probe_root/bin:$PATH" bash "$(dirname "$0")/prepare-ubuntu-apt.sh"
grep -q 'https://azure.archive.ubuntu.com/ubuntu' "$probe_root/etc/apt/apt-mirrors.txt"
! grep -q 'https://mirrors.edge.kernel.org/ubuntu' "$probe_root/curl.log"
grep -q 'https://azure.archive.ubuntu.com/ubuntu/dists/noble-security/InRelease' "$probe_root/curl.log"
grep -q 'APT::Update::Error-Mode=any' "$probe_root/apt.log"
grep -q '^Acquire::ForceIPv4 "true";$' "$probe_root/etc/apt/apt.conf.d/99neuromix-ci-ipv4"
CI_APT_TEST_ROOT="$backup_root" CI_APT_TEST_RUN_FULL=1 CI_APT_TEST_FAIL_ALL=0 CI_APT_TEST_BACKUP=1 \
CI_APT_TEST_CURL_LOG="$backup_root/curl.log" CI_APT_TEST_APT_LOG="$backup_root/apt.log" \
PATH="$probe_root/bin:$PATH" bash "$(dirname "$0")/prepare-ubuntu-apt.sh"
grep -q 'https://archive.ubuntu.com/ubuntu' "$backup_root/etc/apt/apt-mirrors.txt"
grep -q 'https://azure.archive.ubuntu.com/ubuntu/dists/noble/InRelease' "$backup_root/curl.log"
grep -q 'APT::Update::Error-Mode=any' "$backup_root/apt.log"
if CI_APT_TEST_ROOT="$fail_root" CI_APT_TEST_RUN_FULL=1 CI_APT_TEST_FAIL_ALL=1 CI_APT_TEST_BACKUP=0 \
CI_APT_TEST_CURL_LOG="$fail_root/curl.log" CI_APT_TEST_APT_LOG="$fail_root/apt.log" \
PATH="$probe_root/bin:$PATH" bash "$(dirname "$0")/prepare-ubuntu-apt.sh"; then
 echo 'CI apt gate unexpectedly passed with all mirrors inaccessible' >&2
 exit 1
fi
[[ ! -s "$fail_root/apt.log" ]]
echo 'Ubuntu apt mirror selection and fail-closed fallback PASS'
