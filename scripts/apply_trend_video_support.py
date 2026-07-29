from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise AssertionError(f"{path}: expected one anchor, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    Path("bot/handlers/trend_video_compat.py").write_text('from __future__ import annotations\n\nimport html\nimport logging\nfrom pathlib import Path\nfrom typing import Any\n\nfrom aiogram import F, Router, types\nfrom aiogram.filters import StateFilter\nfrom aiogram.fsm.context import FSMContext\nfrom aiogram.fsm.state import State, StatesGroup\nfrom aiogram.types import (\n    InlineKeyboardButton,\n    InlineKeyboardMarkup,\n    InputMediaVideo,\n)\n\nfrom bot import database\nfrom bot.config import config\nfrom bot.services.reference_storage_service import save_reference_file\nfrom bot.utils.validators import detect_explicit_prompt_policy_violation\n\nlogger = logging.getLogger(__name__)\nrouter = Router(name="admin_video_trends")\n\nTREND_TAG = "trend"\nTREND_VIDEO_TAG = "trend-video"\nTREND_VIDEO_MAX_BYTES = 20 * 1024 * 1024\nTREND_VIDEO_MODELS: tuple[tuple[str, str], ...] = (\n    ("v3_pro", "Kling 3.0 Pro"),\n    ("v3_std", "Kling 3.0 Standard"),\n    ("v26_pro", "Kling 2.5 Turbo Pro"),\n    ("grok_imagine", "Grok Imagine"),\n    ("grok_imagine_v15", "Grok Imagine 1.5"),\n    ("seedance_2", "Seedance 2.0"),\n    ("veo3", "Veo 3.1 Quality"),\n    ("veo3_fast", "Veo 3.1 Fast"),\n    ("veo3_lite", "Veo 3.1 Lite"),\n    ("gemini_omni_video", "Gemini Omni Video"),\n    ("glow", "Kling Glow"),\n)\n_VIDEO_MODEL_LABELS = dict(TREND_VIDEO_MODELS)\n_VIDEO_MODEL_IDS = frozenset(_VIDEO_MODEL_LABELS)\n_TRENDS_MODULE: Any | None = None\n_INSTALLED = False\n\n\nclass TrendVideoUploadStates(StatesGroup):\n    waiting_title = State()\n    waiting_description = State()\n    waiting_model = State()\n    waiting_preview = State()\n    waiting_prompt = State()\n    confirming = State()\n\n\ndef is_video_trend(prompt: dict[str, Any] | None) -> bool:\n    if not prompt:\n        return False\n    tags = {str(item or "").strip().lower() for item in prompt.get("tags", []) or []}\n    model = str(prompt.get("model") or "").strip()\n    category = str(prompt.get("category") or "").strip().lower()\n    return (\n        TREND_VIDEO_TAG in tags\n        or category == "video"\n        or model in _VIDEO_MODEL_IDS\n    )\n\n\ndef _is_admin_user(user: types.User | None) -> bool:\n    return bool(user and config.is_admin(user.id))\n\n\nasync def _reject_non_admin_message(\n    message: types.Message,\n    state: FSMContext,\n) -> bool:\n    if _is_admin_user(message.from_user):\n        return False\n    await state.clear()\n    await message.answer("Эта функция доступна только администратору.")\n    return True\n\n\ndef _cancel_keyboard() -> InlineKeyboardMarkup:\n    return InlineKeyboardMarkup(\n        inline_keyboard=[\n            [\n                InlineKeyboardButton(\n                    text="✖️ Отменить",\n                    callback_data="trend_video_add_cancel",\n                )\n            ]\n        ]\n    )\n\n\ndef _description_keyboard() -> InlineKeyboardMarkup:\n    return InlineKeyboardMarkup(\n        inline_keyboard=[\n            [\n                InlineKeyboardButton(\n                    text="Пропустить описание",\n                    callback_data="trend_video_desc_skip",\n                )\n            ],\n            [\n                InlineKeyboardButton(\n                    text="✖️ Отменить",\n                    callback_data="trend_video_add_cancel",\n                )\n            ],\n        ]\n    )\n\n\ndef _video_model_keyboard() -> InlineKeyboardMarkup:\n    rows: list[list[InlineKeyboardButton]] = []\n    current: list[InlineKeyboardButton] = []\n    for model_id, label in TREND_VIDEO_MODELS:\n        current.append(\n            InlineKeyboardButton(\n                text=label,\n                callback_data=f"trend_video_model:{model_id}",\n            )\n        )\n        if len(current) == 2:\n            rows.append(current)\n            current = []\n    if current:\n        rows.append(current)\n    rows.append(\n        [\n            InlineKeyboardButton(\n                text="✖️ Отменить",\n                callback_data="trend_video_add_cancel",\n            )\n        ]\n    )\n    return InlineKeyboardMarkup(inline_keyboard=rows)\n\n\ndef _confirm_keyboard() -> InlineKeyboardMarkup:\n    return InlineKeyboardMarkup(\n        inline_keyboard=[\n            [\n                InlineKeyboardButton(\n                    text="✅ Опубликовать видео-тренд",\n                    callback_data="trend_video_publish_confirm",\n                )\n            ],\n            [\n                InlineKeyboardButton(\n                    text="✖️ Отменить",\n                    callback_data="trend_video_add_cancel",\n                )\n            ],\n        ]\n    )\n\n\ndef _add_video_upload_button(markup: InlineKeyboardMarkup) -> InlineKeyboardMarkup:\n    rows = [list(row) for row in markup.inline_keyboard]\n    if any(\n        button.callback_data == "trend_video_add"\n        for row in rows\n        for button in row\n    ):\n        return markup\n\n    insert_at = 2 if len(rows) >= 2 else len(rows)\n    rows.insert(\n        insert_at,\n        [\n            InlineKeyboardButton(\n                text="🎬 Загрузить видео-тренд",\n                callback_data="trend_video_add",\n            )\n        ],\n    )\n    return InlineKeyboardMarkup(inline_keyboard=rows)\n\n\ndef _empty_admin_keyboard() -> InlineKeyboardMarkup:\n    return InlineKeyboardMarkup(\n        inline_keyboard=[\n            [\n                InlineKeyboardButton(\n                    text="➕ Загрузить фото-тренд",\n                    callback_data="trend_add",\n                )\n            ],\n            [\n                InlineKeyboardButton(\n                    text="🎬 Загрузить видео-тренд",\n                    callback_data="trend_video_add",\n                )\n            ],\n            [\n                InlineKeyboardButton(\n                    text="🏠 Главное меню",\n                    callback_data="back_main",\n                )\n            ],\n        ]\n    )\n\n\ndef _video_file_metadata(message: types.Message) -> tuple[str, str, str] | None:\n    if message.video:\n        filename = str(message.video.file_name or "trend-preview.mp4").strip()\n        suffix = Path(filename).suffix.lower().lstrip(".") or "mp4"\n        content_type = str(message.video.mime_type or "video/mp4").lower()\n        return suffix if suffix in {"mp4", "webm", "mov"} else "mp4", content_type, filename\n\n    document = message.document\n    if not document:\n        return None\n\n    content_type = str(document.mime_type or "").lower()\n    filename = str(document.file_name or "trend-preview").strip()\n    suffix = Path(filename).suffix.lower().lstrip(".")\n    mime_extensions = {\n        "video/mp4": "mp4",\n        "video/webm": "webm",\n        "video/quicktime": "mov",\n    }\n    extension = mime_extensions.get(content_type, suffix)\n    if extension not in {"mp4", "webm", "mov"}:\n        return None\n    if content_type not in mime_extensions:\n        content_type = {\n            "mp4": "video/mp4",\n            "webm": "video/webm",\n            "mov": "video/quicktime",\n        }[extension]\n    return extension, content_type, filename\n\n\nasync def _save_video_preview(message: types.Message) -> str | None:\n    metadata = _video_file_metadata(message)\n    if not metadata or not message.from_user:\n        return None\n\n    extension, content_type, filename = metadata\n    media = message.video or message.document\n    if media is None:\n        return None\n\n    try:\n        telegram_file = await message.bot.get_file(media.file_id)\n        if not telegram_file.file_path:\n            return None\n        stream = await message.bot.download_file(telegram_file.file_path)\n        file_bytes = stream.read()\n    except Exception:\n        logger.exception("Unable to download video trend preview from Telegram")\n        return None\n\n    if not file_bytes or len(file_bytes) > TREND_VIDEO_MAX_BYTES:\n        return None\n\n    public_url, _reference = await save_reference_file(\n        message.from_user.id,\n        file_bytes,\n        file_ext=extension,\n        kind="video",\n        original_filename=filename,\n        content_type=content_type,\n        source="trend_admin_text_bot",\n    )\n    return public_url\n\n\nasync def _show_model_step(message: types.Message, state: FSMContext) -> None:\n    await state.set_state(TrendVideoUploadStates.waiting_model)\n    await message.answer(\n        "<b>Шаг 3/5. Выберите видео-модель</b>\\n\\n"\n        "Пользователю автоматически подставится именно эта нейросеть.",\n        reply_markup=_video_model_keyboard(),\n        parse_mode="HTML",\n    )\n\n\nasync def _show_confirmation(message: types.Message, data: dict[str, Any]) -> None:\n    title = html.escape(str(data.get("title") or "Видео-тренд"))\n    description = html.escape(str(data.get("description") or ""))\n    model_id = str(data.get("model") or "v3_pro")\n    model_label = html.escape(_VIDEO_MODEL_LABELS.get(model_id, model_id))\n    prompt_text = str(data.get("prompt_text") or "")\n    prompt_preview = html.escape(prompt_text[:700])\n    description_line = f"\\n{description}" if description else ""\n    caption = (\n        "<b>Проверьте видео-тренд перед публикацией</b>\\n\\n"\n        f"<b>{title}</b>{description_line}\\n\\n"\n        f"Нейросеть: <code>{model_label}</code>\\n"\n        "Тип: <code>Видео</code>\\n\\n"\n        f"Скрытый prompt:\\n<pre>{prompt_preview}</pre>"\n    )\n    if len(prompt_text) > 700:\n        caption += "\\n<i>Показано начало prompt.</i>"\n\n    preview_url = str(data.get("preview_url") or "")\n    try:\n        await message.answer_video(\n            preview_url,\n            caption=caption,\n            reply_markup=_confirm_keyboard(),\n            parse_mode="HTML",\n            supports_streaming=True,\n        )\n    except Exception:\n        logger.exception("Unable to show video trend confirmation preview")\n        await message.answer(\n            caption,\n            reply_markup=_confirm_keyboard(),\n            parse_mode="HTML",\n        )\n\n\n@router.callback_query(F.data == "trend_video_add")\nasync def start_video_trend_upload(\n    callback: types.CallbackQuery,\n    state: FSMContext,\n) -> None:\n    if not _is_admin_user(callback.from_user):\n        await callback.answer("Нет доступа", show_alert=True)\n        return\n\n    await state.clear()\n    await state.set_state(TrendVideoUploadStates.waiting_title)\n    if callback.message:\n        await callback.message.answer(\n            "<b>Шаг 1/5. Название видео-тренда</b>\\n\\n"\n            "Отправьте короткое название до 80 символов.",\n            reply_markup=_cancel_keyboard(),\n            parse_mode="HTML",\n        )\n    await callback.answer()\n\n\n@router.message(TrendVideoUploadStates.waiting_title)\nasync def receive_video_trend_title(\n    message: types.Message,\n    state: FSMContext,\n) -> None:\n    if await _reject_non_admin_message(message, state):\n        return\n    title = str(message.text or "").strip()\n    if not title:\n        await message.answer("Отправьте название обычным текстом.")\n        return\n    if len(title) > 80:\n        await message.answer("Название слишком длинное. Максимум 80 символов.")\n        return\n\n    await state.update_data(title=title)\n    await state.set_state(TrendVideoUploadStates.waiting_description)\n    await message.answer(\n        "<b>Шаг 2/5. Короткое описание</b>\\n\\n"\n        "Напишите, что получится и какие исходники понадобятся. "\n        "Максимум 240 символов.",\n        reply_markup=_description_keyboard(),\n        parse_mode="HTML",\n    )\n\n\n@router.callback_query(\n    StateFilter(TrendVideoUploadStates.waiting_description),\n    F.data == "trend_video_desc_skip",\n)\nasync def skip_video_trend_description(\n    callback: types.CallbackQuery,\n    state: FSMContext,\n) -> None:\n    if not _is_admin_user(callback.from_user):\n        await callback.answer("Нет доступа", show_alert=True)\n        return\n    await state.update_data(description="")\n    if callback.message:\n        await _show_model_step(callback.message, state)\n    await callback.answer("Описание пропущено")\n\n\n@router.message(TrendVideoUploadStates.waiting_description)\nasync def receive_video_trend_description(\n    message: types.Message,\n    state: FSMContext,\n) -> None:\n    if await _reject_non_admin_message(message, state):\n        return\n    description = str(message.text or "").strip()\n    if not description:\n        await message.answer(\n            "Отправьте описание текстом или нажмите «Пропустить описание».",\n            reply_markup=_description_keyboard(),\n        )\n        return\n    if len(description) > 240:\n        await message.answer("Описание слишком длинное. Максимум 240 символов.")\n        return\n    await state.update_data(description=description)\n    await _show_model_step(message, state)\n\n\n@router.callback_query(\n    StateFilter(TrendVideoUploadStates.waiting_model),\n    F.data.startswith("trend_video_model:"),\n)\nasync def select_video_trend_model(\n    callback: types.CallbackQuery,\n    state: FSMContext,\n) -> None:\n    if not _is_admin_user(callback.from_user):\n        await callback.answer("Нет доступа", show_alert=True)\n        return\n    model_id = str(callback.data or "").partition(":")[2]\n    if model_id not in _VIDEO_MODEL_IDS:\n        await callback.answer("Неизвестная модель", show_alert=True)\n        return\n\n    await state.update_data(model=model_id)\n    await state.set_state(TrendVideoUploadStates.waiting_preview)\n    if callback.message:\n        await callback.message.answer(\n            "<b>Шаг 4/5. Видео-пример тренда</b>\\n\\n"\n            "Отправьте готовый ролик как видео или файл MP4, WEBM либо MOV. "\n            "Лимит — 20 МБ.",\n            reply_markup=_cancel_keyboard(),\n            parse_mode="HTML",\n        )\n    await callback.answer(_VIDEO_MODEL_LABELS[model_id])\n\n\n@router.message(TrendVideoUploadStates.waiting_preview)\nasync def receive_video_trend_preview(\n    message: types.Message,\n    state: FSMContext,\n) -> None:\n    if await _reject_non_admin_message(message, state):\n        return\n    if not _video_file_metadata(message):\n        await message.answer(\n            "Отправьте видео MP4, WEBM или MOV как ролик либо документ.",\n            reply_markup=_cancel_keyboard(),\n        )\n        return\n\n    status = await message.answer("Загружаю видео-пример…")\n    preview_url = await _save_video_preview(message)\n    if not preview_url:\n        await status.edit_text(\n            "Не удалось сохранить видео. Проверьте формат и размер файла."\n        )\n        return\n\n    await state.update_data(preview_url=preview_url)\n    await state.set_state(TrendVideoUploadStates.waiting_prompt)\n    await status.edit_text(\n        "<b>Шаг 5/5. Скрытый prompt</b>\\n\\n"\n        "Отправьте готовый prompt видео-шаблона. Пользователь не увидит его "\n        "в карточке, но он подставится после нажатия «Повторить шаблон».",\n        reply_markup=_cancel_keyboard(),\n        parse_mode="HTML",\n    )\n\n\n@router.message(TrendVideoUploadStates.waiting_prompt)\nasync def receive_video_trend_prompt(\n    message: types.Message,\n    state: FSMContext,\n) -> None:\n    if await _reject_non_admin_message(message, state):\n        return\n    prompt_text = str(message.text or "").strip()\n    if not prompt_text:\n        await message.answer("Отправьте prompt обычным текстом.")\n        return\n    if len(prompt_text) > 8000:\n        await message.answer("Prompt слишком длинный. Максимум 8000 символов.")\n        return\n\n    policy_error = detect_explicit_prompt_policy_violation(prompt_text)\n    if policy_error:\n        await message.answer(policy_error)\n        return\n\n    await state.update_data(prompt_text=prompt_text)\n    await state.set_state(TrendVideoUploadStates.confirming)\n    await _show_confirmation(message, await state.get_data())\n\n\n@router.callback_query(\n    StateFilter(TrendVideoUploadStates.confirming),\n    F.data == "trend_video_publish_confirm",\n)\nasync def publish_video_trend(\n    callback: types.CallbackQuery,\n    state: FSMContext,\n) -> None:\n    if not _is_admin_user(callback.from_user):\n        await callback.answer("Нет доступа", show_alert=True)\n        return\n\n    data = await state.get_data()\n    required = ("title", "model", "preview_url", "prompt_text")\n    if any(not str(data.get(key) or "").strip() for key in required):\n        await callback.answer(\n            "Данные мастера устарели. Начните загрузку заново.",\n            show_alert=True,\n        )\n        await state.clear()\n        return\n\n    user = await database.get_or_create_user(callback.from_user.id)\n    prompt = await database.create_prompt(\n        author_id=user.id,\n        prompt_text=str(data["prompt_text"]),\n        title=str(data["title"]),\n        description=str(data.get("description") or "").strip() or None,\n        category="video",\n        preview_url=str(data["preview_url"]),\n        model=str(data["model"]),\n        tags=[TREND_TAG, TREND_VIDEO_TAG],\n        is_public=True,\n    )\n    if not prompt:\n        await callback.answer("Не удалось создать видео-тренд", show_alert=True)\n        return\n\n    approved = await database.approve_prompt(prompt["id"])\n    if not approved:\n        await callback.answer("Не удалось опубликовать видео-тренд", show_alert=True)\n        return\n\n    await state.clear()\n    await callback.answer("Видео-тренд опубликован")\n    if callback.message:\n        await callback.message.answer(\n            "✅ <b>Видео-тренд опубликован</b>\\n\\n"\n            "Он уже доступен пользователям в текстовом боте и Mini App.",\n            parse_mode="HTML",\n        )\n        if _TRENDS_MODULE is not None:\n            await _TRENDS_MODULE._render_trends(\n                callback.message,\n                index=0,\n                admin_telegram_id=callback.from_user.id,\n            )\n\n\n@router.callback_query(F.data == "trend_video_add_cancel")\nasync def cancel_video_trend_upload(\n    callback: types.CallbackQuery,\n    state: FSMContext,\n) -> None:\n    if not _is_admin_user(callback.from_user):\n        await callback.answer("Нет доступа", show_alert=True)\n        return\n    await state.clear()\n    await callback.answer("Создание отменено")\n    if callback.message:\n        await callback.message.answer(\n            "Создание видео-тренда отменено.",\n            reply_markup=InlineKeyboardMarkup(\n                inline_keyboard=[\n                    [\n                        InlineKeyboardButton(\n                            text="🔥 Вернуться к трендам",\n                            callback_data="menu_trends",\n                        )\n                    ]\n                ]\n            ),\n        )\n\n\ndef _install_miniapp_video_submit(miniapp_module: Any) -> None:\n    async def miniapp_trend_submit(request: Any):\n        try:\n            body = await miniapp_module._miniapp_payload(request)\n            init_data = body.get("init_data", "")\n            telegram_id, ctx = await miniapp_module._get_user_context(\n                request.app,\n                init_data,\n                body.get("start_param_fallback"),\n            )\n            if not config.is_admin(telegram_id):\n                return miniapp_module.web.json_response(\n                    {"ok": False, "error": "Тренды может публиковать только администратор"},\n                    status=403,\n                )\n\n            title = str(body.get("title", "") or "").strip()\n            prompt_text = str(body.get("prompt_text", "") or body.get("prompt", "") or "").strip()\n            preview_url = str(body.get("preview_url", "") or "").strip()\n            model = str(body.get("model", "") or "").strip()\n            requested_tags = {\n                str(item or "").strip().lower()\n                for item in body.get("tags", []) or []\n            }\n            is_video = (\n                TREND_VIDEO_TAG in requested_tags\n                or model in _VIDEO_MODEL_IDS\n            )\n            if not title or not prompt_text or not preview_url or not model:\n                return miniapp_module.web.json_response(\n                    {\n                        "ok": False,\n                        "error": "Для тренда нужны название, preview, нейросеть и prompt",\n                    },\n                    status=400,\n                )\n\n            policy_error = detect_explicit_prompt_policy_violation(prompt_text)\n            if policy_error:\n                return miniapp_module.web.json_response(\n                    {"ok": False, "error": policy_error},\n                    status=400,\n                )\n\n            tags = [TREND_TAG]\n            if is_video:\n                tags.append(TREND_VIDEO_TAG)\n            prompt = await database.create_prompt(\n                author_id=ctx["user"].id,\n                prompt_text=prompt_text,\n                title=title,\n                description=str(body.get("description", "") or "").strip() or None,\n                category="video" if is_video else "photo",\n                preview_url=preview_url,\n                model=model,\n                tags=tags,\n                is_public=True,\n            )\n            if prompt:\n                prompt = await database.approve_prompt(prompt["id"])\n            return miniapp_module.web.json_response({"ok": True, "prompt": prompt})\n        except Exception as error:  # noqa: BLE001 - Mini App API boundary\n            return miniapp_module._miniapp_error_response(\n                error,\n                log_message="Mini App trend submit failed",\n            )\n\n    miniapp_module.miniapp_prompt_submit = miniapp_trend_submit\n\n\ndef install_trend_video_compat(trends_module: Any) -> None:\n    global _INSTALLED, _TRENDS_MODULE\n    if _INSTALLED:\n        return\n\n    _TRENDS_MODULE = trends_module\n    original_keyboard = trends_module._trend_keyboard\n    original_render = trends_module._render_trends\n\n    def trend_keyboard_with_video_upload(\n        prompt: dict[str, Any],\n        *,\n        index: int,\n        total: int,\n        is_admin: bool,\n    ) -> InlineKeyboardMarkup:\n        markup = original_keyboard(\n            prompt,\n            index=index,\n            total=total,\n            is_admin=is_admin,\n        )\n        return _add_video_upload_button(markup) if is_admin else markup\n\n    async def render_trends_with_video(\n        message: types.Message,\n        *,\n        index: int = 0,\n        admin_telegram_id: int | None = None,\n    ) -> None:\n        trends = await trends_module._get_trends()\n        if not trends and config.is_admin(admin_telegram_id):\n            await message.answer(\n                "🔥 <b>Тренды</b>\\n\\n"\n                "Пока витрина пустая. Добавьте фото- или видео-шаблон "\n                "прямо в текстовом боте.",\n                reply_markup=_empty_admin_keyboard(),\n                parse_mode="HTML",\n            )\n            return\n        if not trends:\n            await original_render(\n                message,\n                index=index,\n                admin_telegram_id=admin_telegram_id,\n            )\n            return\n\n        safe_index = max(0, min(index, len(trends) - 1))\n        trend = trends[safe_index]\n        if not is_video_trend(trend):\n            await original_render(\n                message,\n                index=safe_index,\n                admin_telegram_id=admin_telegram_id,\n            )\n            return\n\n        preview_url = str(trend.get("preview_url") or "").strip()\n        caption = trends_module._trend_caption(\n            trend,\n            index=safe_index,\n            total=len(trends),\n        )\n        caption = caption.replace(\n            "Нейросеть:",\n            "Тип: <code>Видео</code>\\nНейросеть:",\n            1,\n        )\n        markup = trend_keyboard_with_video_upload(\n            trend,\n            index=safe_index,\n            total=len(trends),\n            is_admin=config.is_admin(admin_telegram_id),\n        )\n\n        if preview_url and getattr(message, "video", None):\n            try:\n                await message.edit_media(\n                    InputMediaVideo(\n                        media=preview_url,\n                        caption=caption,\n                        parse_mode="HTML",\n                        supports_streaming=True,\n                    ),\n                    reply_markup=markup,\n                )\n                return\n            except Exception:\n                logger.debug("Unable to edit video trend media", exc_info=True)\n\n        if preview_url:\n            try:\n                await message.answer_video(\n                    preview_url,\n                    caption=caption,\n                    reply_markup=markup,\n                    parse_mode="HTML",\n                    supports_streaming=True,\n                )\n                return\n            except Exception:\n                logger.debug("Unable to send video trend preview", exc_info=True)\n\n        await message.answer(caption, reply_markup=markup, parse_mode="HTML")\n\n    trends_module._trend_keyboard = trend_keyboard_with_video_upload\n    trends_module._render_trends = render_trends_with_video\n\n    from bot import miniapp as miniapp_module\n\n    _install_miniapp_video_submit(miniapp_module)\n    _INSTALLED = True\n', encoding="utf-8")
    Path("tests/test_trend_video_compat.py").write_text('from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup\n\nfrom bot.handlers.trend_video_compat import (\n    TREND_VIDEO_MODELS,\n    TREND_VIDEO_TAG,\n    _add_video_upload_button,\n    is_video_trend,\n)\n\n\ndef test_video_trend_detection_supports_tag_category_and_model() -> None:\n    assert is_video_trend({"tags": [TREND_VIDEO_TAG]}) is True\n    assert is_video_trend({"category": "video", "tags": []}) is True\n    assert is_video_trend({"model": "v3_pro", "tags": []}) is True\n    assert is_video_trend({"model": "banana_pro", "tags": ["trend"]}) is False\n    assert is_video_trend(None) is False\n\n\ndef test_video_model_ids_are_unique() -> None:\n    model_ids = [model_id for model_id, _label in TREND_VIDEO_MODELS]\n    assert model_ids\n    assert len(model_ids) == len(set(model_ids))\n\n\ndef test_video_upload_button_is_added_once() -> None:\n    original = InlineKeyboardMarkup(\n        inline_keyboard=[\n            [InlineKeyboardButton(text="Повторить", callback_data="noop")],\n            [InlineKeyboardButton(text="Загрузить фото", callback_data="trend_add")],\n        ]\n    )\n\n    updated = _add_video_upload_button(original)\n    repeated = _add_video_upload_button(updated)\n\n    callbacks = [\n        button.callback_data\n        for row in repeated.inline_keyboard\n        for button in row\n    ]\n    assert callbacks.count("trend_video_add") == 1\n    assert original.inline_keyboard != repeated.inline_keyboard\n', encoding="utf-8")
    Path("frontend/miniapp-v0/components/tabs/trends-tab.tsx").write_text("""'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useApp } from '@/lib/app-context'
import type { PromptItem, ScenarioType } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { deactivatePrompt, fetchPrompts, submitPrompt, uploadFile } from '@/lib/api'
import {
  Film,
  Flame,
  ImagePlus,
  Loader2,
  Plus,
  Repeat2,
  Sparkles,
  Trash2,
  Upload,
  X,
} from 'lucide-react'

type TrendKind = 'image' | 'video'

const VIDEO_TREND_TAG = 'trend-video'

function hasVideoTag(trend: PromptItem) {
  return (trend.tags || []).some((tag) => String(tag).toLowerCase() === VIDEO_TREND_TAG)
}

export function TrendsTab() {
  const {
    state,
    setActiveTab,
    setPromptPreset,
    setVideoPromptPreset,
  } = useApp()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [items, setItems] = useState<PromptItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [trendKind, setTrendKind] = useState<TrendKind>('image')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [promptText, setPromptText] = useState('')
  const [model, setModel] = useState('banana_pro')
  const [previewUrl, setPreviewUrl] = useState('')
  const [uploadingPreview, setUploadingPreview] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [removingId, setRemovingId] = useState<number | null>(null)

  const isLive = state.mode === 'live'
  const isAdmin = state.user.isAdmin
  const availableModels = trendKind === 'video' ? state.videoModels : state.imageModels

  const videoModelIds = useMemo(
    () => new Set(state.videoModels.map((item) => item.id)),
    [state.videoModels],
  )

  const isVideoTrend = (trend: PromptItem) =>
    trend.category === 'video' ||
    hasVideoTag(trend) ||
    videoModelIds.has(String(trend.model || ''))

  async function loadTrends() {
    if (!isLive) {
      setItems([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const trends = await fetchPrompts({ source: 'catalog', limit: 80 })
      setItems(trends)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить тренды')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadTrends()
  }, [isLive])

  useEffect(() => {
    const models = trendKind === 'video' ? state.videoModels : state.imageModels
    if (!models.some((item) => item.id === model)) {
      setModel(models[0]?.id || (trendKind === 'video' ? 'v3_pro' : 'banana_pro'))
    }
    setPreviewUrl('')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [model, state.imageModels, state.videoModels, trendKind])

  const resetForm = () => {
    setTrendKind('image')
    setTitle('')
    setDescription('')
    setPromptText('')
    setModel(state.imageModels[0]?.id || 'banana_pro')
    setPreviewUrl('')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const applyTrend = (trend: PromptItem) => {
    if (isVideoTrend(trend)) {
      const videoModel = state.videoModels.find((item) => item.id === trend.model)
      const scenario = (
        videoModel?.supports.includes('text')
          ? 'text'
          : videoModel?.supports[0] || 'text'
      ) as ScenarioType
      setVideoPromptPreset({
        title: trend.title,
        prompt: trend.prompt_text,
        model: videoModel?.id || state.videoModels[0]?.id || 'v3_pro',
        scenario,
      })
      setActiveTab(2)
      return
    }

    setPromptPreset({
      promptId: trend.id,
      title: trend.title,
      prompt: trend.prompt_text,
      model: trend.model || state.imageModels[0]?.id || 'banana_pro',
    })
    setActiveTab(1)
  }

  const handlePreviewUpload = async (file?: File) => {
    if (!file) return
    const expectedPrefix = trendKind === 'video' ? 'video/' : 'image/'
    if (!file.type.startsWith(expectedPrefix)) {
      setError(
        trendKind === 'video'
          ? 'Для видео-тренда нужен видеофайл'
          : 'Для фото-тренда нужно изображение',
      )
      return
    }

    setUploadingPreview(true)
    setError(null)
    try {
      const uploaded = await uploadFile(
        trendKind === 'video' ? 'video_reference' : 'image_reference',
        file,
      )
      setPreviewUrl(uploaded.url)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить preview')
    } finally {
      setUploadingPreview(false)
    }
  }

  const handleCreate = async () => {
    if (!isAdmin || submitting) return
    if (!title.trim() || !promptText.trim() || !previewUrl || !model) {
      setError('Заполните название, preview, нейросеть и скрытый prompt')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const created = await submitPrompt({
        title: title.trim(),
        description: description.trim(),
        promptText: promptText.trim(),
        previewUrl,
        model,
        tags: trendKind === 'video' ? ['trend', VIDEO_TREND_TAG] : ['trend'],
      })
      setItems((prev) => [created, ...prev.filter((item) => item.id !== created.id)])
      resetForm()
      setIsCreateOpen(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось опубликовать тренд')
    } finally {
      setSubmitting(false)
    }
  }

  const handleRemove = async (trend: PromptItem) => {
    if (!isAdmin || removingId !== null) return
    setRemovingId(trend.id)
    setError(null)
    try {
      await deactivatePrompt(trend.id)
      setItems((prev) => prev.filter((item) => item.id !== trend.id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось убрать тренд')
    } finally {
      setRemovingId(null)
    }
  }

  return (
    <div className="space-y-5 px-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Flame className="h-5 w-5 text-gold" />
            <h2 className="font-serif text-xl font-semibold text-foreground">Тренды</h2>
          </div>
          <p className="mt-1 max-w-xl text-sm text-muted-foreground">
            Готовые фото- и видео-шаблоны от команды NEUROMIX.
          </p>
        </div>
        {isAdmin ? (
          <Button
            type="button"
            size="sm"
            className="shrink-0 bg-gold text-primary-foreground hover:bg-gold/90"
            onClick={() => setIsCreateOpen((value) => !value)}
          >
            {isCreateOpen ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
            {isCreateOpen ? 'Закрыть' : 'Добавить'}
          </Button>
        ) : null}
      </div>

      {isAdmin && isCreateOpen ? (
        <section className="glass space-y-4 rounded-2xl border border-gold/25 p-4">
          <div>
            <p className="text-sm font-semibold text-foreground">Новый тренд</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Пользователи увидят пример и описание, но не увидят скрытый prompt.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => setTrendKind('image')}
              className={`rounded-xl border px-3 py-3 text-sm font-medium transition ${
                trendKind === 'image'
                  ? 'border-gold/50 bg-gold/15 text-gold'
                  : 'border-border/50 bg-secondary/40 text-muted-foreground'
              }`}
            >
              Фото-тренд
            </button>
            <button
              type="button"
              onClick={() => setTrendKind('video')}
              className={`rounded-xl border px-3 py-3 text-sm font-medium transition ${
                trendKind === 'video'
                  ? 'border-gold/50 bg-gold/15 text-gold'
                  : 'border-border/50 bg-secondary/40 text-muted-foreground'
              }`}
            >
              Видео-тренд
            </button>
          </div>

          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Название тренда"
            maxLength={80}
            className="h-11 w-full rounded-xl border border-border/50 bg-secondary/50 px-3 text-sm outline-none focus:border-gold/50"
          />

          <Textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={
              trendKind === 'video'
                ? 'Что получится и какие исходники нужны'
                : 'Что получится и какое фото лучше загрузить'
            }
            className="min-h-[76px] resize-none bg-secondary/50"
            maxLength={240}
          />

          <label className="block space-y-2">
            <span className="text-xs font-medium text-muted-foreground">
              {trendKind === 'video' ? 'Видео-нейросеть' : 'Нейросеть для фото'}
            </span>
            <select
              value={model}
              onChange={(event) => setModel(event.target.value)}
              className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground outline-none focus:border-gold/50"
            >
              {availableModels.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label.replace('🔥 НОВИНКА', '').trim()}
                </option>
              ))}
            </select>
          </label>

          <div className="space-y-2">
            <span className="text-xs font-medium text-muted-foreground">
              {trendKind === 'video' ? 'Видео-пример шаблона' : 'Preview шаблона'}
            </span>
            <input
              ref={fileInputRef}
              type="file"
              accept={
                trendKind === 'video'
                  ? 'video/mp4,video/webm,video/quicktime'
                  : 'image/jpeg,image/png,image/webp'
              }
              className="hidden"
              onChange={(event) => void handlePreviewUpload(event.target.files?.[0])}
            />
            {previewUrl ? (
              <div className="relative overflow-hidden rounded-2xl border border-border/50 bg-secondary/40">
                {trendKind === 'video' ? (
                  <video
                    src={previewUrl}
                    controls
                    muted
                    playsInline
                    preload="metadata"
                    className="aspect-video w-full bg-black object-contain"
                  />
                ) : (
                  <img
                    src={previewUrl}
                    alt="Preview тренда"
                    className="aspect-square w-full object-cover"
                  />
                )}
                <button
                  type="button"
                  onClick={() => {
                    setPreviewUrl('')
                    if (fileInputRef.current) fileInputRef.current.value = ''
                  }}
                  className="absolute right-2 top-2 rounded-full bg-background/80 p-2 text-foreground backdrop-blur"
                  aria-label="Удалить preview"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploadingPreview}
                className="flex aspect-[16/9] w-full flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-border/70 bg-secondary/35 text-sm text-muted-foreground transition-colors hover:border-gold/40 hover:text-foreground"
              >
                {uploadingPreview ? (
                  <Loader2 className="h-6 w-6 animate-spin" />
                ) : trendKind === 'video' ? (
                  <Film className="h-7 w-7" />
                ) : (
                  <ImagePlus className="h-7 w-7" />
                )}
                {uploadingPreview
                  ? 'Загружаю…'
                  : trendKind === 'video'
                    ? 'Загрузить видео'
                    : 'Загрузить изображение'}
              </button>
            )}
          </div>

          <Textarea
            value={promptText}
            onChange={(event) => setPromptText(event.target.value)}
            placeholder="Скрытый prompt, который подставится при повторе"
            className="min-h-[150px] resize-none bg-secondary/50"
          />

          <Button
            type="button"
            className="w-full bg-gold text-primary-foreground hover:bg-gold/90"
            disabled={submitting || uploadingPreview}
            onClick={() => void handleCreate()}
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            Опубликовать тренд
          </Button>
        </section>
      ) : null}

      {error ? (
        <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="flex justify-center py-12 text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : items.length ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((trend) => {
            const videoTrend = isVideoTrend(trend)
            const modelLabel = videoTrend
              ? state.videoModels.find((item) => item.id === trend.model)?.label
              : state.imageModels.find((item) => item.id === trend.model)?.label

            return (
              <article key={trend.id} className="glass overflow-hidden rounded-2xl border border-border/50">
                <div className="relative bg-secondary/40">
                  {trend.preview_url ? (
                    videoTrend ? (
                      <video
                        src={trend.preview_url}
                        controls
                        muted
                        playsInline
                        preload="metadata"
                        className="aspect-video w-full bg-black object-contain"
                      />
                    ) : (
                      <img src={trend.preview_url} alt="" className="aspect-square w-full object-cover" />
                    )
                  ) : (
                    <div className="flex aspect-square items-center justify-center">
                      <Sparkles className="h-10 w-10 text-gold" />
                    </div>
                  )}
                  <span className="absolute left-3 top-3 rounded-full bg-background/80 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-gold backdrop-blur">
                    {videoTrend ? 'Видео-тренд' : 'Фото-тренд'}
                  </span>
                </div>

                <div className="space-y-3 p-4">
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">{trend.title}</h3>
                    {trend.description ? (
                      <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-muted-foreground">
                        {trend.description}
                      </p>
                    ) : null}
                  </div>

                  <div className="rounded-lg bg-secondary/55 px-2.5 py-2 text-[11px] text-muted-foreground">
                    {modelLabel || trend.model || (videoTrend ? 'Видео-модель' : 'Nano Banana Pro')}
                  </div>

                  <div className={isAdmin ? 'grid grid-cols-[1fr_auto] gap-2' : 'grid'}>
                    <Button
                      type="button"
                      className="bg-gold text-primary-foreground hover:bg-gold/90"
                      onClick={() => applyTrend(trend)}
                    >
                      <Repeat2 className="h-4 w-4" />
                      {videoTrend ? 'Повторить видео' : 'Повторить шаблон'}
                    </Button>
                    {isAdmin ? (
                      <Button
                        type="button"
                        variant="secondary"
                        size="icon"
                        onClick={() => void handleRemove(trend)}
                        disabled={removingId === trend.id}
                        aria-label="Убрать тренд"
                      >
                        {removingId === trend.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Trash2 className="h-4 w-4" />
                        )}
                      </Button>
                    ) : null}
                  </div>
                </div>
              </article>
            )
          })}
        </div>
      ) : (
        <div className="glass rounded-2xl border border-border/50 p-8 text-center">
          <Flame className="mx-auto h-9 w-9 text-gold/70" />
          <p className="mt-3 text-sm font-medium text-foreground">Трендов пока нет</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {isAdmin
              ? 'Нажмите «Добавить», чтобы опубликовать первый шаблон.'
              : 'Команда NEUROMIX скоро добавит новые шаблоны.'}
          </p>
        </div>
      )}
    </div>
  )
}
""", encoding="utf-8")

    replace_once(
        "frontend/miniapp-v0/lib/types.ts",
        "  category: 'art' | 'business' | 'marketing' | 'photo' | 'other'\n",
        "  category: 'art' | 'business' | 'marketing' | 'photo' | 'video' | 'other'\n",
    )

    replace_once(
        "frontend/miniapp-v0/lib/app-context.tsx",
        """        if (startTarget.kind === 'prompt') {
          const prompt = await fetchPromptDetail(startTarget.promptId)
          if (cancelled) return
          setPromptPreset({
            promptId: prompt.id,
            title: prompt.title,
            prompt: prompt.prompt_text,
            model: prompt.model,
          })
          setActiveTabState(1)
          return
        }
""",
        """        if (startTarget.kind === 'prompt') {
          const prompt = await fetchPromptDetail(startTarget.promptId)
          if (cancelled) return
          const isVideoTrend =
            prompt.category === 'video' ||
            (prompt.tags || []).some((tag) => String(tag).toLowerCase() === 'trend-video') ||
            state.videoModels.some((model) => model.id === prompt.model)

          if (isVideoTrend) {
            const videoModel = state.videoModels.find((model) => model.id === prompt.model)
            setVideoPromptPreset({
              title: prompt.title,
              prompt: prompt.prompt_text,
              model: videoModel?.id || state.videoModels[0]?.id || 'v3_pro',
              scenario: videoModel?.supports.includes('text')
                ? 'text'
                : videoModel?.supports[0] || 'text',
            })
            setActiveTabState(2)
            return
          }

          setPromptPreset({
            promptId: prompt.id,
            title: prompt.title,
            prompt: prompt.prompt_text,
            model: prompt.model,
          })
          setActiveTabState(1)
          return
        }
""",
    )
    replace_once(
        "frontend/miniapp-v0/lib/app-context.tsx",
        "  }, [applyFeedRemix, openProfile, state.isLoading, state.mode])\n",
        "  }, [applyFeedRemix, openProfile, state.isLoading, state.mode, state.videoModels])\n",
    )

    replace_once(
        "bot/handlers/__init__.py",
        """from .trend_text_upload import install_text_trend_upload
from .trend_text_upload import router as trend_text_upload_router
from .trends_compat import install_trends_compat
""",
        """from .trend_text_upload import install_text_trend_upload
from .trend_text_upload import router as trend_text_upload_router
from .trend_video_compat import install_trend_video_compat
from .trend_video_compat import router as trend_video_compat_router
from .trends_compat import install_trends_compat
""",
    )
    replace_once(
        "bot/handlers/__init__.py",
        """install_trends_compat(common_module, generation_module, admin_module)
install_text_trend_upload(trends_compat_module)
install_feed_model_filter_compat(common_module)
""",
        """install_trends_compat(common_module, generation_module, admin_module)
install_text_trend_upload(trends_compat_module)
install_trend_video_compat(trends_compat_module)
install_feed_model_filter_compat(common_module)
""",
    )
    replace_once(
        "bot/handlers/__init__.py",
        """common_router = Router()
common_router.include_router(trend_text_upload_router)
common_router.include_router(trends_compat_router)
""",
        """common_router = Router()
common_router.include_router(trend_video_compat_router)
common_router.include_router(trend_text_upload_router)
common_router.include_router(trends_compat_router)
""",
    )
    replace_once(
        "bot/handlers/__init__.py",
        '    "trend_text_upload_router",\n    "trends_compat_router",\n',
        '    "trend_text_upload_router",\n    "trend_video_compat_router",\n    "trends_compat_router",\n',
    )

    workflow = Path(".github/workflows/publication-scope-ci.yml")
    workflow_text = workflow.read_text(encoding="utf-8")
    workflow_text = workflow_text.replace(
        '      - "bot/handlers/trend_text_upload.py"\n',
        '      - "bot/handlers/trend_text_upload.py"\n'
        '      - "bot/handlers/trend_video_compat.py"\n',
        1,
    )
    workflow_text = workflow_text.replace(
        '      - "tests/test_trends_compat.py"\n',
        '      - "tests/test_trends_compat.py"\n'
        '      - "tests/test_trend_video_compat.py"\n',
        1,
    )
    workflow_text = workflow_text.replace(
        '            bot/handlers/trend_text_upload.py \\\n',
        '            bot/handlers/trend_text_upload.py \\\n'
        '            bot/handlers/trend_video_compat.py \\\n',
        2,
    )
    workflow_text = workflow_text.replace(
        '            tests/test_trends_compat.py \\\n',
        '            tests/test_trends_compat.py \\\n'
        '            tests/test_trend_video_compat.py \\\n',
        2,
    )
    workflow_text = workflow_text.replace(
        'pytest tests/test_publication_scope_compat.py tests/test_trends_compat.py -vv',
        'pytest tests/test_publication_scope_compat.py tests/test_trends_compat.py tests/test_trend_video_compat.py -vv',
        1,
    )
    workflow.write_text(workflow_text, encoding="utf-8")

    guide = Path("docs/admin-trends-guide.md")
    guide_text = guide.read_text(encoding="utf-8")
    if "## 9. Видео-тренды" not in guide_text:
        guide.write_text(guide_text.rstrip() + '\n\n## 9. Видео-тренды\n\nАдминистратор может публиковать не только изображения, но и готовые видео-шаблоны.\n\n### Через Mini App\n\n1. Откройте **«Тренды» → «Добавить»**.\n2. Выберите **«Видео-тренд»**.\n3. Заполните название и описание.\n4. Выберите видео-нейросеть.\n5. Загрузите ролик-пример в MP4, WEBM или MOV.\n6. Добавьте скрытый prompt.\n7. Нажмите **«Опубликовать тренд»**.\n8. Проверьте кнопку **«Повторить видео»**.\n\nПосле повторения пользователь попадёт во вкладку **«Видео»**. Нейросеть и prompt будут подставлены автоматически.\n\n### Через текстовый бот\n\n1. Откройте **«🔥 Тренды»**.\n2. Нажмите **«🎬 Загрузить видео-тренд»**.\n3. Пройдите мастер: название → описание → видео-модель → ролик → prompt.\n4. Проверьте карточку и нажмите **«✅ Опубликовать видео-тренд»**.\n\nВидео-пример в текстовом боте принимается как обычное видео или как файл MP4, WEBM либо MOV размером до 20 МБ.\n\nФото- и видео-тренды находятся в одной публичной витрине. Создавать и удалять их может только администратор.\n' + "\n", encoding="utf-8")

    Path("scripts/apply_trend_video_support.py").unlink()
    Path(".github/workflows/apply-trend-video-support.yml").unlink()


if __name__ == "__main__":
    main()
