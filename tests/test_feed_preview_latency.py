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
