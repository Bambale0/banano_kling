import io

from PIL import Image

from bot.config import config
from bot.services.feed_preview import feed_media_url, feed_preview_url, load_feed_preview_bytes


def test_feed_media_url_makes_upload_paths_absolute(monkeypatch):
    monkeypatch.setattr(config, "WEBHOOK_HOST", "https://bot.example.test")

    assert (
        feed_media_url("/uploads/feed/task.jpg")
        == "https://bot.example.test/uploads/feed/task.jpg"
    )
    assert (
        feed_media_url("uploads/feed/task.jpg")
        == "https://bot.example.test/uploads/feed/task.jpg"
    )


def test_feed_media_url_keeps_external_urls():
    assert (
        feed_media_url("https://cdn.example.test/task.jpg")
        == "https://cdn.example.test/task.jpg"
    )
    assert feed_media_url("//cdn.example.test/task.jpg") == "https://cdn.example.test/task.jpg"


def test_feed_preview_cache_creates_small_local_preview(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "WEBHOOK_HOST", "https://bot.example.test")
    image_path = tmp_path / "static" / "uploads" / "feed" / "task.png"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (2400, 1600), "red").save(image_path)

    preview_bytes = load_feed_preview_bytes("task", "/uploads/feed/task.png")
    preview_url = feed_preview_url("task", "/uploads/feed/task.png")

    assert preview_bytes
    with Image.open(io.BytesIO(preview_bytes)) as preview:
        assert max(preview.size) <= 960
        assert preview.format == "JPEG"
    assert preview_url.startswith("https://bot.example.test/uploads/feed_previews/")
    assert (tmp_path / "static" / "uploads" / "feed_previews").is_dir()
