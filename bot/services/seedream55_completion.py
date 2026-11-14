"""KIE-verified Seedream 5.5 layer callback with complete durable delivery."""
from __future__ import annotations

import html
import json
import logging

from aiohttp import web

from bot.database import (
    can_attempt_telegram_delivery,
    claim_task_delivery,
    complete_task_in_app,
    complete_video_task,
    get_task_by_id,
    mark_task_delivery_status,
)
from bot.services.feed_persist import persist_feed_result_urls
from bot.services.seedream55_results import (
    extract_layers,
    make_layers_archive,
    settle_layers,
)

logger = logging.getLogger(__name__)


async def deliver_layer_task(request: web.Request, task) -> web.Response:
    """Only called by the canonical/verified KIE webhook success branch."""
    task_id = task.task_id
    try:
        saved = json.loads(task.request_data or "{}")
        settlement = saved.get("seedream55_settlement") or {}
        if settlement.get("status") == "completed":
            urls = list(settlement.get("urls") or [])
            archive_url = str(saved.get("seedream55_layers_archive_url") or "")
            if not urls or not archive_url:
                raise ValueError("Completed layer task missing result bundle")
        else:
            # Canonical payload is retained on the request by the webhook handler.
            canonical = request.get("seedream55_canonical_result") or {}
            result_json = canonical.get("resultJson") or "{}"
            result_json = json.loads(result_json) if isinstance(result_json, str) else result_json
            source_urls, metadata = extract_layers(result_json)
            # Never expose temporary provider URLs in history, feed or notifications.
            urls = await persist_feed_result_urls(source_urls, require_local=True)
            if len(urls) != len(source_urls):
                raise OSError("Could not persist all Seedream 5.5 layers")
            archive_url = await make_layers_archive(task_id, source_urls, metadata)
            if not archive_url:
                raise OSError("Seedream 5.5 ZIP could not be persisted")
            settled = await settle_layers(task_id, urls, metadata, archive_url)
            if not settled:
                task = await get_task_by_id(task_id)
                saved = json.loads(task.request_data or "{}") if task else {}
                settlement = saved.get("seedream55_settlement") or {}
                if settlement.get("status") != "completed":
                    raise RuntimeError("Concurrent layer settlement not committed")
                urls = list(settlement.get("urls") or [])
                archive_url = str(saved.get("seedream55_layers_archive_url") or "")
    except Exception:
        logger.exception("Seedream 5.5 layer persistence failed: task_id=%s", task_id)
        return web.Response(status=503)

    # A VK-native user must never be handed to Telegram for delivery.
    latest = await get_task_by_id(task_id)
    if not latest:
        return web.Response(status=503)
    current_data = json.loads(latest.request_data or "{}")
    if current_data.get("origin_platform") == "vk":
        try:
            if not await complete_task_in_app(task_id, urls[0]):
                return web.Response(status=503)
        except Exception:
            logger.exception("Seedream 5.5 VK completion failed: task=%s", task_id)
            return web.Response(status=503)
        return web.Response(status=200)

    telegram_id = latest.telegram_id
    if not telegram_id:
        logger.warning("Seedream 5.5 layer result has no Telegram recipient: task=%s", task_id)
        return web.Response(status=200)
    bot = request.app["bot"]
    if not await can_attempt_telegram_delivery(
        telegram_id, probe=getattr(bot, "get_chat", None),
    ):
        await complete_video_task(task_id, urls[0])
        await mark_task_delivery_status(task_id, "unavailable", error="chat_not_started")
        return web.Response(status=200)
    if not await claim_task_delivery(task_id):
        return web.Response(status=200)
    message = (
        f"✅ <b>Готово: {len(urls)} изображений и слоёв</b>\n"
        f"Модель: Seedream 5.5\n"
        f"ID: <code>{html.escape(task_id)}</code>\n\n"
        f"📦 <a href=\"{html.escape(archive_url, quote=True)}\">Скачать все слои ZIP</a>\n"
        f"🖼 <a href=\"{html.escape(urls[0], quote=True)}\">Посмотреть основной кадр</a>\n\n"
        "Все изображения также доступны в истории Mini App."
    )
    try:
        await bot.send_message(telegram_id, message, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as exc:  # noqa: BLE001 - external Telegram transport can raise many API/network errors.
        logger.warning("Seedream 5.5 layers Telegram delivery retry: task=%s error=%s", task_id, type(exc).__name__)
        await mark_task_delivery_status(task_id, "pending", error=type(exc).__name__)
        return web.Response(status=503)
    await complete_video_task(task_id, urls[0])
    await mark_task_delivery_status(task_id, "delivered")
    logger.info("Seedream 5.5 layers delivered: task=%s output_count=%s", task_id, len(urls))
    return web.Response(status=200)
