"""Telegram promo editor tests: all Telegram/service effects are faked."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import promo_admin


@pytest.mark.asyncio
async def test_non_admin_cannot_open_saved_promos(monkeypatch):
    monkeypatch.setattr(promo_admin.config, "is_admin", lambda _uid: False)
    callback = SimpleNamespace(data="admin_broadcast", from_user=SimpleNamespace(id=12), answer=AsyncMock())
    state = SimpleNamespace(clear=AsyncMock())
    await promo_admin.open_promos(callback, state)
    callback.answer.assert_awaited_once_with("⛔ Нет доступа", show_alert=True)
    state.clear.assert_not_awaited()

class FakeState:
    def __init__(self):
        self.data = {}
        self.state = None

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **values):
        self.data.update(values)

    async def clear(self):
        self.data = {}
        self.state = None

    async def get_state(self):
        return self.state

    async def set_state(self, value):
        self.state = value.state if hasattr(value, "state") else value


def callback(data="admin_broadcast"):
    card = SimpleNamespace(chat=SimpleNamespace(id=999999999), message_id=100)
    sent = SimpleNamespace(message_id=1000)
    card.edit_text = AsyncMock(return_value=card)
    card.answer = AsyncMock(return_value=sent)
    return SimpleNamespace(data=data, from_user=SimpleNamespace(id=999999999), message=card, bot=SimpleNamespace(), answer=AsyncMock())


def incoming(mid=1001, text=None, photo=None, group=None):
    return SimpleNamespace(from_user=SimpleNamespace(id=999999999), chat=SimpleNamespace(id=999999999), message_id=mid, text=text, caption=None, entities=None, caption_entities=None, photo=[SimpleNamespace(file_id=photo)] if photo else None, video=None, media_group_id=group, answer=AsyncMock(return_value=SimpleNamespace(message_id=1000)))


class FakeService:
    class PromoError(Exception):
        pass

    def __init__(self):
        import copy
        self.copy = copy.deepcopy
        self.record = {"id": 1, "revision": 1, "status": "draft", "message": {"schema_version": 2, "text": "Привет", "parse_mode": "HTML", "media": [], "buttons": []}, "ready": False, "content_hash": "one", "tested_content_hash": None, "test_summary": None, "audience_count": 12, "trend_titles": {"7": "Тестовый тренд"}}
        self.test_promo = AsyncMock()
        self.start_promo = AsyncMock(side_effect=self.start)
        self.create_promo = AsyncMock(side_effect=self.create)
        self.duplicate_promo = AsyncMock(side_effect=self.duplicate)
        self.save_promo = AsyncMock(side_effect=self.save)
        self.search_trends = AsyncMock(return_value={"items": [{"id": 7, "title": "Тестовый тренд"}], "has_more": False})

    async def get_promo(self, _id, _admin):
        return self.copy(self.record)

    async def list_promos(self, *_args, **_kwargs):
        return [self.copy(self.record)]

    async def create(self, *_args, **_kwargs):
        return self.copy(self.record)

    async def duplicate(self, *_args, **_kwargs):
        self.record["id"] += 1
        return self.copy(self.record)

    async def save(self, _id, _admin, message, *, expected_revision):
        assert self.record["revision"] == expected_revision
        self.record.update(message=self.copy(message), revision=expected_revision + 1, ready=False, tested_content_hash=None, test_summary=None, content_hash=f"revision-{expected_revision + 1}")
        return self.copy(self.record)

    async def start(self, *_args, **_kwargs):
        self.record["status"] = "queued"

    def ready(self):
        self.record.update(ready=True, tested_content_hash=self.record["content_hash"], test_summary={"status": "completed", "content_hash": self.record["content_hash"], "sent": 1, "failed": 0})


@pytest.fixture
def editor(monkeypatch):
    service = FakeService()
    monkeypatch.setattr(promo_admin, "_service", lambda: service)
    monkeypatch.setattr(promo_admin.config, "is_admin", lambda uid: uid == 999999999)
    return service, FakeState(), callback()


async def show(editor):
    service, state, cb = editor
    cb.data = "admin_pr:open:1"
    await promo_admin.promo_callback(cb, state)
    return service, state, cb


def action(state, name, arg=None):
    value = f"admin_pr:{name}:{state.data['promo_id']}:{state.data['promo_revision']}:{state.data['promo_token']}"
    return value if arg is None else f"{value}:{arg}"


@pytest.mark.asyncio
async def test_album_is_persisted_in_order_without_automatic_finalize(editor):
    import asyncio
    service, state, cb = await show(editor)
    cb.data = action(state, "media")
    await promo_admin.promo_callback(cb, state)
    await asyncio.gather(promo_admin.promo_message(incoming(1002, photo="second", group="album"), state), promo_admin.promo_message(incoming(1001, photo="first", group="album"), state))
    assert [item["file_id"] for item in service.record["message"]["media"]] == ["first", "second"]
    assert state.state == promo_admin.PromoAdminStates.media.state
    service.test_promo.assert_not_awaited()
    service.start_promo.assert_not_awaited()
    cb.data = action(state, "done")
    await promo_admin.promo_callback(cb, state)
    assert state.state is None


def displayed_callbacks(cb):
    markup = cb.message.edit_text.await_args.kwargs["reply_markup"]
    return [button.callback_data for row in markup.inline_keyboard for button in row]


@pytest.mark.asyncio
async def test_create_double_click_creates_one_draft_without_sending(editor):
    service, state, cb = editor
    await promo_admin.open_promos(cb, state)
    cb.data = f"admin_pr:new:{state.data['promo_token']}"
    await promo_admin.promo_callback(cb, state)
    await promo_admin.promo_callback(cb, state)
    service.create_promo.assert_awaited_once()
    service.test_promo.assert_not_awaited()
    service.start_promo.assert_not_awaited()


@pytest.mark.asyncio
async def test_edit_text_invalidates_ready_and_replayed_save_is_ignored(editor):
    service, state, cb = editor
    service.ready()
    await show(editor)
    assert any(":confirm:" in item for item in displayed_callbacks(cb))
    cb.data = action(state, "text")
    await promo_admin.promo_callback(cb, state)
    msg = incoming(text="Новый <b>текст</b>")
    await promo_admin.promo_message(msg, state)
    await promo_admin.promo_message(msg, state)
    assert service.record["message"]["text"] == "Новый <b>текст</b>"
    assert not service.record["ready"]
    service.save_promo.assert_awaited_once()
    service.start_promo.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_revision_cannot_edit_or_test(editor):
    service, state, cb = await show(editor)
    old_test = action(state, "test")
    old_clear = action(state, "clear")
    service.record["revision"] += 1
    cb.data = old_clear
    await promo_admin.promo_callback(cb, state)
    cb.data = old_test
    await promo_admin.promo_callback(cb, state)
    service.save_promo.assert_not_awaited()
    service.test_promo.assert_not_awaited()
    assert cb.answer.await_args.kwargs["show_alert"]


@pytest.mark.asyncio
async def test_cancelled_album_cannot_append_to_new_upload(editor):
    service, state, cb = await show(editor)
    cb.data = action(state, "media")
    await promo_admin.promo_callback(cb, state)
    await promo_admin.promo_message(incoming(1001, photo="first", group="old-album"), state)
    cb.data = action(state, "cancel")
    await promo_admin.promo_callback(cb, state)
    cb.data = action(state, "media")
    await promo_admin.promo_callback(cb, state)
    await promo_admin.promo_message(incoming(1002, photo="late", group="old-album"), state)
    assert len(service.record["message"]["media"]) == 1
    service.save_promo.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_ignores_updates_older_than_fresh_prompt(editor):
    service, state, cb = await show(editor)
    cb.message.answer.return_value.message_id = 2000
    cb.data = action(state, "media")
    await promo_admin.promo_callback(cb, state)
    await promo_admin.promo_message(incoming(1999, photo="late", group="unknown-old-group"), state)
    service.save_promo.assert_not_awaited()


@pytest.mark.asyncio
async def test_replayed_album_item_and_eleventh_item_are_not_appended(editor):
    service, state, cb = await show(editor)
    cb.data = action(state, "media")
    await promo_admin.promo_callback(cb, state)
    for index in range(10):
        await promo_admin.promo_message(incoming(1001 + index, photo=f"photo-{index}", group="album"), state)
    await promo_admin.promo_message(incoming(1001, photo="photo-0", group="album"), state)
    await promo_admin.promo_message(incoming(1011, photo="photo-11"), state)
    assert len(service.record["message"]["media"]) == 10
    assert service.save_promo.await_count == 10
    service.test_promo.assert_not_awaited()


@pytest.mark.asyncio
async def test_media_reorder_remove_and_new_append_preserve_order(editor):
    service, state, cb = await show(editor)
    cb.data = action(state, "media")
    await promo_admin.promo_callback(cb, state)
    await promo_admin.promo_message(incoming(1001, photo="first"), state)
    await promo_admin.promo_message(incoming(1002, photo="second"), state)
    cb.data = action(state, "up", 1)
    await promo_admin.promo_callback(cb, state)
    assert [item["file_id"] for item in service.record["message"]["media"]] == ["second", "first"]
    cb.data = action(state, "remove", 1)
    await promo_admin.promo_callback(cb, state)
    await promo_admin.promo_message(incoming(1003, photo="third"), state)
    assert [item["file_id"] for item in service.record["message"]["media"]] == ["second", "third"]


async def choose_button(editor):
    service, state, cb = await show(editor)
    cb.data = action(state, "buttons")
    await promo_admin.promo_callback(cb, state)
    cb.data = action(state, "label", 0)
    await promo_admin.promo_callback(cb, state)
    await promo_admin.promo_message(incoming(text="Попробовать тренд"), state)
    await promo_admin.promo_message(incoming(1002, text="Тестовый"), state)
    return service, state, cb


@pytest.mark.asyncio
async def test_button_is_atomic_and_cancel_preserves_test_readiness(editor):
    service, state, cb = editor
    service.ready()
    await choose_button(editor)
    service.save_promo.assert_not_awaited()
    assert service.record["message"]["buttons"] == []
    cb.data = action(state, "cancel")
    await promo_admin.promo_callback(cb, state)
    assert service.record["ready"]


@pytest.mark.asyncio
async def test_search_selection_saves_atomic_button_and_invalidates_test(editor):
    service, state, cb = editor
    service.ready()
    await choose_button(editor)
    cb.data = action(state, "pick", 0)
    await promo_admin.promo_callback(cb, state)
    assert service.record["message"]["buttons"] == [{"position": 1, "text": "Попробовать тренд", "action": "trend", "trend_id": 7}]
    assert not service.record["ready"]
    service.save_promo.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_search_and_cancelled_selection_cannot_save(editor):
    service, state, cb = await choose_button(editor)
    old_pick = action(state, "pick", 0)
    await promo_admin.promo_message(incoming(1003, text="Новый поиск"), state)
    current_pick = action(state, "pick", 0)
    cb.data = old_pick
    await promo_admin.promo_callback(cb, state)
    service.save_promo.assert_not_awaited()
    cb.data = action(state, "cancel")
    await promo_admin.promo_callback(cb, state)
    cb.data = current_pick
    await promo_admin.promo_callback(cb, state)
    service.save_promo.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_pagination_uses_server_query_and_rejects_old_page(editor):
    service, state, cb = await choose_button(editor)
    page = action(state, "page", 1)
    cb.data = page
    await promo_admin.promo_callback(cb, state)
    service.search_trends.assert_awaited_with("Тестовый", page=1, size=8)
    count = service.search_trends.await_count
    await promo_admin.promo_callback(cb, state)
    assert service.search_trends.await_count == count


@pytest.mark.asyncio
async def test_button_label_limit_and_two_button_max(editor):
    service, state, cb = await show(editor)
    cb.data = action(state, "label", 0)
    await promo_admin.promo_callback(cb, state)
    await promo_admin.promo_message(incoming(text="a" * 65), state)
    assert state.state == promo_admin.PromoAdminStates.button_label.state
    service.search_trends.assert_not_awaited()
    service.save_promo.assert_not_awaited()
    cb.data = action(state, "cancel")
    await promo_admin.promo_callback(cb, state)
    cb.data = action(state, "label", 2)
    await promo_admin.promo_callback(cb, state)
    assert state.state is None


@pytest.mark.asyncio
async def test_test_requires_explicit_click_and_double_click_is_not_resent(editor):
    service, state, cb = await show(editor)
    service.test_promo.assert_not_awaited()
    cb.data = action(state, "test")
    await promo_admin.promo_callback(cb, state)
    await promo_admin.promo_callback(cb, state)
    service.test_promo.assert_awaited_once()
    assert service.test_promo.await_args.kwargs["expected_revision"] == 1
    service.start_promo.assert_not_awaited()
    # A newly rendered button permits an explicit retry after a terminal test.
    cb.data = action(state, "test")
    await promo_admin.promo_callback(cb, state)
    assert service.test_promo.await_count == 2
    assert service.test_promo.await_args_list[0].kwargs["idempotency_key"] != service.test_promo.await_args_list[1].kwargs["idempotency_key"]


@pytest.mark.asyncio
@pytest.mark.parametrize("hash_matches,sent", [(True, 0), (False, 1)])
async def test_no_mass_send_without_matching_successful_test(editor, hash_matches, sent):
    service, state, cb = editor
    service.ready()
    service.record["test_summary"]["sent"] = sent
    if not hash_matches:
        service.record["test_summary"]["content_hash"] = "older"
    await show(editor)
    assert not any(":confirm:" in item for item in displayed_callbacks(cb))
    cb.data = action(state, "confirm")
    await promo_admin.promo_callback(cb, state)
    service.start_promo.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmation_shows_audience_and_requires_final_click_once(editor):
    service, state, cb = editor
    service.ready()
    service.record["message"]["buttons"] = [{"position": 1, "text": "Открыть", "action": "trend", "trend_id": 7}]
    await show(editor)
    cb.data = action(state, "confirm")
    await promo_admin.promo_callback(cb, state)
    text = cb.message.edit_text.await_args.args[0]
    assert "Получателей: <b>12</b>" in text
    assert "Тестовый тренд" in text
    assert "Медиа: 0/10" in text
    service.start_promo.assert_not_awaited()
    cb.data = action(state, "send")
    await promo_admin.promo_callback(cb, state)
    await promo_admin.promo_callback(cb, state)
    service.start_promo.assert_awaited_once()
    assert service.start_promo.await_args.kwargs == {"expected_revision": 1, "expected_hash": "one", "expected_audience": 12}
    assert "только для чтения" in cb.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_cancelled_confirmation_cannot_send(editor):
    service, state, cb = editor
    service.ready()
    await show(editor)
    cb.data = action(state, "confirm")
    await promo_admin.promo_callback(cb, state)
    old_send = action(state, "send")
    cb.data = action(state, "cancel")
    await promo_admin.promo_callback(cb, state)
    cb.data = old_send
    await promo_admin.promo_callback(cb, state)
    service.start_promo.assert_not_awaited()


@pytest.mark.asyncio
async def test_read_only_campaign_offers_only_history_refresh_and_duplicate(editor):
    service, state, cb = editor
    service.record.update(status="running", sent_count=7, failed_count=2, blocked_count=1, queued_count=4, error_groups=[{"code": "recipient_blocked", "count": 1}])
    await show(editor)
    assert not any(any(f":{kind}:" in item for kind in ("text", "media", "buttons", "test", "send")) for item in displayed_callbacks(cb))
    text = cb.message.edit_text.await_args.args[0]
    assert "Отправлено: 7" in text and "recipient_blocked: 1" in text
    cb.data = action(state, "clear")
    await promo_admin.promo_callback(cb, state)
    service.save_promo.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoked_admin_cannot_use_callback_or_existing_input_state(editor, monkeypatch):
    service, state, cb = await show(editor)
    cb.data = action(state, "text")
    await promo_admin.promo_callback(cb, state)
    monkeypatch.setattr(promo_admin.config, "is_admin", lambda _uid: False)
    await promo_admin.promo_message(incoming(text="Unauthorized edit"), state)
    cb.data = action(state, "test")
    await promo_admin.promo_callback(cb, state)
    service.save_promo.assert_not_awaited()
    service.test_promo.assert_not_awaited()


@pytest.mark.asyncio
async def test_historical_broadcast_confirmation_only_reopens_editor(editor, monkeypatch):
    from bot.handlers import admin
    _service, state, cb = editor
    await state.update_data(broadcast_text="Old untested text")
    legacy_launch = AsyncMock()
    monkeypatch.setattr(admin, "_create_admin_broadcast_campaign", legacy_launch)
    await admin.admin_execute_broadcast(cb, state, cb.bot)
    legacy_launch.assert_not_awaited()
    _service.start_promo.assert_not_awaited()
    assert state.data["promo_screen"] == "list"
    assert "broadcast_text" not in state.data


@pytest.mark.asyncio
async def test_new_callback_is_reachable_through_existing_admin_router(editor):
    from bot.handlers import admin
    _service, state, cb = editor
    cb.data = "admin_pr:list:0"
    await admin.router.propagate_event("callback_query", cb, state=state, bot=cb.bot)
    assert state.data["promo_screen"] == "list"


@pytest.mark.asyncio
async def test_one_successful_admin_delivery_allows_confirmation_while_others_pending(editor):
    service, state, cb = editor
    service.ready()
    service.record["test_summary"].update(status="sending", pending=2)
    service.record["tested_at"] = "2026-10-07T06:00:00+00:00"
    await show(editor)
    assert any(":confirm:" in item for item in displayed_callbacks(cb))
    text = cb.message.edit_text.await_args.args[0]
    assert "ожидают: 2" in text
    assert "07.10.2026 06:00 UTC" in text
    assert "Проверьте сообщение и каждую кнопку" in text
    cb.data = action(state, "confirm")
    await promo_admin.promo_callback(cb, state)
    markup = cb.message.edit_text.await_args.kwargs["reply_markup"]
    assert "12 получателям" in markup.inline_keyboard[0][0].text
    service.start_promo.assert_not_awaited()


@pytest.mark.asyncio
async def test_button_reorder_and_remove_keep_contiguous_positions(editor):
    service, state, cb = editor
    service.record["message"]["buttons"] = [
        {"position": 1, "text": "Первый", "action": "trend", "trend_id": 7},
        {"position": 2, "text": "Второй", "action": "trend", "trend_id": 8},
    ]
    service.ready()
    await show(editor)
    cb.data = action(state, "buttons")
    await promo_admin.promo_callback(cb, state)
    cb.data = action(state, "swap")
    await promo_admin.promo_callback(cb, state)
    assert [item["trend_id"] for item in service.record["message"]["buttons"]] == [8, 7]
    assert [item["position"] for item in service.record["message"]["buttons"]] == [1, 2]
    assert not service.record["ready"]
    cb.data = action(state, "delbtn", 0)
    await promo_admin.promo_callback(cb, state)
    assert service.record["message"]["buttons"] == [{"position": 1, "text": "Первый", "action": "trend", "trend_id": 7}]


@pytest.mark.asyncio
async def test_format_toggle_and_text_clear_are_revision_guarded(editor):
    service, state, cb = await show(editor)
    cb.data = action(state, "format")
    await promo_admin.promo_callback(cb, state)
    assert service.record["message"]["parse_mode"] is None
    old_clear = action(state, "clear")
    cb.data = old_clear
    await promo_admin.promo_callback(cb, state)
    await promo_admin.promo_callback(cb, state)
    assert service.record["message"]["text"] == ""
    assert service.save_promo.await_count == 2


@pytest.mark.asyncio
async def test_native_telegram_entities_are_preserved_in_html_mode(editor):
    service, state, cb = await show(editor)
    cb.data = action(state, "text")
    await promo_admin.promo_callback(cb, state)
    msg = incoming(text="Текст")
    msg.entities = [SimpleNamespace(type="bold")]
    msg.html_text = "<b>Текст</b>"
    await promo_admin.promo_message(msg, state)
    assert service.record["message"]["text"] == "<b>Текст</b>"


@pytest.mark.asyncio
async def test_status_safely_shows_bounded_per_admin_failures(editor):
    service, _state, cb = editor
    service.record.update(tested_at="2026-10-07T08:00:00+02:00", test_summary={"content_hash": "one", "status": "completed", "sent": 0, "failed": 10, "errors": [{"telegram_id": 999000000 + i, "code": "<blocked>" + "x" * 300} for i in range(10)]})
    service.record["message"]["text"] = "<" * 4000
    await show(editor)
    text = cb.message.edit_text.await_args.args[0]
    assert "Админ 999000000:" in text
    assert "&lt;blocked&gt;" in text
    assert "Ещё ошибок: 6" in text
    assert "07.10.2026 06:00 UTC" in text
    from html import unescape
    assert len(unescape(text)) < 3500


@pytest.mark.asyncio
async def test_editor_callbacks_fit_telegram_limit_for_large_campaign_id(editor):
    service, _state, cb = editor
    service.record.update(id=9223372036854775807, revision=2147483647)
    service.ready()
    await show(editor)
    assert all(len(value.encode()) <= 64 for value in displayed_callbacks(cb))
