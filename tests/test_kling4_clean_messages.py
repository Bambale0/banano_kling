"""User-facing Kling 4 notifications never disclose provider diagnostics."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import kling4
from tests import test_kling4_automatic_telegram as auto
from tests import test_kling4_navigation as nav

telegram = nav.telegram
engine = auto.engine


def assert_clean(text):
    for token in ("KIE", "credits", "kling4_", "pending", "unknown", "427.5"):
        assert token not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "unknown", "submitting", "failed"])
async def test_launch_only_shows_user_status(telegram, engine, status):
    state, message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    engine.launch.return_value = {
        "task_id": "kling4_private_identifier",
        "status": status,
    }
    message.from_user = query.from_user
    await kling4.launch_prompt(message, state, kling4.fresh())
    text = message.answer.await_args.args[0]
    assert_clean(text)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    ["history", "task:kling4_private_identifier", "adopt:kling4_private_identifier"],
)
async def test_history_and_old_callbacks_are_clean(telegram, monkeypatch, action):
    state, message, query = telegram
    task = {
        "task_id": "kling4_private_identifier",
        "status": "unknown",
        "actual_credits": "427.5",
        "result_url": None,
    }
    monkeypatch.setattr(kling4, "actor", AsyncMock(return_value=object()))
    monkeypatch.setattr(
        kling4,
        "kling4_lifecycle",
        SimpleNamespace(
            history=AsyncMock(return_value=[task]), status=AsyncMock(return_value=task)
        ),
    )
    query.data = "k4:" + action
    await kling4.callback(query, state)
    call = message.answer.await_args
    assert_clean(call.args[0])
    for row in call.kwargs["reply_markup"].inline_keyboard:
        for button in row:
            assert_clean(button.text)


from tests import test_kling4 as lifecycle_tests

engine_context = lifecycle_tests.engine_context


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,local_video", [("failed", False), ("done", True), ("done", False)]
)
async def test_delivery_has_no_internal_identifier(
    engine_context, tmp_path, status, local_video
):
    from bot import database, db

    engine, actor, _transport = engine_context
    recipe = {"mode": "reference", "input": {"prompt": "test"}}
    quote = await engine.quote(actor, recipe)
    result = await engine.launch(actor, recipe, quote["quote_hash"], "clean-delivery")
    path = tmp_path / "result.mp4"
    path.write_bytes(b"video")
    async with db.connect(database.DATABASE_PATH) as conn:
        await conn.execute(
            "UPDATE kling4_intents SET status=?,result_path=?,result_url=? WHERE task_id=?",
            (
                status,
                str(path) if local_video else None,
                "https://media.example/video.mp4",
                result["task_id"],
            ),
        )
        await conn.commit()
    engine.telegram_bot = SimpleNamespace(
        send_message=AsyncMock(), send_video=AsyncMock()
    )
    await engine.deliver(result["task_id"])
    call = (
        engine.telegram_bot.send_video.await_args
        if local_video
        else engine.telegram_bot.send_message.await_args
    )
    text = call.kwargs["caption"] if local_video else call.args[1]
    assert_clean(text)
    assert result["task_id"] not in text
    assert "https://" not in text
    assert (await engine.status(actor, result["task_id"]))[
        "delivery_status"
    ] == "delivered"


@pytest.mark.parametrize(
    "message,status",
    [
        ("KIE API не настроен.", 503),
        ("Неверный расход KIE.", 400),
        ("invalid literal for int()", None),
    ],
)
def test_technical_errors_are_hidden(message, status):
    from bot.kling4_editor_view import public_error
    from bot.services.kling4_contract import Kling4Error

    error = (
        ValueError(message) if status is None else Kling4Error(message, status=status)
    )
    assert public_error(error) == "Не удалось выполнить действие. Попробуйте позже."


def test_actionable_validation_is_preserved():
    from bot.kling4_editor_view import public_error
    from bot.services.kling4_contract import Kling4Error

    assert (
        public_error(Kling4Error("Допустимо 3–30 секунд.")) == "Допустимо 3–30 секунд."
    )
