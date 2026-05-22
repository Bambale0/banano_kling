import pytest


@pytest.fixture
def temp_db_path(tmp_path):
    """Temporary database path"""
    return tmp_path / "test.db"


@pytest.fixture(autouse=True)
async def isolated_database(tmp_path, monkeypatch):
    """Run every test against a fresh SQLite database, never the live bot.db."""
    from bot import database

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
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
    monkeypatch.setenv("PAYMENT_PROVIDER", "tbank")
