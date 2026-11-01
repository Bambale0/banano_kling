from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiohttp import web

from bot.handlers import publication_scope_compat as subject


async def test_failed_publication_restores_previous_personalization(monkeypatch):
    previous = [{"key": "old", "label": "Старое", "original_value": "blue coat"}]
    pending = [{"key": "new", "label": "Новое", "original_value": "chocolate cake"}]
    events = []

    async def save(generation_id, fields, *, actor_telegram_id):
        events.append(("save", generation_id, fields, actor_telegram_id))
        return "write-token", previous

    async def restore(generation_id, *, expected_token, previous_fields, actor_telegram_id):
        events.append(("restore", generation_id, expected_token, previous_fields, actor_telegram_id))
        return True

    module = SimpleNamespace(
        _miniapp_payload=AsyncMock(return_value={
            "init_data": "signed", "task_id": "task-42", "publication_scope": "feed",
            "repeat_user_fields": pending,
        }),
        _payload_bool=lambda value, default=False: bool(value) if value is not None else default,
        _optional_reference_indices=lambda *_args: None,
        _get_user_context=AsyncMock(return_value=(123456, {"user": SimpleNamespace(id=7)})),
        _repeat_personalization_allowed=lambda _actor: True,
        normalize_repeat_fields=lambda *_args, **_kwargs: pending,
        get_repeat_fields=AsyncMock(return_value=previous),
        save_repeat_fields=save,
        restore_repeat_fields_if_current=restore,
        clear_repeat_fields=AsyncMock(),
        public_repeat_fields=lambda fields: fields,
        repeat_personalization_preview_enabled=lambda: True,
        web=web,
    )
    monkeypatch.setattr(subject, "share_to_feed_scoped", AsyncMock(return_value=None))
    monkeypatch.setattr(
        subject.database,
        "get_generation_task_payload",
        AsyncMock(return_value={"id": 42, "prompt": "blue coat and chocolate cake"}),
    )
    monkeypatch.setattr(subject, "_invalidate_publication_caches", lambda: None)
    request = SimpleNamespace(app={})

    response = await subject._miniapp_generation_share_scoped(module, request)

    assert response.status == 403
    assert events == [
        ("save", 42, pending, 123456),
        ("restore", 42, "write-token", previous, 123456),
    ]
    subject.share_to_feed_scoped.assert_awaited_once()


async def test_unpublish_clears_personalization_even_when_preview_flag_is_off(monkeypatch):
    previous = [{
        "key": "old", "label": "Старое", "original_value": "blue coat",
    }]
    clear = AsyncMock(return_value=("clear-token", previous))
    module = SimpleNamespace(
        _miniapp_payload=AsyncMock(return_value={
            "init_data": "signed", "task_id": "task-42", "publication_scope": "private",
        }),
        _payload_bool=lambda value, default=False: bool(value) if value is not None else default,
        _optional_reference_indices=lambda *_args: None,
        _get_user_context=AsyncMock(return_value=(123456, {"user": SimpleNamespace(id=7)})),
        repeat_personalization_preview_enabled=lambda: False,
        get_repeat_fields=AsyncMock(return_value=previous),
        clear_repeat_fields=clear,
        restore_repeat_fields_if_current=AsyncMock(return_value=True),
        web=web,
    )
    monkeypatch.setattr(subject, "remove_publication", AsyncMock(return_value=True))
    monkeypatch.setattr(
        subject.database,
        "get_generation_task_payload",
        AsyncMock(return_value={"id": 42}),
    )
    monkeypatch.setattr(subject, "_invalidate_publication_caches", lambda: None)

    response = await subject._miniapp_generation_share_scoped(module, SimpleNamespace(app={}))

    assert response.status == 200
    clear.assert_awaited_once_with(42, actor_telegram_id=123456)
    module.restore_repeat_fields_if_current.assert_not_awaited()
