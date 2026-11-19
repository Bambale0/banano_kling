#!/usr/bin/env bash
# Install real FFmpeg/FFprobe from SHA-256 pinned Linux x64 release assets.
# This avoids 88 slow apt dependencies and an FFmpeg 9 static build whose
# output-mux threads failed under Wan's existing 512 MiB RLIMIT_AS in GH CI.
# Never skip integrity or codec checks; no runtime security limits are changed.
set -Eeuo pipefail

if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  ffmpeg -version | sed -n '1p'
  ffprobe -version | sed -n '1p'
  exit 0
fi

if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
  echo 'Only Linux x86_64 FFmpeg artifacts are pinned for this CI workflow' >&2
  exit 2
fi

: "${GITHUB_PATH:?GITHUB_PATH must be present in GitHub Actions}"
: "${RUNNER_TEMP:?RUNNER_TEMP must be present in GitHub Actions}"

tag=b6.1.1
base="https://github.com/eugeneware/ffmpeg-static/releases/download/$tag"
dir="$RUNNER_TEMP/neuromix-ffmpeg-verified"
mkdir -p "$dir"
chmod 700 "$dir"
for name in ffmpeg ffprobe; do
  case "$name" in
    ffmpeg) expected=bfe8a8fc511530457b528c48d77b5737527b504a3797a9bc4866aeca69c2dffa ;;
    ffprobe) expected=25d9b6ccb05e3d9de9e04e31e2506d8dd7f9f0418981965ac6df12e8d3afd067 ;;
  esac
  curl --fail --location --silent --show-error --retry 2 --retry-delay 2 \
    --connect-timeout 10 --max-time 100 \
    --output "$dir/$name.gz" "$base/$name-linux-x64.gz"
  printf '%s  %s\n' "$expected" "$dir/$name.gz" | sha256sum --check --status
  gzip -t "$dir/$name.gz"
  gzip -dc "$dir/$name.gz" > "$dir/$name"
  chmod 755 "$dir/$name"
  "$dir/$name" -version | sed -n '1p'
done

printf '%s\n' "$dir" >> "$GITHUB_PATH"
echo 'Verified real FFmpeg and FFprobe, hashes match immutable release artifacts.'
