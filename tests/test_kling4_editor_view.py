from bot.kling4_editor_view import keyboard_rows, render_editor_card

RATIOS = ("auto", "16:9", "9:16", "1:1", "21:9")


def recipe(**input_overrides):
    data = {
        "prompt": "",
        "duration": 5,
        "resolution": "720p",
        "aspect_ratio": "auto",
    }
    data.update(input_overrides)
    return {"mode": "reference", "input": data}


def test_reference_card_with_photo_uses_approved_shared_structure():
    card = render_editor_card(
        recipe(image_urls=["owned-photo"]),
        "💰 Цена: <code>12.5</code> 🍌 бананов.\n"
        "Для администратора списание отключено.",
    )

    assert card.startswith("🎬 <b>Kling 4</b>\n\nСценарий: <b>По референсам</b>")
    assert (
        "Качество: <code>720p</code> · Формат кадра: <code>Авто</code> · "
        "Длительность: <code>5с</code>"
    ) in card
    assert "Аудио: <code>создаёт модель</code>" in card
    assert "Сейчас: фото <code>1/10</code>, видео <code>0/5</code>" in card
    assert "Метки: Фото: @image_1" in card
    assert "Цена: <code>12.5</code>" in card
    assert "Для администратора списание отключено" in card
    assert card.index("Сценарий:") < card.index("Сейчас:") < card.index("💰 Цена:")
    assert card.endswith("генерация запустится сразу.")


def test_card_preserves_explicit_unconfigured_price_instead_of_zero():
    card = render_editor_card(
        recipe(image_urls=["owned-photo"]),
        "💰 Цена не настроена. Задайте тариф Kling 4 в админке.\n"
        "Для администратора списание отключено.",
    )

    assert "Цена не настроена" in card
    assert "Цена: <code>0" not in card
    assert "Для администратора списание отключено" in card


def test_reference_keyboard_contains_every_supported_control():
    rows = keyboard_rows(recipe(image_urls=["owned-photo"]), RATIOS)
    labels = [[text for text, _callback in row] for row in rows]
    callbacks = {callback for row in rows for _text, callback in row}

    assert labels == [
        ["✅ 🧩 По референсам", "🎞 По кадрам"],
        ["✅ 720p", "1080p"],
        ["✅ Авто", "16:9", "9:16"],
        ["1:1", "21:9"],
        ["− 1с", "⏱ 5с", "+ 1с"],
        ["🧩 Материалы (0) · 🎙 Голоса (0)", "🔊 Звук: авто"],
        ["🧹 Очистить медиа"],
        ["← Модели Kling"],
    ]
    assert {
        "k4:mode:reference",
        "k4:mode:keyframe",
        "k4:resolution:720p",
        "k4:resolution:1080p",
        "k4:ratio:auto",
        "k4:ratio:16:9",
        "k4:ratio:9:16",
        "k4:ratio:1:1",
        "k4:ratio:21:9",
        "k4:duration:-1",
        "k4:duration:0",
        "k4:duration:1",
        "k4:materials",
        "k4:sound",
        "k4:clear",
        "video_models:kling:0",
    } == callbacks


def test_video_and_keyframe_states_keep_contextual_controls():
    video = recipe(video_urls=["owned-video"], keep_original_sound=True)
    video_card = render_editor_card(video, "price after measurement")
    video_rows = keyboard_rows(video, RATIOS)
    assert "Аудио: <code>исходный звук включён</code>" in video_card
    assert any(
        text == "🔊 Исходный звук: вкл" for row in video_rows for text, _ in row
    )

    frames = recipe(first_frame_url="owned-first", keyframe_urls=["owned-middle"])
    frames["mode"] = "keyframe"
    frame_card = render_editor_card(frames, "configured price")
    frame_rows = keyboard_rows(frames, RATIOS)
    assert "Сценарий: <b>По кадрам</b>" in frame_card
    assert "первый ✅, промежуточных <code>1</code>, последний —" in frame_card
    assert [text for text, _ in frame_rows[5]] == [
        "Первый кадр",
        "Средние",
        "Последний",
    ]
