"""Unit tests for bot/utils/validators.py"""

import pytest

from bot.utils.validators import (sanitize_input, validate_aspect_ratio,
                                  validate_credits_amount, validate_duration,
                                  validate_image_size, validate_prompt,
                                  validate_telegram_id)


class TestValidators:
    def test_validate_prompt_valid(self):
        is_valid, error = validate_prompt("A beautiful landscape with mountains")
        assert is_valid
        assert error is None

    def test_validate_prompt_empty(self):
        is_valid, error = validate_prompt("")
        assert not is_valid
        assert error == "Промпт не может быть пустым"

    def test_validate_prompt_too_short(self):
        is_valid, error = validate_prompt("ab")
        assert not is_valid
        assert error == "Промпт слишком короткий (минимум 3 символа)"

    def test_validate_prompt_too_long(self):
        long_prompt = "a" * 1001
        is_valid, error = validate_prompt(long_prompt)
        assert not is_valid
        assert "максимум 1000" in error

    def test_validate_prompt_forbidden_script(self):
        is_valid, error = validate_prompt("<script>alert(1)</script>")
        assert not is_valid
        assert "недопустимый контент" in error

    def test_validate_prompt_forbidden_js(self):
        is_valid, error = validate_prompt("javascript:alert(1)")
        assert not is_valid
        assert "недопустимый контент" in error

    def test_validate_prompt_onclick(self):
        is_valid, error = validate_prompt('onload="evil()"')
        assert not is_valid
        assert "недопустимый контент" in error

    def test_validate_image_size_valid(self):
        is_valid, error = validate_image_size(1024 * 1024)  # 1MB
        assert is_valid
        assert error is None

    def test_validate_image_size_zero(self):
        is_valid, error = validate_image_size(0)
        assert not is_valid
        assert error == "Изображение пустое"

    def test_validate_image_size_too_big(self):
        is_valid, error = validate_image_size(20 * 1024 * 1024)  # 20MB
        assert not is_valid
        assert "слишком большое" in error

    def test_validate_image_size_too_small(self):
        is_valid, error = validate_image_size(50)
        assert not is_valid
        assert error == "Изображение слишком маленькое"

    def test_sanitize_input_empty(self):
        assert sanitize_input("") == ""

    def test_sanitize_input_normalize_spaces(self):
        result = sanitize_input("  multiple   spaces  ")
        assert result == "multiple spaces"

    def test_sanitize_input_truncate(self):
        long = "a" * 600
        result = sanitize_input(long, max_length=500)
        assert len(result) == 500

    def test_sanitize_input_html_escape(self):
        result = sanitize_input("<script>alert(1)</script>", max_length=100)
        assert "<" not in result
        assert ">" not in result

    def test_validate_telegram_id_valid(self):
        assert validate_telegram_id(123456789) is True

    def test_validate_telegram_id_negative(self):
        assert validate_telegram_id(-1) is False

    def test_validate_telegram_id_zero(self):
        assert validate_telegram_id(0) is False

    def test_validate_telegram_id_string(self):
        assert validate_telegram_id("123") is False

    def test_validate_credits_amount_valid(self):
        is_valid, error = validate_credits_amount(100)
        assert is_valid
        assert error is None

    def test_validate_credits_amount_negative(self):
        is_valid, error = validate_credits_amount(-1)
        assert not is_valid
        assert error == "Количество не может быть отрицательным"

    def test_validate_credits_amount_too_large(self):
        is_valid, error = validate_credits_amount(100001)
        assert not is_valid
        assert error == "Превышен лимит кредитов"

    def test_validate_credits_amount_float(self):
        is_valid, error = validate_credits_amount(10.5)
        assert not is_valid
        assert error == "Количество должно быть целым числом"

    def test_validate_aspect_ratio_valid(self):
        assert validate_aspect_ratio("1:1") is True
        assert validate_aspect_ratio("16:9") is True
        assert validate_aspect_ratio("9:16") is True
        assert validate_aspect_ratio("4:3") is True
        assert validate_aspect_ratio("3:2") is True

    def test_validate_aspect_ratio_invalid(self):
        assert validate_aspect_ratio("invalid") is False
        assert validate_aspect_ratio("2:1") is False

    def test_validate_duration_valid(self):
        assert validate_duration(5) is True
        assert validate_duration(60) is True
        assert validate_duration(1) is True

    def test_validate_duration_invalid(self):
        assert validate_duration(0) is False
        assert validate_duration(61) is False
        assert validate_duration("5") is False
        assert validate_duration(-1) is False
