import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import aiosqlite

logger = logging.getLogger(__name__)

DATABASE_PATH = os.getenv("DATABASE_PATH", "bot.db")


@dataclass
class User:
    id: int
    telegram_id: int
    credits: int
    created_at: datetime
    updated_at: datetime


@dataclass
class Transaction:
    id: int
    order_id: str
    user_id: int
    payment_id: str
    credits: int
    amount_rub: float
    status: str
    created_at: datetime


@dataclass
class GenerationTask:
    id: int
    user_id: int
    task_id: str
    type: str
    preset_id: str
    status: str
    result_url: Optional[str]
    created_at: datetime


async def init_db():
    """Инициализация базы данных"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Таблица пользователей
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                credits INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        # Таблица транзакций (платежи)
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                payment_id TEXT,
                credits INTEGER NOT NULL,
                amount_rub REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """
        )

        # Таблица задач генерации
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS generation_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                task_id TEXT UNIQUE NOT NULL,
                type TEXT NOT NULL,
                preset_id TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                result_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """
        )

        # Таблица истории генераций
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS generation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                preset_id TEXT NOT NULL,
                prompt TEXT,
                cost INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """
        )

        await db.commit()
        logger.info("Database initialized successfully")


async def get_or_create_user(telegram_id: int) -> User:
    """Получает или создаёт пользователя (thread-safe)"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Ищем пользователя
        cursor = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()

        if row:
            return User(
                id=row["id"],
                telegram_id=row["telegram_id"],
                credits=row["credits"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

        # Создаём нового пользователя с бонусными кредитами
        # Используем INSERT OR IGNORE для защиты от race condition
        try:
            await db.execute(
                "INSERT INTO users (telegram_id, credits) VALUES (?, 10)", (telegram_id,)
            )
            await db.commit()
            logger.info(f"Created new user: {telegram_id}")
        except aiosqlite.IntegrityError:
            # Пользователь уже создан другим параллельным запросом
            logger.debug(f"User {telegram_id} already exists (race condition handled)")

        # Получаем пользователя (созданного нами или другим запросом)
        cursor = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()

        return User(
            id=row["id"],
            telegram_id=row["telegram_id"],
            credits=row["credits"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


async def get_user_credits(telegram_id: int) -> int:
    """Получает баланс кредитов пользователя"""
    user = await get_or_create_user(telegram_id)
    return user.credits


async def add_credits(telegram_id: int, amount: int) -> bool:
    """Добавляет кредиты пользователю"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE users SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (amount, telegram_id),
        )
        await db.commit()
        logger.info(f"Added {amount} credits to user {telegram_id}")
        return True


async def deduct_credits(telegram_id: int, amount: int, check_balance: bool = True) -> bool:
    """Списывает кредиты с проверкой баланса"""
    from bot.config import config
    
    # Админы не платят
    if config.is_admin(telegram_id):
        logger.info(f"Admin {telegram_id} - free access (skipped {amount} credits)")
        return True
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Проверяем баланс
        cursor = await db.execute(
            "SELECT credits FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()

        if not row or row["credits"] < amount:
            return False

        # Списываем
        await db.execute(
            "UPDATE users SET credits = credits - ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (amount, telegram_id),
        )
        await db.commit()
        logger.info(f"Deducted {amount} credits from user {telegram_id}")
        return True


async def check_can_afford(telegram_id: int, amount: int) -> bool:
    """Проверяет, может ли пользователь позволить себе операцию"""
    from bot.config import config
    
    # Админы всегда могут
    if config.is_admin(telegram_id):
        return True
    
    user = await get_or_create_user(telegram_id)
    return user.credits >= amount


async def create_transaction(
    order_id: str,
    user_id: int,
    payment_id: str,
    credits: int,
    amount_rub: float,
    status: str = "pending",
) -> bool:
    """Создаёт транзакцию платежа"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            await db.execute(
                """INSERT INTO transactions 
                   (order_id, user_id, payment_id, credits, amount_rub, status) 
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (order_id, user_id, payment_id, credits, amount_rub, status),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            logger.warning(f"Transaction already exists: {order_id}")
            return False


async def get_transaction_by_order(order_id: str) -> Optional[Transaction]:
    """Получает транзакцию по order_id"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            "SELECT * FROM transactions WHERE order_id = ?", (order_id,)
        )
        row = await cursor.fetchone()

        if not row:
            return None

        return Transaction(
            id=row["id"],
            order_id=row["order_id"],
            user_id=row["user_id"],
            payment_id=row["payment_id"],
            credits=row["credits"],
            amount_rub=row["amount_rub"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )


async def update_transaction_status(order_id: str, status: str) -> bool:
    """Обновляет статус транзакции"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE transactions SET status = ? WHERE order_id = ?", (status, order_id)
        )
        await db.commit()
        return True


async def add_generation_task(
    user_id: int, task_id: str, type: str, preset_id: str
) -> bool:
    """Создаёт задачу генерации"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            await db.execute(
                """INSERT INTO generation_tasks 
                   (user_id, task_id, type, preset_id, status) 
                   VALUES (?, ?, ?, ?, 'pending')""",
                (user_id, task_id, type, preset_id),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            logger.warning(f"Task already exists: {task_id}")
            return False


async def get_task_by_id(task_id: str) -> Optional[GenerationTask]:
    """Получает задачу по task_id"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            "SELECT * FROM generation_tasks WHERE task_id = ?", (task_id,)
        )
        row = await cursor.fetchone()

        if not row:
            return None

        return GenerationTask(
            id=row["id"],
            user_id=row["user_id"],
            task_id=row["task_id"],
            type=row["type"],
            preset_id=row["preset_id"],
            status=row["status"],
            result_url=row["result_url"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )


async def complete_video_task(task_id: str, result_url: str) -> bool:
    """Отмечает задачу как выполненную"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """UPDATE generation_tasks 
               SET status = 'completed', result_url = ?, completed_at = CURRENT_TIMESTAMP 
               WHERE task_id = ?""",
            (result_url, task_id),
        )
        await db.commit()
        return True


async def add_generation_history(
    user_id: int, preset_id: str, prompt: str, cost: int
) -> bool:
    """Добавляет запись в историю генераций"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """INSERT INTO generation_history 
               (user_id, preset_id, prompt, cost) 
               VALUES (?, ?, ?, ?)""",
            (user_id, preset_id, prompt, cost),
        )
        await db.commit()
        return True


async def get_user_stats(telegram_id: int) -> dict:
    """Получает статистику пользователя"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Получаем пользователя
        user = await get_or_create_user(telegram_id)

        # Считаем количество генераций
        cursor = await db.execute(
            "SELECT COUNT(*) as count FROM generation_history WHERE user_id = ?",
            (user.id,),
        )
        gen_row = await cursor.fetchone()

        # Считаем потраченные кредиты
        cursor = await db.execute(
            "SELECT SUM(cost) as total FROM generation_history WHERE user_id = ?",
            (user.id,),
        )
        cost_row = await cursor.fetchone()

        return {
            "credits": user.credits,
            "generations": gen_row["count"] or 0,
            "total_spent": cost_row["total"] or 0,
            "member_since": user.created_at.strftime("%d.%m.%Y"),
        }


async def get_admin_stats() -> dict:
    """Получает общую статистику для админа"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Всего пользователей
        cursor = await db.execute("SELECT COUNT(*) as count FROM users")
        users_row = await cursor.fetchone()

        # Всего генераций
        cursor = await db.execute("SELECT COUNT(*) as count FROM generation_history")
        gen_row = await cursor.fetchone()

        # Всего транзакций
        cursor = await db.execute(
            "SELECT COUNT(*) as count, SUM(amount_rub) as total FROM transactions WHERE status = 'completed'"
        )
        trans_row = await cursor.fetchone()

        # Пакетных генераций
        cursor = await db.execute("SELECT COUNT(*) as count FROM batch_jobs")
        batch_row = await cursor.fetchone()

        return {
            "total_users": users_row["count"] or 0,
            "total_generations": gen_row["count"] or 0,
            "total_revenue": trans_row["total"] or 0,
            "total_transactions": trans_row["count"] or 0,
            "total_batch_jobs": batch_row["count"] or 0,
        }


async def save_batch_job(
    job_id: str,
    user_id: int,
    mode: str,
    total_cost: int,
    results_count: int,
    duration: Optional[float] = None,
) -> bool:
    """Сохраняет результаты пакетной генерации"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            # Создаём таблицу если не существует
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS batch_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT UNIQUE NOT NULL,
                    user_id INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    total_cost INTEGER NOT NULL,
                    results_count INTEGER DEFAULT 0,
                    duration REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """
            )

            await db.execute(
                """INSERT INTO batch_jobs 
                   (job_id, user_id, mode, total_cost, results_count, duration) 
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (job_id, user_id, mode, total_cost, results_count, duration),
            )
            await db.commit()
            logger.info(f"Saved batch job: {job_id}")
            return True
        except aiosqlite.IntegrityError:
            logger.warning(f"Batch job already exists: {job_id}")
            return False


async def get_batch_jobs_by_user(telegram_id: int, limit: int = 10) -> list:
    """Получает историю пакетных генераций пользователя"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        user = await get_or_create_user(telegram_id)

        cursor = await db.execute(
            """SELECT * FROM batch_jobs 
               WHERE user_id = ? 
               ORDER BY created_at DESC 
               LIMIT ?""",
            (user.id, limit),
        )
        rows = await cursor.fetchall()

        return [
            {
                "job_id": row["job_id"],
                "mode": row["mode"],
                "total_cost": row["total_cost"],
                "results_count": row["results_count"],
                "duration": row["duration"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
