from pathlib import Path

from bot import postgres_pool


def test_runtime_image_uses_postgresql_16_client_for_pg16_backups() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    runtime = dockerfile.split("FROM python:3.12-slim-bookworm AS runtime", 1)[1]
    assert "apt.postgresql.org" in runtime
    assert "postgresql-client-16" in runtime


def test_postgres_pool_defaults_absorb_short_production_bursts(monkeypatch) -> None:
    monkeypatch.delenv("PG_POOL_MIN_SIZE", raising=False)
    monkeypatch.delenv("PG_POOL_MAX_SIZE", raising=False)
    monkeypatch.delenv("PG_POOL_TIMEOUT_SECONDS", raising=False)

    assert postgres_pool._pool_min_size() == 2
    assert postgres_pool._pool_max_size() == 24
    assert postgres_pool._pool_timeout() == 10.0


def test_ios_image_uploads_prefer_json_transport() -> None:
    api = Path("frontend/miniapp-v0/lib/api.ts").read_text(encoding="utf-8")

    assert "function shouldPreferJsonUpload" in api
    assert "iPhone|iPad|iPod" in api
    assert "fileKind !== 'image_reference'" in api
    assert "IOS_JSON_UPLOAD_MAX_BYTES" in api
    assert "upload-json-preferred-start" in api
    assert "const data = await uploadFileAsJson(" in api
