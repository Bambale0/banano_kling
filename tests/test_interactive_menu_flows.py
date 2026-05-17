"""Regression tests for interactive menu/FSM flows."""

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from io import BytesIO

import pytest

from bot import keyboards
from bot.handlers import common, generation
from bot.services.preset_manager import preset_manager
from bot.states import GenerationStates


def _callback_data(markup):
    values = []
    for row in markup.inline_keyboard:
        for button in row:
            callback_data = getattr(button, "callback_data", None)
            if callback_data:
                values.append(callback_data)
    return values


def _handler_patterns():
    source = "\n".join(
        path.read_text()
        for path in Path("bot/handlers").glob("*.py")
    )
    exact = set(re.findall(r'F\.data\s*==\s*[\'"]([^\'"]+)[\'"]', source))
    prefixes = set(
        re.findall(r'F\.data\.startswith\(\s*[\'"]([^\'"]+)[\'"]\s*\)', source)
    )
    return exact, prefixes


def _is_handled(callback_data, exact, prefixes):
    return callback_data in exact or any(
        callback_data.startswith(prefix) for prefix in prefixes
    )


def test_generation_router_has_no_duplicate_exact_callback_decorators():
    """Duplicate exact callback registrations can double-process one Telegram click."""
    source = Path("bot/handlers/generation.py").read_text()
    callbacks = re.findall(r"@router\.callback_query\(F\.data\s*==\s*['\"]([^'\"]+)['\"]\)", source)
    duplicates = sorted({value for value in callbacks if callbacks.count(value) > 1})
    assert duplicates == []


def test_keyboard_module_has_no_duplicate_function_names():
    """Later duplicate defs silently override earlier keyboards and create dead button logic."""
    source = Path("bot/keyboards.py").read_text()
    names = re.findall(r"^def\s+(\w+)\(", source, flags=re.MULTILINE)
    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert duplicates == []


@pytest.mark.asyncio
async def test_create_image_menu_initializes_references_without_name_error(monkeypatch):
    """Regression: clicking AI-image entry must not crash on primary-reference setup."""
    import bot.database as database

    monkeypatch.setattr(database, "get_user_credits", AsyncMock(return_value=42))
    monkeypatch.setattr(
        generation,
        "get_primary_reference_asset",
        AsyncMock(return_value={"image_url": "https://u.test/main.jpg"}),
    )
    monkeypatch.setattr(generation, "track_event", AsyncMock())

    class FakeState:
        def __init__(self):
            self.data = {}
            self.state = None

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def set_state(self, value):
            self.state = value

    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=339795159),
        message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
    )
    state = FakeState()

    await generation.show_create_image_menu(callback, state)

    assert state.data["reference_images"] == ["https://u.test/main.jpg"]
    assert state.state == GenerationStates.uploading_reference_images
    callback.message.edit_text.assert_awaited_once()
    callback.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_generic_no_preset_image_ratio_handler_updates_keyboard():
    class FakeState:
        def __init__(self):
            self.data = {"img_service": "banana_pro"}
            self.state = None

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def set_state(self, value):
            self.state = value

    callback = SimpleNamespace(
        data="img_ratio_16_9",
        message=SimpleNamespace(edit_reply_markup=AsyncMock()),
        answer=AsyncMock(),
    )
    state = FakeState()

    await generation.handle_image_ratio_generic(callback, state)

    assert state.data["img_ratio"] == "16:9"
    assert state.state == GenerationStates.waiting_for_input
    callback.message.edit_reply_markup.assert_awaited_once()
    callback.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_generic_no_preset_video_ratio_handler_updates_keyboard():
    class FakeState:
        def __init__(self):
            self.data = {"v_type": "text", "v_model": "v3_std", "v_duration": 5}
            self.state = None

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def set_state(self, value):
            self.state = value

    callback = SimpleNamespace(
        data="ratio_9_16",
        message=SimpleNamespace(edit_reply_markup=AsyncMock()),
        answer=AsyncMock(),
    )
    state = FakeState()

    await generation.handle_video_ratio_generic(callback, state)

    assert state.data["v_ratio"] == "9:16"
    assert state.state == GenerationStates.waiting_for_input
    callback.message.edit_reply_markup.assert_awaited_once()
    callback.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_generic_no_preset_image_model_handler_updates_text():
    class FakeState:
        def __init__(self):
            self.data = {"img_ratio": "1:1", "reference_images": ["https://u.test/ref.jpg"]}
            self.state = None

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def set_state(self, value):
            self.state = value

    callback = SimpleNamespace(
        data="model_seedream_45",
        message=SimpleNamespace(edit_text=AsyncMock()),
        answer=AsyncMock(),
    )
    state = FakeState()

    await generation.handle_image_model_generic(callback, state)

    assert state.data["img_service"] == "seedream_45"
    assert state.state == GenerationStates.waiting_for_input
    callback.message.edit_text.assert_awaited_once()
    callback.answer.assert_awaited_once()


def test_primary_menu_callbacks_have_handlers():
    """Every callback visible in core menus should route somewhere."""
    menu_builders = {
        "main": lambda: keyboards.get_main_menu_keyboard(42),
        "content": keyboards.get_content_menu_keyboard,
        "output_formats": keyboards.get_flow_output_keyboard,
        "admin": keyboards.get_admin_keyboard,
        "balance": lambda: keyboards.get_balance_keyboard(42),
        "support": keyboards.get_support_keyboard,
        "help": keyboards.get_help_keyboard,
        "topup": keyboards.get_topup_keyboard,
        "packages": lambda: keyboards.get_payment_packages_keyboard(
            keyboards.PACKAGES[:2], "yookassa"
        ),
        "payment_confirm": lambda: keyboards.get_payment_confirmation_keyboard(
            "https://pay.example.test", "order_1"
        ),
        "video_text": lambda: keyboards.get_create_video_keyboard(
            current_v_type="text", current_model="v3_std"
        ),
        "video_imgtxt_seedance": lambda: keyboards.get_create_video_keyboard(
            current_v_type="imgtxt",
            current_model="seedance2",
            current_duration=5,
            current_ratio="1:1",
        ),
        "video_reference": lambda: keyboards.get_create_video_keyboard(
            current_v_type="video", current_model="aleph"
        ),
        "image": lambda: keyboards.get_create_image_keyboard("flux_pro", "1:1"),
        "reference_images": lambda: keyboards.get_reference_images_upload_keyboard(
            1, 14, "new"
        ),
        "reference_videos": lambda: keyboards.get_reference_videos_upload_keyboard(
            1, 5, "video_new"
        ),
        "generation_started": keyboards.get_generation_started_keyboard,
        "generation_error": keyboards.get_generation_error_keyboard,
        "image_actions": keyboards.get_image_result_actions_keyboard,
        "settings": keyboards.get_settings_keyboard,
        "ai_assistant": keyboards.get_ai_assistant_keyboard,
    }

    exact, prefixes = _handler_patterns()
    missing = {}
    for menu_name, build in menu_builders.items():
        callbacks = set(_callback_data(build()))
        unhandled = sorted(
            callback for callback in callbacks if not _is_handled(callback, exact, prefixes)
        )
        if unhandled:
            missing[menu_name] = unhandled

    assert missing == {}


def test_video_keyboard_seedance_scenario_exposes_expected_controls():
    callbacks = set(
        _callback_data(
            keyboards.get_create_video_keyboard(
                current_v_type="imgtxt",
                current_model="seedance2",
                current_duration=5,
                current_ratio="1:1",
            )
        )
    )

    assert "v_model_seedance2" in callbacks
    assert "ratio_1_1" in callbacks
    assert "video_dur_5" in callbacks
    assert "v_type_imgtxt" in callbacks


def test_create_image_keyboard_exposes_reference_only_gpt_image_2():
    no_ref_callbacks = set(
        _callback_data(keyboards.get_create_image_keyboard(num_refs=0))
    )
    ref_callbacks = set(_callback_data(keyboards.get_create_image_keyboard(num_refs=1)))

    assert "model_flux_pro" in no_ref_callbacks
    assert "model_gpt_image_2" not in no_ref_callbacks
    assert "model_gpt_image_2" in ref_callbacks


def test_reference_upload_keyboard_exposes_saved_reference_actions():
    callbacks = set(
        _callback_data(keyboards.get_reference_images_upload_keyboard(1, 14, "new"))
    )

    assert "ref_use_main_new" in callbacks
    assert "ref_use_clothing_new" in callbacks
    assert "ref_save_main_new" in callbacks
    assert "ref_save_clothing_new" in callbacks


def test_image_result_keyboard_can_save_generated_references():
    callbacks = set(_callback_data(keyboards.get_image_result_actions_keyboard("img_1")))

    assert "edit_generated_image:img_1" in callbacks
    assert "tryon_generated_image:img_1" in callbacks
    assert "save_clothing:img_1" in callbacks
    assert "save_main_ref:img_1" in callbacks


def test_video_keyboard_image_to_video_exposes_wan_27():
    callbacks = set(
        _callback_data(
            keyboards.get_create_video_keyboard(
                current_v_type="imgtxt",
                current_model="wan_27",
                current_duration=5,
                current_ratio="16:9",
            )
        )
    )

    assert "v_model_wan_27" in callbacks
    assert "ratio_16_9" in callbacks


def test_video_cost_is_calculated_from_one_second_rate():
    assert preset_manager.get_video_cost("seedance2", 1) == 3
    assert preset_manager.get_video_cost("seedance2", 5) == 15
    assert preset_manager.get_video_cost("seedance2", 10) == 30
    assert keyboards.get_video_total_cost("seedance2", 15) == 45


@pytest.mark.asyncio
async def test_video_prompt_in_waiting_for_input_routes_to_video_flow(monkeypatch):
    """Seedance regression: text in waiting_for_input must not be swallowed."""
    run_video = AsyncMock()
    monkeypatch.setattr(generation, "run_no_preset_video_from_message", run_video)

    class FakeState:
        def __init__(self):
            self.data = {
                "generation_type": "video",
                "v_type": "imgtxt",
                "v_model": "seedance2",
                "v_duration": 5,
                "v_ratio": "1:1",
                "v_image_url": "https://example.test/start.jpg",
            }
            self.state = GenerationStates.waiting_for_input

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

    state = FakeState()
    message = SimpleNamespace(
        text="создай аватар для бренда",
        from_user=SimpleNamespace(id=339795159),
        answer=AsyncMock(),
    )

    await generation.handle_image_prompt_text(message, state)

    run_video.assert_awaited_once_with(message, state, "создай аватар для бренда")
    assert state.data["user_prompt"] == "создай аватар для бренда"
    message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_video_duration_handler_supports_price_config_values():
    """Price config can add duration buttons like video_dur_3 without new code."""

    class FakeState:
        def __init__(self):
            self.data = {"v_type": "text", "v_model": "v3_std", "v_ratio": "16:9"}
            self.state = None

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def set_state(self, value):
            self.state = value

    callback = SimpleNamespace(
        data="video_dur_3",
        message=SimpleNamespace(edit_reply_markup=AsyncMock()),
        answer=AsyncMock(),
    )
    state = FakeState()

    await generation.handle_video_duration_generic(callback, state)

    assert state.data["v_duration"] == 3
    assert state.state == GenerationStates.waiting_for_video_prompt
    callback.message.edit_reply_markup.assert_awaited_once()
    callback.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_motion_control_cost_uses_uploaded_video_duration(monkeypatch, tmp_path):
    from bot.config import config
    import bot.database as database

    monkeypatch.setattr(config, "public_upload_dir", lambda fname: str(tmp_path / fname))
    monkeypatch.setattr(config, "public_upload_url", lambda fname: f"https://u.test/{fname}")

    monkeypatch.setattr(
        database,
        "get_or_create_user",
        AsyncMock(return_value=SimpleNamespace(id=1, credits=20)),
    )
    monkeypatch.setattr(database, "get_user_credits", AsyncMock(return_value=20))
    deduct = AsyncMock()
    monkeypatch.setattr(database, "deduct_credits", deduct)
    monkeypatch.setattr(database, "add_generation_task", AsyncMock())

    class FakeState:
        async def get_data(self):
            return {
                "v_image_url": "https://u.test/person.jpg",
                "video_model": "v26_motion_std",
                "mode": "std",
            }

    class FakeBot:
        async def get_file(self, file_id):
            return SimpleNamespace(file_path="motion.mp4")

        async def download_file(self, file_path):
            return BytesIO(b"video")

    message = SimpleNamespace(
        bot=FakeBot(),
        from_user=SimpleNamespace(id=339795159),
        video=SimpleNamespace(file_id="vid1", duration=7),
        answer=AsyncMock(),
    )

    await common.handle_motion_video_upload(message, FakeState())

    deduct.assert_not_awaited()
    message.answer.assert_awaited_once()
    text = message.answer.await_args.args[0]
    assert "<code>7</code> сек" in text
    assert "<code>21</code>💎" in text
