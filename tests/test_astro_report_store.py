"""Durable Astro checkpoints: owner isolation, dedupe and privacy deletion."""

import asyncio

import pytest

from bot.services.astro_report_store import AstroReportSqlStore


@pytest.fixture(autouse=True)
def sqlite_backend(monkeypatch):
    # Tests must never connect to production PostgreSQL.
    monkeypatch.setenv("DATABASE_URL", "")


def test_owner_scoped_checkpoint_idempotency_and_erasure(tmp_path):
    async def scenario():
        store = AstroReportSqlStore(db_path=str(tmp_path / "astro.sqlite"))
        fingerprint = "a" * 64
        first = await store.save_if_absent(
            owner_id=101, fingerprint=fingerprint, section_id="section_01", text="First response"
        )
        duplicate = await store.save_if_absent(
            owner_id=101, fingerprint=fingerprint, section_id="section_01", text="Must not replace"
        )
        assert first == "First response"
        assert duplicate == first
        assert await store.read(owner_id=101, fingerprint=fingerprint, section_id="section_01") == first
        assert await store.read(owner_id=202, fingerprint=fingerprint, section_id="section_01") is None
        await store.save_if_absent(
            owner_id=202, fingerprint=fingerprint, section_id="section_01", text="Other owner"
        )
        assert await store.delete_owner(owner_id=101) == 1
        assert await store.read(owner_id=101, fingerprint=fingerprint, section_id="section_01") is None
        assert await store.read(owner_id=202, fingerprint=fingerprint, section_id="section_01") == "Other owner"

    asyncio.run(scenario())


def test_fingerprint_rejects_bad_values(tmp_path):
    async def scenario():
        store = AstroReportSqlStore(db_path=str(tmp_path / "astro.sqlite"))
        for owner_id, fingerprint, section_id in [
            (-1, "a" * 64, "one"),
            (123, "not-a-fingerprint", "one"),
            (123, "a" * 64, "../other"),
        ]:
            with pytest.raises(ValueError):
                await store.read(owner_id=owner_id, fingerprint=fingerprint, section_id=section_id)
    asyncio.run(scenario())


def test_expired_checkpoint_cleanup(tmp_path, monkeypatch):
    import bot.services.astro_report_store as module
    initial = 1_700_000_000
    monkeypatch.setattr(module.time, "time", lambda: initial)

    async def scenario():
        store = AstroReportSqlStore(db_path=str(tmp_path / "astro.sqlite"))
        fingerprint = "b" * 64
        await store.save_if_absent(
            owner_id=91, fingerprint=fingerprint, section_id="section_01", text="Old report"
        )
        assert await store.read(owner_id=91, fingerprint=fingerprint, section_id="section_01") == "Old report"
        monkeypatch.setattr(module.time, "time", lambda: initial + 366 * 86400)
        assert await store.read(owner_id=91, fingerprint=fingerprint, section_id="section_01") is None
        assert await store.purge_expired() == 1
        assert await store.read(owner_id=91, fingerprint=fingerprint, section_id="section_01") is None

    asyncio.run(scenario())
