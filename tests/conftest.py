import os

# This must be set while pytest loads conftest, before test modules import
# bot.config. Unit and integration tests must never read production .env files.
os.environ["BANANO_SKIP_PROJECT_ENV"] = "1"
os.environ["BOT_TOKEN"] = "test:fake-bot-token"
os.environ["ADMIN_IDS"] = "999999999"

import pytest


@pytest.fixture(autouse=True)
def mock_external_feed_downloads(monkeypatch):
    """Keep feed database tests deterministic and free of network side effects."""
    from bot.services import feed_persist

    async def fake_download(_url: str, max_size_bytes: int = 50 * 1024 * 1024):
        del max_size_bytes
        return "https://test.example.com/uploads/feed/test-result.png"

    monkeypatch.setattr(feed_persist, "download_to_local", fake_download)


@pytest.fixture
def temp_db_path(tmp_path):
    """Temporary database path"""
    return tmp_path / "test.db"


@pytest.fixture(autouse=True)
async def isolated_database(tmp_path, monkeypatch):
    """Run every test against a fresh SQLite database, never the live bot.db."""
    db_path = tmp_path / "test.db"
    sqlite_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    from bot import database
    from bot import db as db_backend

    monkeypatch.setattr(db_backend, "DATABASE_URL", sqlite_url)
    monkeypatch.setattr(db_backend, "DATABASE_PATH", str(db_path))
    monkeypatch.setattr(database, "DATABASE_PATH", str(db_path))
    await database.init_db()
    yield


@pytest.fixture
def mock_env(monkeypatch):
    """Mock common environment variables"""
    monkeypatch.setenv("BOT_TOKEN", "test_bot_token")
    monkeypatch.setenv("ADMIN_IDS", "123456,789012")
    monkeypatch.setenv("WEBHOOK_HOST", "https://test.example.com")
    monkeypatch.setenv("WEBHOOK_PATH", "/webhook")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("PAYMENT_PROVIDER", "yookassa")
