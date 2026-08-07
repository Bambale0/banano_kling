from __future__ import annotations

import os

import pytest

from bot.services import payment_email_store as store


@pytest.mark.asyncio
async def test_payment_email_is_saved_in_server_local_database(tmp_path, monkeypatch):
    database_path = tmp_path / "private" / "payment-emails.sqlite3"
    monkeypatch.setattr(store, "DATABASE_PATH", database_path)
    monkeypatch.setattr(store, "_SCHEMA_READY", False)
    monkeypatch.setattr(store, "_SCHEMA_LOCK", None)

    saved = await store.save_payment_email(12345, "User2026@Mail.Ru")

    assert saved == "user2026@mail.ru"
    assert await store.get_payment_email(12345) == "user2026@mail.ru"
    assert await store.has_payment_email(12345) is True
    assert await store.has_payment_email(99999) is False
    assert database_path.exists()

    if os.name == "posix":
        assert database_path.stat().st_mode & 0o777 == 0o600
        assert database_path.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.asyncio
async def test_payment_email_update_replaces_previous_value(tmp_path, monkeypatch):
    database_path = tmp_path / "payment-emails.sqlite3"
    monkeypatch.setattr(store, "DATABASE_PATH", database_path)
    monkeypatch.setattr(store, "_SCHEMA_READY", False)
    monkeypatch.setattr(store, "_SCHEMA_LOCK", None)

    await store.save_payment_email(77, "first@mail.ru")
    await store.save_payment_email(77, "second@mail.ru")

    assert await store.get_payment_email(77) == "second@mail.ru"
