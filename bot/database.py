import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import aiosqlite

logger = logging.getLogger(__name__)

DATABASE_PATH = os.getenv("DATABASE_PATH", "bot.db")
MASTER_PARTNER_TELEGRAM_ID = int(os.getenv("MASTER_PARTNER_TELEGRAM_ID", "339795159"))


@dataclass
class User:
    id: int
    telegram_id: int
    credits: int
    created_at: datetime
    updated_at: datetime
    referral_code: Optional[str] = None
    referred_by: Optional[int] = None
    referral_earned: int = 0
    has_paid: bool = False
    partner_agreed_at: Optional[datetime] = None
    partner_total_revenue_rub: float = 0.0
    partner_balance_rub: float = 0.0
    partner_withdrawn_rub: float = 0.0
    partner_tier: str = "basic"


@dataclass
class Transaction:
    id: int
    order_id: str
    user_id: int
    payment_id: str
    provider: str
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
    model: Optional[str] = None
    duration: Optional[int] = None
    aspect_ratio: Optional[str] = None
    prompt: Optional[str] = None
    cost: Optional[int] = None
    status: str = "pending"
    telegram_id: Optional[int] = None
    result_url: Optional[str] = None
    request_data: Optional[str] = None
    created_at: Optional[datetime] = None


async def init_db():
    """Инициализация базы данных"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Таблица пользователей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                credits INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Referral system migrations for existing databases
        try:
            await db.execute("ALTER TABLE users ADD COLUMN referral_code TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN referral_earned INTEGER DEFAULT 0"
            )
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN has_paid BOOLEAN DEFAULT 0")
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN partner_agreed_at TIMESTAMP")
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN partner_total_revenue_rub REAL DEFAULT 0"
            )
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN partner_balance_rub REAL DEFAULT 0"
            )
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN partner_withdrawn_rub REAL DEFAULT 0"
            )
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN partner_tier TEXT DEFAULT 'basic'"
            )
        except aiosqlite.OperationalError:
            pass

        # Таблица транзакций (платежи)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                payment_id TEXT,
                provider TEXT DEFAULT 'cryptobot',
                credits INTEGER NOT NULL,
                amount_rub REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        # Таблица задач генерации
        await db.execute("""
            CREATE TABLE IF NOT EXISTS generation_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                telegram_id INTEGER,
                task_id TEXT UNIQUE NOT NULL,
                type TEXT NOT NULL,
                preset_id TEXT NOT NULL,
                model TEXT,
                duration INTEGER,
                aspect_ratio TEXT,
                prompt TEXT,
                cost INTEGER,
                request_data TEXT,
                status TEXT DEFAULT 'pending',
                result_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        # Migration: add columns if not exists
        try:
            await db.execute(
                "ALTER TABLE generation_tasks ADD COLUMN telegram_id INTEGER"
            )
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE generation_tasks ADD COLUMN model TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE generation_tasks ADD COLUMN duration INTEGER")
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE generation_tasks ADD COLUMN aspect_ratio TEXT"
            )
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE generation_tasks ADD COLUMN prompt TEXT")
        except aiosqlite.OperationalError:
            pass  # Column already exists
        try:
            await db.execute("ALTER TABLE generation_tasks ADD COLUMN cost INTEGER")
        except aiosqlite.OperationalError:
            pass  # Column already exists
        try:
            await db.execute(
                "ALTER TABLE generation_tasks ADD COLUMN request_data TEXT"
            )
        except aiosqlite.OperationalError:
            pass

        # Миграция: добавляем provider в transactions
        try:
            await db.execute(
                "ALTER TABLE transactions ADD COLUMN provider TEXT DEFAULT 'cryptobot'"
            )
        except aiosqlite.OperationalError:
            pass

        # Таблица истории генераций
        await db.execute("""
            CREATE TABLE IF NOT EXISTS generation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                preset_id TEXT NOT NULL,
                prompt TEXT,
                cost INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        # Таблица настроек пользователя
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                preferred_model TEXT DEFAULT 'flash',
                preferred_video_model TEXT DEFAULT 'v3_std',
                preferred_i2v_model TEXT DEFAULT 'v3_std',
                image_service TEXT DEFAULT 'nanobanana',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)

        # Referral system tables and migrations
        # Add columns to users if not exist
        try:
            await db.execute("ALTER TABLE users ADD COLUMN referral_code TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN referred_by INTEGER REFERENCES users(id)"
            )
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN referral_earned INTEGER DEFAULT 0"
            )
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN has_paid BOOLEAN DEFAULT FALSE"
            )
        except aiosqlite.OperationalError:
            pass

        try:
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code)"
            )
        except aiosqlite.OperationalError:
            pass

        # Referrals table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL,
                bonus_credits INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referrer_id) REFERENCES users(id),
                FOREIGN KEY (referred_id) REFERENCES users(id),
                UNIQUE(referrer_id, referred_id)
            )
        """)

        # Backfill missing referral codes for existing users later in get_or_create_user

        # Миграция: добавляем колонку image_service если её нет
        try:
            await db.execute(
                "ALTER TABLE user_settings ADD COLUMN image_service TEXT DEFAULT 'nanobanana'"
            )
        except aiosqlite.OperationalError:
            pass  # Колонка уже существует

        await db.execute("""
            CREATE TABLE IF NOT EXISTS partner_withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount_rub REAL NOT NULL,
                method TEXT NOT NULL,
                requisites TEXT,
                status TEXT DEFAULT 'requested',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        # Таблица batch_jobs
        await db.execute("""
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
        """)

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
            referral_code = (
                row["referral_code"] if "referral_code" in row.keys() else None
            )
            referred_by = row["referred_by"] if "referred_by" in row.keys() else None
            referral_earned = (
                row["referral_earned"] if "referral_earned" in row.keys() else 0
            )
            has_paid = bool(row["has_paid"]) if "has_paid" in row.keys() else False
            partner_agreed_at = (
                datetime.fromisoformat(row["partner_agreed_at"])
                if row["partner_agreed_at"] and "partner_agreed_at" in row.keys()
                else None
            )
            return User(
                id=row["id"],
                telegram_id=row["telegram_id"],
                credits=int(row["credits"] or 0),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                referral_code=referral_code,
                referred_by=referred_by,
                referral_earned=referral_earned or 0,
                has_paid=has_paid,
                partner_agreed_at=partner_agreed_at,
                partner_total_revenue_rub=(
                    float(row["partner_total_revenue_rub"] or 0)
                    if "partner_total_revenue_rub" in row.keys()
                    else 0.0
                ),
                partner_balance_rub=(
                    float(row["partner_balance_rub"] or 0)
                    if "partner_balance_rub" in row.keys()
                    else 0.0
                ),
                partner_withdrawn_rub=(
                    float(row["partner_withdrawn_rub"] or 0)
                    if "partner_withdrawn_rub" in row.keys()
                    else 0.0
                ),
                partner_tier=(
                    row["partner_tier"]
                    if "partner_tier" in row.keys() and row["partner_tier"]
                    else "basic"
                ),
            )

        # Создаём нового пользователя с бонусными кредитами
        # Используем INSERT OR IGNORE для защиты от race condition
        try:
            referral_code = await generate_referral_code(db)
            await db.execute(
                "INSERT INTO users (telegram_id, credits, referral_code) VALUES (?, 25, ?)",
                (telegram_id, referral_code),
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
        if not row:
            logger.error(f"Failed to fetch newly created user {telegram_id}")
            raise ValueError(f"User {telegram_id} not found after creation")

        referral_code = row["referral_code"] if "referral_code" in row.keys() else None
        referred_by = row["referred_by"] if "referred_by" in row.keys() else None
        referral_earned = (
            row["referral_earned"] if "referral_earned" in row.keys() else 0
        )
        has_paid = bool(row["has_paid"]) if "has_paid" in row.keys() else False
        partner_agreed_at = (
            datetime.fromisoformat(row["partner_agreed_at"])
            if row["partner_agreed_at"] and "partner_agreed_at" in row.keys()
            else None
        )
        return User(
            id=row["id"],
            telegram_id=row["telegram_id"],
            credits=int(row["credits"] or 0),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            referral_code=referral_code,
            referred_by=referred_by,
            referral_earned=referral_earned or 0,
            has_paid=has_paid,
            partner_agreed_at=partner_agreed_at,
            partner_total_revenue_rub=(
                float(row["partner_total_revenue_rub"] or 0)
                if "partner_total_revenue_rub" in row.keys()
                else 0.0
            ),
            partner_balance_rub=(
                float(row["partner_balance_rub"] or 0)
                if "partner_balance_rub" in row.keys()
                else 0.0
            ),
            partner_withdrawn_rub=(
                float(row["partner_withdrawn_rub"] or 0)
                if "partner_withdrawn_rub" in row.keys()
                else 0.0
            ),
            partner_tier=(
                row["partner_tier"]
                if "partner_tier" in row.keys() and row["partner_tier"]
                else "basic"
            ),
        )


async def get_master_partner_user() -> User:
    """Возвращает центрального партнёра, которому начисляются все реферальные бонусы."""
    master = await get_or_create_user(MASTER_PARTNER_TELEGRAM_ID)
    return master


async def generate_referral_code(db: Optional[aiosqlite.Connection] = None) -> str:
    """Генерирует уникальный реферальный код."""
    import secrets
    import string

    alphabet = string.ascii_uppercase + string.digits
    conn = db
    owns_connection = conn is None

    if owns_connection:
        conn = await aiosqlite.connect(DATABASE_PATH)

    assert conn is not None
    conn.row_factory = aiosqlite.Row

    try:
        for _ in range(20):
            code = "".join(secrets.choice(alphabet) for _ in range(8))
            cursor = await conn.execute(
                "SELECT 1 FROM users WHERE referral_code = ? LIMIT 1", (code,)
            )
            if not await cursor.fetchone():
                return code
        raise RuntimeError("Failed to generate unique referral code")
    finally:
        if owns_connection:
            await conn.close()


async def get_user_by_referral_code(referral_code: str) -> Optional[User]:
    """Получает пользователя по реферальному коду."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE referral_code = ?",
            (referral_code.strip().upper(),),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return User(
            id=row["id"],
            telegram_id=row["telegram_id"],
            credits=row["credits"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            referral_code=(
                row["referral_code"] if "referral_code" in row.keys() else None
            ),
            referred_by=row["referred_by"] if "referred_by" in row.keys() else None,
            referral_earned=(
                row["referral_earned"] if "referral_earned" in row.keys() else 0
            ),
            has_paid=bool(row["has_paid"]) if "has_paid" in row.keys() else False,
            partner_agreed_at=(
                datetime.fromisoformat(row["partner_agreed_at"])
                if row["partner_agreed_at"] and "partner_agreed_at" in row.keys()
                else None
            ),
            partner_total_revenue_rub=(
                float(row["partner_total_revenue_rub"] or 0)
                if "partner_total_revenue_rub" in row.keys()
                else 0.0
            ),
            partner_balance_rub=(
                float(row["partner_balance_rub"] or 0)
                if "partner_balance_rub" in row.keys()
                else 0.0
            ),
            partner_withdrawn_rub=(
                float(row["partner_withdrawn_rub"] or 0)
                if "partner_withdrawn_rub" in row.keys()
                else 0.0
            ),
            partner_tier=(
                row["partner_tier"]
                if "partner_tier" in row.keys() and row["partner_tier"]
                else "basic"
            ),
        )


async def update_user_referral_code(telegram_id: int, referral_code: str) -> bool:
    """Сохраняет реферальный код пользователя."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE users SET referral_code = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (referral_code, telegram_id),
        )
        await db.commit()
        return True


async def set_user_referrer(telegram_id: int, referrer_telegram_id: int) -> bool:
    """Привязывает пользователя к рефереру один раз."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        user_cursor = await db.execute(
            "SELECT id, referred_by FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        user_row = await user_cursor.fetchone()
        ref_cursor = await db.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (referrer_telegram_id,)
        )
        ref_row = await ref_cursor.fetchone()

        if not user_row or not ref_row:
            return False
        if user_row["referred_by"]:
            return False
        if user_row["id"] == ref_row["id"]:
            return False

        await db.execute(
            "UPDATE users SET referred_by = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (ref_row["id"], telegram_id),
        )
        await db.execute(
            "INSERT OR IGNORE INTO referrals (referrer_id, referred_id, bonus_credits) VALUES (?, ?, 0)",
            (ref_row["id"], user_row["id"]),
        )
        await db.commit()
        return True


async def process_referral(
    referred_telegram_id: int,
    referral_code: str,
    signup_bonus: int = 25,
    inviter_bonus: int = 5,
) -> bool:
    """Закрепляет пользователя за партнёром: новичку +25🍌, пригласившему +5🍌."""
    referral_code = (referral_code or "").strip().upper()
    if not referral_code:
        return False

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        referrer_cursor = await db.execute(
            "SELECT id FROM users WHERE referral_code = ?",
            (referral_code,),
        )
        referrer = await referrer_cursor.fetchone()
        if not referrer:
            return False

        referred_cursor = await db.execute(
            "SELECT id, referred_by FROM users WHERE telegram_id = ?",
            (referred_telegram_id,),
        )
        referred = await referred_cursor.fetchone()
        if not referred or referred["referred_by"]:
            return False
        if referred["id"] == referrer["id"]:
            return False

        await db.execute(
            "UPDATE users SET referred_by = ?, credits = credits + ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (referrer["id"], signup_bonus, referred_telegram_id),
        )
        await db.execute(
            "INSERT OR IGNORE INTO referrals (referrer_id, referred_id, bonus_credits) VALUES (?, ?, ?)",
            (referrer["id"], referred["id"], signup_bonus),
        )
        await db.execute(
            "UPDATE users SET credits = credits + ?, referral_earned = referral_earned + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (inviter_bonus, inviter_bonus, referrer["id"]),
        )
        await db.commit()
        return True


async def mark_user_paid(telegram_id: int) -> bool:
    """Помечает пользователя как оплатившего хотя бы один раз."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE users SET has_paid = 1, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (telegram_id,),
        )
        await db.commit()
        return True


async def credit_first_payment_referral_bonus(
    telegram_id: int,
    transaction_credits: int,
    transaction_amount_rub: Optional[float] = None,
    bonus_percent: int = 30,
) -> dict:
    """Начисляет 30% партнёру 1 уровня и 7% партнёру 2 уровня."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, referred_by, has_paid FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        user = await cursor.fetchone()
        if not user or not user["referred_by"] or user["has_paid"]:
            return {"mode": "none", "value": 0, "percent": 0}

        base_value = float(
            transaction_amount_rub
            if transaction_amount_rub is not None
            else transaction_credits
        )
        level1_bonus = round(base_value * 30 / 100.0, 2)
        level2_bonus = 0.0

        ref1_id = user["referred_by"]
        await db.execute(
            "UPDATE users SET partner_total_revenue_rub = partner_total_revenue_rub + ?, partner_balance_rub = partner_balance_rub + ?, partner_tier = 'basic', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (base_value, level1_bonus, ref1_id),
        )

        ref_cursor = await db.execute(
            "SELECT referred_by FROM users WHERE id = ?", (ref1_id,)
        )
        ref1 = await ref_cursor.fetchone()
        if ref1 and ref1["referred_by"]:
            ref2_id = ref1["referred_by"]
            level2_bonus = round(base_value * 7 / 100.0, 2)
            await db.execute(
                "UPDATE users SET partner_total_revenue_rub = partner_total_revenue_rub + ?, partner_balance_rub = partner_balance_rub + ?, partner_tier = 'basic', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (base_value, level2_bonus, ref2_id),
            )

        await db.execute(
            "UPDATE users SET has_paid = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (user["id"],),
        )
        await db.commit()
        return {
            "mode": "partner",
            "value": level1_bonus,
            "percent": 30,
            "level2_value": level2_bonus,
            "level2_percent": 7,
        }


def get_partner_percent_by_tier(tier: str) -> int:
    return 30


def get_partner_tier_by_total(total_revenue_rub: float) -> str:
    return "basic"


async def accept_partner_agreement(telegram_id: int) -> bool:
    """Подтверждает участие в партнёрской программе."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Read current referral-related fields to ensure we don't accidentally overwrite them
        cursor = await db.execute(
            "SELECT referral_code, referred_by, referral_earned, partner_agreed_at, partner_tier FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        before = await cursor.fetchone()

        await db.execute(
            "UPDATE users SET partner_agreed_at = CURRENT_TIMESTAMP, partner_tier = COALESCE(partner_tier, 'basic'), updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (telegram_id,),
        )
        await db.commit()

        # Read back and log unexpected changes
        cursor = await db.execute(
            "SELECT referral_code, referred_by, referral_earned, partner_agreed_at, partner_tier FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        after = await cursor.fetchone()

        try:
            # If any referral fields changed unexpectedly, log a warning for diagnostics
            if before and after:
                for field in ("referral_code", "referred_by", "referral_earned"):
                    if before[field] != after[field]:
                        logger.warning(
                            "accept_partner_agreement changed %s for %s: %s -> %s",
                            field,
                            telegram_id,
                            before[field],
                            after[field],
                        )
        except Exception:
            logger.exception(
                "Error while validating referral fields after accept_partner_agreement"
            )

        return True


async def get_partner_overview(telegram_id: int) -> dict:
    """Возвращает данные партнёрского кабинета."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Получаем пользователя, для которого запрошен обзор партнёрки
        # Если пользователь ещё не активировал партнёрку, возвращаем данные master-партнёра
        master_partner = await get_master_partner_user()
        if not master_partner.partner_agreed_at:
            await accept_partner_agreement(master_partner.telegram_id)
            master_partner = await get_master_partner_user()

        # Попытка получить целевого пользователя (тот, кто открыл экран партнёрки)
        requested_user = await get_or_create_user(telegram_id)

        # Если пользователь сам активировал партнёрку, показываем его статистику,
        # иначе показываем статистику master-партнёра (текущее поведение по умолчанию)
        target_user = requested_user
        target_user_id = target_user.id

        ref_cursor = await db.execute(
            "SELECT COUNT(*) as count FROM users WHERE referred_by = ?",
            (target_user_id,),
        )
        referrals_row = await ref_cursor.fetchone()

        pay_cursor = await db.execute(
            """
            SELECT COUNT(*) as count,
                   COALESCE(SUM(t.amount_rub), 0) as revenue,
                   COALESCE(SUM(CASE WHEN date(t.created_at) = date('now') THEN t.amount_rub ELSE 0 END), 0) as today_revenue,
                   COALESCE(SUM(CASE WHEN date(t.created_at) = date('now') THEN 1 ELSE 0 END), 0) as today_payments,
                   COALESCE(SUM(CASE WHEN date(t.created_at) >= date('now', '-7 day') THEN 1 ELSE 0 END), 0) as active_7d
            FROM transactions t
            JOIN users u ON u.id = t.user_id
            WHERE u.referred_by = ? AND t.status = 'completed'
            """,
            (target_user_id,),
        )
        pay_row = await pay_cursor.fetchone()

        level2_cursor = await db.execute(
            """
            SELECT COUNT(*) as count
            FROM users u2
            JOIN users u1 ON u2.referred_by = u1.id
            WHERE u1.referred_by = ?
            """,
            (target_user_id,),
        )
        level2_row = await level2_cursor.fetchone()

        withdrawal_cursor = await db.execute(
            "SELECT COALESCE(SUM(amount_rub), 0) as total FROM partner_withdrawals WHERE user_id = ? AND status = 'completed'",
            (target_user_id,),
        )
        withdrawal_row = await withdrawal_cursor.fetchone()

        # Используем значения целевого пользователя для вычисления уровня/процента
        tier = get_partner_tier_by_total(target_user.partner_total_revenue_rub or 0)
        percent = get_partner_percent_by_tier(tier)

        return {
            "is_partner": bool(target_user.partner_agreed_at),
            "partner_agreed_at": (
                target_user.partner_agreed_at.isoformat()
                if target_user.partner_agreed_at
                else None
            ),
            "referrals_count": referrals_row["count"] or 0,
            "level1_count": referrals_row["count"] or 0,
            "level2_count": level2_row["count"] or 0,
            "total_revenue_rub": round(target_user.partner_total_revenue_rub or 0, 2),
            "balance_rub": round(target_user.partner_balance_rub or 0, 2),
            "withdrawn_rub": round(withdrawal_row["total"] or 0, 2),
            "tier": tier,
            "percent": percent,
            "active_7d": pay_row["active_7d"] or 0,
            "total_payments": pay_row["count"] or 0,
            "monthly_revenue": round(pay_row["revenue"] or 0, 2),
            "today_payments": pay_row["today_payments"] or 0,
            "today_revenue": round(pay_row["today_revenue"] or 0, 2),
        }


async def create_partner_withdrawal(
    telegram_id: int, amount_rub: float, method: str, requisites: str
) -> bool:
    """Создаёт заявку на вывод партнёрского заработка."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        user = await get_master_partner_user()
        if not user.partner_agreed_at:
            await accept_partner_agreement(user.telegram_id)
            user = await get_master_partner_user()
        if not user.partner_agreed_at:
            return False
        if amount_rub > (user.partner_balance_rub or 0):
            return False

        await db.execute(
            "INSERT INTO partner_withdrawals (user_id, amount_rub, method, requisites, status) VALUES (?, ?, ?, ?, 'requested')",
            (user.id, amount_rub, method, requisites),
        )
        await db.execute(
            "UPDATE users SET partner_balance_rub = partner_balance_rub - ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (amount_rub, user.id),
        )
        await db.commit()
        return True


async def get_referral_stats(telegram_id: int) -> dict:
    """Возвращает статистику по рефералам пользователя."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        user = await get_or_create_user(telegram_id)

        cursor = await db.execute(
            "SELECT COUNT(*) as count, COALESCE(SUM(bonus_credits), 0) as total_bonus FROM referrals WHERE referrer_id = ?",
            (user.id,),
        )
        row = await cursor.fetchone()

        return {
            "referral_code": user.referral_code or "",
            "referrals_count": row["count"] or 0,
            "referral_earned": row["total_bonus"] or 0,
        }


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


async def deduct_credits(
    telegram_id: int, amount: int, check_balance: bool = True
) -> bool:
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
    provider: str,
    credits: int,
    amount_rub: float,
    status: str = "pending",
) -> bool:
    """Создаёт транзакцию платежа"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            await db.execute(
                """INSERT INTO transactions 
                   (order_id, user_id, payment_id, provider, credits, amount_rub, status) 
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (order_id, user_id, payment_id, provider, credits, amount_rub, status),
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
            provider=(
                row["provider"]
                if "provider" in row.keys() and row["provider"]
                else "cryptobot"
            ),
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


async def get_telegram_id_by_user_id(user_id: int) -> Optional[int]:
    """Получает telegram_id по внутреннему user_id"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT telegram_id FROM users WHERE id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return row["telegram_id"] if row else None


async def add_generation_task(
    user_id: int,
    telegram_id: int,
    task_id: str,
    type: str,
    preset_id: str,
    model: Optional[str] = None,
    duration: Optional[int] = None,
    aspect_ratio: Optional[str] = None,
    prompt: Optional[str] = None,
    cost: Optional[int] = None,
    request_data: Optional[dict | str] = None,
) -> bool:
    """Создаёт задачу генерации"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        serialized_request = (
            json.dumps(request_data, ensure_ascii=False)
            if isinstance(request_data, dict)
            else request_data
        )
        result = await db.execute(
            """INSERT OR IGNORE INTO generation_tasks 
               (user_id, telegram_id, task_id, type, preset_id, model, duration, aspect_ratio, prompt, cost, request_data, status) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (
                user_id,
                telegram_id,
                task_id,
                type,
                preset_id,
                model,
                duration,
                aspect_ratio,
                prompt,
                cost,
                serialized_request,
            ),
        )
        await db.commit()
        if result.rowcount > 0:
            logger.info(
                f"Added new generation task: {task_id} for telegram_id {telegram_id}"
            )
            return True
        else:
            logger.debug(f"Generation task already exists: {task_id}")
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
            model=row["model"],
            duration=row["duration"],
            aspect_ratio=row["aspect_ratio"],
            prompt=row["prompt"],
            cost=row["cost"],
            status=row["status"],
            telegram_id=row["telegram_id"],
            result_url=row["result_url"],
            request_data=row["request_data"] if "request_data" in row.keys() else None,
            created_at=datetime.fromisoformat(row["created_at"]),
        )


async def complete_video_task(task_id: str, result_url: str) -> bool:
    """Отмечает задачу как выполненную"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        final_status = "completed" if result_url else "failed"
        await db.execute(
            """UPDATE generation_tasks 
               SET status = ?, result_url = ?, completed_at = CURRENT_TIMESTAMP 
               WHERE task_id = ?""",
            (final_status, result_url, task_id),
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

        referral_stats = await get_referral_stats(telegram_id)

        return {
            "credits": user.credits,
            "generations": gen_row["count"] or 0,
            "total_spent": cost_row["total"] or 0,
            "member_since": user.created_at.strftime("%d.%m.%Y"),
            "referral_code": referral_stats["referral_code"],
            "referrals_count": referral_stats["referrals_count"],
            "referral_earned": referral_stats["referral_earned"],
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

        cursor = await db.execute("SELECT COUNT(*) as count FROM referrals")
        referrals_row = await cursor.fetchone()

        return {
            "total_users": users_row["count"] or 0,
            "total_generations": gen_row["count"] or 0,
            "total_revenue": trans_row["total"] or 0,
            "total_transactions": trans_row["count"] or 0,
            "total_batch_jobs": batch_row["count"] or 0,
            "total_referrals": referrals_row["count"] or 0,
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
            await db.execute("""
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
            """)

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


async def get_user_last_generation(user_id: int, limit: int = 1) -> Optional[dict]:
    """Получает последнюю(ие) генерацию(и) пользователя"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            """SELECT * FROM generation_tasks 
               WHERE user_id = ? 
               ORDER BY created_at DESC 
               LIMIT ?""",
            (user_id, limit),
        )
        rows = await cursor.fetchall()

        if not rows:
            return None

        if limit == 1:
            row = rows[0]
            return {
                "id": row["id"],
                "task_id": row["task_id"],
                "type": row["type"],
                "preset_id": row["preset_id"],
                "status": row["status"],
                "result_url": row["result_url"],
                "created_at": row["created_at"],
            }

        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "type": row["type"],
                "preset_id": row["preset_id"],
                "status": row["status"],
                "result_url": row["result_url"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


async def _ensure_user_settings_table(db):
    """Создает таблицу user_settings если она не существует (миграция)"""
    await db.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            preferred_model TEXT DEFAULT 'flash',
            preferred_video_model TEXT DEFAULT 'v3_std',
            preferred_i2v_model TEXT DEFAULT 'v3_std',
            image_service TEXT DEFAULT 'nanobanana',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)
    # Миграция: добавляем колонку image_service если её нет
    try:
        await db.execute(
            "ALTER TABLE user_settings ADD COLUMN image_service TEXT DEFAULT 'nanobanana'"
        )
    except aiosqlite.OperationalError:
        pass  # Колонка уже существует
    await db.commit()


async def get_user_settings(telegram_id: int) -> dict:
    """Получает настройки пользователя из БД"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Создаем таблицу если не существует
        await _ensure_user_settings_table(db)

        # Получаем внутренний user_id
        user = await get_or_create_user(telegram_id)

        cursor = await db.execute(
            """SELECT preferred_model, preferred_video_model, preferred_i2v_model, image_service 
               FROM user_settings WHERE user_id = ?""",
            (user.id,),
        )
        row = await cursor.fetchone()

        if row:
            return {
                "preferred_model": row["preferred_model"],
                "preferred_video_model": row["preferred_video_model"],
                "preferred_i2v_model": row["preferred_i2v_model"],
                "image_service": (
                    row["image_service"]
                    if "image_service" in row.keys()
                    else "nanobanana"
                ),
            }

        # Если настроек нет, возвращаем значения по умолчанию
        return {
            "preferred_model": "flash",
            "preferred_video_model": "v3_std",
            "preferred_i2v_model": "v3_std",
            "image_service": "nanobanana",
        }


async def save_user_settings(
    telegram_id: int,
    preferred_model: str = None,
    preferred_video_model: str = None,
    preferred_i2v_model: str = None,
    image_service: str = None,
) -> bool:
    """Сохраняет настройки пользователя в БД"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Создаем таблицу если не существует
        await _ensure_user_settings_table(db)

        # Получаем внутренний user_id
        user = await get_or_create_user(telegram_id)

        # Получаем текущие настройки
        cursor = await db.execute(
            "SELECT * FROM user_settings WHERE user_id = ?",
            (user.id,),
        )
        existing = await cursor.fetchone()

        if existing:
            # Обновляем только переданные значения
            updates = []
            params = []
            if preferred_model is not None:
                updates.append("preferred_model = ?")
                params.append(preferred_model)
            if preferred_video_model is not None:
                updates.append("preferred_video_model = ?")
                params.append(preferred_video_model)
            if preferred_i2v_model is not None:
                updates.append("preferred_i2v_model = ?")
                params.append(preferred_i2v_model)
            if image_service is not None:
                updates.append("image_service = ?")
                params.append(image_service)

            if updates:
                params.append(user.id)
                await db.execute(
                    f"""UPDATE user_settings 
                        SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP 
                        WHERE user_id = ?""",
                    params,
                )
                await db.commit()
                logger.info(f"Updated settings for user {telegram_id}")
        else:
            # Создаём новую запись с переданными значениями
            await db.execute(
                """INSERT INTO user_settings 
                   (user_id, preferred_model, preferred_video_model, preferred_i2v_model, image_service) 
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    user.id,
                    preferred_model or "flash",
                    preferred_video_model or "v3_std",
                    preferred_i2v_model or "v3_std",
                    image_service or "nanobanana",
                ),
            )
            await db.commit()
            logger.info(f"Created settings for user {telegram_id}")

        return True
