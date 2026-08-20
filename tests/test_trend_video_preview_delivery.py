import pytest

from bot import browser_auth


@pytest.mark.asyncio
async def test_public_trend_video_uses_compatible_preview(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_preview(url: str | None) -> str | None:
        calls.append(str(url or ""))
        return "https://example.test/uploads/trend-previews/compatible.mp4"

    monkeypatch.setattr(
        browser_auth,
        "ensure_lightweight_trend_preview_url",
        fake_preview,
    )
    payload = {
        "prompts": [
            {
                "id": 1126,
                "tags": ["trend", "trend-video"],
                "preview_url": "/uploads/refs/video/source.mov",
            },
            {
                "id": 7,
                "tags": ["portrait"],
                "preview_url": "/uploads/ordinary.mp4",
            },
        ]
    }

    result = await browser_auth._with_compatible_trend_previews(payload)

    assert calls == ["/uploads/refs/video/source.mov"]
    assert result["prompts"][0]["preview_url"].endswith("compatible.mp4")
    assert result["prompts"][1]["preview_url"] == "/uploads/ordinary.mp4"


@pytest.mark.asyncio
async def test_trend_without_preview_is_left_untouched(monkeypatch) -> None:
    async def should_not_run(url: str | None) -> str | None:
        raise AssertionError("preview service should not run")

    monkeypatch.setattr(
        browser_auth,
        "ensure_lightweight_trend_preview_url",
        should_not_run,
    )
    payload = {"prompt": {"id": 1, "tags": ["trend"], "preview_url": ""}}
    assert await browser_auth._with_compatible_trend_previews(payload) == payload
