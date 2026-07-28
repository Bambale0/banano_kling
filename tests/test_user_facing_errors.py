from bot.handlers.generation import _classify_image_generation_result
from bot.miniapp import _classify_video_generation_result
from bot.utils.user_facing_errors import make_user_friendly_generation_error


def test_user_friendly_error_hides_provider_name():
    message = make_user_friendly_generation_error(
        "Kie.ai response did not include an audio id"
    )

    assert "Kie" not in message
    assert "сервис генерации" in message.lower()


def test_user_friendly_error_turns_overload_into_clear_text():
    message = make_user_friendly_generation_error(
        "The system load is too high. Please try again later."
    )

    assert "system load" not in message.lower()
    assert "перегружен" in message


def test_generation_classifiers_sanitize_provider_errors():
    image_status, image_message = _classify_image_generation_result(
        {"error": "api_error", "message": "Kie.ai API key is not configured"}
    )
    video_status, video_message = _classify_video_generation_result(
        {"error": "api_error", "message": "Kie.ai response did not include a task id"}
    )

    assert image_status == "failed"
    assert video_status == "failed"
    assert "Kie" not in image_message
    assert "Kie" not in video_message


def test_real_person_image_failure_names_reference_and_explains_replacement():
    message = make_user_friendly_generation_error(
        "The request failed because the input image 'content[0]' may contain real person."
    )

    assert "фото-референс №1" in message
    assert "промпте" in message
    assert "иллюстрацию или 3D-рендер" in message
    assert "content[0]" not in message
