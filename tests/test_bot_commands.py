import pytest
from aiogram import types

from bot.config import config
from bot.main import register_bot_commands


class FakeBot:
    def __init__(self):
        self.command_calls = []

    async def set_my_commands(
        self, commands, scope=None, language_code=None, request_timeout=None
    ):
        self.command_calls.append(
            {
                "commands": commands,
                "scope": scope,
                "language_code": language_code,
                "request_timeout": request_timeout,
            }
        )
        return True


@pytest.mark.asyncio
async def test_register_bot_commands_sets_public_and_admin_scopes(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS_STR", "123,456")
    bot = FakeBot()

    await register_bot_commands(bot)

    assert len(bot.command_calls) == 3
    public_call = bot.command_calls[0]
    assert isinstance(public_call["scope"], types.BotCommandScopeDefault)
    assert [command.command for command in public_call["commands"]] == ["start", "help"]

    admin_calls = bot.command_calls[1:]
    assert [call["scope"].chat_id for call in admin_calls] == [123, 456]
    for call in admin_calls:
        assert isinstance(call["scope"], types.BotCommandScopeChat)
        assert [command.command for command in call["commands"]] == [
            "start",
            "help",
            "admin",
        ]
