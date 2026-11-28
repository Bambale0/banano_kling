"""Latency contracts for public feed cards and stable S3 thumbnails."""

import asyncio
import threading
import time

import pytest

from bot import database
from bot.services import feed_persist


@pytest.mark.asyncio
async def test_public_feed_card_serialization_keeps_telegram_loop_responsive(monkeypatch):
    start = time.monotonic()
    loop = asyncio.get_running_loop()
    callback_delays = []

    def slow_s3_card(row, **_kwargs):
        time.sleep(0.20)
        return {"id": row["id"]}

    monkeypatch.setattr(database, "_generation_row_to_card", slow_s3_card)
    timer = threading.Timer(
        0.02,
        lambda: loop.call_soon_threadsafe(
            lambda: callback_delays.append(time.monotonic() - start)
        ),
    )
    timer.start()
    try:
        cards = await database._serialize_feed_cards_nonblocking(
            [{"id": 1}, {"id": 2}, {"id": 3}], viewer_user_id=123, include_unavailable=True
        )
    finally:
        timer.join(timeout=1)
    assert [card["id"] for card in cards] == [1, 2, 3]
    assert callback_delays and callback_delays[0] < 0.11


def test_positive_s3_thumbnail_is_cached_without_rechecking_remote(monkeypatch, tmp_path):
    from bot.services import media_storage

    source = tmp_path / "positive-feed-photo.png"
    thumbnail = tmp_path / "positive-feed-photo.jpg"
    calls = []
    monkeypatch.setattr(feed_persist, "_local_feed_upload_path", lambda _: source)
    monkeypatch.setattr(feed_persist, "_thumbnail_paths", lambda _: (thumbnail, tmp_path / "old.webp"))
    monkeypatch.setattr(media_storage, "is_s3_enabled", lambda: True)
    monkeypatch.setattr(media_storage, "upload_exists", lambda relative: calls.append(relative) or True)
    monkeypatch.setattr(media_storage, "public_upload_url", lambda relative: f"https://example.test/uploads/{relative}")
    monkeypatch.setattr(feed_persist, "ensure_feed_thumbnail", lambda _: None)

    one = feed_persist.feed_thumbnail_url_for("https://example.test/uploads/feed/positive-feed-photo.png")
    two = feed_persist.feed_thumbnail_url_for("https://example.test/uploads/feed/positive-feed-photo.png")
    assert one == two
    assert len(calls) == 1


def test_missing_s3_thumbnail_retries_on_next_request(monkeypatch, tmp_path):
    from bot.services import media_storage

    source = tmp_path / "missed-feed-photo.png"
    thumbnail = tmp_path / "missed-feed-photo.jpg"
    calls = []
    monkeypatch.setattr(feed_persist, "_local_feed_upload_path", lambda _: source)
    monkeypatch.setattr(feed_persist, "_thumbnail_paths", lambda _: (thumbnail, tmp_path / "old.webp"))
    monkeypatch.setattr(media_storage, "is_s3_enabled", lambda: True)
    monkeypatch.setattr(media_storage, "upload_exists", lambda _: calls.append(1) or len(calls) > 1)
    monkeypatch.setattr(media_storage, "public_upload_url", lambda relative: f"https://example.test/uploads/{relative}")
    monkeypatch.setattr(feed_persist, "ensure_feed_thumbnail", lambda _: None)

    one = feed_persist.feed_thumbnail_url_for("https://example.test/uploads/feed/missed-feed-photo.png")
    two = feed_persist.feed_thumbnail_url_for("https://example.test/uploads/feed/missed-feed-photo.png")
    assert one is None
    assert two and two.endswith("/feed/thumbs/missed-feed-photo.jpg")
    assert len(calls) == 2


@pytest.mark.parametrize("viewer_id", [42, 99])
def test_feed_card_does_not_download_originals_or_references(monkeypatch, viewer_id):
    import json
    from bot.services import media_input_utils

    base = "https://neuromixbot.com/uploads/"
    result = base + "feed/result.png"
    ref = base + "refs/image/ref.png"
    missing = base + "refs/image/missing.png"
    probes = []
    downloads = []
    monkeypatch.setattr(media_input_utils, "is_local_upload_source", lambda url: url.startswith(base))
    monkeypatch.setattr(media_input_utils, "local_upload_presence_without_download",
                        lambda url: probes.append(url) or url != missing)
    monkeypatch.setattr(media_input_utils, "resolve_local_upload_path",
                        lambda url: downloads.append(url) or "/fake/media")
    monkeypatch.setattr(feed_persist, "feed_thumbnail_url_for", lambda url: None)
    row = {"id": 1, "task_id": "test", "user_id": 42, "model": "nano_banana_2",
           "preset_id": "", "type": "image", "result_url": result, "result_urls": "[]",
           "request_data": json.dumps({"reference_images": [ref, missing]}),
           "prompt": "test", "likes_count": 0, "shares_count": 0, "aspect_ratio": "1:1",
           "created_at": "2026-11-28 10:00:00", "is_public_feed": 1,
           "feed_prompt_visible": 1, "feed_references_visible": 1}
    card = database._generation_row_to_card(row, viewer_user_id=viewer_id)
    assert card["result_url"] == result
    assert card["reference_images"] == ([ref] if viewer_id == 42 else [])
    assert not downloads
    assert result in probes and ref in probes and missing in probes
