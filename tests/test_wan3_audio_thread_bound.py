"""Wan FFmpeg audio conversion must fit the existing 512 MiB sandbox."""
import json
from pathlib import Path
from types import SimpleNamespace

from bot.services import wan3_prime_audio_worker as worker


def test_audio_worker_caps_filter_threads_without_weakening_sandbox(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "ffprobe":
            return SimpleNamespace(stdout=json.dumps({
                "streams": [{"codec_type": "audio"}],
                "format": {"duration": "1.2"},
            }))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    worker.transcode(
        Path("/tmp/synthetic-audio.ogg"), Path("/tmp/synthetic-converted.mp3"),
        15.0, 15_728_640,
    )
    assert len(calls) == 2
    cmd = calls[1][0]
    assert cmd[cmd.index("-filter_threads") + 1] == "1"
    # Keep codec thread caps, protocol whitelist and file size limits.
    assert cmd.count("-threads") >= 2
    assert all(cmd[index + 1] == "1" for index, arg in enumerate(cmd) if arg == "-threads")
    assert cmd[cmd.index("-protocol_whitelist") + 1] == "file,pipe"
    assert cmd[cmd.index("-fs") + 1] == "15728640"
    assert calls[1][1]["check"] is True
    assert calls[1][1]["timeout"] == 15
