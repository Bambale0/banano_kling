import asyncio
import base64
import hashlib
import hmac
import html
import json
import logging
import mimetypes
import os
import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qsl, urlparse
from uuid import uuid4

import aiohttp
from aiogram.types import BufferedInputFile, LabeledPrice
from aiohttp import web

from bot import creator_tariff_display
from bot import db as db_backend
from bot.config import config
from bot.creator_tariff import VideoQuote, quote_video_for_actor
from bot.kling4_api import catalog_entry as kling4_catalog_entry
from bot.kling4_tariff import kling4_public_enabled
from bot.payment_platform_policy import vk_payment_provider_denied
from bot.services.generation_origin import (
    generation_origin_from_context,
    generation_origin_metadata,
)
from bot.services.runtime_http import database_error_response
from bot.trend_user_fields import (
    TrendUserFieldsError,
    normalize_user_fields_settings,
)

FILE_KIND_MAP: dict[str, dict[str, Any]] = {}

from bot.database import (
    DATABASE_PATH,
    MAX_ACTIVE_PROMPTS_PER_USER,
    SavedReference,
    add_credits,
    add_feed_comment,
    add_generation_task,
    approve_prompt,
    can_attempt_telegram_delivery,
    check_can_afford,
    complete_task_in_app,
    complete_video_task,
    count_active_prompts_by_author,
    create_prompt,
    create_transaction,
    credit_feed_prompt_repeat,
    deactivate_prompt,
    deduct_credits,
    generation_adult_content,
    generation_profile_visible,
    generation_publication_references,
    generation_publication_scope,
    generation_reference_selection,
    generation_repeat_reference_indices,
    generation_repeat_reference_selection,
    get_and_clear_miniapp_notifications,
    get_approved_prompts,
    get_author_prompts,
    get_feed_comments,
    get_feed_generation_card,
    get_feed_generations,
    get_generation_task_payload,
    get_miniapp_prompt_repeat_snapshot,
    get_or_create_user,
    get_partner_overview,
    get_popular_prompts,
    get_profile_generation_card,
    get_promo_bonus_for_credits,
    get_promo_code_by_code,
    get_prompt_by_id,
    get_prompts_by_tag,
    get_top_prompts,
    get_user_by_referral_code,
    get_user_feed_generations,
    get_user_feed_summary,
    get_user_stats,
    increment_feed_share,
    is_channel_subscription_required,
    like_feed_generation,
    like_prompt,
    list_saved_references,
    mark_task_delivery_status,
    mark_telegram_chat_available,
    mark_telegram_chat_unavailable,
    needs_telegram_bot_start,
    reject_prompt,
    remove_from_feed,
    remove_from_library,
    resolve_public_generation_result_urls,
    retire_telegram_bot_start_offer,
    save_user_channel_url,
    set_feed_blurred,
    share_to_feed,
    share_to_library,
    touch_saved_references,
    update_prompt_preview_url,
    update_transaction_status,
    update_user_profile,
    use_prompt,
)
from bot.keyboards import (
    get_ai_assistant_keyboard,
    get_animate_hub_keyboard,
    get_balance_keyboard,
    get_create_hub_keyboard,
    get_edit_hub_keyboard,
    get_image_model_label,
    get_image_result_keyboard,
    get_main_menu_button_keyboard,
    get_main_menu_keyboard,
    get_more_menu_keyboard,
    get_partner_program_keyboard,
    get_payment_packages_keyboard,
    get_support_keyboard,
    get_video_model_label,
)
from bot.miniapp_links import (
    feed_bot_link as build_feed_bot_link,
)
from bot.miniapp_links import (
    feed_link as build_feed_link,
)
from bot.miniapp_links import (
    profile_link as build_profile_link,
)
from bot.miniapp_links import (
    prompt_link as build_prompt_link,
)
from bot.miniapp_links import (
    referral_bot_link as build_referral_bot_link,
)
from bot.miniapp_links import (
    referral_link as build_referral_link,
)
from bot.miniapp_links import (
    remix_bot_link as build_remix_bot_link,
)
from bot.miniapp_links import (
    remix_link as build_remix_link,
)
from bot.payment_utils import (
    TELEGRAM_STARS_CURRENCY,
    TELEGRAM_STARS_PROVIDER,
    build_stars_invoice_payload,
    package_stars_amount,
    total_package_credits,
)
from bot.quality_pricing import QUALITY_COSTS, SEEDREAM_5_PRO_QUALITY_COSTS
from bot.repeat_personalization import (
    clear_repeat_fields,  # noqa: F401 - re-exported to publication compatibility patch
    get_repeat_fields,
    get_repeat_fields_many,
    normalize_repeat_fields,  # noqa: F401 - re-exported to publication compatibility patch
    public_repeat_fields,
    render_repeat_base,
    restore_repeat_fields_if_current,  # noqa: F401 - re-exported to publication compatibility patch
    save_repeat_fields,  # noqa: F401 - re-exported to publication compatibility patch
)
from bot.services.ai_assistant_service import ai_assistant_service
from bot.services.lava_service import lava_service
from bot.services.media_input_utils import (
    canonicalize_local_upload_url,
    is_reference_contact_sheet_url,
    missing_local_upload_sources,
    reference_source_identity,
    resolve_local_upload_path,
    resolve_reference_source,
)
from bot.services.photo_prompt_billing import (
    PhotoPromptInsufficientBalance,
    refund_photo_prompt_charge,
    reserve_photo_prompt_charge,
)
from bot.services.preset_manager import preset_manager
from bot.services.reference_storage_service import save_reference_file
from bot.services.remix_prompt import compose_feed_remix_prompt
from bot.services.seedream55_pricing import (
    image_generation_cost as seedream55_cost,
)
from bot.services.seedream55_pricing import (
    input_image_price as seedream55_input_price,
)
from bot.services.seedream55_pricing import (
    quality_prices as seedream55_quality_prices,
)
from bot.services.subscription_service import (
    REQUIRED_CHANNEL_USERNAME,
    check_required_channel_subscription,
    should_block_for_subscription,
)
from bot.services.yookassa_service import yookassa_service
from bot.utils.user_facing_errors import make_user_friendly_generation_error
from bot.utils.validators import detect_explicit_prompt_policy_violation
from bot.video_reference_policy import (
    get_max_audio_references,
    get_max_video_image_references,
    get_max_video_references,
    normalize_reference_urls,
    video_model_supports_reference_videos,
)

MINIAPP_MEDIA_CACHE_DIR = Path("static/uploads/miniapp-media-cache")
MINIAPP_MEDIA_MAX_BYTES = 50 * 1024 * 1024
MINIAPP_UPLOAD_TIMEOUT_SECONDS = 900
MINIAPP_UPLOAD_DEFAULT_MAX_BYTES = 50 * 1024 * 1024
MINIAPP_TREND_VIDEO_MAX_BYTES = 200 * 1024 * 1024
_miniapp_media_locks: dict[str, asyncio.Lock] = {}


class RepeatPersonalizationAccessError(PermissionError):
    """Structured repeat values were submitted outside the admin preview."""


def _repeat_personalization_allowed(telegram_id: int) -> bool:
    from bot.repeat_personalization import personalization_allowed
    return personalization_allowed(telegram_id)


async def _attach_repeat_personalization(
    cards: list[dict[str, Any]],
    *,
    telegram_id: int,
) -> None:
    if not cards or not _repeat_personalization_allowed(telegram_id):
        return
    by_generation = await get_repeat_fields_many(
        [int(card.get("id") or 0) for card in cards]
    )
    for card in cards:
        fields = by_generation.get(int(card.get("id") or 0), [])
        if fields:
            card["repeat_user_fields"] = public_repeat_fields(fields)
            # Catalog image choices occupy *existing* replaceable source slots;
            # source URLs remain server-side and only the slot binding is public.
            slots = card.get("repeat_reference_slots")
            if (isinstance(slots, dict) and slots.get("available")
                    and isinstance(slots.get("images"), list)):
                from bot.repeat_personalization import assign_catalog_image_slots
                try:
                    assigned = assign_catalog_image_slots(slots["images"], fields)
                    card["repeat_reference_slots"] = {
                        **slots,
                        "images": [{key: value for key, value in slot.items()
                                    if key != "choice_key"} for slot in assigned],
                    }
                except ValueError:
                    card["repeat_reference_slots"] = {
                        "version": 1, "available": False, "images": [], "videos": [],
                    }


async def _repeat_personalized_source_prompt(
    source_id: int,
    source_prompt: str,
    body: dict[str, Any],
    *,
    telegram_id: int,
    image_references: list[str] | None = None,
    image_choices_supported: bool = True,
    image_model: str | None = None,
    image_source_references: list[str] | None = None,
    image_indices: list[int] | None = None,
) -> str:
    fields = None
    if image_model and _repeat_personalization_allowed(telegram_id):
        fields = await get_repeat_fields(int(source_id))
        if any(field.get("image_choices") for field in fields):
            from bot.video_repeat_reference_contract import (
                is_owned_personal_image_reference,
            )

            submitted = body.get("reference_images")
            if (not isinstance(submitted, list) or not submitted
                    or not isinstance(submitted[0], str)
                    or not is_owned_personal_image_reference(submitted[0].strip(), telegram_id)):
                logger.info("Image repeat rejected: source_id=%s user_id=%s reason=personal_photo_required",
                            source_id, telegram_id)
                raise ValueError("Ð¡Ð½Ð°Ñ‡Ð°Ð»Ð° Ð´Ð¾Ð±Ð°Ð²ÑŒÑ‚Ðµ ÑÐ²Ð¾Ñ‘ Ñ„Ð¾Ñ‚Ð¾ Ð´Ð»Ñ Ð¿Ð¾Ð²Ñ‚Ð¾Ñ€Ð°.")
            # Check explicit client input, never restored author/catalog images.
            # Slot-preserving assembly must still contain the user's own file.
            if resolve_reference_source(submitted[0].strip(), image_references or []) is None:
                raise ValueError("Ð›Ð¸Ñ‡Ð½Ð¾Ðµ Ñ„Ð¾Ñ‚Ð¾ Ð´Ð»Ñ Ð¿Ð¾Ð²Ñ‚Ð¾Ñ€Ð° Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½Ð¾. Ð—Ð°Ð³Ñ€ÑƒÐ·Ð¸Ñ‚Ðµ ÐµÐ³Ð¾ Ð·Ð°Ð½Ð¾Ð²Ð¾.")
            personal_photo = submitted[0].strip()
            if image_references and image_source_references:
                # A grant may retain the author's Image1 as well as auxiliaries.
                # Replace only that primary slot; keep Image2..N at their ordinals.
                source_primary = image_source_references[0]
                if resolve_reference_source(image_references[0], [source_primary]) is not None:
                    image_references[0] = personal_photo
                    image_references[:] = [image_references[0], *[
                        url for url in image_references[1:]
                        if resolve_reference_source(url, [personal_photo]) is None
                    ]]
            if not image_references or resolve_reference_source(image_references[0], [personal_photo]) is None:
                raise ValueError("Ð”Ð¾Ð±Ð°Ð²ÑŒÑ‚Ðµ ÑÐ²Ð¾Ñ‘ Ñ„Ð¾Ñ‚Ð¾ Ð¿ÐµÑ€Ð²Ñ‹Ð¼ Ñ€ÐµÑ„ÐµÑ€ÐµÐ½ÑÐ¾Ð¼ Ð´Ð»Ñ Ð¿Ð¾Ð²Ñ‚Ð¾Ñ€Ð°.")
    if "repeat_user_values" not in body:
        return source_prompt
    if not _repeat_personalization_allowed(telegram_id):
        raise RepeatPersonalizationAccessError("Ð˜Ð·Ð¼ÐµÐ½ÐµÐ½Ð¸Ðµ Ð´ÐµÑ‚Ð°Ð»ÐµÐ¹ ÑÐµÐ¹Ñ‡Ð°Ñ Ð½ÐµÐ´Ð¾ÑÑ‚ÑƒÐ¿Ð½Ð¾. ÐŸÐ¾Ð¿Ñ€Ð¾Ð±ÑƒÐ¹Ñ‚Ðµ Ð¿Ð¾Ð·Ð¶Ðµ.")
    if fields is None:
        fields = await get_repeat_fields(int(source_id))
    if not fields:
        raise TrendUserFieldsError("Ð”Ð»Ñ ÑÑ‚Ð¾Ð¹ Ð¿ÑƒÐ±Ð»Ð¸ÐºÐ°Ñ†Ð¸Ð¸ Ð¿Ð°Ñ€Ð°Ð¼ÐµÑ‚Ñ€Ñ‹ Ð¿Ð¾Ð²Ñ‚Ð¾Ñ€Ð° Ð½Ðµ Ð½Ð°ÑÑ‚Ñ€Ð¾ÐµÐ½Ñ‹")
    from bot.repeat_personalization import append_repeat_images, repeat_image_references

    images = repeat_image_references(fields, body.get("repeat_user_values"), telegram_id=telegram_id)
    if images and not image_choices_supported:
        raise ValueError("Ð’ ÑÑ‚Ð¾Ð¼ Ñ€ÐµÐ¶Ð¸Ð¼Ðµ Ð½ÐµÐ»ÑŒÐ·Ñ Ð²Ñ‹Ð±Ñ€Ð°Ñ‚ÑŒ ÐºÐ°Ñ€Ñ‚Ð¸Ð½ÐºÐ¸. Ð’Ñ‹Ð±ÐµÑ€Ð¸Ñ‚Ðµ ÑÐ¾Ð·Ð´Ð°Ð½Ð¸Ðµ Ð¿Ð¾ Ð¾Ð±Ñ€Ð°Ð·Ñ†Ð°Ð¼.")
    if images and image_references is None:
        raise ValueError("Ð’ ÑÑ‚Ð¾Ð¼ Ñ€ÐµÐ¶Ð¸Ð¼Ðµ Ð½ÐµÐ´Ð¾ÑÑ‚ÑƒÐ¿ÐµÐ½ Ð²Ñ‹Ð±Ð¾Ñ€ Ð¸Ð·Ð¾Ð±Ñ€Ð°Ð¶ÐµÐ½Ð¸Ð¹")
    compiled_images = list(image_references or [])
    # A publication with curated source-slot choices already placed selected
    # files into the original image positions at the authenticated boundary.
    # Appending them again would double the provider inputs and lose face slots.
    if image_indices is None:
        indices = append_repeat_images(compiled_images, images)
    else:
        if len(image_indices) != len(images):
            raise ValueError("Ð˜Ð·Ð¾Ð±Ñ€Ð°Ð¶ÐµÐ½Ð¸Ñ Ð´Ð»Ñ Ð¿Ð¾Ð²Ñ‚Ð¾Ñ€Ð° Ð¸Ð·Ð¼ÐµÐ½Ð¸Ð»Ð¸ÑÑŒ. ÐžÑ‚ÐºÑ€Ð¾Ð¹Ñ‚Ðµ Ñ€Ð°Ð±Ð¾Ñ‚Ñƒ Ð·Ð°Ð½Ð¾Ð²Ð¾")
        indices = image_indices
    if images and image_model:
        from bot.handlers.generation import _prepare_banana_reference_images
        from bot.services.media_input_utils import reference_source_identity

        effective_images = _prepare_banana_reference_images(image_model, compiled_images)
        if [reference_source_identity(url) for url in effective_images] != [reference_source_identity(url) for url in compiled_images]:
            raise ValueError("Ð¡Ð»Ð¸ÑˆÐºÐ¾Ð¼ Ð¼Ð½Ð¾Ð³Ð¾ Ñ€ÐµÑ„ÐµÑ€ÐµÐ½ÑÐ¾Ð² Ð´Ð»Ñ Ð²Ñ‹Ð±Ñ€Ð°Ð½Ð½Ð¾Ð¹ Ð¼Ð¾Ð´ÐµÐ»Ð¸ Ñ ÑƒÑ‡Ñ‘Ñ‚Ð¾Ð¼ Ð¿ÐµÑ€ÑÐ¾Ð½Ð°Ð»Ð¸Ð·Ð°Ñ†Ð¸Ð¸")
    rendered = render_repeat_base(
        source_prompt, fields, body.get("repeat_user_values"),
        image_indices=indices,
    )
    if image_references is not None:
        image_references[:] = compiled_images
    return rendered

logger = logging.getLogger(__name__)


def _save_uploaded_file_lazy(raw: bytes, extension: str):
    from bot.handlers.generation import save_uploaded_file

    return save_uploaded_file(raw, extension)


async def _start_image_generation_task_lazy(**kwargs):
    from bot.handlers.generation import _start_image_generation_task

    return await _start_image_generation_task(**kwargs)


_MINIAPP_INIT_DATA_ERRORS = {
    "Missing init_data": "ÐžÑ‚ÐºÑ€Ð¾Ð¹Ñ‚Ðµ Mini App Ð¸Ð· Telegram Ð¸ Ð¿Ð¾Ð¿Ñ€Ð¾Ð±ÑƒÐ¹Ñ‚Ðµ ÑÐ½Ð¾Ð²Ð°.",
    "Missing Telegram hash": "ÐžÑ‚ÐºÑ€Ð¾Ð¹Ñ‚Ðµ Mini App Ð¸Ð· Telegram Ð¸ Ð¿Ð¾Ð¿Ñ€Ð¾Ð±ÑƒÐ¹Ñ‚Ðµ ÑÐ½Ð¾Ð²Ð°.",
    "Invalid Telegram signature": "ÐžÑ‚ÐºÑ€Ð¾Ð¹Ñ‚Ðµ Mini App Ð·Ð°Ð½Ð¾Ð²Ð¾ Ð¸Ð· Telegram.",
    "Expired Telegram session": "Ð¡ÐµÑÑÐ¸Ñ Telegram Ð¸ÑÑ‚ÐµÐºÐ»Ð°. ÐžÑ‚ÐºÑ€Ð¾Ð¹Ñ‚Ðµ Mini App Ð·Ð°Ð½Ð¾Ð²Ð¾ Ð¸Ð· Telegram.",
    "Missing Telegram user": "ÐžÑ‚ÐºÑ€Ð¾Ð¹Ñ‚Ðµ Mini App Ð·Ð°Ð½Ð¾Ð²Ð¾ Ð¸Ð· Telegram.",
}


def _miniapp_expected_error_response(error: Exception) -> web.Response | None:
    unavailable = database_error_response(error)
    if unavailable is not None:
        return unavailable
    if isinstance(error, PermissionError):
        return web.json_response({"ok": False, "error": str(error)}, status=403)

    if isinstance(error, ValueError):
        message = str(error)
        if message in _MINIAPP_INIT_DATA_ERRORS:
            return web.json_response(
                {"ok": False, "error": _MINIAPP_INIT_DATA_ERRORS[message]},
                status=401,
            )
        if (
            "Could not find starting boundary" in message
            or "Invalid boundary" in message
            or "multipart" in message.lower()
        ):
            return web.json_response(
                {"ok": False, "error": "Ð—Ð°Ð³Ñ€ÑƒÐ·ÐºÐ° Ð±Ñ‹Ð»Ð° Ð¿Ñ€ÐµÑ€Ð²Ð°Ð½Ð°. ÐŸÐ¾Ð²Ñ‚Ð¾Ñ€Ð¸Ñ‚Ðµ Ð¿Ð¾Ð¿Ñ‹Ñ‚ÐºÑƒ."},
                status=400,
            )

    if isinstance(error, TimeoutError):
        return web.json_response(
            {"ok": False, "error": "Ð—Ð°Ð³Ñ€ÑƒÐ·ÐºÐ° Ð½Ðµ Ð·Ð°Ð²ÐµÑ€ÑˆÐ¸Ð»Ð°ÑÑŒ Ð·Ð° 60 ÑÐµÐºÑƒÐ½Ð´. ÐŸÐ¾Ð¿Ñ€Ð¾Ð±ÑƒÐ¹Ñ‚Ðµ ÐµÑ‰Ñ‘ Ñ€Ð°Ð·."},
            status=408,
        )

    if isinstance(error, ConnectionResetError):
        return web.json_response(
            {"ok": False, "error": "Ð—Ð°Ð³Ñ€ÑƒÐ·ÐºÐ° Ð±Ñ‹Ð»Ð° Ð¿Ñ€ÐµÑ€Ð²Ð°Ð½Ð°. ÐŸÐ¾Ð¿Ñ€Ð¾Ð±ÑƒÐ¹Ñ‚Ðµ ÐµÑ‰Ñ‘ Ñ€Ð°Ð·."},
            status=499,
        )

    if isinstance(error, web.HTTPException):
        return web.json_response(
            {"ok": False, "error": error.reason or "Mini App request failed"},
            status=error.status,
        )

    return None


def _private_image_error_response(error: Exception, *, log_message: str) -> web.Response:
    # Adapter failures may echo input URLs or the source recipe. Preserve an
    # error class for diagnosis without returning/logging the provider text.
    expected = _miniapp_expected_error_response(error)
    status = expected.status if expected is not None else 500
    if status == 401:
        message = "ÐžÑ‚ÐºÑ€Ð¾Ð¹Ñ‚Ðµ Mini App Ð·Ð°Ð½Ð¾Ð²Ð¾ Ð¸Ð· Telegram."
    elif status == 403:
        message = "ÐÐµÑ‚ Ð´Ð¾ÑÑ‚ÑƒÐ¿Ð° Ðº ÑÑ‚Ð¾Ð¼Ñƒ Ð´ÐµÐ¹ÑÑ‚Ð²Ð¸ÑŽ. ÐŸÑ€Ð¾Ð²ÐµÑ€ÑŒÑ‚Ðµ Ð´Ð¾ÑÑ‚ÑƒÐ¿ Ð² Mini App."
    elif status in {400, 408, 499}:
        message = "Ð—Ð°Ð¿Ñ€Ð¾Ñ Ð±Ñ‹Ð» Ð¿Ñ€ÐµÑ€Ð²Ð°Ð½. ÐŸÐ¾Ð¿Ñ€Ð¾Ð±ÑƒÐ¹Ñ‚Ðµ ÐµÑ‰Ñ‘ Ñ€Ð°Ð·."
    else:
        message = "ÐÐµ ÑƒÐ´Ð°Ð»Ð¾ÑÑŒ Ð²Ñ‹Ð¿Ð¾Ð»Ð½Ð¸Ñ‚ÑŒ Ð·Ð°Ð¿Ñ€Ð¾Ñ Ð³ÐµÐ½ÐµÑ€Ð°Ñ†Ð¸Ð¸. ÐŸÐ¾Ð¿Ñ€Ð¾Ð±ÑƒÐ¹Ñ‚Ðµ ÐµÑ‰Ñ‘ Ñ€Ð°Ð·."
    logger.error("%s: error_type=%s status=%s", log_message, type(error).__name__, status)
    return web.json_response({"ok": False, "error": message}, status=status)


def _video_repeat_prompt_too_long_response() -> web.Response:
    return web.json_response(
        {"ok": False, "code": "repeat_prompt_too_long",
         "error": "ÐžÐ¿Ð¸ÑÐ°Ð½Ð¸Ðµ Ð°Ð²Ñ‚Ð¾Ñ€Ð° Ð²Ð¼ÐµÑÑ‚Ðµ Ñ Ð¿Ñ€Ð°Ð²ÐºÐ°Ð¼Ð¸ Ð½Ðµ Ð¿Ð¾Ð¼ÐµÑ‰Ð°ÐµÑ‚ÑÑ Ð² Ð·Ð°Ð¿Ñ€Ð¾Ñ. "
                  "Ð¡Ð¾ÐºÑ€Ð°Ñ‚Ð¸Ñ‚Ðµ ÑÐ²Ð¾Ð¸ Ð¿Ñ€Ð°Ð²ÐºÐ¸ Ð¸Ð»Ð¸ Ð²Ñ‹Ð±ÐµÑ€Ð¸Ñ‚Ðµ Ð´Ñ€ÑƒÐ³ÑƒÑŽ Ð¿ÑƒÐ±Ð»Ð¸ÐºÐ°Ñ†Ð¸ÑŽ."},
        status=400,
    )


def _miniapp_error_response(
    error: Exception,
    *,
    log_message: str,
    default_error: str | None = None,
) -> web.Response:
    expected_response = _miniapp_expected_error_response(error)
    if expected_response is not None:
        logger.warning("%s: error_type=%s status=%s", log_message, type(error).__name__, expected_response.status)
        return expected_response

    logger.exception(log_message)
    return web.json_response(
        {"ok": False, "error": default_error or str(error)},
        status=500,
    )


def _bounded_int(value: Any, *, default: int, minimum: int = 1, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed <= 0:
        parsed = default
    return min(max(parsed, minimum), maximum)


def _miniapp_optional_int(value: Any, *, field_label: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_label} Ð´Ð¾Ð»Ð¶ÐµÐ½ Ð±Ñ‹Ñ‚ÑŒ Ñ‡Ð¸ÑÐ»Ð¾Ð¼")  # noqa: TRY004 - preserves the public validation-error contract
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise ValueError(f"{field_label} Ð´Ð¾Ð»Ð¶ÐµÐ½ Ð±Ñ‹Ñ‚ÑŒ Ñ‡Ð¸ÑÐ»Ð¾Ð¼")


def _miniapp_bool(value: Any, *, default: bool, field_label: str) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field_label} Ð´Ð¾Ð»Ð¶ÐµÐ½ Ð±Ñ‹Ñ‚ÑŒ true Ð¸Ð»Ð¸ false")


def _saved_reference_payload(reference: SavedReference) -> dict[str, Any]:
    file_url = reference.file_url
    if reference.kind == "image":
        from bot.services.media_input_utils import image_source_to_provider_safe_png_url

        file_url = image_source_to_provider_safe_png_url(file_url)

    return {
        "id": str(reference.id),
        "kind": reference.kind,
        "url": file_url,
        "filename": reference.original_filename or Path(reference.file_url).name,
        "content_type": reference.content_type,
        "source": reference.source,
        "created_at": reference.created_at.isoformat() if reference.created_at else None,
        "last_used_at": reference.last_used_at.isoformat() if reference.last_used_at else None,
    }


def _payment_package_payload(package: dict[str, Any]) -> dict[str, Any]:
    payload = dict(package)
    payload["price_stars"] = package_stars_amount(package)
    return payload


def _lava_unavailable_response(result: Any) -> web.Response | None:
    status = result.get("status") if isinstance(result, dict) else None
    if status is None or status in {401, 403, 429} or (
        isinstance(status, int) and status >= 500
    ):
        logger.warning("Lava checkout unavailable: provider_status=%s", status)
        return web.json_response(
            {
                "ok": False,
                "code": "payment_provider_unavailable",
                "error": "Lava Ð²Ñ€ÐµÐ¼ÐµÐ½Ð½Ð¾ Ð½ÐµÐ´Ð¾ÑÑ‚ÑƒÐ¿Ð½Ð°. Ð’Ñ‹Ð±ÐµÑ€Ð¸Ñ‚Ðµ Ð´Ñ€ÑƒÐ³Ð¾Ð¹ ÑÐ¿Ð¾ÑÐ¾Ð± Ð¾Ð¿Ð»Ð°Ñ‚Ñ‹ Ð¸Ð»Ð¸ Ð¿Ð¾Ð¿Ñ€Ð¾Ð±ÑƒÐ¹Ñ‚Ðµ Ð¿Ð¾Ð·Ð¶Ðµ.",
            },
            status=503,
        )
    return None


def _miniapp_package_lava_offer_config(package: dict[str, Any]) -> tuple[str, str]:
    package_id = str(package.get("id") or "")
    offer_id = str(package.get("lava_offer_id") or "").strip()
    if offer_id:
        currency = str(package.get("lava_currency") or "RUB").strip().upper() or "RUB"
        return offer_id, currency
    return config.lava_offer_id_for_package(package_id), "RUB"


def _miniapp_package_lava_foreign_offer_config(
    package: dict[str, Any],
) -> tuple[str, str]:
    offer_id = str(package.get("lava_foreign_offer_id") or "").strip()
    if offer_id:
        currency = (
            str(package.get("lava_foreign_currency") or "USD").strip().upper() or "USD"
        )
        return offer_id, currency
    product_id = str(package.get("lava_foreign_product_id") or "").strip()
    return product_id, "USD" if product_id else ""


def _runtime_image_model_metadata(item: dict) -> dict:
    """Return live prices, never the frozen module-import snapshot."""
    if item.get("id") not in {"seedream_55", "seedream_55_layers"}:
        return item
    quality_prices = seedream55_quality_prices()
    return {
        **item,
        "cost": quality_prices["2K"],
        "quality_costs": quality_prices,
        "reference_unit_cost": seedream55_input_price(),
    }


IMAGE_MODELS = (
    {
        "id": "nano-banana-2-lite",
        "label": "Nano Banana 2 Lite ðŸ”¥ ÐÐžÐ’Ð˜ÐÐšÐ",
        "description": "Ð‘Ñ‹ÑÑ‚Ñ€Ð°Ñ Ð½Ð¾Ð²Ð¸Ð½ÐºÐ° Ð´Ð»Ñ Ð»Ñ‘Ð³ÐºÐ¸Ñ… image-Ð·Ð°Ð´Ð°Ñ‡ Ð¸ Ð±Ñ‹ÑÑ‚Ñ€Ñ‹Ñ… Ð¸Ñ‚ÐµÑ€Ð°Ñ†Ð¸Ð¹",
        "cost": preset_manager.get_generation_cost("nano-banana-2-lite"),
        "ratios": [
            "1:1",
            "16:9",
            "9:16",
            "4:3",
            "3:4",
            "4:5",
            "5:4",
            "3:2",
            "2:3",
            "21:9",
        ],
        "requires_reference": False,
        "max_references": 8,
    },
    {
        "id": "seedream_55",
        "label": "Seedream 5.5",
        "description": "Ð¡Ð¾Ð·Ð´Ð°Ð½Ð¸Ðµ Ñ Ð½ÑƒÐ»Ñ Ð¸ Ñ€ÐµÐ´Ð°ÐºÑ‚Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð¸Ðµ Ñ 1â€“10 Ñ€ÐµÑ„ÐµÑ€ÐµÐ½ÑÐ°Ð¼Ð¸",
        "cost": seedream55_quality_prices()["2K"],
        "ratios": ["1:1", "4:3", "3:4", "16:9", "9:16", "2:3", "3:2", "21:9", "auto"],
        "requires_reference": False,
        "max_references": 10,
        "qualities": ["1K", "1.5K", "2K"],
        "quality_costs": seedream55_quality_prices(),
        "reference_unit_cost": seedream55_input_price(),
        "supports_nsfw_checker": True,
        "supports_output_format": True,
        "supports_background": True,
    },
    {
        "id": "seedream_55_layers",
        "label": "Seedream 5.5 â€” ÑÐ»Ð¾Ð¸",
        "description": "Ð Ð°Ð·Ð´ÐµÐ»ÐµÐ½Ð¸Ðµ Ð¸Ð·Ð¾Ð±Ñ€Ð°Ð¶ÐµÐ½Ð¸Ñ Ð½Ð° Ð½ÐµÐ·Ð°Ð²Ð¸ÑÐ¸Ð¼Ñ‹Ðµ ÑÐ»Ð¾Ð¸ (2â€“100); Ñ€ÐµÐ·ÐµÑ€Ð² ÑÐ¿Ð¸ÑÑ‹Ð²Ð°ÐµÑ‚ÑÑ Ð´Ð¾ Ð·Ð°Ð¿ÑƒÑÐºÐ°, Ð¾ÑÑ‚Ð°Ñ‚Ð¾Ðº Ð²Ð¾Ð·Ð²Ñ€Ð°Ñ‰Ð°ÐµÑ‚ÑÑ Ð¿Ð¾ÑÐ»Ðµ Ñ€ÐµÐ·ÑƒÐ»ÑŒÑ‚Ð°Ñ‚Ð°",
        "cost": seedream55_quality_prices()["2K"],
        "ratios": ["1:1"],
        "requires_reference": True,
        "max_references": 1,
        "qualities": ["1K", "1.5K", "2K"],
        "quality_costs": seedream55_quality_prices(),
        "reference_unit_cost": seedream55_input_price(),
        "supports_nsfw_checker": True,
        "supports_output_format": True,
        "supports_layers": True,
    },
    {
        "id": "seedream_5_pro",
        "label": "Seedream 5 Pro ðŸ”¥ ÐÐžÐ’Ð˜ÐÐšÐ",
        "description": "Ð¤Ð¾Ñ‚Ð¾Ñ€ÐµÐ°Ð»Ð¸ÑÑ‚Ð¸Ñ‡Ð½Ð°Ñ Ð³ÐµÐ½ÐµÑ€Ð°Ñ†Ð¸Ñ Ñ Ð½ÑƒÐ»Ñ Ð¸ image-to-image Ð² Ð¾Ð´Ð½Ð¾Ð¹ Ð¼Ð¾Ð´ÐµÐ»Ð¸",
        "cost": SEEDREAM_5_PRO_QUALITY_COSTS["basic"],
        "ratios": ["1:1", "9:16", "16:9", "3:4", "4:3", "2:3", "3:2", "21:9"],
        "requires_reference": False,
        "max_references": 5,
        "qualities": ["basic", "high"],
        "quality_costs": {quality: SEEDREAM_5_PRO_QUALITY_COSTS[quality] for quality in ("basic", "high")},
        "supports_nsfw_checker": False,
    },
    {
        "id": "banana_pro",
        "label": "Nano Banana Pro",
        "description": "Ð£Ð½Ð¸Ð²ÐµÑ€ÑÐ°Ð»ÑŒÐ½Ð°Ñ Ð¼Ð¾Ð´ÐµÐ»ÑŒ Ð´Ð»Ñ ÐºÐ°Ñ‡ÐµÑÑ‚Ð²ÐµÐ½Ð½Ñ‹Ñ… Ð¸Ð·Ð¾Ð±Ñ€Ð°Ð¶ÐµÐ½Ð¸Ð¹",
        "cost": preset_manager.get_generation_cost("nano-banana-pro"),
        "ratios": [
            "1:1",
            "16:9",
            "9:16",
            "4:3",
            "3:4",
            "4:5",
            "5:4",
            "3:2",
            "2:3",
            "21:9",
        ],
        "requires_reference": False,
        "max_references": 8,
        "qualities": ["1K", "2K", "4K"],
        "quality_costs": {
            "1K": QUALITY_COSTS["1K"],
            "2K": QUALITY_COSTS["2K"],
            "4K": QUALITY_COSTS["4K"],
        },
    },
    {
        "id": "banana_2",
        "label": "Nano Banana 2",
        "description": "ÐÐ¾Ð²Ð°Ñ Ð²ÐµÑ€ÑÐ¸Ñ Nano Banana Ñ ÑƒÐ»ÑƒÑ‡ÑˆÐµÐ½Ð½Ð¾Ð¹ Ð´ÐµÑ‚Ð°Ð»Ð¸Ð·Ð°Ñ†Ð¸ÐµÐ¹ Ð¸ Ñ†Ð²ÐµÑ‚Ð¾Ð¿ÐµÑ€ÐµÐ´Ð°Ñ‡ÐµÐ¹",
        "cost": preset_manager.get_generation_cost("banana_2"),
        "ratios": [
            "1:1",
            "16:9",
            "9:16",
            "4:3",
            "3:4",
            "4:5",
            "5:4",
            "3:2",
            "2:3",
            "21:9",
        ],
        "requires_reference": False,
        "max_references": 8,
        "qualities": ["1K", "2K", "4K"],
        "quality_costs": {
            "1K": QUALITY_COSTS["1K"],
            "2K": QUALITY_COSTS["2K"],
            "4K": QUALITY_COSTS["4K"],
        },
    },
    {
        "id": "seedream_edit",
        "label": "Seedream 4.5 Edit",
        "description": "Ð¡Ð¸Ð»ÑŒÐ½Ñ‹Ð¹ edit Ð¿Ð¾ Ð¸ÑÑ…Ð¾Ð´Ð½Ð¸ÐºÐ°Ð¼",
        "cost": preset_manager.get_generation_cost("seedream_edit"),
        "ratios": ["1:1", "9:16", "16:9", "3:4", "4:3", "2:3", "3:2", "21:9"],
        "requires_reference": True,
        "max_references": 9,
        "qualities": ["2K", "4K"],
        "supports_nsfw_checker": False,
    },
    {
        "id": "flux_pro",
        "label": "GPT Image 2",
        "description": "Ð”ÐµÑ‚Ð°Ð»ÑŒÐ½Ð°Ñ Ð³ÐµÐ½ÐµÑ€Ð°Ñ†Ð¸Ñ Ð¸ Ð¼ÑÐ³ÐºÐ¸Ð¹ image-to-image",
        "cost": preset_manager.get_generation_cost("flux_pro"),
        "ratios": ["auto", "1:1", "9:16", "16:9", "3:4", "4:3", "2:3"],
        "requires_reference": False,
        "max_references": 9,
        "supports_nsfw_checker": True,
    },
    {
        "id": "wan_27",
        "label": "Wan 2.7 Pro",
        "description": "Ð“ÐµÐ½ÐµÑ€Ð°Ñ†Ð¸Ñ Ð¸ Ñ€ÐµÐ´Ð°ÐºÑ‚Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð¸Ðµ Ñ‡ÐµÑ€ÐµÐ· Wan 2.7",
        "cost": preset_manager.get_generation_cost("wan_27"),
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "21:9"],
        "requires_reference": False,
        "max_references": 9,
        "supports_nsfw_checker": False,
        "supports_wan_options": True,
    },
    {
        "id": "grok_imagine_i2i",
        "label": "Grok Imagine",
        "description": "I2I-ÑÑ†ÐµÐ½Ð°Ñ€Ð¸Ð¹ Ð´Ð»Ñ ÑÑ€ÐºÐ¸Ñ… Ð¿ÐµÑ€ÐµÑ€Ð°Ð±Ð¾Ñ‚Ð¾Ðº",
        "cost": preset_manager.get_generation_cost("grok_imagine_i2i"),
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],
        "requires_reference": True,
        "max_references": 9,
        "supports_nsfw_mode": True,
    },
)


def _resolve_image_unit_cost(
    img_service: str,
    img_quality: str,
    *,
    tariff: str = "standard",
    reference_count: int = 0,
    max_images: int = 30,
) -> float:
    if img_service in {"seedream_55", "seedream_55_layers"}:
        return seedream55_cost(
            img_service, img_quality, reference_count=reference_count,
            max_images=max_images, tariff=tariff,
        )
    if tariff == "creator":
        from bot.creator_tariff import resolve_image_unit_cost

        return resolve_image_unit_cost(
            img_service,
            img_quality,
            tariff=tariff,
        )
    quality_value = str(img_quality or "").strip()
    if img_service in ("banana_pro", "banana_2"):
        return QUALITY_COSTS.get(
            quality_value,
            QUALITY_COSTS.get(
                quality_value.upper(),
                preset_manager.get_generation_cost(img_service),
            ),
        )
    if img_service == "seedream_5_pro":
        return SEEDREAM_5_PRO_QUALITY_COSTS.get(
            quality_value,
            SEEDREAM_5_PRO_QUALITY_COSTS.get(
                quality_value.upper(),
                preset_manager.get_generation_cost(img_service),
            ),
        )
    return preset_manager.get_generation_cost(img_service)


async def _resolve_actor_image_unit_cost(
    telegram_id: int,
    img_service: str,
    img_quality: str,
    *,
    reference_count: int = 0,
    max_images: int = 30,
) -> float:
    tariff = await creator_tariff_display.get_actor_tariff(telegram_id)
    if img_service in {"seedream_55", "seedream_55_layers"}:
        return seedream55_cost(
            img_service, img_quality, reference_count=reference_count,
            max_images=max_images, tariff=tariff,
        )
    if tariff == "creator":
        from bot.creator_tariff import resolve_image_unit_cost

        return resolve_image_unit_cost(
            img_service,
            img_quality,
            tariff=tariff,
        )
    return _resolve_image_unit_cost(img_service, img_quality)

VIDEO_MODELS = (
    {
        "id": "v3_pro",
        "label": "Kling 3.0",
        "description": "Ð¤Ð»Ð°Ð³Ð¼Ð°Ð½ÑÐºÐ¸Ð¹ Ð²Ð¸Ð´ÐµÐ¾-Ñ€ÐµÐ¶Ð¸Ð¼",
        "durations": [5, 10, 15],
        "ratios": ["16:9", "9:16", "1:1"],
        "supports": ["text", "imgtxt"],
        "max_image_references": 9,
    },
    {
        "id": "v3_std",
        "label": "Kling v3",
        "description": "Ð‘Ñ‹ÑÑ‚Ñ€ÐµÐµ Ð¸ Ð´ÐµÑˆÐµÐ²Ð»Ðµ Ð´Ð»Ñ everyday-Ð²Ð¸Ð´ÐµÐ¾",
        "durations": [5, 10, 15],
        "ratios": ["16:9", "9:16", "1:1"],
        "supports": ["text", "imgtxt"],
        "max_image_references": 9,
    },
    {
        "id": "v26_pro",
        "label": "Kling 2.5 Turbo Pro",
        "description": "Ð¥Ð¾Ñ€Ð¾Ñˆ Ð´Ð»Ñ image-to-video",
        "durations": [5, 10],
        "ratios": ["16:9", "9:16", "1:1"],
        "supports": ["text", "imgtxt"],
        "supports_negative_prompt": True,
        "supports_cfg_scale": True,
        "max_image_references": 9,
    },
    {
        "id": "grok_imagine",
        "label": "Grok Imagine",
        "description": "Ð’Ð¸Ð´ÐµÐ¾ Ð¸Ð· Ñ„Ð¾Ñ‚Ð¾ Ñ Ñ€ÐµÐ¶Ð¸Ð¼Ð°Ð¼Ð¸ Normal/Fun/Spicy",
        "durations": [6, 10, 20, 30],
        "ratios": ["16:9", "9:16", "1:1", "3:2", "2:3"],
        "supports": ["imgtxt"],
        "grok_modes": ["normal", "fun", "spicy"],
        "max_image_references": 6,
    },
    {
        "id": "grok_imagine_v15",
        "label": "Grok Imagine 1.5 NEWðŸ”¥ðŸ”¥ðŸ”¥",
        "description": "Ð’Ð¸Ð´ÐµÐ¾ 1-15 ÑÐµÐºÑƒÐ½Ð´ Ð¸Ð· Ð¾Ð´Ð½Ð¾Ð³Ð¾ ÑÑ‚Ð°Ñ€Ñ‚Ð¾Ð²Ð¾Ð³Ð¾ Ñ„Ð¾Ñ‚Ð¾",
        "durations": list(range(1, 16)),
        "ratios": ["auto", "16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"],
        "supports": ["imgtxt"],
        "grok_resolutions": ["480p", "720p"],
        "max_image_references": 0,
    },
    {
        "id": "seedance_2",
        "label": "Bytedance Seedance 2.0",
        "description": "ÐœÑƒÐ»ÑŒÑ‚Ð¸Ð¼Ð¾Ð´Ð°Ð»ÑŒÐ½Ð°Ñ Ð²Ð¸Ð´ÐµÐ¾-Ð¼Ð¾Ð´ÐµÐ»ÑŒ Ñ Ñ‚ÐµÐºÑÑ‚Ð¾Ð¼, Ñ„Ð¾Ñ‚Ð¾ Ð¸ Ð²Ð¸Ð´ÐµÐ¾-Ñ€ÐµÑ„Ð°Ð¼Ð¸",
        "durations": [5, 10, 15],
        "ratios": ["16:9", "9:16", "1:1"],
        "supports": ["text", "imgtxt", "video"],
        "max_image_references": 9,
        "max_video_references": 3,
        "max_audio_references": get_max_audio_references("seedance_2"),
    },
    {
        "id": "wan_3_prime",
        "label": "Wan 3.0 Video Prime",
        "description": "Wan 3.0: Ñ‚ÐµÐºÑÑ‚, ÐºÐ°Ð´Ñ€Ñ‹, Ñ€ÐµÑ„ÐµÑ€ÐµÐ½ÑÑ‹, edit, Ð´Ð¾ÐºÑƒÐ¼ÐµÐ½Ñ‚Ñ‹ Ð¸ ÑÑÑ‹Ð»ÐºÐ¸",
        "durations": [-1] + list(range(2, 31)),
        "ratios": ["adaptive", "16:9", "4:3", "1:1", "3:4", "9:16"],
        "supports": ["text", "imgtxt", "first_last", "video", "edit", "file", "link"],
        "wan_resolutions": ["480P", "720P", "1080P"],
        "supports_seed": True,
        "supports_wan_audio": True,
        "supports_nsfw_checker": True,
        "requires_quality_pricing": True,
        "max_image_references": 10,
        "max_video_references": 5,
        "max_audio_references": get_max_audio_references("wan_3_prime"),
    },
    {
        "id": "wan_3",
        "label": "Wan 3.0 Video",
        "description": "Wan 3.0: Ñ‚ÐµÐºÑÑ‚, ÐºÐ°Ð´Ñ€Ñ‹, Ñ€ÐµÑ„ÐµÑ€ÐµÐ½ÑÑ‹, edit, Ð´Ð¾ÐºÑƒÐ¼ÐµÐ½Ñ‚Ñ‹ Ð¸ ÑÑÑ‹Ð»ÐºÐ¸",
        "durations": [-1] + list(range(2, 31)),
        "ratios": ["adaptive", "16:9", "4:3", "1:1", "3:4", "9:16"],
        "supports": ["text", "imgtxt", "first_last", "video", "edit", "file", "link"],
        "wan_resolutions": ["480P", "720P", "1080P"],
        "supports_seed": True,
        "supports_wan_audio": True,
        "supports_nsfw_checker": True,
        "requires_quality_pricing": True,
        "max_image_references": 10,
        "max_video_references": 5,
        "max_audio_references": get_max_audio_references("wan_3"),
    },
    {
        "id": "gemini_omni",
        "label": "Gemini Omni",
        "description": "Ð•Ð´Ð¸Ð½Ð¾Ðµ Ð¼ÐµÐ½ÑŽ Ð´Ð»Ñ Gemini Omni Video, Audio ID Ð¸ Character ID",
        "durations": [4, 6, 8, 10],
        "ratios": ["16:9", "9:16"],
        "supports": ["text", "imgtxt", "video", "audio", "character"],
        "omni_modes": ["video", "audio", "character"],
        "omni_resolutions": ["720p", "1080p", "4k"],
        "supports_omni_seed": True,
        "supports_omni_audio_ids": True,
        "supports_omni_character_ids": True,
        "supports_omni_character_audio_ids": True,
        "omni_base_voices": [
            "achernar",
            "achird",
            "algenib",
            "algieba",
            "alnilam",
            "aoede",
            "autonoe",
            "callirrhoe",
            "charon",
            "despina",
            "enceladus",
            "erinome",
            "fenrir",
            "gacrux",
            "iapetus",
            "kore",
            "laomedeia",
            "leda",
            "orus",
            "puck",
            "pulcherrima",
            "rasalgethi",
            "sadachbia",
            "sadaltager",
            "schedar",
            "sulafat",
            "umbriel",
            "vindemiatrix",
            "zephyr",
            "zubenelgenubi",
        ],
        "max_image_references": 7,
        "max_video_references": 1,
        "max_audio_references": 1,
    },
    {
        "id": "veo3_fast",
        "label": "Veo 3.1 Fast",
        "description": "Ð‘Ñ‹ÑÑ‚Ñ€Ñ‹Ð¹ ÐºÐ¸Ð½ÐµÐ¼Ð°Ñ‚Ð¾Ð³Ñ€Ð°Ñ„Ð¸Ñ‡Ð½Ñ‹Ð¹ Ñ€ÐµÐ½Ð´ÐµÑ€",
        "durations": [2, 4, 6, 8, 10],
        "ratios": ["16:9", "9:16", "Auto"],
        "supports": ["text", "imgtxt"],
        "veo_generation_types": [
            "TEXT_2_VIDEO",
            "FIRST_AND_LAST_FRAMES_2_VIDEO",
            "REFERENCE_2_VIDEO",
        ],
        "veo_resolutions": ["720p", "1080p", "4k"],
        "supports_translation": True,
        "supports_seed": True,
        "supports_watermark": True,
        "max_image_references": 9,
    },
    {
        "id": "motion_control_v26",
        "label": "Kling 2.6 Motion Control",
        "description": "ÐŸÐµÑ€ÐµÐ½Ð¾Ñ Ð´Ð²Ð¸Ð¶ÐµÐ½Ð¸Ñ Ð¿Ð¾ Ñ„Ð¾Ñ‚Ð¾ Ð¿ÐµÑ€ÑÐ¾Ð½Ð°Ð¶Ð° Ð¸ Ð²Ð¸Ð´ÐµÐ¾ Ð´Ð²Ð¸Ð¶ÐµÐ½Ð¸Ñ",
        "durations": [5],
        "ratios": ["1:1"],
        "supports": ["motion"],
        "motion_versions": ["2.6"],
        "motion_modes": ["720p", "1080p"],
        "max_image_references": 9,
        "max_video_references": 1,
    },
    {
        "id": "motion_control_v30",
        "label": "Kling 3.0 Motion Control",
        "description": "ÐžÐ±Ð½Ð¾Ð²Ð»Ñ‘Ð½Ð½Ð°Ñ Ð²ÐµÑ€ÑÐ¸Ñ Motion Control Ð´Ð»Ñ Ñ„Ð¾Ñ‚Ð¾ Ð¸ Ð²Ð¸Ð´ÐµÐ¾ Ð´Ð²Ð¸Ð¶ÐµÐ½Ð¸Ñ",
        "durations": [5],
        "ratios": ["motion"],
        "supports": ["motion"],
        "motion_versions": ["3.0"],
        "motion_modes": ["720p", "1080p"],
        "max_image_references": 9,
        "max_video_references": 1,
    },
    {
        "id": "avatar_std",
        "label": "Kling Avatar Standard",
        "description": "Ð“Ð¾Ð²Ð¾Ñ€ÑÑ‰Ð¸Ð¹ Ð°Ð²Ð°Ñ‚Ð°Ñ€ Ð¿Ð¾ Ñ„Ð¾Ñ‚Ð¾ Ð¸ Ð°ÑƒÐ´Ð¸Ð¾",
        "durations": [5],
        "ratios": ["avatar"],
        "supports": ["avatar"],
        "requires_audio": True,
        "requires_image": True,
        "max_image_references": 9,
        "max_audio_references": 1,
    },
    {
        "id": "avatar_pro",
        "label": "Kling Avatar Pro",
        "description": "ÐšÐ°Ñ‡ÐµÑÑ‚Ð²ÐµÐ½Ð½Ñ‹Ð¹ Ð³Ð¾Ð²Ð¾Ñ€ÑÑ‰Ð¸Ð¹ Ð°Ð²Ð°Ñ‚Ð°Ñ€ Ð¿Ð¾ Ñ„Ð¾Ñ‚Ð¾ Ð¸ Ð°ÑƒÐ´Ð¸Ð¾",
        "durations": [5],
        "ratios": ["avatar"],
        "supports": ["avatar"],
        "requires_audio": True,
        "requires_image": True,
        "max_image_references": 9,
        "max_audio_references": 1,
    },
)

GEMINI_OMNI_INTERNAL_MODELS = {
    "gemini_omni_video",
    "gemini_omni_audio",
    "gemini_omni_character",
}


def _find_video_model_meta(model: str) -> dict[str, Any] | None:
    meta = next((item for item in VIDEO_MODELS if item["id"] == model), None)
    if meta:
        return meta
    if model in GEMINI_OMNI_INTERNAL_MODELS:
        return next((item for item in VIDEO_MODELS if item["id"] == "gemini_omni"), None)
    return None


def _resolve_gemini_omni_model(model: str, generation_type: str) -> str:
    if model != "gemini_omni":
        return model
    if generation_type == "audio":
        return "gemini_omni_audio"
    if generation_type == "character":
        return "gemini_omni_character"
    return "gemini_omni_video"


def _video_pricing_quality(
    model: str,
    veo_resolution: str | None = None,
    omni_resolution: str | None = None,
) -> str | None:
    key = preset_manager.normalize_video_model_key(model)
    if key.startswith("veo3"):
        return veo_resolution or "720p"
    if key == "gemini_omni_video":
        return omni_resolution or "720p"
    if key in {"wan_3_prime", "wan_3"}:
        return (veo_resolution or "1080P").lower()
    return None


def _clean_unique_values(values: list[Any] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        text = canonicalize_local_upload_url(text)
        if text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _clean_ordered_values(values: list[Any] | None) -> list[str]:
    cleaned: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text:
            cleaned.append(canonicalize_local_upload_url(text))
    return cleaned


def _collect_gemini_omni_images(
    image_url: str | None,
    image_references: list[str] | None,
) -> list[str]:
    return _clean_unique_values([image_url, *list(image_references or [])])


def _collect_gemini_omni_video_urls(video_references: list[str] | None) -> list[str]:
    return _clean_unique_values(video_references)


def _build_gemini_omni_video_list(
    video_references: list[str],
    duration: int,
) -> list[dict[str, Any]]:
    try:
        ends = min(20, max(1, int(duration)))
    except (TypeError, ValueError):
        ends = 10
    return [{"url": url, "start": 0, "ends": ends} for url in video_references]


def _validate_gemini_omni_video_inputs(
    *,
    image_urls: list[str],
    video_urls: list[str],
    audio_ids: list[str],
    character_ids: list[str],
) -> str | None:
    if len(video_urls) > 1:
        return "Gemini Omni Ð¿Ñ€Ð¸Ð½Ð¸Ð¼Ð°ÐµÑ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð¾Ð´Ð¸Ð½ Ð²Ð¸Ð´ÐµÐ¾-Ñ€ÐµÑ„ÐµÑ€ÐµÐ½Ñ. Ð£Ð´Ð°Ð»Ð¸Ñ‚Ðµ Ñ‚ÐµÐºÑƒÑ‰Ð¸Ð¹ Ð¸Ð»Ð¸ Ð·Ð°Ð¼ÐµÐ½Ð¸Ñ‚Ðµ ÐµÐ³Ð¾."
    if len(audio_ids) > 1:
        return "Gemini Omni Video Ð¿Ñ€Ð¸Ð½Ð¸Ð¼Ð°ÐµÑ‚ Ð¾Ð´Ð¸Ð½ Audio ID Ð·Ð° Ð·Ð°Ð¿ÑƒÑÐº."
    if len(character_ids) > 3:
        return "Gemini Omni Ð¿Ñ€Ð¸Ð½Ð¸Ð¼Ð°ÐµÑ‚ Ð¼Ð°ÐºÑÐ¸Ð¼ÑƒÐ¼ 3 Character ID."
    units = len(image_urls) + len(video_urls) * 2 + len(character_ids)
    if units > 7:
        return "Ð¡Ð»Ð¸ÑˆÐºÐ¾Ð¼ Ð¼Ð½Ð¾Ð³Ð¾ Ð²Ñ…Ð¾Ð´Ð¾Ð² Ð´Ð»Ñ Gemini Omni. Ð›Ð¸Ð¼Ð¸Ñ‚: Ñ„Ð¾Ñ‚Ð¾ + Ð²Ð¸Ð´ÐµÐ¾*2 + Character ID <= 7."
    return None


FILE_KIND_MAP.update({
    "repeat_choice_image": {"prefix": "image/", "fallback_ext": "jpg", "group": "image"},
    "image_reference": {"prefix": "image/", "fallback_ext": "png", "group": "image"},
    "video_reference": {"prefix": "video/", "fallback_ext": "mp4", "group": "video"},
    "audio_reference": {"prefix": "audio/", "fallback_ext": "mp3", "group": "audio"},
    "assistant_audio": {"prefix": "audio/", "fallback_ext": "webm", "group": "audio"},
    "trend_video_preview": {
        "prefix": "video/",
        "fallback_ext": "mp4",
        "group": "video",
        "max_bytes": MINIAPP_TREND_VIDEO_MAX_BYTES,
        "durable_reference": True,
        "source": "miniapp_trend",
    },
})


def _normalize_miniapp_upload_content_type(
    file_kind: str,
    filename: str,
    content_type: str,
    raw: bytes,
) -> str:
    """Accept iOS WebView uploads with missing/octet-stream MIME after safe sniffing."""
    declared = (content_type or "").split(";", 1)[0].strip().lower()
    config_entry = FILE_KIND_MAP[file_kind]
    expected_prefix = config_entry["prefix"]
    if declared.startswith(expected_prefix):
        return declared

    if declared not in {"", "application/octet-stream", "binary/octet-stream"}:
        return ""

    filename_mime = (mimetypes.guess_type(filename or "")[0] or "").lower()
    if filename_mime.startswith(expected_prefix):
        return filename_mime

    extension = Path(filename or "").suffix.lstrip(".").lower()
    extension_mimes = {
        "heic": "image/heic",
        "heif": "image/heif",
        "avif": "image/avif",
        "mov": "video/quicktime",
        "m4v": "video/x-m4v",
        "m4a": "audio/mp4",
    }
    extension_mime = extension_mimes.get(extension, "")
    if extension_mime.startswith(expected_prefix):
        return extension_mime

    if config_entry["group"] != "image":
        return ""

    try:
        import io

        from PIL import Image, UnidentifiedImageError

        try:
            from pillow_heif import register_heif_opener
        except ImportError:
            register_heif_opener = None
        if register_heif_opener is not None:
            register_heif_opener()

        with Image.open(io.BytesIO(raw)) as image:
            image_format = str(image.format or "").upper()
        return {
            "JPEG": "image/jpeg",
            "JPG": "image/jpeg",
            "PNG": "image/png",
            "WEBP": "image/webp",
            "GIF": "image/gif",
            "TIFF": "image/tiff",
            "AVIF": "image/avif",
            "HEIF": "image/heif",
            "HEIC": "image/heic",
        }.get(image_format, "")
    except (OSError, UnidentifiedImageError):
        return ""

MINIAPP_ASSISTANT_AUDIO_EXT_FORMATS = {
    "mp3": "mp3",
    "wav": "wav",
    "aac": "aac",
    "aiff": "aiff",
    "aif": "aiff",
    "ogg": "ogg",
    "oga": "ogg",
    "flac": "flac",
    "webm": "webm",
    "m4a": "m4a",
    "mp4": "m4a",
}


def _miniapp_assistant_audio_format(
    audio_url: str,
    content_type: str = "",
) -> tuple[str, str]:
    mime_type = (content_type or "").split(";", 1)[0].strip().lower()
    if not mime_type:
        mime_type = (mimetypes.guess_type(audio_url)[0] or "").strip().lower()

    from bot.handlers.common import AI_ASSISTANT_AUDIO_FORMATS

    audio_format = AI_ASSISTANT_AUDIO_FORMATS.get(mime_type, "")
    if audio_format:
        return mime_type, audio_format

    ext = Path(urlparse(audio_url).path or audio_url).suffix.lstrip(".").lower()
    audio_format = MINIAPP_ASSISTANT_AUDIO_EXT_FORMATS.get(ext, "")
    return mime_type, audio_format


def _load_miniapp_assistant_audio(
    audio_url: str,
    content_type: str = "",
) -> tuple[bytes, str, str]:
    local_path = resolve_local_upload_path(audio_url)
    if not local_path:
        raise ValueError("ÐÑƒÐ´Ð¸Ð¾ Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½Ð¾. Ð—Ð°Ð¿Ð¸ÑˆÐ¸Ñ‚Ðµ Ð¸Ð»Ð¸ Ð·Ð°Ð³Ñ€ÑƒÐ·Ð¸Ñ‚Ðµ ÐµÐ³Ð¾ ÐµÑ‰Ñ‘ Ñ€Ð°Ð·.")

    path = Path(local_path)
    if path.stat().st_size > config.PHOTO_PROMPT_MAX_AUDIO_BYTES:
        max_mb = max(1, config.PHOTO_PROMPT_MAX_AUDIO_BYTES // (1024 * 1024))
        raise ValueError(f"ÐÑƒÐ´Ð¸Ð¾ ÑÐ»Ð¸ÑˆÐºÐ¾Ð¼ Ð±Ð¾Ð»ÑŒÑˆÐ¾Ðµ. ÐœÐ°ÐºÑÐ¸Ð¼ÑƒÐ¼ {max_mb}MB.")

    audio_bytes = path.read_bytes()
    if len(audio_bytes) > config.PHOTO_PROMPT_MAX_AUDIO_BYTES:
        max_mb = max(1, config.PHOTO_PROMPT_MAX_AUDIO_BYTES // (1024 * 1024))
        raise ValueError(f"ÐÑƒÐ´Ð¸Ð¾ ÑÐ»Ð¸ÑˆÐºÐ¾Ð¼ Ð±Ð¾Ð»ÑŒÑˆÐ¾Ðµ. ÐœÐ°ÐºÑÐ¸Ð¼ÑƒÐ¼ {max_mb}MB.")

    mime_type, audio_format = _miniapp_assistant_audio_format(
        audio_url,
        content_type=content_type,
    )
    if not audio_format:
        raise ValueError("Ð­Ñ‚Ð¾Ñ‚ Ð°ÑƒÐ´Ð¸Ð¾Ñ„Ð¾Ñ€Ð¼Ð°Ñ‚ Ð½Ðµ Ð¿Ð¾Ð´Ð´ÐµÑ€Ð¶Ð¸Ð²Ð°ÐµÑ‚ÑÑ. ÐŸÐ¾Ð¿Ñ€Ð¾Ð±ÑƒÐ¹Ñ‚Ðµ ogg, mp3, wav Ð¸Ð»Ð¸ webm.")

    return audio_bytes, mime_type, audio_format


def _resolve_miniapp_static_root() -> Path:
    """Prefer a built Next.js export when available, fallback to bundled static app.

    Use repository-relative absolute paths (based on this file location) so
    resolution does not depend on the process working directory.
    """
    base = Path(__file__).resolve().parent.parent
    candidates = [
        base / "frontend" / "miniapp-v0" / "out",
        base / "frontend" / "miniapp-v0" / "dist",
        base / "static" / "miniapp",
    ]
    for candidate in candidates:
        index_file = candidate / "index.html"
        if index_file.exists():
            return candidate
    # Fallback to repo static path (absolute) even if index missing â€” callers
    # will handle missing file and return correct 404. This avoids relying on
    # the current working directory.
    return base / "static" / "miniapp"


class _MessageTarget:
    """Tiny adapter so existing helpers can send messages outside updates."""

    def __init__(self, bot, telegram_id: int):
        self._bot = bot
        self.from_user = SimpleNamespace(id=telegram_id)
        self._telegram_id = telegram_id

    async def answer(self, text: str, **kwargs):
        return await self._bot.send_message(self._telegram_id, text, **kwargs)


def _validate_init_data(init_data: str, bot_token: str) -> dict[str, Any]:
    if not init_data:
        raise ValueError("Missing init_data")

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    their_hash = parsed.pop("hash", "")
    if not their_hash:
        raise ValueError("Missing Telegram hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, their_hash):
        raise ValueError("Invalid Telegram signature")

    auth_date = int(parsed.get("auth_date", "0") or 0)
    if not auth_date or abs(time.time() - auth_date) > 86400:
        raise ValueError("Expired Telegram session")

    user = json.loads(parsed.get("user", "{}") or "{}")
    if not user or "id" not in user:
        raise ValueError("Missing Telegram user")

    parsed["user"] = user
    return parsed


from bot.services.referral_service import (
    process_referral_click,
    referral_code_from_start_param,
)

_referral_code_from_start_param = referral_code_from_start_param

# Ð¢Ñ€Ð¾Ñ‚Ñ‚Ð»Ð¸Ð½Ð³ Ð¿Ð¾Ð²Ñ‚Ð¾Ñ€Ð½Ñ‹Ñ… Ð¿Ð¾Ð¿Ñ‹Ñ‚Ð¾Ðº Ð°ÐºÑ‚Ð¸Ð²Ð°Ñ†Ð¸Ð¸ Ñ€ÐµÑ„ÐµÑ€Ð°Ð»ÑŒÐ½Ð¾Ð³Ð¾ ÐºÐ¾Ð´Ð° Ð¸Ð· Mini App.
# Ð Ð°Ð½ÑŒÑˆÐµ ÐºÐ°Ð¶Ð´Ð¾Ðµ Ð¾Ñ‚ÐºÑ€Ñ‹Ñ‚Ð¸Ðµ Mini App Ñ Ñ€ÐµÑ„ÐµÑ€Ð°Ð»ÑŒÐ½Ñ‹Ð¼ start_param Ñƒ Ð½ÐµÐ·Ð°Ð½ÑÑ‚Ð¾Ð³Ð¾
# Ð¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ñ‚ÐµÐ»Ñ Ð·Ð°Ð¿ÑƒÑÐºÐ°Ð»Ð¾ process_referral_click (Ð½ÐµÑÐºÐ¾Ð»ÑŒÐºÐ¾ SELECT + Ð·Ð°Ð¿Ð¸ÑÑŒ
# referral_event + COMMIT), Ð´Ð°Ð¶Ðµ ÐºÐ¾Ð³Ð´Ð° ÐºÐ¾Ð´ ÑƒÐ¶Ðµ ÑƒÐ¿Ð¸Ñ€Ð°Ð»ÑÑ Ð² Ð»Ð¸Ð¼Ð¸Ñ‚Ñ‹ Ñ€ÐµÑ„ÐµÑ€ÐµÑ€Ð°
# (daily/hourly) Ð¸Ð»Ð¸ Ð±Ñ‹Ð» Ð½ÐµÐ´Ð¾ÑÑ‚ÑƒÐ¿ÐµÐ½. Ð­Ñ‚Ð¾ ÑÐ¾Ð·Ð´Ð°Ð²Ð°Ð»Ð¾ Ð»Ð¸ÑˆÐ½ÑŽÑŽ Ð½Ð°Ð³Ñ€ÑƒÐ·ÐºÑƒ Ð½Ð° DB
# Ð¸ Ð·Ð°Ð´ÐµÑ€Ð¶Ð¸Ð²Ð°Ð»Ð¾ bootstrap. ÐŸÑ€Ð¾Ð¿ÑƒÑÐºÐ°ÐµÐ¼ Ð¿Ð¾Ð²Ñ‚Ð¾Ñ€Ð½Ñ‹Ðµ Ð¿Ð¾Ð¿Ñ‹Ñ‚ÐºÐ¸ Ð² Ñ‚ÐµÑ‡ÐµÐ½Ð¸Ðµ Ð¾ÐºÐ½Ð°.
_MINIAPP_REFERRAL_THROTTLE_SECONDS = 3600
# Ð¡ÐºÐ¾Ð»ÑŒÐ·ÑÑ‰Ð¸Ð¹ ÐºÐµÑˆ Ð¿Ð¾ÑÐ»ÐµÐ´Ð½ÐµÐ¹ Ð¿Ð¾Ð¿Ñ‹Ñ‚ÐºÐ¸: (telegram_id, referral_code) -> monotonic()
_mini_app_referral_last_attempt: dict[tuple[int, str], float] = {}
_MINIAPP_REFERRAL_LAST_ATTEMPT_MAX = 10000


async def _activate_start_param_referral(
    app: web.Application,
    *,
    telegram_id: int,
    telegram_user: dict[str, Any],
    start_param: Any,
) -> None:
    referral_code = referral_code_from_start_param(start_param)
    if not referral_code:
        if start_param:
            logger.info(
                "Mini App referral skipped: unsupported start_param user_id=%s start_param=%s",
                telegram_id,
                start_param,
            )
        return

    # ÐŸÑ€Ð¾Ð¿ÑƒÑÐºÐ°ÐµÐ¼ Ð¿Ð¾Ð²Ñ‚Ð¾Ñ€Ð½Ñ‹Ðµ Ð¿Ð¾Ð¿Ñ‹Ñ‚ÐºÐ¸ Ð² Ñ‚ÐµÑ‡ÐµÐ½Ð¸Ðµ Ð¾ÐºÐ½Ð° Ñ‚Ñ€Ð¾Ñ‚Ñ‚Ð»Ð¸Ð½Ð³Ð°: Ð¿ÐµÑ€Ð²Ñ‹Ð¹ ÐºÐ»Ð¸Ðº
    # Ð²ÑÑ‘ Ñ€Ð°Ð²Ð½Ð¾ Ð¾Ð±Ñ€Ð°Ð±Ð°Ñ‚Ñ‹Ð²Ð°ÐµÑ‚ÑÑ, Ð½Ð¾ Ð¿Ð¾Ð²Ñ‚Ð¾Ñ€Ð½Ñ‹Ðµ Ð¾Ñ‚ÐºÑ€Ñ‹Ñ‚Ð¸Ñ Mini App Ñ Ñ‚ÐµÐ¼ Ð¶Ðµ ÐºÐ¾Ð´Ð¾Ð¼
    # Ð½Ðµ Ð³Ð¾Ð½ÑÑŽÑ‚ process_referral_click Ð¸ Ð½Ðµ Ð¿Ð¸ÑˆÑƒÑ‚ referral_event Ð·Ð°Ð·Ñ€Ñ.
    attempt_key = (telegram_id, referral_code)
    now = time.monotonic()
    last_attempt = _mini_app_referral_last_attempt.get(attempt_key)
    if (
        last_attempt is not None
        and (now - last_attempt) < _MINIAPP_REFERRAL_THROTTLE_SECONDS
    ):
        logger.debug(
            "Mini App referral attempt skipped (throttled): user_id=%s code=%s",
            telegram_id,
            referral_code,
        )
        return
    _mini_app_referral_last_attempt[attempt_key] = now
    if len(_mini_app_referral_last_attempt) > _MINIAPP_REFERRAL_LAST_ATTEMPT_MAX:
        _mini_app_referral_last_attempt.clear()

    # ÐÐµ Ð·Ð°Ð¿ÑƒÑÐºÐ°ÐµÐ¼ process_referral_click Ð´Ð»Ñ Ð¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ñ‚ÐµÐ»Ñ, ÐºÐ¾Ñ‚Ð¾Ñ€Ñ‹Ð¹ ÑƒÐ¶Ðµ
    # Ð¿Ñ€Ð¸Ð²ÑÐ·Ð°Ð½ Ðº Ñ€ÐµÑ„ÐµÑ€ÐµÑ€Ñƒ (Ð¿Ñ€Ð¸Ð²ÑÐ·ÐºÐ° Ð¼Ð¾Ð³Ð»Ð° Ð¿Ñ€Ð¾Ð¸Ð·Ð¾Ð¹Ñ‚Ð¸ Ð¿Ð°Ñ€Ð°Ð»Ð»ÐµÐ»ÑŒÐ½Ð¾ â€” Ð² /start
    # Ð¸Ð»Ð¸ Ð² ÑÐ¾ÑÐµÐ´Ð½ÐµÐ¼ bootstrap-Ð·Ð°Ð¿Ñ€Ð¾ÑÐµ).
    try:
        async with db_backend.connect(DATABASE_PATH) as _db:
            _db.row_factory = db_backend.Row
            _cursor = await _db.execute(
                "SELECT referred_by FROM users WHERE telegram_id = ?",
                (telegram_id,),
            )
            _ref_row = await _cursor.fetchone()
            if _ref_row and _ref_row["referred_by"]:
                logger.debug(
                    "Mini App referral skipped (already attached): user_id=%s referred_by=%s",
                    telegram_id,
                    _ref_row["referred_by"],
                )
                return
    except Exception:
        logger.exception(
            "Failed to check Mini App referral state for user_id=%s start_param=%s",
            telegram_id,
            start_param,
        )

    try:
        logger.info(
            "Mini App referral requested: user_id=%s username=%s start_param=%s code=%s",
            telegram_id,
            telegram_user.get("username"),
            start_param,
            referral_code,
        )
        ref_result = await process_referral_click(
            telegram_id,
            referral_code,
            source="miniapp",
            start_param=str(start_param or ""),
        )
        referrer = (
            await get_user_by_referral_code(ref_result.clicked_code or referral_code)
            if ref_result.attached
            else None
        )
    except Exception:
        logger.exception(
            "Failed to activate Mini App referral for user_id=%s start_param=%s",
            telegram_id,
            start_param,
        )
        return

    if not ref_result.attached:
        logger.info(
            "Mini App referral not applied: user_id=%s username=%s start_param=%s code=%s reason=%s",
            telegram_id,
            telegram_user.get("username"),
            start_param,
            referral_code,
            ref_result.reason,
        )
        return

    if ref_result.notify_partner and referrer:
        referred = SimpleNamespace(
            id=telegram_id,
            username=telegram_user.get("username"),
            first_name=telegram_user.get("first_name"),
            last_name=telegram_user.get("last_name"),
            full_name=" ".join(
                str(telegram_user.get(key) or "").strip()
                for key in ("first_name", "last_name")
                if str(telegram_user.get(key) or "").strip()
            ),
        )
        from bot.handlers.common import _notify_partner_about_new_referral

        sent = await _notify_partner_about_new_referral(
            app["bot"],
            referrer_telegram_id=referrer.telegram_id,
            referred=referred,
        )
        logger.info(
            "Mini App referral %s: user_id=%s code=%s referrer=%s",
            "notified" if sent else "skipped",
            telegram_id,
            referral_code,
            referrer.telegram_id,
        )


async def _get_vk_session_user_context(init_data: str) -> tuple[int, dict]:
    """Map an authenticated VK session to the already-linked legacy user."""
    from bot.shared_accounts.errors import AuthenticationError
    from bot.shared_accounts.policy import load_policy
    from bot.shared_accounts.store import get_session, linked_telegram_id

    prefix = "vk_session:"
    token = init_data[len(prefix):] if init_data.startswith(prefix) else ""
    policy = await load_policy()
    try:
        if not policy.enabled:
            raise AuthenticationError("VK Mini App is unavailable")
        account = await get_session(token, policy.revision)
        if account.identity.platform != "vk" or not policy.allows_public(account.identity):
            raise AuthenticationError("VK Mini App access denied")
        telegram_id = await linked_telegram_id(account.id)
    except (AuthenticationError, PermissionError) as exc:
        raise ValueError("ÐžÑ‚ÐºÑ€Ð¾Ð¹Ñ‚Ðµ Ð¿Ñ€Ð¸Ð»Ð¾Ð¶ÐµÐ½Ð¸Ðµ Ð·Ð°Ð½Ð¾Ð²Ð¾ Ð¸Ð· Ð’ÐšÐ¾Ð½Ñ‚Ð°ÐºÑ‚Ðµ.") from exc
    if telegram_id is None:
        raise ValueError("Ð¡Ð½Ð°Ñ‡Ð°Ð»Ð° ÑÐ²ÑÐ¶Ð¸Ñ‚Ðµ Ð°ÐºÐºÐ°ÑƒÐ½Ñ‚Ñ‹ Ð¢Ð“ Ð¸ Ð’Ðš.")
    # A legacy link is created only for an existing Telegram user. Reusing it
    # keeps balance, tasks, history and generation ownership in one source.
    user = await get_or_create_user(telegram_id)
    payload = {
        "platform": "vk",
        "vk_user_id": account.identity.external_id,
        "user": {
            "id": telegram_id,
            "username": user.username or "",
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "photo_url": user.photo_url or "",
        }+žØ§z\m®éÜj×Û¾|çVòµë6†&vVBÒ&ööÂ†6÷7BâæBFV&—FVB—2æ÷BfÇ6R ¢v—B&V6÷&E÷f–FVõ÷&WVEöÆVæ6‚‡&V6V—Eö–BÂW6W"æ–BÂ†6SÒ&ÆVæ6†–ær"Â6÷7CÖ6÷7B–b6†&vVBVÇ6R¢ÆVæ6…öö'6W'fF–öå²'&V6V—E÷F6µö–B%ÒÒ&V6V—Eö–@¢ÆVæ6…÷7F'FVBÒG'VP¢ÆVæ6…÷&W7VÇBÒv—BöÆVæ6…÷f–FVõövVæW&F–öå÷F6²€¢öÆVæ6…öö'6W'fF–öãÖÆVæ6…öö'6W'fF–öâÀ¢¢¢‡²'f–FVõ÷&WVEö6öçG&7E÷fW'6–öâ#¢Ò–bvWFGG"‡&WVW7BÂ%÷f–FVõ÷&WVEöWF†÷&—¦F–öâ"ÂæöæR’VÇ6R·Ò’À¢FVÆVw&Õö–C×FVÆVw&Õö–BÀ¢W6W#×W6W"À¢¢¦vVæW&F–öåö÷&–v–åög&öÕö6öçFW‡B†7G‚’À¢ÖöFVÃÖVffV7F—fUöÖöFVÂÀ¢&–ÆÆ–æu÷V÷FSÖ&–ÆÆ–æu÷V÷FRÀ¢&ö×C×&ö×BÀ¢GW&F–öãÖGW&F–öâÀ¢7V7E÷&F–óÖ7V7E÷&F–òÀ¢vVæW&F–öå÷G—SÖvVæW&F–öå÷G—RÀ¢–ÖvU÷W&ÃÖ–ÖvU÷W&ÂÀ¢–ÖvU÷&VfW&Væ6W3Ö–ÖvU÷&VfW&Væ6W2À¢f–FVõ÷&VfW&Væ6W3×f–FVõ÷&VfW&Væ6W2À¢VF–õ÷W&ÃÖVF–õ÷W&ÂÀ¢w&öµöÖöFSÖw&öµöÖöFRÀ¢w&öµ÷&W6öÇWF–öãÖw&öµ÷&W6öÇWF–öâÀ¢fVõövVæW&F–öå÷G—S×fVõövVæW&F–öå÷G—RÀ¢fVõ÷G&ç6ÆF–öã×fVõ÷G&ç6ÆF–öâÀ¢fVõ÷&W6öÇWF–öã×fVõ÷&W6öÇWF–öâÀ¢fVõ÷6VVC×fVõ÷6VVBÀ¢fVõ÷vFW&Ö&³×fVõ÷vFW&Ö&²À¢vå÷&W6öÇWF–öã×vå÷&W6öÇWF–öâÀ¢vå÷6VVC×vå÷6VVBÀ¢våöVF–ó×våöVF–òÀ¢våöç6guö6†V6¶W#×våöç6guö6†V6¶W"À¢våöf—'7Eög&ÖU÷W&Ã×våöf—'7Eög&ÖU÷W&ÂÀ¢våöÆ7Eög&ÖU÷W&Ã×våöÆ7Eög&ÖU÷W&ÂÀ¢vå÷&VfW&Væ6Uöf–ÆU÷W&Ç3×vå÷&VfW&Væ6Uöf–ÆU÷W&Ç2À¢vå÷&VfW&Væ6UöÆ–æµ÷W&Ç3×vå÷&VfW&Væ6UöÆ–æµ÷W&Ç2À¢¶Æ–æuöæVvF—fU÷&ö×CÖ¶Æ–æuöæVvF—fU÷&ö×BÀ¢¶Æ–æuö6fu÷66ÆSÖ¶Æ–æuö6fu÷66ÆRÀ¢öÖæ•÷&W6öÇWF–öãÖöÖæ•÷&W6öÇWF–öâÀ¢öÖæ•÷6VVCÖöÖæ•÷6VVBÀ¢öÖæ•öVF–õö–G3ÖöÖæ•öVF–õö–G2À¢öÖæ•ö6†&7FW%ö–G3ÖöÖæ•ö6†&7FW%ö–G2À¢öÖæ•ö&6U÷fö–6SÖöÖæ•ö&6U÷fö–6RÀ¢öÖæ•÷fö–6UöæÖSÖöÖæ•÷fö–6UöæÖRÀ¢öÖæ•÷fö–6UöFW67&—F–öãÖöÖæ•÷fö–6UöFW67&—F–öâÀ¢öÖæ•öW†×ÆUöF–ÆöwVSÖöÖæ•öW†×ÆUöF–ÆöwVRÀ¢öÖæ•ö6†&7FW%öæÖSÖöÖæ•ö6†&7FW%öæÖRÀ¢öÖæ•ö6†&7FW%öVF–õö–G3ÖöÖæ•ö6†&7FW%öVF–õö–G2À¢6÷W&6UöfVVEövVåö–C×6÷W&6UöfVVEövVåö–BÀ¢&VçEövVæW&F–öåö–CÒ†–ÖÖVF–FU÷&VçEö–B–b6÷W&6UöfVVEövVåö–BVÇ6RæöæR’À¢7F–öå÷G—SÒ‚'&WVB"–b6÷W&6UöfVVEövVåö–BVÇ6RæöæR’À¢ ¢–bÆVæ6…÷&W7VÇBævWB‚'7FGW2"’–â²'VWVVB"Â&FöæR'Ó ¢ÆVæ6…öö'6W'fF–öå²&66WFVB%ÒÒG'VP¢–bæ÷BÆVæ6…öö'6W'fF–öâævWB‚'&÷f–FW%÷F6µö–B"“ ¢ÆVæ6…öö'6W'fF–öå²'&÷f–FW%÷F6µö–B%ÒÒ7G"†ÆVæ6…÷&W7VÇBævWB‚'F6µö–B"’÷"""¢–bÆVæ6…÷&W7VÇE²'7FGW2%ÒÓÒ&f–ÆVB# ¢&÷f–FW%÷&V¦V7FVBÒG'VP¢–b6†&vVC ¢&VgVæEöGFV×FVBÒG'VP¢&VgVæFVBÒv—BFEö7&VF—G2‡FVÆVw&Õö–BÂ6÷7B¢–b&—fFU÷&WVBæB&VgVæFVB—2fÇ6S ¢&—6R'VçF–ÖTW'&÷"‚'f–FVõ÷&VgVæE÷Væ6öæf—&ÖVB"¢6†&vVBÒfÇ6P¢v—B&V6÷&E÷f–FVõ÷&WVEöÆVæ6‚‡&V6V—Eö–BÂW6W"æ–BÂ†6SÒ'&V¦V7FVB"Â6÷7CÓÂFW&Ö–æÃÕG'VR¢&WGW&âvV"æ§6öå÷&W7öç6R€¢°¢&ö²#¢fÇ6RÀ¢&W'&÷"#¢€¢-	ÝR=M½íÂ}ý=--Â-M]ââ	ýíýí=-R]râ ¢–b6÷W&6UöfVVEövVåö–@¢VÇ6RÆVæ6…÷&W7VÇBævWB‚&W'&÷""’÷"-	ÝR=M½íÂ}ý=--Â-M]â ¢’À¢ÒÀ¢7FGW3ÓSÀ¢ ¢–b6÷W&6UöfVVEövVåö–C ¢v—B7&VF—EöfVVE÷&ö×E÷&WVB€¢–ÖÖVF–FU÷&VçEö–BÀ¢W6W"æ–BÀ¢&WVE÷F6µö–C×7G"†ÆVæ6…÷&W7VÇBævWB‚'F6µö–B"’÷"""’À¢7&VF—G5÷7VçCÖ6÷7BÀ¢ ¢g&W6…÷W6W"Òv—BvWEö÷%ö7&VFU÷W6W"‡FVÆVw&Õö–B¢&WGW&âvV"æ§6öå÷&W7öç6R€¢°¢&ö²#¢G'VRÀ¢'7FGW2#¢ÆVæ6…÷&W7VÇE²'7FGW2%ÒÀ¢'F6µö–B#¢ÆVæ6…÷&W7VÇE²'F6µö–B%ÒÀ¢'6fVE÷W&Â#¢ÆVæ6…÷&W7VÇBævWB‚'6fVE÷W&Â"’À¢'F6µ÷G—R#¢ÆVæ6…÷&W7VÇBævWB‚'F6µ÷G—R"’À¢&7&VF—G2#¢g&W6…÷W6W"æ7&VF—G2À¢&6÷7B#¢6÷7BÀ¢&ÖöFVÂ#¢ÖöFVÂÀ¢&ÖöFVÅöÆ&VÂ#¢vWE÷f–FVõöÖöFVÅöÆ&VÂ†VffV7F—fUöÖöFVÂ’À¢&7V7E÷&F–ò#¢7V7E÷&F–òÀ¢&GW&F–öâ#¢GW&F–öâÀ¢'66Væ&–ò#¢vVæW&F–öå÷G—RÀ¢'&ö×Eö†–FFVâ#¢&ööÂ‡6÷W&6UöfVVEövVåö–B’À¢'&ö×Eö7F–öç5öÆÆ÷vVB#¢æ÷B&ööÂ‡6÷W&6UöfVVEövVåö–B’À¢'6÷W&6UöfVVEövVåö–B#¢6÷W&6UöfVVEövVåö–BÀ¢Ð¢¢W†6WBW†6WF–öâ2S ¢–b&—fFU÷&WVC ¢–bÆVæ6…öö'6W'fF–öâævWB‚&66WFVB"“ ¢–b†æ÷BÆVæ6…öö'6W'fF–öâævWB‚'F6µ÷W'6—7FVB"’æB&V6V—Eö–@¢æBv—B&V6÷fW%÷f–FVõ÷&WVEöÆVæ6‚‡&V6V—Eö–BÂW6W"æ–BÂÆVæ6…öö'6W'fF–öâævWB‚'&÷f–FW%÷F6µö–B"’’“ ¢ÆVæ6…öö'6W'fF–öå²'F6µ÷W'6—7FVB%ÒÒG'VP¢ÆövvW"æW'&÷"€¢%&—fFRf–FVò66WFVC²7FGW2&V6öæ6–Æ–F–öâæVVFVC¢FVÆVw&Õö–CÒW2&÷f–FW%÷F6µö–CÒW2W'&÷%÷G—SÒW2"À¢FVÆVw&Õö–BÂÆVæ6…öö'6W'fF–öâævWB‚'&÷f–FW%÷F6µö–B"’ÂG—R†R’åõöæÖUõòÀ¢¢&WGW&âvV"æ§6öå÷&W7öç6R€¢²&ö²#¢fÇ6RÂ&6öFR#¢'f–FVõ÷7FGW5÷VæF–ær"À¢'F6µö–B#¢†ÆVæ6…öö'6W'fF–öâævWB‚'&÷f–FW%÷F6µö–B"¢–bÆVæ6…öö'6W'fF–öâævWB‚'F6µ÷W'6—7FVB"’÷"æ÷B&V6V—Eö–BVÇ6R&V6V—Eö–B’÷"æöæRÀ¢&W'&÷"#¢-	-M]âýÝý-âýí-M]íÂÂÝâ--=ýí­ÝRýíM--]mMÒâ	ÝRýí--íý-R}ý=¢}2â'ÒÀ¢7FGW3ÓSÀ¢¢–b6†&vVBæBæ÷B&VgVæEöGFV×FVC ¢2G&ç7÷'Bö†VÇW"W†6WF–öâFöW2æ÷B&÷fRF†Bæò&VÖ÷FP¢2¦ö"W†—7G2â&W7F÷&RF†RW6W"w26†&vRöæ6RæB&WF–âöæÇ¢26fR&V6öæ6–Æ–F–öâÖWFFF²æWfW"&WG'’âVæ6W'F–â&VgVæBà¢&VgVæEöGFV×FVBÒG'VP¢G'“ ¢&VgVæFVBÒv—BFEö7&VF—G2‡FVÆVw&Õö–BÂ6÷7B¢–b&VgVæFVB—2æ÷BfÇ6S ¢6†&vVBÒfÇ6P¢W†6WBW†6WF–öâ2&VgVæEöW'&÷#¢2æ÷¢$ÄSÒVæ6W'F–â6öÖÖ—B×W7Bæ÷B&R&WG&–V@¢ÆövvW"æW'&÷"‚%&—fFRf–FVò&VgVæBVæ6öæf—&ÖVC¢FVÆVw&Õö–CÒW2W'&÷%÷G—SÒW2"À¢FVÆVw&Õö–BÂG—R‡&VgVæEöW'&÷"’åõöæÖUõò¢ÆövvW"çv&æ–ær‚%&—fFRf–FVòÆVæ6‚÷WF6öÖRVæ¶æ÷vã¢FVÆVw&Õö–CÒW2&VgVæFVCÒW2W'&÷%÷G—SÒW2"À¢FVÆVw&Õö–BÂæ÷B6†&vVBÂG—R†R’åõöæÖUõò¢–b6†&vVC ¢ÆövvW"æW'&÷"‚%&—fFRf–FVò&VgVæB&V6öæ6–Æ–F–öâæVVFVC¢FVÆVw&Õö–CÒW2Ö÷VçCÒW2"À¢FVÆVw&Õö–BÂ6÷7B¢&WGW&âvV"æ§6öå÷&W7öç6R€¢²&ö²#¢fÇ6RÂ&6öFR#¢'f–FVõ÷&VgVæE÷VæF–ær"À¢&W'&÷"#¢-	ÝR=M½íÂýíM--]M-Â-í}-"ÝÝí"â
-]=]-òýí-]­ý½-]m²ÝRýí--íý-R}ý=¢}2â'ÒÀ¢7FGW3ÓSÀ¢¢–b&V6V—Eö–C ¢FW&Ö–æÂÒ&÷f–FW%÷&V¦V7FVB÷"†æ÷BÆVæ6…÷7F'FVBæB†æ÷BFV&—EöGFV×FVB÷"FV&—Eö6ö×ÆWFVB’¢G'“ ¢v—B&V6÷&E÷f–FVõ÷&WVEöÆVæ6‚‡&V6V—Eö–BÂW6W"æ–BÀ¢†6SÒ‚'&VÆVæ6…öf–ÆVB"–bFW&Ö–æÂVÇ6R&FV&—E÷Væ¶æ÷vâ ¢–bFV&—EöGFV×FVBæBæ÷BFV&—Eö6ö×ÆWFVBVÇ6R&÷WF6öÖU÷Væ¶æ÷vâ"’À¢6÷7CÔæöæR–bFV&—EöGFV×FVBæBæ÷BFV&—Eö6ö×ÆWFVBVÇ6RÂFW&Ö–æÃ×FW&Ö–æÂ¢W†6WBW†6WF–öâ2&V6V—EöW'&÷#¢2æ÷¢$ÄSÒVæ6W'F–â&V6V—B7F—2&Æö6¶V@¢ÆövvW"æW'&÷"‚%&—fFRf–FVò&V6V—B&V6öæ6–Æ–F–öâæVVFVC¢F6µö–CÒW2W'&÷%÷G—SÒW2"À¢&V6V—Eö–BÂG—R‡&V6V—EöW'&÷"’åõöæÖUõò¢&WGW&âf–FVõ÷&WVE÷VæF–æu÷&W7öç6R‡&V6V—Eö–B¢–bæ÷BFW&Ö–æÃ ¢&WGW&âf–FVõ÷&WVE÷VæF–æu÷&W7öç6R‡&V6V—Eö–B¢&WGW&â÷&—fFUö–ÖvUöW'&÷%÷&W7öç6R†RÂÆöuöÖW76vSÒ%&—fFRf–FVò&WVBf–ÆVB"¢–b6†&vVBæBæ÷B&VgVæEöGFV×FVBæBæ÷BÆVæ6…öö'6W'fF–öâævWB‚&66WFVB"“ ¢&VgVæEöGFV×FVBÒG'VP¢v—BFEö7&VF—G2‡FVÆVw&Õö–BÂ6÷7B¢–b6÷W&6UöfVVEövVåö–C ¢&WGW&â÷&—fFUö–ÖvUöW'&÷%÷&W7öç6R†RÂÆöuöÖW76vSÒ%f–FVò&WVBf–ÆVB"¢&WGW&âöÖ–æ–öW'&÷%÷&W7öç6R†RÂÆöuöÖW76vSÒ$Ö–æ’f–FVòvVæW&F–öâf–ÆVB"  ¦7–æ2FVbÖ–æ–÷V÷FUöÖ÷F–öâ‡&WVW7C¢vV"å&WVW7B’ÓâvV"å&W7öç6S ¢–×÷'B7—0 ¢g&öÒ&÷Bæ†æFÆW'2æÖ÷F–öåöÆVæ6‚–×÷'BV÷FUöÖ÷F–öà ¢&WGW&âv—BV÷FUöÖ÷F–öâ‡&WVW7BÂ7—2æÖöGVÆW5µõöæÖUõõÒ  ¦7–æ2FVbÖ–æ–÷7FGW5öÖ÷F–öâ‡&WVW7C¢vV"å&WVW7B’ÓâvV"å&W7öç6S ¢–×÷'B7—0 ¢g&öÒ&÷Bæ†æFÆW'2æÖ÷F–öåöÆVæ6‚–×÷'B7FGW5öÖ÷F–öà ¢&WGW&âv—B7FGW5öÖ÷F–öâ‡&WVW7BÂ7—2æÖöGVÆW5µõöæÖUõõÒ  ¦7–æ2FVbÖ–æ–övVæW&FUöÖ÷F–öâ‡&WVW7C¢vV"å&WVW7B’ÓâvV"å&W7öç6S ¢–×÷'B7—0 ¢g&öÒ&÷Bæ†æFÆW'2æÖ÷F–öåöÆVæ6‚–×÷'BvVæW&FUöÖ÷F–öà ¢&WGW&âv—BvVæW&FUöÖ÷F–öâ‡&WVW7BÂ7—2æÖöGVÆW5µõöæÖUõõÒ  ¦7–æ2FVbÖ–æ–÷'FæW%ö÷fW'f–Wr‡&WVW7C¢vV"å&WVW7B’ÓâvV"å&W7öç6S ¢""%&WGW&â&VÂ'FæW"&öw&ÒFFf÷"Ö–æ’â"" ¢G'“ ¢&öG’Òv—B&WVW7Bæ§6öâ‚¢–æ—EöFFÒ&öG’ævWB‚&–æ—EöFF"Â"" ¢FVÆVw&Õö–BÂ7G‚Òv—BövWE÷W6W%ö6öçFW‡B€¢&WVW7BæÀ¢–æ—EöFFÀ¢&öG’ævWB‚'7F'E÷&ÕöfÆÆ&6²"’À¢¢7FG2Òv—BvWE÷'FæW%ö÷fW'f–Wr‡FVÆVw&Õö–B¢W6W"Òv—BvWEö÷%ö7&VFU÷W6W"‡FVÆVw&Õö–B¢ÖRÒv—B&WVW7Bæ²&&÷B%ÒævWEöÖR‚ ¢Æ–æµö·v&w2ÒöÖ–æ–öÆ–æµö·v&w2†7G‚¢&VfW'&ÅöÆ–æ²Ò€¢'V–ÆE÷&VfW'&ÅöÆ–æ²†ÖRçW6W&æÖRÂW6W"ç&VfW'&Åö6öFRÂ¢¦Æ–æµö·v&w2¢–bW6W"ç&VfW'&Åö6öFP¢VÇ6R" ¢¢&VfW'&Åö&÷EöÆ–æµ÷7G"Ò€¢&VfW'&ÅöÆ–æ°¢–b7G‚ævWB‚'ÆFf÷&Ò"’ÓÒ'f² ¢VÇ6R€¢'V–ÆE÷&VfW'&Åö&÷EöÆ–æ²†ÖRçW6W&æÖRÂW6W"ç&VfW'&Åö6öFR¢–bW6W"ç&VfW'&Åö6öFP¢VÇ6R" ¢¢ ¢&WGW&âvV"æ§6öå÷&W7öç6R€¢°¢&ö²#¢G'VRÀ¢&—5÷'FæW"#¢&ööÂ‡7FG2ævWB‚&—5÷'FæW""’’À¢'W&6VçB#¢7FG5²'W&6VçB%ÒÀ¢&ÆWfVÃ%÷W&6VçB#¢7FG5²&ÆWfVÃ%÷W&6VçB%ÒÀ¢'&VfW'&Ç5ö6÷VçB#¢–çB‡7FG2ævWB‚'&VfW'&Ç5ö6÷VçB"Â’÷"’À¢&&Ææ6U÷'V"#¢fÆöB‡7FG2ævWB‚&&Ææ6U÷'V""Â’÷"’À¢'&ö×E÷&WVEö&Ææ6U÷'V"#¢fÆöB€¢7FG2ævWB‚'&ö×E÷&WVEö&Ææ6U÷'V""Â’÷" ¢’À¢'&ö×E÷&WVE÷F÷FÅ÷'V"#¢fÆöB€¢7FG2ævWB‚'&ö×E÷&WVE÷F÷FÅ÷'V""Â’÷" ¢’À¢&6†ææVÅ÷W&Â#¢W6W"æ6†ææVÅ÷W&Â÷"""À¢'&VfW'&ÅöÆ–æ²#¢&VfW'&ÅöÆ–æ²À¢'&VfW'&Åö&÷EöÆ–æ²#¢&VfW'&Åö&÷EöÆ–æµ÷7G"À¢'7FGW2#¢''FæW""–b7FG2ævWB‚&—5÷'FæW""’VÇ6R&&6–2"À¢Ð¢¢W†6WBW†6WF–öâ2S ¢&WGW&âöÖ–æ–öW'&÷%÷&W7öç6R†RÂÆöuöÖW76vSÒ$Ö–æ’'FæW"÷fW'f–Wrf–ÆVB"  ¦FVböÖ–æ–öÖVF–öW‡FVç6–öâ†6öçFVçE÷G—S¢7G"ÂW&Ã¢7G"’Óâ7G# ¢Ö–ÖRÒ7G"†6öçFVçE÷G—R÷"""’ç7Æ—B‚#²"Â•³Òç7G&—‚’æÆ÷vW"‚¢W‡FVç6–öç2Ò°¢&–ÖvRö§Vr#¢"æ§r"À¢&–ÖvR÷ær#¢"çær"À¢&–ÖvR÷vV'#¢"çvV'"À¢&–ÖvRöv–b#¢"æv–b"À¢'f–FVòö×B#¢"æ×B"À¢'f–FVò÷vV&Ò#¢"çvV&Ò"À¢'f–FVò÷V–6·F–ÖR#¢"æÖ÷b"À¢Ð¢–bÖ–ÖR–âW‡FVç6–öç3 ¢&WGW&âW‡FVç6–öç5¶Ö–ÖUÐ¢7Vff—‚ÒF‚‡W&Ç'6R‡W&Â’çF‚’ç7Vff—‚æÆ÷vW"‚¢&WGW&â7Vff—‚–b7Vff—‚–â6WB†W‡FVç6–öç2çfÇVW2‚’’VÇ6R"æ&–â   ¦7–æ2FVbÖ–æ–öÖVF–‡&WVW7C¢vV"å&WVW7B’ÓâvV"å7G&VÕ&W7öç6S ¢F6µö–BÒ7G"‡&WVW7BæÖF6…ö–æfòævWB‚'F6µö–B"’÷"""’ç7G&—‚¢G'“ ¢–æFW‚ÒÖ‚ƒÂ–çB‡&WVW7BæÖF6…ö–æfòævWB‚&–æFW‚"’÷"’¢W†6WB…G—TW'&÷"ÂfÇVTW'&÷"“ ¢&—6RvV"ä…EE&E&WVW7B‡FW‡CÒ$–çfÆ–BÖVF––æFW‚"¢–bæ÷BF6µö–B÷"ÆVâ‡F6µö–B’â# ¢&—6RvV"ä…EE&E&WVW7B‡FW‡CÒ$–çfÆ–BF6²–B" ¢7–æ2v—F‚F%ö&6¶VæBæ6öææV7B„DD$4UõD‚’2F# ¢F"ç&÷uöf7F÷'’ÒF%ö&6¶VæBå&÷p¢7W'6÷"Òv—BF"æW†V7WFR€¢""%4TÄT5B&W7VÇE÷W&ÂÂ&W7VÇE÷W&Ç2Â6ö×ÆWFVEöBÂWFFVEöBÂ7&VFVEö@¢e$ôÒvVæW&F–öå÷F6·2t„U$RF6µö–BÒòÄ”Ô•B"""À¢‡F6µö–BÂ’À¢¢&÷rÒv—B7W'6÷"æfWF6†öæR‚¢–bæ÷B&÷s ¢&—6RvV"ä…EEæ÷Df÷VæB‡FW‡CÒ$ÖVF–æ÷Bf÷VæB" ¢W&Ç2Ò÷V&Æ–5÷&W7VÇE÷W&Ç2†F–7B‡&÷r’¢–b–æFW‚ãÒÆVâ‡W&Ç2“ ¢&—6RvV"ä…EEæ÷Df÷VæB‡FW‡CÒ$ÖVF–æ÷Bf÷VæB"¢6÷W&6U÷W&ÂÒW&Ç5¶–æFW…Ð ¢g&öÒ&÷Bç6W'f–6W2æÖVF–ö–çWE÷WF–Ç2–×÷'B&W6öÇfUöÆö6Å÷WÆöE÷F€ ¢Æö6Å÷F‚Ò&W6öÇfUöÆö6Å÷WÆöE÷F‚‡6÷W&6U÷W&Â¢–bÆö6Å÷Fƒ ¢&W7öç6RÒvV"äf–ÆU&W7öç6R†Æö6Å÷F‚¢&W7öç6Ræ†VFW'5²$66†RÔ6öçG&öÂ%ÒÒ'V&Æ–2ÂÖ‚ÖvSÓƒcC ¢&WGW&â&W7öç6P ¢g&öÒ&÷BæFF&6R–×÷'BdTTEôU„TÔU$Åõ$U5TÅEô„õ5E2ÂöfVVE÷&W7VÇEö†÷7@ ¢†÷7BÒöfVVE÷&W7VÇEö†÷7B‡6÷W&6U÷W&Â¢–bæ÷Bç’††÷7BÓÒÆÆ÷vVB÷"†÷7BæVæG7v—F‚†b"ç¶ÆÆ÷vVGÒ"’f÷"ÆÆ÷vVB–âdTTEôU„TÔU$Åõ$U5TÅEô„õ5E2“ ¢&—6RvV"ä…EEf÷&&–FFVâ‡FW‡CÒ$ÖVF–†÷7B—2æ÷BÆÆ÷vVB" ¢66†Uö¶W’Ò†6†Æ–"ç6†#Sb‡6÷W&6U÷W&ÂæVæ6öFR‚'WFbÓ‚"’’æ†W†F–vW7B‚¢Ô”ä”ôÔTD”ô44„UôD•"æÖ¶F—"‡&VçG3ÕG'VRÂW†—7Eöö³ÕG'VR¢66†VBÒæW‡B„Ô”ä”ôÔTD”ô44„UôD•"ævÆö"†b'¶66†Uö¶W—Òâ¢"’ÂæöæR¢–b66†VBæB66†VBæ—5öf–ÆR‚“ ¢&W7öç6RÒvV"äf–ÆU&W7öç6R†66†VB¢&W7öç6Ræ†VFW'5²$66†RÔ6öçG&öÂ%ÒÒ'V&Æ–2ÂÖ‚ÖvSÓƒcC ¢&WGW&â&W7öç6P ¢Æö6²ÒöÖ–æ–öÖVF–öÆö6·2ç6WFFVfVÇB†66†Uö¶W’Â7–æ6–òäÆö6²‚’¢7–æ2v—F‚Æö6³ ¢66†VBÒæW‡B„Ô”ä”ôÔTD”ô44„UôD•"ævÆö"†b'¶66†Uö¶W—Òâ¢"’ÂæöæR¢–bæ÷B66†VC ¢F–ÖV÷WBÒ–ö‡GGä6Æ–VçEF–ÖV÷WB‡F÷FÃÓc¢7–æ2v—F‚–ö‡GGä6Æ–VçE6W76–öâ‡F–ÖV÷WC×F–ÖV÷WB’26W76–öã ¢7–æ2v—F‚6W76–öâævWB‡6÷W&6U÷W&ÂÂÆÆ÷u÷&VF—&V7G3ÕG'VR’2W7G&VÓ ¢–bW7G&VÒç7FGW2Ò# ¢&—6RvV"ä…EE&DvFWv’‡FW‡CÒ$ÖVF–6÷W&6R—2Væf–Æ&ÆR"¢6öçFVçEöÆVæwF‚Ò–çB‡W7G&VÒæ†VFW'2ævWB‚$6öçFVçBÔÆVæwF‚"’÷"¢–b6öçFVçEöÆVæwF‚âÔ”ä”ôÔTD”ôÔ…ô%•DU3 ¢&—6RvV"ä…EE&WVW7DVçF—G•FöôÆ&vR€¢Ö…÷6—¦SÔÔ”ä”ôÔTD”ôÔ…ô%•DU2À¢7GVÅ÷6—¦SÖ6öçFVçEöÆVæwF‚À¢¢6öçFVçBÒv—BW7G&VÒç&VB‚¢–bÆVâ†6öçFVçB’âÔ”ä”ôÔTD”ôÔ…ô%•DU3 ¢&—6RvV"ä…EE&WVW7DVçF—G•FöôÆ&vR€¢Ö…÷6—¦SÔÔ”ä”ôÔTD”ôÔ…ô%•DU2À¢7GVÅ÷6—¦SÖÆVâ†6öçFVçB’À¢¢W‡FVç6–öâÒöÖ–æ–öÖVF–öW‡FVç6–öâ€¢W7G&VÒæ†VFW'2ævWB‚$6öçFVçBÕG—R"Â""’Â6÷W&6U÷W&À¢¢66†VBÒÔ”ä”ôÔTD”ô44„UôD•"òb'¶66†Uö¶W—×¶W‡FVç6–öçÒ ¢FV×÷&'’Ò66†VBçv—F…÷7Vff—‚†b'¶66†VBç7Vff—‡ÒçF×"¢v—B7–æ6–òçFõ÷F‡&VB‡FV×÷&'’çw&—FUö'—FW2Â6öçFVçB¢v—B7–æ6–òçFõ÷F‡&VB‡FV×÷&'’ç&WÆ6RÂ66†VB¢öÖ–æ–öÖVF–öÆö6·2ç÷†66†Uö¶W’ÂæöæR¢&W7öç6RÒvV"äf–ÆU&W7öç6R†66†VB¢&W7öç6Ræ†VFW'5²$66†RÔ6öçG&öÂ%ÒÒ'V&Æ–2ÂÖ‚ÖvSÓƒcC ¢&WGW&â&W7öç6P  ¦7–æ2FVbÖ–æ–÷F6µö†—7F÷'’‡&WVW7C¢vV"å&WVW7B’ÓâvV"å&W7öç6S ¢""$6öçF–çVR÷væVB7GVF–ò†—7F÷'’v—F†÷WBW‡æF–ærF†RöÆÆVB&ö÷G7G&â"" ¢7F'FVEöBÒF–ÖRæÖöæ÷Föæ–2‚¢G'“ ¢G'“ ¢&öG’Òv—B&WVW7Bæ§6öâ‚¢W†6WB…fÇVTW'&÷"ÂG—TW'&÷"“ ¢&WGW&âvV"æ§6öå÷&W7öç6R‡²&ö²#¢fÇ6RÂ&W'&÷"#¢-	Ý]­í]­-Ý½’}ýí-í‚â'ÒÂ7FGW3ÓC¢–bæ÷B—6–ç7Fæ6R†&öG’ÂF–7B“ ¢&WGW&âvV"æ§6öå÷&W7öç6R‡²&ö²#¢fÇ6RÂ&W'&÷"#¢-	Ý]­í]­-Ý½’}ýí-í‚â'ÒÂ7FGW3ÓC¢FVÆVw&Õö–BÂö7G‚Òv—BövWE÷W6W%ö6öçFW‡B€¢&WVW7BæÂ&öG’ævWB‚&–æ—EöFF"Â""’Â&öG’ævWB‚'7F'E÷&ÕöfÆÆ&6²"’À¢¢7W'6÷"Ò&öG’ævWB‚&7W'6÷""¢–b7W'6÷"—2æ÷BæöæRæB†æ÷B—6–ç7Fæ6R†7W'6÷"Â7G"’÷"æ÷B7W'6÷"ç7G&—‚’÷"ÆVâ†7W'6÷"’â#Sb“ ¢&WGW&âvV"æ§6öå÷&W7öç6R‡²&ö²#¢fÇ6RÂ&W'&÷"#¢-	Ý]­í]­-Ý½’­=í-í‚â'ÒÂ7FGW3ÓC¢2V–v‡B—2G&ç7÷'BvRÂæWfW"Ö†–×VÒçVÖ&W"öbW6W"v÷&·2à¢7W'6÷%÷&W6WBÒfÇ6P¢G'“ ¢&÷w2Òv—BöfWF6…÷&V6VçE÷F6·2‡FVÆVw&Õö–BÂÆ–Ö—CÓ’Â&Vf÷&U÷F6µö–CÖ7W'6÷"¢W†6WBF6´†—7F÷'”7W'6÷$W'&÷# ¢2FVÆWFVB÷7FÆRöf÷&V–vâæ6†÷"æWfW"6VÆV7G2æ÷F†W"÷væW"w0¢2&V6÷&G2â&W7F'BBF†R÷væVB†VB6òF†RæW‡BvR6â&öw&W72à¢7W'6÷%÷&W6WBÒG'VP¢&÷w2Òv—BöfWF6…÷&V6VçE÷F6·2‡FVÆVw&Õö–BÂÆ–Ö—CÓ’¢F6·2Ò&÷w5³£…Ð¢g&öÒçG&VæE÷F6µ÷&—f7’–×÷'B6æ—F—¦U÷F6µö•÷–Æö@ ¢–ÆöBÒv—B6æ—F—¦U÷F6µö•÷–ÆöB‡°¢&ö²#¢G'VRÂ'&V6VçE÷F6·2#¢F6·2À¢&æW‡Eö7W'6÷"#¢F6·5²ÓÕ²'F6µö–B%Ò–bÆVâ‡&÷w2’â‚VÇ6RæöæRÀ¢&7W'6÷%÷&W6WB#¢7W'6÷%÷&W6WBÀ¢Ò¢ÆövvW"æ–æfò€¢$Ö–æ’F6²†—7F÷'“¢FVÆVw&Õö–CÒW26÷VçCÒW2†5öÖ÷&SÒW27W'6÷%÷&W6WCÒW2GW&F–öåö×3ÒW2"À¢FVÆVw&Õö–BÂÆVâ‡F6·2’Â–ÆöE²&æW‡Eö7W'6÷"%Ò—2æ÷BæöæRÀ¢7W'6÷%÷&W6WBÀ¢&÷VæB‚‡F–ÖRæÖöæ÷Föæ–2‚’Ò7F'FVEöB’¢’À¢¢&WGW&âvV"æ§6öå÷&W7öç6R‡–ÆöBÂ†VFW'3×²$66†RÔ6öçG&öÂ#¢&æò×7F÷&R'Ò¢W†6WBW†6WF–öâ2W'&÷#¢2æ÷¢$ÄSÒ…EE&÷VæF'’W6W2F†R6†&VB6fRW'&÷"Ö–æp¢&WGW&âöÖ–æ–öW'&÷%÷&W7öç6R€¢W'&÷"ÂÆöuöÖW76vSÒ$Ö–æ’F6²†—7F÷'’f–ÆVB"À¢FVfVÇEöW'&÷#Ò-	ÝR=M½íÂ}==}-Â-íââ	ýíýí=-R]râ"À¢  ¦7–æ2FVbÖ–æ–÷F6µöFWF–Â‡&WVW7C¢vV"å&WVW7B’ÓâvV"å&W7öç6S ¢G'“ ¢&öG’Òv—B&WVW7Bæ§6öâ‚¢–æ—EöFFÒ&öG’ævWB‚&–æ—EöFF"Â""¢F6µö–BÒ7G"†&öG’ævWB‚'F6µö–B"Â""’’ç7G&—‚¢–bæ÷BF6µö–C ¢&WGW&âvV"æ§6öå÷&W7öç6R€¢²&ö²#¢fÇ6RÂ&W'&÷"#¢'F6µö–B—2&WV—&VB'ÒÂ7FGW3ÓC ¢ ¢FVÆVw&Õö–BÂö7G‚Òv—BövWE÷W6W%ö6öçFW‡B‡&WVW7BæÂ–æ—EöFFÂ&öG’ævWB‚'7F'E÷&ÕöfÆÆ&6²"’¢FWF–ÂÒv—BöfWF6…÷F6µöFWF–Â‡FVÆVw&Õö–BÂF6µö–B¢–bæ÷BFWF–Ã ¢&WGW&âvV"æ§6öå÷&W7öç6R€¢²&ö²#¢fÇ6RÂ&W'&÷"#¢-	}M}ÝRÝM]Ý'ÒÂ7FGW3ÓC@¢¢–b÷&WVE÷W'6öæÆ—¦F–öåöÆÆ÷vVB‡FVÆVw&Õö–B“ ¢g&öÒ&÷Bç&WVE÷W'6öæÆ—¦F–öâ–×÷'B&WVEö–ÖvUöÖöFU÷7W÷'FV@ ¢FWF–Å²'&WVE÷W'6öæÆ—¦F–öåöVF—F÷%öVæ&ÆVB%ÒÒG'VP¢FWF–Å²'&WVEö–ÖvUö6†ö–6W5÷7W÷'FVB%ÒÒ&WVEö–ÖvUöÖöFU÷7W÷'FVB†FWF–Â¢FWF–Å²'&WVE÷W6W%öf–VÆG2%ÒÒv—BvWE÷&WVEöf–VÆG2€¢–çB†FWF–ÂævWB‚&fVVEö–B"’÷"¢ ¢2Væf÷&6RF†R6ÖR&V6—R&÷VæF'’f÷"F—&V7BFVÆVw&ÒÖWF†VçF–6FV@¢2&WVW7G22'&÷w6W"ÖWF‚Ö–FFÆWv&RÂ–æ6ÇVF–ærÆVv7’&VÖ—‚&÷w2à¢g&öÒçG&VæE÷F6µ÷&—f7’–×÷'B6æ—F—¦U÷F6µö•÷–Æö@ ¢–ÆöBÒv—B6æ—F—¦U÷F6µö•÷–ÆöB‡²&ö²#¢G'VRÂ'F6²#¢FWF–ÇÒ¢&WGW&âvV"æ§6öå÷&W7öç6R‡–ÆöB¢W†6WBW†6WF–öâ2S ¢&WGW&âöÖ–æ–öW'&÷%÷&W7öç6R†RÂÆöuöÖW76vSÒ$Ö–æ’F6²FWF–Âf–ÆVB"  ¦7–æ2FVbÖ–æ–ö•ö76—7FçB‡&WVW7C¢vV"å&WVW7B’ÓâvV"å&W7öç6S ¢""$’Ý-]Ý"}]]rÝ-íý’ÄÄÒ&6¶VæBâ"" ¢G'“ ¢&öG’Òv—B&WVW7Bæ§6öâ‚¢–æ—EöFFÒ&öG’ævWB‚&–æ—EöFF"Â""¢W6W%öÖW76vRÒ7G"†&öG’ævWB‚&ÖW76vR"Â""’’ç7G&—‚¢VF–õ÷W&ÂÒ7G"†&öG’ævWB‚&VF–õ÷W&Â"Â""’÷"""’ç7G&—‚¢VF–õö6öçFVçE÷G—RÒ7G"†&öG’ævWB‚&VF–õö6öçFVçE÷G—R"Â""’÷"""’ç7G&—‚¢†—7F÷'’ÒÆ—7B†&öG’ævWB‚&†—7F÷'’"ÂµÒ’÷"µÒ ¢–bæ÷BW6W%öÖW76vRæBæ÷BVF–õ÷W&Ã ¢&WGW&âvV"æ§6öå÷&W7öç6R€¢²&ö²#¢fÇ6RÂ&W'&÷"#¢-
íí]ÝRÝRÍím]"½-Âý=-½Â'ÒÂ7FGW3ÓC ¢ ¢FVÆVw&Õö–BÂ7G‚Òv—BövWE÷W6W%ö6öçFW‡B‡&WVW7BæÂ–æ—EöFFÂ&öG’ævWB‚'7F'E÷&ÕöfÆÆ&6²"’¢W6W"Ò7G…²'W6W"%Ð¢VF–õö'—FW2ÒæöæP¢VF–õöf÷&ÖBÒ"  ¢–bVF–õ÷W&Ã ¢G'“ ¢VF–õö'—FW2ÂöÖ–ÖU÷G—RÂVF–õöf÷&ÖBÒöÆöEöÖ–æ–ö76—7FçEöVF–ò€¢VF–õ÷W&ÂÀ¢6öçFVçE÷G—SÖVF–õö6öçFVçE÷G—RÀ¢¢W†6WBfÇVTW'&÷"2S ¢&WGW&âvV"æ§6öå÷&W7öç6R€¢²&ö²#¢fÇ6RÂ&W'&÷"#¢7G"†R—ÒÀ¢7FGW3ÓCÀ¢ ¢6öçFW‡BÒ°¢'W6W%ö7&VF—G2#¢W6W"æ7&VF—G2À¢&ÖVçUöÆö6F–öâ#¢&Ö–æ•öö76—7FçB"À¢Ð ¢–bVF–õö'—FW3 ¢&W7öç6U÷FW‡BÒv—B•ö76—7FçE÷6W'f–6RævWEö76—7FçE÷&W7öç6U÷v—F…öVF–ò€¢W6W%öÖW76vS×W6W%öÖW76vRÀ¢6öçFW‡CÖ6öçFW‡BÀ¢VF–õö'—FW3ÖVF–õö'—FW2À¢VF–õöf÷&ÖCÖVF–õöf÷&ÖBÀ¢¢VÇ6S ¢&W7öç6U÷FW‡BÒv—B•ö76—7FçE÷6W'f–6RævWEö76—7FçE÷&W7öç6R€¢W6W%öÖW76vS×W6W%öÖW76vRÀ¢6öçFW‡CÖ6öçFW‡BÀ¢ ¢–b&W7öç6U÷FW‡B—2æöæS ¢&WGW&âvV"æ§6öå÷&W7öç6R€¢°¢&ö²#¢fÇ6RÀ¢&W'&÷"#¢$’Ý-]Ý"-]Í]ÝÝâÝ]Mí-=ý]Òâ	ýíýí=-Rýí}mRâ"À¢ÒÀ¢7FGW3ÓS2À¢ ¢&WGW&âvV"æ§6öå÷&W7öç6R‡²&ö²#¢G'VRÂ'&WÇ’#¢&W7öç6U÷FW‡GÒ¢W†6WBW†6WF–öâ2S ¢&WGW&âöÖ–æ–öW'&÷%÷&W7öç6R†RÂÆöuöÖW76vSÒ$Ö–æ’’76—7FçBf–ÆVB"  ¦7–æ2FVbÖ–æ–ö•öæ÷Eöf÷VæB‡&WVW7C¢vV"å&WVW7B’ÓâvV"å&W7öç6S ¢ÆövvW"çv&æ–ær€¢$Ö–æ’’&÷WFRæ÷Bf÷VæC¢ÖWF†öCÒW2FƒÒW2"À¢&WVW7BæÖWF†öBÀ¢&WVW7BçF‚À¢¢&WGW&âvV"æ§6öå÷&W7öç6R€¢²&ö²#¢fÇ6RÂ&W'&÷"#¢$’VæGö–çBæ÷Bf÷VæB'ÒÀ¢7FGW3ÓCBÀ¢  ¦FVb6WGWöÖ–æ–÷&÷WFW2†¢vV"äÆ–6F–öâ“ ¢Ö–æ–÷F‚Ò6öæf–räÔ”ä•ôõD‚÷""öÖ–æ’Ö ¢–bæ÷BÖ–æ–÷F‚ç7F'G7v—F‚‚"ò"“ ¢Ö–æ–÷F‚Òb"÷¶Ö–æ–÷F‡Ò ¢Ö–æ–÷&ö÷BÒÖ–æ–÷F‚ç'7G&—‚"ò"¢Ö–æ–ög&öçFVæEö†÷7BÒW&Ç'6R†6öæf–ræÖ–æ•ö÷W&Â÷"""’ææWFÆö2æÆ÷vW"‚ ¢FVb÷6†÷VÆE÷&VF—&V7E÷Fõög&öçFVæB‡&WVW7C¢vV"å&WVW7B’Óâ&ööÃ ¢–bæ÷BÖ–æ–ög&öçFVæEö†÷7C ¢&WGW&âfÇ6P¢&WVW7Eö†÷7BÒ&WVW7Bæ†÷7Bç7Æ—B‚#¢"Â•³ÒæÆ÷vW"‚¢&WGW&â&WVW7Eö†÷7BÒÖ–æ–ög&öçFVæEö†÷7@ ¢FVbög&öçFVæEöÖ–æ–÷W&Â‡7Vff—ƒ¢7G"Ò""’Óâ7G# ¢&6RÒ†6öæf–ræÖ–æ•ö÷W&Â÷"""’ç'7G&—‚"ò"¢7Vff—‚Ò7Vff—‚æÇ7G&—‚"ò"¢&WGW&âb'¶&6WÒ÷·7Vff—‡Ò"–b7Vff—‚VÇ6Rb'¶&6WÒò  ¢vV"æÖ–FFÆWv&P¢7–æ2FVböÖ–æ–ö6÷'5öÖ–FFÆWv&R€¢&WVW7C¢vV"å&WVW7BÀ¢†æFÆW"À¢’ÓâvV"å7G&VÕ&W7öç6S ¢""$FB4õ%2†VFW'2FòÖ–æ’’&W7öç6W2à ¢FVÆVw&ÒÖ–æ’2'Vâ–ç6–FRâ–g&ÖRâ6öÖReç2÷&÷†–W2–ç7V7B÷ ¢7G&—4õ%2†VFW'2Â6W6–ærfWF6‚‚’&WVW7G2g&öÒF†RÖ–æ’ÖFòf–À¢–bF†R&W7öç6RÆ6·2W‡Æ–6—B66W72Ô6öçG&öÂÔÆÆ÷rÔ÷&–v–âà ¢vRV6†òF†R&WVW7B÷&–v–â&6²†æ÷Br¢r’&V6W6R7&VFVçF–ÆVB&WVW7G0¢‡v—F‚‚ÕFVÆVw&ÒÔ–æ—BÔFF’&WV—&R6öæ7&WFR÷&–v–âÂæ÷Bv–ÆF6&Bà¢"" ¢–b&WVW7BæÖWF†öBÓÒ$õD”ôå2# ¢&W7öç6RÒvV"å&W7öç6R‡7FGW3Ó#B¢÷&–v–âÒ&WVW7Bæ†VFW'2ævWB‚$÷&–v–â"Â""¢–b÷&–v–ã ¢&W7öç6Ræ†VFW'5²$66W72Ô6öçG&öÂÔÆÆ÷rÔ÷&–v–â%ÒÒ÷&–v–à¢&W7öç6Ræ†VFW'5²$66W72Ô6öçG&öÂÔÆÆ÷rÔ7&VFVçF–Ç2%ÒÒ'G'VR ¢&W7öç6Ræ†VFW'5²$66W72Ô6öçG&öÂÔÆÆ÷rÔÖWF†öG2%ÒÒ$tUBÂõ5BÂõD”ôå2 ¢&W7öç6Ræ†VFW'5²$66W72Ô6öçG&öÂÔÆÆ÷rÔ†VFW'2%ÒÒ€¢$6öçFVçBÕG—RÂWF†÷&—¦F–öâÂ‚ÕFVÆVw&ÒÔ–æ—BÔFFÂ‚Õ&WVW7FVBÕv—F‚ ¢¢&W7öç6Ræ†VFW'5²$66W72Ô6öçG&öÂÔÖ‚ÔvR%ÒÒ#ƒcC ¢&WGW&â&W7öç6P ¢&W7öç6RÒv—B†æFÆW"‡&WVW7B¢÷&–v–âÒ&WVW7Bæ†VFW'2ævWB‚$÷&–v–â"Â""¢–b÷&–v–ã ¢&W7öç6Ræ†VFW'5²$66W72Ô6öçG&öÂÔÆÆ÷rÔ÷&–v–â%ÒÒ÷&–v–à¢&W7öç6Ræ†VFW'5²$66W72Ô6öçG&öÂÔÆÆ÷rÔ7&VFVçF–Ç2%ÒÒ'G'VR ¢–b&WVW7BçF‚ç7F'G7v—F‚†b'¶Ö–æ–÷&ö÷GÒõöæW‡B÷7FF–2ò"’÷"&WVW7BçF‚ÓÒb'¶Ö–æ–÷&ö÷GÒ÷FVÆVw&Ò×vV"Öæ§2# ¢&W7öç6Ræ†VFW'5²$66†RÔ6öçG&öÂ%ÒÒ&æò×7F÷&RÂæòÖ66†RÂ×W7B×&WfÆ–FFRÂÖ‚ÖvSÓ ¢&W7öç6Ræ†VFW'5²%&vÖ%ÒÒ&æòÖ66†R ¢&W7öç6Ræ†VFW'5²$W‡—&W2%ÒÒ# ¢&WGW&â&W7öç6P ¢vV"æÖ–FFÆWv&P¢7–æ2FVböÖ–æ–ö•ö§6öåöW'&÷'2€¢&WVW7C¢vV"å&WVW7BÀ¢†æFÆW"À¢’ÓâvV"å7G&VÕ&W7öç6S ¢G'“ ¢&WGW&âv—B†æFÆW"‡&WVW7B¢W†6WBvV"ä…EEW†6WF–öâ2W†3 ¢–b&WVW7BçF‚ç7F'G7v—F‚†b'¶Ö–æ–÷&ö÷GÒö’ò"’÷"&WVW7BçF‚ç7F'G7v—F‚€¢"ö’÷cò ¢“ ¢&WGW&âvV"æ§6öå÷&W7öç6R€¢²&ö²#¢fÇ6RÂ&W'&÷"#¢W†2ç&V6öâ÷"$’&WVW7Bf–ÆVB'ÒÀ¢7FGW3ÖW†2ç7FGW2À¢¢&—6P ¢24õ%2Ö–FFÆWv&R×W7B&Rd•%5B6ò—Bw&2ÆÂ÷F†W"Ö–FFÆWv&W2æ@¢2Æ–W2FòWfW'’Ö–æ’ò’&W7öç6Rà¢æÖ–FFÆWv&W2æ–ç6W'BƒÂöÖ–æ–ö6÷'5öÖ–FFÆWv&R¢æÖ–FFÆWv&W2æVæB…öÖ–æ–ö•ö§6öåöW'&÷'2 ¢2÷F–öæÂÆFf÷&ÒÖæF—fRF—7F6‚W6W2F†RW†7B4ÔRÖ–æ’&÷WFW2à¢2&VÖ–ç2â–æW'B72×F‡&÷Vv‚VæÆW72WfW'’d²FFW"—2&Vv—7FW&VBæ@¢2dµôeTÄÅôõ$•E•ôTä$ÄTB—2Væ&ÆVBâFVÆVw&Ò&VÖ–ç2Væ6†ævVBà¢g&öÒ&÷Bç6†&VEö66÷VçG2ævFWv’–×÷'BfµöÖ–æ–övFWv¢g&öÒ&÷Bç6†&VEö66÷VçG2ææF—fUö&ö÷G7G&–×÷'Bf´æF—fTFFW ¢g&öÒ&÷Bç6†&VEö66÷VçG2ææF—fU÷F6·2–×÷'Bf´æF—fUF6·4FFW  ¢²wfµöæF—fU÷F6·5öFFW"uÒÒf´æF—fUF6·4FFW"‚¢2–æ7&VÖVçFÂd²7F÷"&ö÷G7G&²F6·3²gVÆÂÖFöÖ–â&VF–æW727F–ÆÂôdbà¢²wfµögVÆÅööFFW"uÒÒf´æF—fTFFW"‡F6·3Ö²wfµöæF—fU÷F6·5öFFW"uÒ¢æÖ–FFÆWv&W2æVæB‡fµöÖ–æ–övFWv’†Ö–æ–÷&ö÷B’ ¢2Ö–æ–÷7FF–5öÖ÷VçE÷c¢g&öÒF†Æ–"–×÷'BF‚2ôÖ–æ”F€ ¢Ö–æ–ö÷WEöF—"Ò€¢ôÖ–æ”F‚…õöf–ÆUõò’ç&W6öÇfR‚’ç&VçBç&Vç@¢ò&g&öçFVæB ¢ò&Ö–æ–×c ¢ò&÷WB ¢¢Ö–æ–öæW‡E÷7FF–5öF—"ÒÖ–æ–ö÷WEöF—"ò%öæW‡B"ò'7FF–2 ¢–bÖ–æ–öæW‡E÷7FF–5öF—"æW†—7G2‚“ ¢ç&÷WFW"æFE÷7FF–2€¢"öÖ–æ’ÖõöæW‡B÷7FF–2ò"À¢Fƒ×7G"†Ö–æ–öæW‡E÷7FF–5öF—"’À¢æÖSÒ&Ö–æ–öæW‡E÷7FF–2"À¢ ¢7–æ2FVböÖ–æ–÷&ö÷Eöf–ÆR‡&WVW7C¢vV"å&WVW7B’ÓâvV"å&W7öç6S ¢76WEöæÖRÒ&WVW7BæÖF6…ö–æfòævWB‚&76WB"Â""’÷"&–6öâÖÆ–v‡BÓ3'ƒ3"çær ¢76WE÷F‚ÒÖ–æ–ö÷WEöF—"ò76WEöæÖP¢–b76WE÷F‚æW†—7G2‚’æB76WE÷F‚æ—5öf–ÆR‚“ ¢&WGW&âvV"äf–ÆU&W7öç6R†76WE÷F‚¢–b76WEöæÖRÓÒ&ff–6öâæ–6ò# ¢f÷"fÆÆ&6µöæÖR–â‚&–6öâç7fr"Â&–6öâÖÆ–v‡BÓ3'ƒ3"çær"“ ¢fÆÆ&6µ÷F‚ÒÖ–æ–ö÷WEöF—"òfÆÆ&6µöæÖP¢–bfÆÆ&6µ÷F‚æW†—7G2‚’æBfÆÆ&6µ÷F‚æ—5öf–ÆR‚“ ¢&WGW&âvV"äf–ÆU&W7öç6R†fÆÆ&6µ÷F‚¢&—6RvV"ä…EEæ÷Df÷VæB‚ ¢7–æ2FVböV×G•÷fW&6VÅö–ç6–v‡G2‡&WVW7C¢vV"å&WVW7B’ÓâvV"å&W7öç6S ¢2F†RW‡÷'FVBÖ–æ–6â&WVW7BfW&6VÂ–ç6–v‡G2g&öÒF†R6—FR&ö÷Bà¢2vRFòæ÷B'VâfW&6VÂ†W&RÂ6ò6W'fRæòÖ÷67&—B–ç7FVBöbæö—7’CG2à¢&WGW&âvV"å&W7öç6R€¢FW‡CÒ"ò¢fW&6VÂ–ç6–v‡G2F—6&ÆVBöâ6VÆbÖ†÷7FVBFWÆ÷–ÖVçBâ¢õÆâ"À¢6öçFVçE÷G—SÒ&Æ–6F–öâö¦f67&—B"À¢†VFW'3×²$66†RÔ6öçG&öÂ#¢'V&Æ–2ÂÖ‚ÖvSÓ3c'ÒÀ¢ ¢7–æ2FVböÖ–æ–ög&öçFVæE÷&VF—&V7B‡&WVW7C¢vV"å&WVW7B’ÓâvV"å&W7öç6S ¢–b÷6†÷VÆE÷&VF—&V7E÷Fõög&öçFVæB‡&WVW7B“ ¢&WGW&âvV"ä…EEf÷VæB…ög&öçFVæEöÖ–æ–÷W&Â‚’¢&WGW&âv—BÖ–æ–ö–æFW‚‡&WVW7B ¢7–æ2FVböÖ–æ–ö76WEö÷%÷&VF—&V7B‡&WVW7C¢vV"å&WVW7B’ÓâvV"å&W7öç6S ¢–b÷6†÷VÆE÷&VF—&V7E÷Fõög&öçFVæB‡&WVW7B“ ¢F–ÂÒ&WVW7BæÖF6…ö–æfòævWB‚'F–Â"Â""¢&WGW&âvV"ä…EEf÷VæB…ög&öçFVæEöÖ–æ–÷W&Â‡F–Â’¢&WGW&âv—BÖ–æ–ö76WB‡&WVW7B ¢2Fòæ÷BÖ÷VçBF†RgVÆÂ÷WBöF—&V7F÷'’27FF–2&W6÷W&6R†W&Rà¢26W'f–æröb–æFW‚æ‡FÖÆæB÷F†W"f–ÆW2—2†æFÆVBW‡Æ–6—FÇ’'¢2Ö–æ–ö–æFW†æBÖ–æ–ö76WF6òvRfö–B6öæfÆ–7G2v†W&RF†P¢27FF–2&W6÷W&6Rv÷VÆBÖF6‚öÖ–æ’ÖöæB&WGW&âC2f÷"F—&V7F÷'¢2&WVW7G2v†Vâ6†÷uö–æFW†—2F—6&ÆVBâ¶VWöæÇ’öæW‡B÷7FF–6 ¢2Ö÷VçFVB&÷fRf÷"æW‡Bæ§2'VçF–ÖR76WG2à¢ç&÷WFW"æFEövWB‚"ö–6öâÖÆ–v‡BÓ3'ƒ3"çær"ÂöÖ–æ–÷&ö÷Eöf–ÆR¢ç&÷WFW"æFEövWB‚"ö–6öâç7fr"ÂöÖ–æ–÷&ö÷Eöf–ÆR¢ç&÷WFW"æFEövWB‚"ö–6öâÖF&²Ó3'ƒ3"çær"ÂöÖ–æ–÷&ö÷Eöf–ÆR¢ç&÷WFW"æFEövWB‚"öff–6öâæ–6ò"ÂöÖ–æ–÷&ö÷Eöf–ÆR¢ç&÷WFW"æFEövWB‚"öÆRÖ–6öâçær"ÂöÖ–æ–÷&ö÷Eöf–ÆR¢ç&÷WFW"æFEövWB‚"õ÷fW&6VÂö–ç6–v‡G2÷67&—Bæ§2"ÂöV×G•÷fW&6VÅö–ç6–v‡G2¢ç&÷WFW"æFEövWB‚"÷FVÆVw&Ò×vV"Öæ§2"ÂöÖ–æ–÷&ö÷Eöf–ÆR¢ç&÷WFW"æFEövWB†Ö–æ–÷&ö÷BÂöÖ–æ–ög&öçFVæE÷&VF—&V7B¢ç&÷WFW"æFEövWB†b'¶Ö–æ–÷&ö÷GÒò"ÂöÖ–æ–ög&öçFVæE÷&VF—&V7B¢g&öÒ&÷Bæ¶Æ–æsEö’–×÷'B6WGWö¶Æ–æsE÷&÷WFW0¢6WGWö¶Æ–æsE÷&÷WFW2†ÂÖ–æ–÷&ö÷B¢g&öÒ&÷Bçvã5÷&–ÖUö’–×÷'B6WGW÷vã5÷&–ÖU÷&÷WFW0¢6WGW÷vã5÷&–ÖU÷&÷WFW2†ÂÖ–æ–÷&ö÷B¢g&öÒ&÷BçG&VæEö6FÆöuö’–×÷'B6WGW÷G&VæEö6FÆöu÷&÷WFW0¢6WGW÷G&VæEö6FÆöu÷&÷WFW2†ÂÖ–æ–÷&ö÷B¢g&öÒ&÷Bæ7G&õö’–×÷'B6WGWö7G&õ÷&÷WFW0¢6WGWö7G&õ÷&÷WFW2†ÂÖ–æ–÷&ö÷B¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’ö&ö÷G7G&"ÂÖ–æ–ö&ö÷G7G&¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’÷w&—FRÖ66W72"ÂÖ–æ–÷w&—FUö66W72¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’ö6Æ–VçBÖÆör"ÂÖ–æ–ö6Æ–VçEöÆör¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’ö7F–öâ"ÂÖ–æ–ö7F–öâ¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’÷WÆöB"ÂÖ–æ–÷WÆöB¢g&öÒ&÷Bç&VfW&Væ6UöÆ–'&'•ö’–×÷'B&VfW&Væ6UöÆ–'&'•ö7F–öà ¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’÷&VfW&Væ6RÖÆ–'&'’"Â&VfW&Væ6UöÆ–'&'•ö7F–öâ¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’÷†÷Fò×Fò×&ö×B"ÂÖ–æ–÷†÷Fõ÷Fõ÷&ö×B¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’÷&ö×G2"ÂÖ–æ–÷&ö×G2¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’÷&ö×G2öFWF–Â"ÂÖ–æ–÷&ö×EöFWF–Â¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’÷&ö×G2öÆ–¶R"ÂÖ–æ–÷&ö×EöÆ–¶R¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’÷&ö×G2÷W6R"ÂÖ–æ–÷&ö×E÷W6R¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’÷&ö×G2öÆ–æ²"ÂÖ–æ–÷&ö×EöÆ–æ²¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’÷&ö×G2÷7V&Ö—B"ÂÖ–æ–÷&ö×E÷7V&Ö—B¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’÷&ö×G2öFV7F—fFR"ÂÖ–æ–÷&ö×EöFV7F—fFR¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’öFÖ–â÷&ö×G2÷WFFR×&Wf–Wr"ÂÖ–æ–÷&ö×E÷WFFU÷&Wf–Wr¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’öFÖ–â÷&ö×G2öÖöFW&FR"ÂÖ–æ–÷&ö×EöÖöFW&FR¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’öfVVB"ÂÖ–æ–öfVVB¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’öfVVBö—FVÒ"ÂÖ–æ–öfVVEö—FVÒ¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’öfVVBö×’"ÂÖ–æ–ö×•öfVVB¢ç&÷WFW"æFEövWB†Ö–æ–÷&ö÷B²"ö’öfVVB÷&öf–ÆR"ÂÖ–æ–÷&öf–ÆUöfVVB¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’öfVVB÷&öf–ÆR"ÂÖ–æ–÷&öf–ÆUöfVVB¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’÷&öf–ÆRö6†ææVÂ"ÂÖ–æ–÷&öf–ÆUö6†ææVÅ÷6fR¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’öfVVBöÆ–¶R"ÂÖ–æ–öfVVEöÆ–¶R¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’öfVVB÷6†&R"ÂÖ–æ–öfVVE÷6†&R¢ç&÷WFW"æFEövWB†Ö–æ–÷&ö÷B²"ö’öfVVBö6öÖÖVçG2"ÂÖ–æ–öfVVEö6öÖÖVçG2¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’öfVVBö6öÖÖVçG2"ÂÖ–æ–öfVVEö6öÖÖVçG2¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’öfVVBö6öÖÖVçB"ÂÖ–æ–öfVVEö6öÖÖVçEöFB¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’öfVVBö&ÇW""ÂÖ–æ–öfVVEö&ÇW"¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’öfVVB÷&VÖ÷fR"ÂÖ–æ–öfVVE÷&VÖ÷fR¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’öfVVB÷&VÖ—‚"ÂÖ–æ–öfVVE÷&VÖ—‚¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’övVæW&F–öç2÷6†&R"ÂÖ–æ–övVæW&F–öå÷6†&R¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’övVæW&F–öç2÷V&Æ—6‚"ÂÖ–æ–övVæW&F–öå÷6†&R¢ç&÷WFW"æFE÷÷7B€¢Ö–æ–÷&ö÷B²"ö’övVæW&F–öç2÷6†&RÖÆ–'&'’"À¢Ö–æ–övVæW&F–öå÷6†&UöÆ–'&'’À¢¢ç&÷WFW"æFE÷÷7B€¢Ö–æ–÷&ö÷B²"ö’övVæW&F–öç2÷&VÖ÷fRÖÆ–'&'’"À¢Ö–æ–övVæW&F–öå÷&VÖ÷fUöÆ–'&'’À¢¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’övVæW&FRÖ–ÖvR"ÂÖ–æ–övVæW&FUö–ÖvR¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’övVæW&FR×f–FVò"ÂÖ–æ–övVæW&FU÷f–FVò¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’÷V÷FRÖÖ÷F–öâ"ÂÖ–æ–÷V÷FUöÖ÷F–öâ¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’÷7FGW2ÖÖ÷F–öâ"ÂÖ–æ–÷7FGW5öÖ÷F–öâ¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’övVæW&FRÖÖ÷F–öâ"ÂÖ–æ–övVæW&FUöÖ÷F–öâ¢ç&÷WFW"æFE÷÷7B€¢Ö–æ–÷&ö÷B²"ö’÷'FæW"Ö÷fW'f–Wr"ÂÖ–æ–÷'FæW%ö÷fW'f–Wp¢¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’ö7&VFR×–ÖVçB"ÂÖ–æ–ö7&VFU÷–ÖVçB¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’÷F6²ÖFWF–Â"ÂÖ–æ–÷F6µöFWF–Â¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’÷F6²Ö†—7F÷'’"ÂÖ–æ–÷F6µö†—7F÷'’¢ç&÷WFW"æFE÷÷7B†Ö–æ–÷&ö÷B²"ö’ö’Ö76—7FçB"ÂÖ–æ–ö•ö76—7FçB¢ç&÷WFW"æFEövWB€¢Ö–æ–÷&ö÷B²"ö’öÖVF–÷·F6µö–GÒ÷¶–æFW‡Ò"ÂÖ–æ–öÖVF–¢¢ç&÷WFW"æFE÷&÷WFR‚"¢"ÂÖ–æ–÷&ö÷B²"ö’÷·F–Ã¢â§Ò"ÂÖ–æ–ö•öæ÷Eöf÷VæB ¢•÷c÷&ö÷BÒ"ö’÷c ¢ç&÷WFW"æFEövWB†•÷c÷&ö÷B²"öfVVB"ÂÖ–æ–öfVVB¢ç&÷WFW"æFEövWB†•÷c÷&ö÷B²"öÖRöfVVB"ÂÖ–æ–ö×•öfVVB¢ç&÷WFW"æFEövWB†•÷c÷&ö÷B²"öfVVB÷&öf–ÆR"ÂÖ–æ–÷&öf–ÆUöfVVB¢ç&÷WFW"æFE÷÷7B†•÷c÷&ö÷B²"öfVVB÷&öf–ÆR"ÂÖ–æ–÷&öf–ÆUöfVVB¢ç&÷WFW"æFEövWB†•÷c÷&ö÷B²"öfVVB÷¶vVåö–GÒ"ÂÖ–æ–öfVVEö—FVÒ¢ç&÷WFW"æFEövWB†•÷c÷&ö÷B²"÷&öf–ÆW2÷·&VfW'&Åö6öFWÒöfVVB"ÂÖ–æ–÷&öf–ÆUöfVVB¢ç&÷WFW"æFE÷÷7B†•÷c÷&ö÷B²"÷&öf–ÆW2÷·&VfW'&Åö6öFWÒöfVVB"ÂÖ–æ–÷&öf–ÆUöfVVB¢ç&÷WFW"æFE÷÷7B†•÷c÷&ö÷B²"öÖRö6†ææVÂ"ÂÖ–æ–÷&öf–ÆUö6†ææVÅ÷6fR¢ç&÷WFW"æFEövWB†•÷c÷&ö÷B²"öfVVB÷¶vVåö–GÒö6öÖÖVçG2"ÂÖ–æ–öfVVEö6öÖÖVçG2¢ç&÷WFW"æFE÷÷7B†•÷c÷&ö÷B²"öfVVB÷¶vVåö–GÒö6öÖÖVçG2"ÂÖ–æ–öfVVEö6öÖÖVçEöFB¢ç&÷WFW"æFE÷÷7B†•÷c÷&ö÷B²"övVæW&F–öç2÷¶vVåö–GÒ÷6†&R"ÂÖ–æ–övVæW&F–öå÷6†&R¢ç&÷WFW"æFE÷÷7B†•÷c÷&ö÷B²"övVæW&F–öç2÷¶vVåö–GÒ÷V&Æ—6‚"ÂÖ–æ–övVæW&F–öå÷6†&R¢ç&÷WFW"æFE÷÷7B€¢•÷c÷&ö÷B²"övVæW&F–öç2÷¶vVåö–GÒ÷6†&RÖÆ–'&'’"À¢Ö–æ–övVæW&F–öå÷6†&UöÆ–'&'’À¢¢ç&÷WFW"æFE÷÷7B€¢•÷c÷&ö÷B²"övVæW&F–öç2÷¶vVåö–GÒ÷&VÖ÷fRÖÆ–'&'’"À¢Ö–æ–övVæW&F–öå÷&VÖ÷fUöÆ–'&'’À¢¢ç&÷WFW"æFE÷÷7B†•÷c÷&ö÷B²"öfVVB÷¶vVåö–GÒ÷&VÖ÷fR"ÂÖ–æ–öfVVE÷&VÖ÷fR¢ç&÷WFW"æFE÷÷7B†•÷c÷&ö÷B²"öfVVB÷¶vVåö–GÒö&ÇW""ÂÖ–æ–öfVVEö&ÇW"¢ç&÷WFW"æFE÷÷7B†•÷c÷&ö÷B²"öfVVB÷¶vVåö–GÒöÆ–¶R"ÂÖ–æ–öfVVEöÆ–¶R¢ç&÷WFW"æFE÷÷7B†•÷c÷&ö÷B²"öfVVB÷¶vVåö–GÒ÷&VÖ—‚"ÂÖ–æ–öfVVE÷&VÖ—‚¢ç&÷WFW"æFEövWB†•÷c÷&ö÷B²"öfVVB÷¶vVåö–GÒöÆ–æ²"ÂÖ–æ–öfVVE÷6†&R¢ç&÷WFW"æFEövWB†•÷c÷&ö÷B²"÷&ö×G2"ÂÖ–æ–÷&ö×G2¢ç&÷WFW"æFE÷÷7B†•÷c÷&ö÷B²"÷&ö×G2"ÂÖ–æ–÷&ö×E÷7V&Ö—B¢ç&÷WFW"æFEövWB†•÷c÷&ö÷B²"÷&ö×G2ö×’"ÂÖ–æ–÷&ö×G2¢ç&÷WFW"æFEövWB†•÷c÷&ö÷B²"÷&ö×G2÷·&ö×Eö–GÒ"ÂÖ–æ–÷&ö×EöFWF–Â¢ç&÷WFW"æFEövWB†•÷c÷&ö÷B²"÷&ö×G2÷·&ö×Eö–GÒöÆ–æ²"ÂÖ–æ–÷&ö×EöÆ–æ²¢ç&÷WFW"æFE÷÷7B†•÷c÷&ö÷B²"÷&ö×G2÷·&ö×Eö–GÒöÆ–¶R"ÂÖ–æ–÷&ö×EöÆ–¶R¢ç&÷WFW"æFE÷÷7B†•÷c÷&ö÷B²"÷&ö×G2÷·&ö×Eö–GÒ÷W6R"ÂÖ–æ–÷&ö×E÷W6R¢ç&÷WFW"æFE÷÷7B€¢•÷c÷&ö÷B²"÷&ö×G2÷·&ö×Eö–GÒöFV7F—fFR"À¢Ö–æ–÷&ö×EöFV7F—fFRÀ¢¢ç&÷WFW"æFE÷÷7B†•÷c÷&ö÷B²"övVæW&FRö–ÖvR"ÂÖ–æ–övVæW&FUö–ÖvR¢ç&÷WFW"æFE÷&÷WFR‚"¢"Â•÷c÷&ö÷B²"÷·F–Ã¢â§Ò"ÂÖ–æ–ö•öæ÷Eöf÷VæB¢ç&÷WFW"æFEövWB†Ö–æ–÷&ö÷B²"÷·F–Ã¢â§Ò"ÂöÖ–æ–ö76WEö÷%÷&VF—&V7B