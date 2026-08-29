from __future__ import annotations

from bot.generation_progress import (
    _terminal_text,
    build_progress_line,
    ensure_progress_line,
    extract_task_ids,
)


def test_progress_indicator_is_indeterminate_not_fake_percentage() -> None:
    line = build_progress_line("pending", frame=3)
    assert "⏳" in line
    assert "В работе" in line
    assert "%" not in line
    assert "▰" in line


def test_progress_line_is_added_only_once() -> None:
    source = "🚀 <b>Генерация запущена</b>\n\n• ID задачи: <code>img_123</code>"
    once = ensure_progress_line(source)
    twice = ensure_progress_line(once)
    assert once == twice
    assert once.count("⏳ <code>") == 1


def test_task_ids_include_local_and_provider_trace() -> None:
    source = (
        "• ID задачи: <code>img_local_123</code>\n"
        "• ID провайдера: <code>rg-creation-123</code>"
    )
    assert extract_task_ids(source) == ["img_local_123", "rg-creation-123"]


def test_terminal_progress_reuses_same_message_contract() -> None:
    source = (
        "🚀 <b>Генерация запущена</b>\n"
        f"{build_progress_line()}\n\n"
        "• ID задачи: <code>img_123</code>\n\n"
        "Обычно результат приходит в течение 1–3 минут.\n"
        "Я пришлю его сюда сразу после готовности."
    )
    completed = _terminal_text(source, "completed")
    assert "✅ <b>Генерация готова</b>" in completed
    assert "✅ <code>▰▰▰▰▰▰▰▰</code> Готово" in completed
    assert "Результат готов." in completed
    assert "1–3 минут" not in completed
