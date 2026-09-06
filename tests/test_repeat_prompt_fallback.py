from types import SimpleNamespace

from bot.handlers.generation import _repeat_source_prompt


def test_repeat_source_prompt_falls_back_to_task_prompt_when_request_prompt_is_empty():
    task = SimpleNamespace(prompt="server-side source prompt")

    assert _repeat_source_prompt({"prompt": ""}, task) == "server-side source prompt"


def test_repeat_source_prompt_prefers_non_empty_request_prompt():
    task = SimpleNamespace(prompt="server-side source prompt")

    assert _repeat_source_prompt({"prompt": "request prompt"}, task) == "request prompt"


def test_repeat_source_prompt_falls_back_for_whitespace_only_request_prompt():
    task = SimpleNamespace(prompt="server-side source prompt")

    assert _repeat_source_prompt({"prompt": "   \n\t"}, task) == "server-side source prompt"
