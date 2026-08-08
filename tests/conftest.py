import os

# This must be set while pytest loads conftest, before test modules import
# bot.config. Unit and integration tests must never read production .env files.
os.environ["BANANO_SKIP_PROJECT_ENV"] = "1"
_PARTNER_POSTGRES_TEST = str(os.getenv("PARTNER_POSTGRES_TEST", "")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# A developer may run pytest from a production-like shell where values from
# `.env` are already exported. Skipping dotenv loading alone is insufficient in
# that case, so remove every application setting present in the production env
# contract before bot modules are imported. The dedicated partner PostgreSQL
# job is the only exception: it must preserve its explicit ephemeral CI DSN.
for _name in (
    "ALLOW_NSFW", "CRYPTOBOT_API_TOKEN", "DATABASE_URL", "DEBUG",
    "DOWNLOAD_EXTERNAL_IMAGES", "FREEKASSA_API_KEY", "FREEKASSA_CURRENCY",
    "FREEKASSA_MERCHANT_ID", "FREEKASSA_SECRET_WORD", "FREEKASSA_SECRET_WORD_2",
    "FREEKASSA_VERIFY_IP", "FREEKASSA_WEBHOOK_PATH", "INTERNAL_API_ALLOWED_NETWORKS",
    "INTERNAL_API_MAX_CLOCK_SKEW_SECONDS", "INTERNAL_API_SECRET",
    "INTERNAL_API_SERVICE_VERSION", "KIE_AI_API_KEY", "KIE_AI_WEBHOOK_SECRET",
    "LAVA_API_BASE_URL", "LAVA_API_KEY", "LAVA_DEFAULT_EMAIL",
    "LAVA_OFFER_ID_BUSINESS", "LAVA_OFFER_ID_MINI", "LAVA_OFFER_ID_OPTIMAL",
    "LAVA_OFFER_ID_PRO", "LAVA_OFFER_ID_START", "LAVA_OFFER_ID_STUDIO",
    "LAVA_WEBHOOK_PATH", "LAVA_WEBHOOK_SECRET", "MINI_APP_URL",
    "NANOBANANA2_FALLBACK_API_KEY", "NANOBANANA2_FALLBACK_BASE_URL",
    "NANO_BANANA_PRO_FALLBACK_API_KEY", "NANO_BANANA_PRO_FALLBACK_BASE_URL",
    "PARTNER_MIN_WITHDRAWAL_RUB", "PAYMENT_PROVIDER", "REDIS_PREFIX", "REDIS_URL",
    "REFERRAL_ANTIFRAUD_BLOCK_CODES", "REFERRAL_ANTIFRAUD_BLOCK_REFERRER_IDS",
    "REFERRAL_ANTIFRAUD_BURST_MAX", "REFERRAL_ANTIFRAUD_BURST_WINDOW_SECONDS",
    "REFERRAL_ANTIFRAUD_MAX_PER_DAY", "REFERRAL_ANTIFRAUD_MAX_PER_HOUR",
    "STATIC_BASE_URL", "TELEGRAM_STARS_FLAT_FEE", "TELEGRAM_STARS_PER_RUB",
    "WEBHOOK_HOST", "WEBHOOK_PATH", "WEBHOOK_PORT", "YOOKASSA_RETURN_URL",
    "YOOKASSA_SECRET_KEY", "YOOKASSA_SHOP_ID", "YOOKASSA_WEBHOOK_URL",
):
    if _PARTNER_POSTGRES_TEST and _name == "DATABASE_URL":
        continue
    os.environ.pop(_name, None)

os.environ["BOT_TOKEN"] = "test:fake-bot-token"
os.environ["ADMIN_IDS"] = "999999999"

# Paid live tests are a separate, explicitly enabled suite. Excluding the
# directory during normal collection also prevents module-level provider setup
# from affecting the isolated unit-test process.
collect_ignore_glob = (
    []
    if str(os.getenv("BANANO_LIVE_SMOKE", "")).strip().lower() in {"1", "true", "yes", "on"}
    else ["live/test_*.py"]
)

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
    """Use SQLite by default; dedicated partner CI may opt into ephemeral PostgreSQL."""
    if _PARTNER_POSTGRES_TEST:
        from bot import db as db_backend

        assert db_backend.is_postgres()
        # Production PostgreSQL already has the legacy base schema. The focused
        # partner test bootstraps that minimal schema directly before exercising
        # the normal postgres_aiosqlite runtime adapter.
        yield
        return

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
