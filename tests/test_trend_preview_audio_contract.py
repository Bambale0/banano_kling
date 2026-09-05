from pathlib import Path

from bot.services import trend_preview_service


def test_lightweight_trend_preview_preserves_optional_audio(monkeypatch, tmp_path: Path):
    source = tmp_path / "source.mov"
    source.write_bytes(b"source")
    output = tmp_path / "preview.mp4"
    captured: list[str] = []

    def fake_run(command, *, check, timeout):
        assert check is True
        assert timeout == 120
        captured.extend(command)
        Path(command[-1]).write_bytes(b"preview")

    monkeypatch.setattr(trend_preview_service.subprocess, "run", fake_run)

    trend_preview_service._run_ffmpeg_preview(source, output)

    assert output.exists()
    assert "-an" not in captured
    assert captured[captured.index("-map") + 1] == "0:v:0"
    audio_map = captured.index("-map", captured.index("-map") + 1)
    assert captured[audio_map + 1] == "0:a:0?"
    assert captured[captured.index("-c:a") + 1] == "aac"
    assert captured[captured.index("-b:a") + 1] == "96k"
    assert trend_preview_service.TREND_PREVIEW_VERSION == "full-v3-audio"
