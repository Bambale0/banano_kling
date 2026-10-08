"""Exercise callback authorization without importing production configuration."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "bot/handlers/banana_resolution_pricing_compat.py"


def callback_handler(name, authorized):
    tree = ast.parse(SOURCE.read_text())
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {name, "_is_price_admin"}:
            node.decorator_list = []
            selected.append(node)
    code = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *selected], type_ignores=[])
    namespace = {
        "_admin_module": SimpleNamespace(is_admin=lambda user_id: authorized and user_id == 123),
        # Deliberately disagree: legacy preset admins must not control this surface.
        "preset_manager": SimpleNamespace(is_admin=lambda user_id: not authorized),
        "_quality_costs": lambda: {"1K": 2, "2K": 3, "4K": 4},
        "_format_cost": str,
        "_banana_quality_keyboard": lambda: None,
        "_QUALITY_CALLBACKS": {"admin_banana_quality_1K": "1K"},
        "AdminStates": SimpleNamespace(waiting_price_value="waiting"),
        "types": SimpleNamespace(
            InlineKeyboardMarkup=lambda **kwargs: kwargs,
            InlineKeyboardButton=lambda **kwargs: kwargs,
        ),
    }
    exec(compile(ast.fix_missing_locations(code), str(SOURCE), "exec"), namespace)
    return namespace[name], namespace


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["admin_banana_quality_prices", "admin_banana_quality_value"])
@pytest.mark.parametrize("authorized", [False, True])
async def test_banana_callbacks_use_main_admin_authority(name, authorized):
    handler, _ = callback_handler(name, authorized)
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123), data="admin_banana_quality_1K",
        answer=AsyncMock(), message=SimpleNamespace(edit_text=AsyncMock()),
    )
    state = SimpleNamespace(clear=AsyncMock(), set_state=AsyncMock(), update_data=AsyncMock())
    await handler(callback, state)
    if authorized:
        callback.message.edit_text.assert_awaited_once()
        callback.answer.assert_awaited_once_with()
    else:
        callback.answer.assert_awaited_once_with("⛔ Нет доступа")
        callback.message.edit_text.assert_not_awaited()
        state.clear.assert_not_awaited()
        state.set_state.assert_not_awaited()
        state.update_data.assert_not_awaited()


def test_uninstalled_price_admin_guard_fails_closed():
    _, namespace = callback_handler("admin_banana_quality_prices", True)
    namespace["_admin_module"] = None
    assert namespace["_is_price_admin"](123) is False
