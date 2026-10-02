from __future__ import annotations

import ast
from pathlib import Path


def test_feed_loader_does_not_create_a_second_event_loop() -> None:
    source = Path("bot/handlers/common.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    loader = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_load_feed_cards"
    )

    calls = [node for node in ast.walk(loader) if isinstance(node, ast.Call)]
    dotted_calls = {
        f"{node.func.value.id}.{node.func.attr}"
        for node in calls
        if isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }
    direct_calls = {node.func.id for node in calls if isinstance(node.func, ast.Name)}

    assert "asyncio.run" not in dotted_calls
    assert "asyncio.to_thread" not in dotted_calls
    assert "get_feed_generations" in direct_calls
    assert any(
        isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "get_feed_generations"
        for node in ast.walk(loader)
    )
