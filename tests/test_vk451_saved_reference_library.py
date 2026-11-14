"""VK reference collection is owner-isolated, idempotent and never TG-owned."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import make_mocked_request

from bot import db as db_backend
from bot.shared_accounts import api
from bot.shared_accounts.actor import PlatformActor
from bot.shared_accounts.schema import ensure_schema
from bot.shared_accounts.vk_saved_refs import (
    forget_vk_reference,
    list_vk_references,
    save_vk_reference,
)

OWNER_URL = "https://neuromixbot.com/uploads/vk-refs/image/2001/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg"
OTHER_URL = "https://neuromixbot.com/uploads/vk-refs/image/3003/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg"


@pytest.fixture(autouse=True)
async def refs_schema():
    async with db_backend.connect() as db:
        await ensure_schema(db)


@pytest.mark.asyncio
async def test_reference_owner_is_vk_not_telegram_and_save_is_idempotent(monkeypatch):
    monkeypatch.setattr("bot.shared_accounts.vk_saved_refs.verified_image_urls", lambda actor, items: items if actor == 2001 else [])
    first = await save_vk_reference(2001, OWNER_URL, "Мой референс")
    again = await save_vk_reference(2001, OWNER_URL, "Другое имя")
    assert first["reference_id"] == again["reference_id"]
    own = await list_vk_references(2001)
    assert len(own) == 1
    assert own[0]["reference_id"] == first["reference_id"]
    assert own[0]["name"] == "Мой референс"
    assert own[0]["url"] == OWNER_URL
    assert await list_vk_references(3003) == []
    assert set(own[0]) == {"reference_id", "url", "name", "created_at"}


@pytest.mark.asyncio
async def test_ownership_guard_precedes_database_write(monkeypatch):
    def guard(actor, values):
        raise ValueError("VK reference is not owned by this account")
    monkeypatch.setattr("bot.shared_accounts.vk_saved_refs.verified_image_urls", guard)
    with pytest.raises(ValueError, match="not owned"):
        await save_vk_reference(2001, OTHER_URL, "wrong")
    assert await list_vk_references(2001) == []
    assert await list_vk_references(3003) == []


@pytest.mark.asyncio
async def test_forget_is_metadata_only_owner_scoped_and_idempotent(monkeypatch):
    monkeypatch.setattr("bot.shared_accounts.vk_saved_refs.verified_image_urls", lambda actor, items: items)
    row = await save_vk_reference(2001, OWNER_URL, "test")
    assert not await forget_vk_reference(3003, row["reference_id"])
    assert len(await list_vk_references(2001)) == 1
    assert await forget_vk_reference(2001, row["reference_id"])
    assert not await forget_vk_reference(2001, row["reference_id"])
    assert await list_vk_references(2001) == []


@pytest.mark.asyncio
async def test_concurrent_duplicate_save_creates_only_one_record(monkeypatch):
    monkeypatch.setattr("bot.shared_accounts.vk_saved_refs.verified_image_urls", lambda actor, items: items)
    saved = await asyncio.gather(*[
        save_vk_reference(2001, OWNER_URL, "same")
        for _ in range(6)
    ])
    assert len({item["reference_id"] for item in saved}) == 1
    assert len(await list_vk_references(2001)) == 1


@pytest.mark.asyncio
async def test_limit_prevents_unbounded_reference_metadata(monkeypatch):
    monkeypatch.setenv("VK_MINIAPP_SAVED_REF_MAX_ITEMS", "1")
    monkeypatch.setattr("bot.shared_accounts.vk_saved_refs.verified_image_urls", lambda actor, items: items)
    await save_vk_reference(2001, OWNER_URL, "first")
    with pytest.raises(ValueError, match="limit"):
        await save_vk_reference(2001, OTHER_URL, "second")
    assert len(await list_vk_references(2001)) == 1


@pytest.mark.asyncio
async def test_invalid_reference_names_and_ids_fail_closed(monkeypatch):
    monkeypatch.setattr("bot.shared_accounts.vk_saved_refs.verified_image_urls", lambda actor, items: items)
    for name in ("", "a" * 81, "hello\x00world"):
        with pytest.raises(ValueError):
            await save_vk_reference(2001, OWNER_URL, name)
    with pytest.raises(ValueError):
        await save_vk_reference(True, OWNER_URL, "test")
    with pytest.raises(ValueError):
        await forget_vk_reference(2001, "bad")


def _request(method):
    return make_mocked_request(method, "/mini-app/api/account-preview/vk-references",
                               headers={"Authorization": "Bearer test-session"})


@pytest.mark.asyncio
async def test_signed_vk_library_route_does_not_accept_client_selected_user_id(monkeypatch):
    actor = PlatformActor(platform="vk", external_id=2001, shared_account_id="a" * 32,
                          linked_platforms=("vk",), linked_telegram_id=None)
    auth = AsyncMock(return_value=actor)
    monkeypatch.setattr(api, "resolve_platform_actor", auth)
    listing = AsyncMock(return_value=[{"reference_id": "f" * 32, "name": "a",
                                       "url": OWNER_URL, "created_at": "2026-11-13"}])
    monkeypatch.setattr(api, "list_vk_references", listing)
    result = await api.vk_reference_library(_request("GET"))
    assert result.status == 200
    assert json.loads(result.text)["references"][0]["name"] == "a"
    listing.assert_awaited_once_with(2001)
    auth.assert_awaited_once_with("test-session", expected_platform="vk")
    fake_body = AsyncMock(return_value={"action": "save", "url": OWNER_URL, "name": "new", "user_id": 3003})
    monkeypatch.setattr(api, "_body", fake_body)
    with pytest.raises(ValueError):
        await api.vk_reference_library(_request("POST"))


@pytest.mark.asyncio
async def test_linked_actor_can_manage_existing_native_references_without_tg_wallet(monkeypatch):
    actor = PlatformActor(platform="vk", external_id=2001, shared_account_id="a" * 32,
                          linked_platforms=("vk", "telegram"), linked_telegram_id=987)
    monkeypatch.setattr(api, "resolve_platform_actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(api, "_body", AsyncMock(return_value={"action": "forget", "reference_id": "c" * 32}))
    forgetting = AsyncMock(return_value=True)
    monkeypatch.setattr(api, "forget_vk_reference", forgetting)
    response = await api.vk_reference_library(_request("POST"))
    assert response.status == 200
    assert json.loads(response.text) == {"ok": True, "deleted": True}
    forgetting.assert_awaited_once_with(2001, "c" * 32)
