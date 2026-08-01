import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import miniapp


PRODUCTION_GENERATION_FILES = (
    Path("bot/miniapp.py"),
    Path("bot/handlers/generation.py"),
    Path("bot/handlers/batch_generation.py"),
)


def _is_deduct_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "deduct_credits"
    )


def test_generation_code_never_ignores_deduct_result():
    violations: list[str] = []

    for path in PRODUCTION_GENERATION_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and _is_deduct_call(node.value):
                violations.append(f"{path}:{node.lineno}")

    assert not violations, (
        "Every generation debit must consume the atomic deduct_credits result; "
        f"ignored at: {', '.join(violations)}"
    )


@pytest.mark.asyncio
async def test_miniapp_debit_stops_request_when_balance_changed(monkeypatch):
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _telegram_id: False)
    monkeypatch.setattr(
        miniapp,
        "deduct_credits",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        miniapp,
        "get_or_create_user",
        AsyncMock(return_value=SimpleNamespace(credits=1)),
    )

    response = await miniapp._deduct_miniapp_generation_cost(123, 5)

    assert response is not None
    assert response.status == 400
    assert json.loads(response.text) == {
        "ok": False,
        "error": "Недостаточно бананов. Нужно 5🍌",
        "credits": 1,
    }


@pytest.mark.asyncio
async def test_miniapp_debit_allows_launch_only_after_success(monkeypatch):
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _telegram_id: False)
    debit = AsyncMock(return_value=True)
    monkeypatch.setattr(miniapp, "deduct_credits", debit)

    response = await miniapp._deduct_miniapp_generation_cost(123, 5)

    assert response is None
    debit.assert_awaited_once_with(123, 5)


@pytest.mark.asyncio
async def test_miniapp_admin_does_not_touch_balance(monkeypatch):
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _telegram_id: True)
    debit = AsyncMock()
    monkeypatch.setattr(miniapp, "deduct_credits", debit)

    response = await miniapp._deduct_miniapp_generation_cost(123, 5)

    assert response is None
    debit.assert_not_awaited()
