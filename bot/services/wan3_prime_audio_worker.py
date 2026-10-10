"""Resource-limited local-only audio preprocessing, never a webhook process."""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path


def apply_limits(maximum_bytes: int, memory_bytes: int) -> None:
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
    resource.setrlimit(resource.RLIMIT_FSIZE, (maximum_bytes, maximum_bytes))


def transcode(source: Path, destination: Path, maximum_seconds: float, maximum_bytes: int) -> None:
    probe = subprocess.run(
        ['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
         '-format_whitelist', 'ogg,mov,wav,mp3,aac', '-show_entries', 'format=duration:stream=codec_type,duration',
         '-of', 'json', str(source)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, timeout=10, check=True,
    )
    metadata = json.loads(probe.stdout)
    audio = next((item for item in metadata.get('streams', []) if item.get('codec_type') == 'audio'), None)
    if not audio:
        raise ValueError('No audio stream')
    duration = float((metadata.get('format') or {}).get('duration') or audio.get('duration') or 0)
    if not math.isfinite(duration) or not 1 <= duration <= maximum_seconds:
        raise ValueError('Audio duration is outside the supported range')
    # The extra second is a safety fence for forged metadata, not normal clipping.
    # The regular media validator rejects any actual output beyond the limit.
    subprocess.run(
        ['ffmpeg', '-nostdin', '-v', 'error', '-protocol_whitelist', 'file,pipe',
         '-format_whitelist', 'ogg,mov,wav,mp3,aac', '-threads', '1', '-i', str(source),
         '-map', '0:a:0', '-vn', '-threads', '1', '-c:a', 'libmp3lame', '-b:a', '128k',
         '-t', str(maximum_seconds + 1), '-fs', str(maximum_bytes), '-y', str(destination)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=True,
    )


def main() -> None:
    source, destination = Path(sys.argv[1]), Path(sys.argv[2])
    seconds, size, memory = float(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
    apply_limits(size, memory)
    transcode(source, destination, seconds, size)


if __name__ == '__main__':
    main()
