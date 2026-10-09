from contextlib import asynccontextmanager
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted,debited", [(True, True), (False, True), (True, False)])
async def test_motion_qualifies_only_after_provider_accepts_and_binding_commits(tmp_path, monkeypatch, accepted, debited):
    from bot import database, partner_policy
    from bot.handlers import common
    from bot.services.kling_service import kling_service
    from bot.services.preset_manager import preset_manager

    monkeypatch.chdir(tmp_path)
    user = SimpleNamespace(id=17, telegram_id=710111)
    monkeypatch.setattr(database, "get_or_create_user", AsyncMock(return_value=user))
    monkeypatch.setattr(database, "deduct_credits", AsyncMock(return_value=debited))
    task_insert = AsyncMock()
    refund = AsyncMock()
    monkeypatch.setattr(database, "add_generation_task", task_insert)
    monkeypatch.setattr(database, "add_credits", refund)
    monkeypatch.setattr(preset_manager, "get_video_cost_with_quality", lambda *_args: 5)
    monkeypatch.setattr(kling_service, "generate_motion_control", AsyncMock(return_value={"task_id": "provider-motion"} if accepted else None))
    events = []
    cursor = SimpleNamespace(fetchone=AsyncMock(return_value={"request_data": '{"kept":true}'}))
    conn = SimpleNamespace(execute=AsyncMock(return_value=cursor), row_factory=None)

    async def commit():
        events.append("binding_committed")

    async def mark(task_id):
        assert task_id == "provider-motion"
        events.append("accepted")

    conn.commit = commit

    @asynccontextmanager
    async def connect(*_args, **_kwargs):
        yield conn

    monkeypatch.setattr(common.db_backend, "connect", connect)
    mark_accepted = AsyncMock(side_effect=mark)
    monkeypatch.setattr(partner_policy, "mark_generation_accepted", mark_accepted)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=user.telegram_id),
        video=SimpleNamespace(file_id="test-video", duration=5),
        bot=SimpleNamespace(
            get_file=AsyncMock(return_value=SimpleNamespace(file_path="video.mp4")),
            download_file=AsyncMock(return_value=BytesIO(b"video")),
        ),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(
        get_data=AsyncMock(return_value={"v_image_url": "https://example.test/image.jpg", "video_model": "v3_std", "mode": "std"}),
        clear=AsyncMock(),
    )
    await common.handle_motion_video_upload(message, state)
    if not debited:
        task_insert.assert_not_awaited()
        kling_service.generate_motion_control.assert_not_awaited()
        mark_accepted.assert_not_awaited()
        refund.assert_not_awaited()
        return
    assert "provider_accepted" not in task_insert.await_args.kwargs
    if accepted:
        assert events == ["binding_committed", "accepted"]
        mark_accepted.assert_awaited_once_with("provider-motion")
        refund.assert_not_awaited()
    else:
        mark_accepted.assert_not_awaited()
        refund.assert_awaited_once_with(user.telegram_id, 5)
