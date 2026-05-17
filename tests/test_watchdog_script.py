from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WATCHDOG = ROOT / "scripts" / "2loop_watchdog.sh"


def test_watchdog_covers_required_runtime_dependencies() -> None:
    script = WATCHDOG.read_text()

    assert "flock -n" in script
    assert "REDIS_URL" in script
    assert "redis-cli" in script
    assert "POSTGRES_DSN" in script
    assert "pg_isready" in script or "asyncpg.connect" in script
    assert "/health" in script
    assert "/api/miniapp/health" in script
    assert "2loop-bot.service" in script
