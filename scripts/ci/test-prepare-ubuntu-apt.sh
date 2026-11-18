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
printf 'URIs: http://us-east-2.ec2.archive.ubuntu.com/ubuntu\nSuites: noble noble-updates\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n' > "$root/etc/apt/sources.list.d/regional.sources"
CI_APT_TEST_ROOT="$root" bash "$(dirname "$0")/prepare-ubuntu-apt.sh"
! grep -ER '(azure\.archive|archive\.ubuntu\.com|security\.ubuntu\.com)' "$root/etc/apt"
[[ $(grep -c 'https://mirrors.edge.kernel.org/ubuntu' "$root/etc/apt/apt-mirrors.txt") -eq 2 ]]
grep -q 'mirror+file:/etc/apt/apt-mirrors.txt' "$root/etc/apt/sources.list.d/ubuntu.sources"
grep -q 'https://mirrors.edge.kernel.org/ubuntu' "$root/etc/apt/sources.list.d/security.list"
grep -q '^URIs: https://mirrors.edge.kernel.org/ubuntu$' "$root/etc/apt/sources.list.d/regional.sources"
grep -q '^Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg$' "$root/etc/apt/sources.list.d/regional.sources"
CI_APT_TEST_ROOT="$root" bash "$(dirname "$0")/prepare-ubuntu-apt.sh"
echo 'Ubuntu apt mirror fallback source fixture PASS'

# Exercise real mirror candidate selection with all network and apt calls mocked.
probe_root=$(mktemp -d)
backup_root=$(mktemp -d)
chain_root=$(mktemp -d)
fail_root=$(mktemp -d)
trap 'rm -rf "$root" "$probe_root" "$backup_root" "$chain_root" "$fail_root"' EXIT
cp -R "$root/etc" "$probe_root/"
cp -R "$root/etc" "$backup_root/"
cp -R "$root/etc" "$chain_root/"
cp -R "$root/etc" "$fail_root/"
mkdir -p "$probe_root/bin"
cat > "$probe_root/bin/curl" <<'MOCK'
#!/usr/bin/env bash
url=$(printf '%s\n' "$@" | tail -n 1)
printf '%s\n' "$url" >> "$CI_APT_TEST_CURL_LOG"
[[ "$CI_APT_TEST_FAIL_ALL" == 1 ]] && exit 28
if [[ "$CI_APT_TEST_CHAIN" == 1 ]]; then
 case "$url" in
  https://ubuntu.osuosl.org/ubuntu/*|https://mirrors.ocf.berkeley.edu/ubuntu/*|https://mirrors.edge.kernel.org/ubuntu/*) exit 0 ;;
 esac
 exit 28
fi
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
if [[ "$CI_APT_TEST_CHAIN" == 1 ]]; then
 source_url=$(head -n 1 "$CI_APT_TEST_ROOT/etc/apt/apt-mirrors.txt")
 printf 'source=%s\n' "$source_url" >> "$CI_APT_TEST_APT_LOG"
 [[ "$source_url" == 'https://mirrors.edge.kernel.org/ubuntu' ]]
 exit
fi
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
CI_APT_TEST_ROOT="$chain_root" CI_APT_TEST_RUN_FULL=1 CI_APT_TEST_FAIL_ALL=0 CI_APT_TEST_BACKUP=0 CI_APT_TEST_CHAIN=1 \
CI_APT_TEST_CURL_LOG="$chain_root/curl.log" CI_APT_TEST_APT_LOG="$chain_root/apt.log" \
PATH="$probe_root/bin:$PATH" bash "$(dirname "$0")/prepare-ubuntu-apt.sh"
grep -q '^https://mirrors.edge.kernel.org/ubuntu$' "$chain_root/etc/apt/apt-mirrors.txt"
grep -q 'source=https://ubuntu.osuosl.org/ubuntu' "$chain_root/apt.log"
grep -q 'source=https://mirrors.ocf.berkeley.edu/ubuntu' "$chain_root/apt.log"
grep -q 'source=https://mirrors.edge.kernel.org/ubuntu' "$chain_root/apt.log"
if CI_APT_TEST_ROOT="$fail_root" CI_APT_TEST_RUN_FULL=1 CI_APT_TEST_FAIL_ALL=1 CI_APT_TEST_BACKUP=0 \
CI_APT_TEST_CURL_LOG="$fail_root/curl.log" CI_APT_TEST_APT_LOG="$fail_root/apt.log" \
PATH="$probe_root/bin:$PATH" bash "$(dirname "$0")/prepare-ubuntu-apt.sh"; then
 echo 'CI apt gate unexpectedly passed with all mirrors inaccessible' >&2
 exit 1
fi
[[ ! -s "$fail_root/apt.log" ]]
# A third-party Microsoft feed returning 429 must not block signed Ubuntu
# dependency installation on an ephemeral GitHub Actions runner.
mkdir -p "$probe_root/etc/apt/sources.list.d"
printf 'deb https://packages.microsoft.com/ubuntu/24.04/prod noble main\\n' > "$probe_root/etc/apt/sources.list.d/microsoft-prod.list"
CI_APT_TEST_ROOT="$probe_root" CI_APT_TEST_RUN_FULL=1 GITHUB_ACTIONS=true CI_APT_TEST_FAIL_ALL=0 CI_APT_TEST_BACKUP=0 \\
CI_APT_TEST_CURL_LOG="$probe_root/curl.log" CI_APT_TEST_APT_LOG="$probe_root/apt.log" \\
PATH="$probe_root/bin:$PATH" bash "$(dirname "$0")/prepare-ubuntu-apt.sh"
[[ ! -f "$probe_root/etc/apt/sources.list.d/microsoft-prod.list" ]]
grep -q 'packages.microsoft.com' "$probe_root/etc/apt/sources.list.d/microsoft-prod.list.neuromix-ci-disabled"
echo 'GitHub runner third-party apt 429 isolation PASS'

echo 'Ubuntu apt mirror selection and fail-closed fallback PASS'
