"""Task watchdog: фоновый процесс для обработки зависших задач генерации.

Сканирует generation_tasks в статусе 'processing' старше N минут,
пытается запросить статус у провайдера через API,
и переводит в failed с возвратом credits, если задача не имеет финального статуса.

Запускается как asyncio task при старте бота (main.py:701).
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from bot import db as db_backend
from bot.database import DATABASE_PATH, get_telegram_id_by_user_id

logger = logging.getLogger(__name__)

# Конфигурация
WATCHDOG_INTERVAL_SECONDS = 300  # 5 минут
STUCK_THRESHOLD_MINUTES = 30  # задача считается зависшей через 30 минут
MAX_STUCK_MINUTES = 120  # принудительно failed через 2 часа


async def get_stuck_tasks(minutes: int = STUCK_THRESHOLD_MINUTES) -> list[Dict[str, Any]]:
    """Возвращает задачи в processing, созданные больше N минут назад."""
    since = datetime.utcnow() - timedelta(minutes=minutes)
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT id, user_id, task_id, external_task_id, service_name, model,
                   prompt, cost, credits_spent, created_at
            FROM generation_tasks
            WHERE status = 'processing'
              AND created_at <= ?
            ORDER BY created_at ASC
            LIMIT 50
            """,
            (since.isoformat(),),
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

    try:
        if "kling" in (service_name or "").lower():
            from bot.services.kling_service import kling_service
            result = await kling_service.get_task(external_task_id)
            if result:
                status = (result.get("data") or {}).get("state") or result.get("state")
                if status and str(status).lower() in ("success", "completed", "done"):
                    return "completed"
                if status and str(status).lower() in ("failed", "error", "rejected"):
                    return "failed"
        elif "veo" in (service_name or "").lower():
            from bot.services.veo_service import veo_service
            result = await veo_service.get_task(external_task_id)
            # Veo возвращает результат асинхронно — polling вряд ли поможет
            return None
        elif "seedance" in (service_name or "").lower():
            from bot.services.seedance_service import seedance_service
            result = await seedance_service.get_task(external_task_id)
            if result:
                status = result.get("state") or result.get("status")
                if status and str(status).lower() in ("success", "completed", "done"):
                    return "completed"
                if status and str(status).lower() in ("failed", "error", "rejected"):
                    return "failed"
        elif "seedream" in (service_name or "").lower():
            from bot.services.seedream_service import seedream_service
            result = await seedream_service.get_task(external_task_id)
            if result:
                status = result.get("state") or result.get("status")
                if status and str(status).lower() in ("success", "completed", "done"):
                    return "completed"
                if status and str(status).lower() in ("failed", "error", "rejected"):
                    return "failed"
        elif "wan27" in (service_name or "").lower():
            from bot.services.wan27_service import wan27_service
            result = await wan27_service.get_task(external_task_id)
            if result:
                status = result.get("state") or result.get("status")
                if status and str(status).lower() in ("success", "completed", "done"):
                    return "completed"
                if status and str(status).lower() in ("failed", "error", "rejected"):
                    return "failed"
        elif "nano_banana" in (service_name or "").lower() or "nano-banana" in (service_name or "").lower():
            from bot.services.kie_market_service import kie_market_service
            result = await kie_market_service.get_task(external_task_id)
            if result:
                status = result.get("state") or result.get("status")
                if status and str(status).lower() in ("success", "completed", "done"):
                    return "completed"
                if status and str(status).lower() in ("failed", "error", "rejected"):
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
            WHERE id = ? AND status = 'processing'
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


async def run_watchdog_cycle() -> int:
    """Один цикл watchdog: находит > форсит зависшие задачи.

    Returns: количество переведённых в failed задач.
    """
    stuck = await get_stuck_tasks(STUCK_THRESHOLD_MINUTES)
    if not stuck:
        return 0

    max_stuck_cutoff = datetime.utcnow() - timedelta(minutes=MAX_STUCK_MINUTES)
    recovered = 0

    for task in stuck:
        task_id = task["id"]
        user_id = task["user_id"]
        external_task_id = task.get("external_task_id") or ""
        service_name = task.get("service_name") or ""
        cost = float(task.get("cost") or task.get("credits_spent") or 0)
        created_at = task.get("created_at")

        # Задачи старше MAX_STUCK_MINUTES — принудительно в failed
        if created_at and created_at <= max_stuck_cutoff:
            if await force_fail_task(task_id, user_id, cost):
                logger.warning(
                    "Watchdog: force-failed task %s (user=%s, service=%s, cost=%s) "
                    "— stuck for >%s min",
                    task_id, user_id, service_name, cost, MAX_STUCK_MINUTES,
                )
                recovered += 1
            continue

        # Пробуем проверить статус у провайдера
        if external_task_id:
            try:
                provider_status = await check_task_with_provider(
                    external_task_id, service_name
                )
                if provider_status == "completed":
                    # Завершаем задачу (без отправки результата пользователю)
                    async with db_backend.connect(DATABASE_PATH) as db:
                        await db.execute(
                            """
                            UPDATE generation_tasks
                            SET status = 'completed', completed_at = CURRENT_TIMESTAMP
                            WHERE id = ? AND status = 'processing'
                            """,
                            (task_id,),
                        )
                        await db.commit()
                    logger.info(
                        "Watchdog: task %s recovered as completed (provider=%s)",
                        task_id, service_name,
                    )
                    recovered += 1
                elif provider_status == "failed":
                    if await force_fail_task(task_id, user_id, cost):
                        logger.warning(
                            "Watchdog: task %s recovered as failed (provider=%s)",
                            task_id, service_name,
                        )
                        recovered += 1
            except Exception:
                logger.debug(
                    "Watchdog: error checking task %s with provider %s",
                    task_id, service_name, exc_info=True,
                )

    if recovered:
        logger.info(
            "Watchdog cycle: %d/%d stuck tasks recovered",
            recovered, len(stuck),
        )
    return recovered


async def watchdog_loop():
    """Бесконечный цикл watchdog, запускается при старте бота."""
    logger.info(
        "Task watchdog started: interval=%ss, threshold=%smin, max_stuck=%smin",
        WATCHDOG_INTERVAL_SECONDS, STUCK_THRESHOLD_MINUTES, MAX_STUCK_MINUTES,
    )
    while True:
        try:
            await run_watchdog_cycle()
        except Exception:
            logger.exception("Watchdog cycle error")
        await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
