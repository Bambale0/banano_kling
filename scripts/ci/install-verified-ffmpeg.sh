#!/usr/bin/env bash
# Install pinned, real FFmpeg and FFprobe without depending on Ubuntu apt mirrors.
# The wheel's exact SHA-256 is checked before either executable is extracted.
set -Eeuo pipefail

[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || {
  echo "Only Linux x86_64 CI runners are supported" >&2; exit 2;
}
version=1.1.0
sha256=b8a6d67f5895a8a105e25746db3bb3a4d6b76629cde22814f9866fd9af76a399
install_dir="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/neuromix-ffmpeg-${version}"
download_dir="$(mktemp -d)"
trap 'rm -rf -- "$download_dir"' EXIT

python3 -m pip download --disable-pip-version-check --no-deps \
  --only-binary=:all: --retries 3 --timeout 20 \
  --dest "$download_dir" "ffmpeg-binaries==${version}"

python3 - "$download_dir" "$install_dir" "$sha256" <<'PY'
from pathlib import Path
import hashlib
import sys
import zipfile

source, target, expected = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
wheels = list(source.glob("ffmpeg_binaries-1.1.0-py3-none-manylinux1_x86_64.whl"))
if len(wheels) != 1:
    raise SystemExit("Expected one pinned Linux x86_64 FFmpeg wheel")
with wheels[0].open("rb") as stream:
    actual = hashlib.file_digest(stream, "sha256").hexdigest()
if actual != expected:
    raise SystemExit("FFmpeg wheel SHA-256 mismatch")
target.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(wheels[0]) as archive:
    for name in ("ffmpeg", "ffprobe"):
        path = target / name
        path.write_bytes(archive.read("ffmpeg/binaries/" + name))
        path.chmod(0o755)
PY

"$install_dir/ffmpeg" -version | head -1
"$install_dir/ffprobe" -version | head -1
"$install_dir/ffmpeg" -v error -f lavfi -i "color=c=black:s=64x64:d=0.3" \
  -t 0.3 -c:v libx264 -y "$download_dir/smoke.mp4"
"$install_dir/ffprobe" -v error -show_entries format=duration \
  -of default=nw=1 "$download_dir/smoke.mp4"

if [[ -n "${GITHUB_PATH:-}" ]]; then
  printf '%s\n' "$install_dir" >> "$GITHUB_PATH"
else
  echo "Verified binaries at $install_dir (add to PATH before running tests)"
fi
