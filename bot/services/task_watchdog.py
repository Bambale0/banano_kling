"""Task watchdog: фоновый процесс для обработки зависших задач генерации.

Сканирует generation_tasks в статусе 'pending'/'processing' старше N минут,
пытается запросить статус у провайдера через API,
и переводит в failed с возвратом credits, если задача не имеет финального статуса.

Запускается как asyncio task при старте бота (main.py:701).
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from bot import db as db_backend
from bot.database import DATABASE_PATH, cleanup_stale_local_generation_tasks

logger = logging.getLogger(__name__)

# Конфигурация
WATCHDOG_INTERVAL_SECONDS = 60  # быстро подхватываем webhook-race после рестарта
STUCK_THRESHOLD_MINUTES = 2  # provider уже мог завершить задачу, но webhook потеряться
MAX_STUCK_MINUTES = 120  # принудительно failed через 2 часа
LOCAL_ORPHAN_MAX_AGE_SECONDS = 15 * 60  # локальная задача без provider id



async def get_stuck_tasks(minutes: int = STUCK_THRESHOLD_MINUTES) -> list[Dict[str, Any]]:
    """Возвращает provider-задачи, созданные больше N минут назад.

    Cutoff считается часами самой БД. PostgreSQL хранит created_at как
    timestamp without time zone в timezone сессии, поэтому Python
    datetime.utcnow() может сдвигать окно и полностью отключать recovery.
    """
    safe_minutes = max(0, int(minutes))
    if db_backend.is_postgres():
        age_expr = "EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - created_at)) / 60.0"
    else:
        age_expr = "(julianday(CURRENT_TIMESTAMP) - julianday(created_at)) * 1440.0"

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            f"""
            SELECT id, user_id, task_id, model,
                   prompt, cost, request_data, created_at,
                   {age_expr} AS watchdog_age_minutes
            FROM generation_tasks
            WHERE status IN ('pending', 'processing')
              AND task_id NOT LIKE 'img_%'
              AND {age_expr} >= ?
            ORDER BY created_at ASC
            LIMIT 50
            """,
            (safe_minutes,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def check_task_with_provider(
    external_task_id: str,
    service_name: str,
) -> Optional[str]:
    """Пытается запросить статус задачи у провайдера.

    Возвращает статус ('completed', 'failed') или None если не удалось.
    """
    if not external_task_id or not service_name:
        return None

    normalized_service = str(service_name or "").strip().lower()

    try:
        if "kling" in normalized_service:
            from bot.services.kling_service import kling_service
            result = await kling_service.get_task_status(external_task_id)
            if result:
                status = (result.get("data") or {}).get("status") or result.get("status")
                if status and str(status).lower() in ("success", "completed", "done"):
                    return "completed"
                if status and str(status).lower() in ("failed", "error", "rejected"):
                    return "failed"
        elif "veo" in normalized_service:
            from bot.services.veo_service import veo_service
            result = await veo_service.get_task(external_task_id)
            # Veo возвращает результат асинхронно — polling вряд ли поможет
            return None
        elif "seedance" in normalized_service:
            from bot.services.kie_market_service import kie_market_service
            result = await kie_market_service.get_task_status(external_task_id)
            if result:
                status = result.get("state") or result.get("status")
                if status and str(status).lower() in ("success", "completed", "done"):
                    return "completed"
                if status and str(status).lower() in ("failed", "error", "rejected"):
                    return "failed"
        elif "seedream" in normalized_service:
            from bot.services.seedream_service import seedream_service
            result = await seedream_service.get_task_status(external_task_id)
            if result:
                status = (result.get("data") or {}).get("status") or result.get("state") or result.get("status")
                if status and str(status).lower() in ("success", "completed", "done"):
                    return "completed"
                if status and str(status).lower() in ("failed", "error", "rejected"):
                    return "failed"
        elif normalized_service in {"wan27", "wan_27"} or (
            "wan" in normalized_service and "2-7" in normalized_service
        ):
            from bot.services.wan27_service import wan27_service
            result = await wan27_service.get_task_status(external_task_id)
            if result:
                status = (result.get("data") or {}).get("status") or result.get("state") or result.get("status")
                if status and str(status).lower() in ("success", "completed", "done"):
                    return "completed"
                if status and str(status).lower() in ("failed", "error", "rejected"):
                    return "failed"
        elif normalized_service in {
            "nano-banana-2-lite",
            "nano_banana_2_lite",
            "banana_2_lite",
            "flux_pro",
            "gpt-image-2",
            "gpt_image_2",
            "grok_imagine",
            "grok_imagine_v15",
            "motion_control_v26",
            "v3_std",
            "v3_pro",
        }:
            from bot.services.kie_market_service import kie_market_service
            result = await kie_market_service.get_task_status(external_task_id)
            if result:
                status = result.get("state") or result.get("status")
                if status and str(status).lower() in ("success", "completed", "done"):
                    return "completed"
                if status and str(status).lower() in ("failed", "error", "rejected"):
                    return "failed"
        elif normalized_service in {"banana_2", "nano-banana-2", "nano_banana_2"}:
            from bot.services.nano_banana_2_service import nano_banana_2_service
            result = await nano_banana_2_service.get_task_status(external_task_id)
            if result:
                status = result.get("state") or result.get("status")
                if status and str(status).lower() in ("success", "completed", "done"):
                    return "completed"
                if status and str(status).lower() in ("failed", "error", "rejected", "fail"):
                    return "failed"
        elif normalized_service in {"banana_pro", "nanobanana", "nano-banana-pro", "nano_banana_pro"}:
            from bot.services.nano_banana_pro_service import nano_banana_pro_service
            result = await nano_banana_pro_service.get_task_status(external_task_id)
            if result:
                status = result.get("state") or result.get("status")
                if status and str(status).lower() in ("success", "completed", "done"):
                    return "completed"
                if status and str(status).lower() in ("failed", "error", "rejected", "fail"):
                    return "failed"
    except Exception:
        logger.debug(
            "Watchdog: failed to check task %s with provider %s",
            external_task_id,
            service_name,
            exc_info=True,
        )
    return None


async def force_fail_task(task_id: int, user_id: int, cost: float) -> bool:
    """Переводит задачу в failed и возвращает credits пользователю."""
    async with db_backend.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE generation_tasks
            SET status = 'failed',
                completed_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status IN ('pending', 'processing')
            """,
            (task_id,),
        )
        if cursor.rowcount == 0:
            return False

        # Возвращаем credits
        if cost and cost > 0:
            await db.execute(
                "UPDATE users SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (cost, user_id),
            )

        await db.commit()
        return True


async def run_watchdog_cycle(on_completed=None) -> int:
    """Один цикл watchdog: восстанавливает orphan и зависшие provider-задачи.

    Returns: количество переведённых в failed задач.
    """
    orphan_stats = await cleanup_stale_local_generation_tasks(
        max_age_seconds=LOCAL_ORPHAN_MAX_AGE_SECONDS
    )
    recovered = int(orphan_stats.get("failed_count") or 0)
    if recovered:
        logger.warning(
            "Watchdog: recovered %s local orphan task(s), refunded_credits=%s",
            recovered,
            orphan_stats.get("refunded_credits", 0.0),
        )

    stuck = await get_stuck_tasks(STUCK_THRESHOLD_MINUTES)
    if not stuck:
        return recovered

    for task in stuck:
        tid = task["id"]
        uid = task["user_id"]
        model = task.get("model") or ""
        raw_request = task.get("request_data") or "{}"
        cost = float(task.get("cost") or 0)
        try:
            task_age_minutes = float(task.get("watchdog_age_minutes") or 0)
        except (TypeError, ValueError):
            task_age_minutes = 0.0
        request_data: dict = {}
        if isinstance(raw_request, str):
            try:
                request_data = json.loads(raw_request)
            except (TypeError, json.JSONDecodeError):
                request_data = {}
        elif isinstance(raw_request, dict):
            request_data = raw_request

        external_task_id = task.get("task_id") or ""
        service_name = model or request_data.get("img_service") or request_data.get("service_name") or ""

        provider_status = None
        if external_task_id and service_name:
            provider_status = await check_task_with_provider(external_task_id, service_name)

        if provider_status == "completed":
            if on_completed is not None:
                try:
                    if await on_completed(task):
                        logger.warning(
                            "Watchdog: replayed completed upstream task %s (provider_task_id=%s, model=%s)",
                            tid,
                            external_task_id,
                            model,
                        )
                        recovered += 1
                except Exception:
                    logger.exception(
                        "Watchdog: completed-task replay failed for task %s provider_task_id=%s",
                        tid,
                        external_task_id,
                    )
            continue

        if provider_status == "failed":
            if await force_fail_task(tid, uid, cost):
                logger.warning(
                    "Watchdog: recovered failed upstream task %s (user=%s, model=%s, cost=%s)",
                    tid, uid, model, cost,
                )
                recovered += 1
            continue

        # Задачи старше MAX_STUCK_MINUTES — принудительно в failed.
        # Возраст вычислен часами самой БД в get_stuck_tasks(), без timezone drift.
        if task_age_minutes >= MAX_STUCK_MINUTES:
            if await force_fail_task(tid, uid, cost):
                logger.warning(
                    "Watchdog: force-failed task %s (user=%s, model=%s, cost=%s) "
                    "— stuck for >%s min (provider_status=%s)",
                    tid, uid, model, cost, MAX_STUCK_MINUTES, provider_status or "unknown",
                )
                recovered += 1
            continue

    if recovered:
        logger.info(
            "Watchdog cycle: %d/%d stuck tasks recovered",
            recovered, len(stuck),
        )
    return recovered


async def watchdog_loop(on_completed=None):
    """Бесконечный цикл watchdog, запускается при старте бота."""
    # Задержка при старте — даём БД инициализироваться
    await asyncio.sleep(15)
    logger.info(
        "Task watchdog started: interval=%ss, threshold=%smin, max_stuck=%smin",
        WATCHDOG_INTERVAL_SECONDS, STUCK_THRESHOLD_MINUTES, MAX_STUCK_MINUTES,
    )
    while True:
        try:
            await run_watchdog_cycle(on_completed=on_completed)
        except Exception:
            logger.exception("Watchdog cycle error")
        await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
