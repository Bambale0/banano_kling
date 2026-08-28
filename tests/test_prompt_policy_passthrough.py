from bot.utils.validators import (
    detect_explicit_prompt_policy_violation,
    validate_prompt,
)


def test_prompt_keyword_policy_is_disabled() -> None:
    prompts = (
        "cinematic scene with the word explicit in metadata",
        "fashion editorial in lingerie, no logos, 16:9",
        "откровенная кинематографичная сцена без надписей",
    )

    for prompt in prompts:
        assert detect_explicit_prompt_policy_violation(prompt) is None


def test_script_injection_validation_remains_enabled() -> None:
    is_valid, error = validate_prompt("<script>alert(1)</script>")

    assert is_valid is False
    assert error == "Промпт содержит недопустимый контент"
