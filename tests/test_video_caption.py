from bot.database import GenerationTask
from bot.main import _build_generation_success_caption


def test_video_caption_is_pretty_and_uses_per_second_cost():
    task = GenerationTask(
        id=1,
        user_id=1,
        task_id="task_1",
        type="video",
        preset_id="no_preset_video",
        model="v3_omni_pro",
        duration=5,
        aspect_ratio="1:1",
        prompt="все должно быть красиво",
        cost=15,
    )

    caption = _build_generation_success_caption(task, task.task_id)

    assert "Видео готово" in caption
    assert "Kling Omni Pro" in caption
    assert "3 GOE/с × 5с = 15 GOE" in caption
    assert "Промпт" in caption
    assert "no_preset_video" not in caption
