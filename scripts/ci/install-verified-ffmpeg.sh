#!/usr/bin/env bash
# CI-only portable FFmpeg setup. Linux amd64 wheels are pinned to published
# SHA-256 digests, and the package independently verifies embedded binaries.
# Does not skip media tests or substitute fake ffmpeg/ffprobe executables.
set -Eeuo pipefail

if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  ffmpeg -version | sed -n '1p'
  ffprobe -version | sed -n '1p'
  exit 0
fi

if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
  echo 'Only Ubuntu x86_64 CI runners are supported for the pinned FFmpeg bundle' >&2
  exit 2
fi

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
python -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: \
  --require-hashes -r "$root/scripts/ci/ffmpeg-pinned-wheels.txt"

python - <<'PY'
import os
from pathlib import Path
import subprocess
from portable_ffmpeg import get_ffmpeg

ffmpeg, ffprobe = (Path(path) for path in get_ffmpeg())
if ffmpeg.parent != ffprobe.parent:
    raise RuntimeError("FFmpeg and FFprobe must be installed together")
for path in (ffmpeg, ffprobe):
    if not path.is_file() or not os.access(path, os.X_OK):
        raise RuntimeError(f"CI media executable unavailable: {path.name}")
    result = subprocess.run(
        [str(path), "-version"], capture_output=True, text=True, timeout=15,
        check=True,
    )
    print(result.stdout.splitlines()[0], flush=True)
github_path = os.environ.get("GITHUB_PATH")
if not github_path:
    raise RuntimeError("GITHUB_PATH missing from GitHub Actions environment")
with open(github_path, "a", encoding="utf-8") as handle:
    handle.write(str(ffmpeg.parent) + "\n")
print("CI verified FFmpeg and FFprobe ready for next job steps", flush=True)
PY
