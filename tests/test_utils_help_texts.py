"""Unit tests for bot/utils/help_texts.py"""

import pytest

from bot.utils.help_texts import (
    UserHints,
    format_generation_options,
    format_preset_info,
    get_aspect_ratio_help,
    get_editing_help,
    get_error_handling,
    get_image_generation_intro,
    get_model_selection_help,
    get_multiturn_help,
    get_prompt_tips,
    get_reference_images_help,
    get_resolution_help,
    get_search_grounding_help,
    get_success_message,
    get_welcome_message,
)


class TestHelpTexts:
    def test_get_welcome_message(self):
        msg = get_welcome_message()
        assert "Добро пожаловать" in msg
        assert "🍌" in msg

    def test_get_image_generation_intro_image_generation(self):
        msg = get_image_generation_intro("image_generation")
        assert "Генерация изображений" in msg

    def test_get_image_generation_intro_image_editing(self):
        msg = get_image_generation_intro("image_editing")
        assert "Редактирование изображений" in msg

    def test_get_image_generation_intro_unknown(self):
        msg = get_image_generation_intro("unknown")
        assert msg == ""

    def test_get_model_selection_help(self):
        msg = get_model_selection_help()
        assert "Выбор модели AI" in msg
        assert "FLUX.2 Pro" in msg

    def test_get_resolution_help(self):
        msg = get_resolution_help()
        assert "Выбор разрешения" in msg
        assert "1K (1024px)" in msg

    def test_get_aspect_ratio_help(self):
        msg = get_aspect_ratio_help()
        assert "Выбор формата изображения" in msg
        assert "1:1" in msg

    def test_get_reference_images_help(self):
        msg = get_reference_images_help()
        assert "Референсные изображения" in msg
        assert "До 14 изображений" in msg

    def test_get_search_grounding_help(self):
        msg = get_search_grounding_help()
        assert "Поиск в интернете" in msg

    def test_get_prompt_tips(self):
        tips = get_prompt_tips()
        assert "photo" in tips
        assert "illustration" in tips
        assert len(tips["photo"]) > 100

    def test_get_editing_help(self):
        msg = get_editing_help()
        assert "Редактирование изображений" in msg
        assert "➕ Добавить объект" in msg

    def test_get_multiturn_help(self):
        msg = get_multiturn_help()
        assert "Многоходовое редактирование" in msg

    def test_get_error_handling(self):
        errors = get_error_handling()
        assert "no_credits" in errors
        assert "generation_failed" in errors

    def test_get_success_message(self):
        msg = get_success_message("test_preset", 5)
        assert "Готово!" in msg
        assert "test_preset" in msg
        assert "5🍌" in msg

    def test_user_hints_get_hint_for_stage(self):
        hints = UserHints()
        msg = hints.get_hint_for_stage("main_menu")
        assert "Нажмите на категорию" in msg

        unknown = hints.get_hint_for_stage("unknown")
        assert unknown == ""

    def test_user_hints_encouragement(self):
        hints = UserHints()
        enc = hints.get_encouragement()
        assert len(enc) > 0
        assert "🎨" in enc[0]

    def test_format_preset_info(self):
        class MockPreset:
            name = "Test"
            cost = 5
            model = "flux_pro"
            description = "Test desc"
            aspect_ratio = "1:1"
            requires_upload = True
            requires_input = True
            input_prompt = "Enter prompt"

        preset = MockPreset()
        info = format_preset_info(preset)
        assert "Test" in info
        assert "5" in info
        assert "🍌" in info
        assert "flux_pro" in info

    def test_format_generation_options(self):
        options = {
            "model": "flux_pro",
            "aspect_ratio": "16:9",
            "resolution": "2K",
            "enable_search": True,
            "reference_count": 3,
        }
        formatted = format_generation_options(options)
        assert "flux_pro" in formatted
        assert "16:9" in formatted
        assert "ВКЛ" in formatted
