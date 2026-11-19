"""CI-only diagnostic: real FFmpeg/FFprobe under Wan's production memory fence.

All media are generated inside a temporary directory; no user data or
secrets are inspected. This is an additional fail-closed smoke, not a test skip.
"""
from __future__ import annotations

import json
import resource
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_MEMORY_BYTES = 536_870_912


def limited() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY_BYTES, MAX_MEMORY_BYTES))


def execute(label: str, args: list[str], *, fenced: bool) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=20,
        preexec_fn=limited if fenced else None, check=False,
    )
    print(f"{label} returncode={result.returncode}", flush=True)
    if result.returncode:
        # Synthetic input; prints only sanitized CLI diagnostics.
        print(f"{label} stderr tail: {result.stderr[-900:]}", flush=True)
    return result


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="wan3-ci-synthetic-ogg-") as tmp:
        folder = Path(tmp)
        source = folder / "synthetic.ogg"
        result = execute(
            "generate", [
                "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi",
                "-i", "sine=frequency=440:duration=1.2",
                "-c:a", "libopus", str(source),
            ], fenced=False,
        )
        if result.returncode:
            raise SystemExit(1)

        probe = execute(
            "fenced-probe", [
                "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
                "-format_whitelist", "ogg,mov,wav,mp3,aac",
                "-show_entries", "format=duration:stream=codec_type,duration",
                "-of", "json", str(source),
            ], fenced=True,
        )
        if probe.returncode:
            raise SystemExit(1)
        metadata = json.loads(probe.stdout)
        print("fenced-probe-codec=", [
            item.get("codec_type") for item in metadata.get("streams", [])
        ], flush=True)

        direct = execute(
            "fenced-convert", [
                "ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist",
                "file,pipe", "-format_whitelist", "ogg,mov,wav,mp3,aac",
                "-threads", "1", "-i", str(source), "-map", "0:a:0",
                "-vn", "-threads", "1", "-c:a", "libmp3lame", "-b:a", "128k",
                "-t", "16.0", "-fs", "15728640", "-y", str(folder / "direct.mp3"),
            ], fenced=True,
        )
        if direct.returncode:
            raise SystemExit(1)

        worker = execute(
            "isolated-worker", [
                sys.executable, "-I", str(Path(__file__).resolve().parents[2]
                                         / "bot/services/wan3_prime_audio_worker.py"),
                str(source), str(folder / "worker.mp3"), "15", "15728640",
                str(MAX_MEMORY_BYTES),
            ], fenced=False,
        )
        if worker.returncode:
            raise SystemExit(1)
        assert (folder / "worker.mp3").stat().st_size > 0
    print("WAN3_FFMPEG_SANDBOX_OK", flush=True)


if __name__ == "__main__":
    main()
