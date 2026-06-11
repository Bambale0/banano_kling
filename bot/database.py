import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

import aiosqlite

logger = logging.getLogger(__name__)

DATABASE_PATH = os.getenv("DATABASE_PATH", "bot.db")


def _get_master_partner_telegram_id() -> int:
    explicit = os.getenv("MASTER_PARTNER_TELEGRAM_ID", "").strip()
    if explicit:
        try:
            return int(explicit)
        except ValueError:
            logger.warning("Invalid MASTER_PARTNER_TELEGRAM_ID: %s", explicit)
    first_admin = (os.getenv("ADMIN_IDS", "").split(",")[0] or "").strip()
    if first_admin:
        try:
            return int(first_admin)
        except ValueError:
            logger.warning("Invalid first ADMIN_IDS value for master partner: %s", first_admin)
    return 0


MASTER_PARTNER_TELEGRAM_ID = _get_master_partner_telegram_id()
PARTNER_LEVEL_PERCENTS: tuple[int, ...] = (30, 10, 3)


async def _migrate_promo_redemptions_schema(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("PRAGMA table_info(promo_redemptions)")
    columns = [row[1] for row in await cursor.fetchall()]
    if not columns:
        return

    needs_rebuild = "order_id" not in columns
    cursor = await db.execute("PRAGMA index_list(promo_redemptions)")
    for index in await cursor.fetchall():
        index_name = index[1]
        is_unique = bool(index[2])
        if not is_unique:
            continue
        cursor = await db.execute(f"PRAGMA index_info({index_name})")
        index_columns = [row[2] for row in await cursor.fetchall()]
        if index_columns == ["promo_id", "user_id"]:
            needs_rebuild = True
            break

    if not needs_rebuild:
        return

    await db.execute("ALTER TABLE promo_redemptions RENAME TO promo_redemptions_old")
    await db.execute(
        """
        CREATE TABLE promo_redemptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            promo_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            telegram_id INTEGER NOT NULL,
            order_id TEXT,
            redeemed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (promo_id) REFERENCES promo_codes(id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(promo_id, order_id)
        )
    """
    )
    await db.execute(
        """
        INSERT INTO promo_redemptions (
            id, promo_id, user_id, telegram_id, redeemed_at
        )
        SELECT id, promo_id, user_id, telegram_id, redeemed_at
        FROM promo_redemptions_old
        """
    )
    await db.execute("DROP TABLE promo_redemptions_old")


async def _migrate_promo_codes_schema(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("PRAGMA table_info(promo_codes)")
    columns = {row[1] for row in await cursor.fetchall()}
    if not columns:
        return
    if "promo_type" not in columns:
        await db.execute(
            "ALTER TABLE promo_codes ADD COLUMN promo_type TEXT DEFAULT 'discount'"
        )
    if "reward_credits" not in columns:
        await db.execute(
            "ALTER TABLE promo_codes ADD COLUMN reward_credits INTEGER DEFAULT 0"
        )


@dataclass
class User:
    id: int
    telegram_id: int
    credits: int
    created_at: datetime
    updated_at: datetime
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    referral_code: Optional[str] = None
    referred_by: Optional[int] = None
    referral_earned: int = 0
    has_paid: bool = False
    partner_agreed_at: Optional[datetime] = None
    partner_total_revenue_rub: float = 0.0
    partner_balance_rub: float = 0.0
    partner_withdrawn_rub: float = 0.0
    partner_tier: str = "basic"
    is_banned: bool = False
    free_generations: int = 0


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
    promo_code: Optional[str] = None
    promo_discount_percent: int = 0
    original_amount_rub: Optional[float] = None


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
    reference_images: Optional[str] = None
    created_at: Optional[datetime] = None
    is_public_feed: bool = False
    likes_count: int = 0
    shares_count: int = 0
    source_feed_task_id: Optional[str] = None
    billing_source: str = "credits"
    subscription_usage_id: Optional[int] = None


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
        try:
            await db.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN free_generations INTEGER DEFAULT 0"
            )
        except aiosqlite.OperationalError:
            pass
        for column_name in ("username", "first_name", "last_name"):
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {column_name} TEXT")
            except aiosqlite.OperationalError:
                pass

        # Таблица транзакций (платежи)
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                payment_id TEXT,
                provider TEXT DEFAULT 'tbank',
                credits INTEGER NOT NULL,
                amount_rub REAL NOT NULL,
                original_amount_rub REAL,
                promo_code TEXT,
                promo_discount_percent INTEGER DEFAULT 0,
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
                telegram_id INTEGER,
                task_id TEXT UNIQUE NOT NULL,
                type TEXT NOT NULL,
                preset_id TEXT NOT NULL,
                model TEXT,
                duration INTEGER,
                aspect_ratio TEXT,
                prompt TEXT,
                cost INTEGER,
                status TEXT DEFAULT 'pending',
                result_url TEXT,
                reference_images TEXT,
                is_public_feed INTEGER DEFAULT 0,
                likes_count INTEGER DEFAULT 0,
                shares_count INTEGER DEFAULT 0,
                source_feed_task_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """
        )

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
                "ALTER TABLE generation_tasks ADD COLUMN reference_images TEXT"
            )
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE generation_tasks ADD COLUMN is_public_feed INTEGER DEFAULT 0"
            )
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE generation_tasks ADD COLUMN likes_count INTEGER DEFAULT 0"
            )
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE generation_tasks ADD COLUMN shares_count INTEGER DEFAULT 0"
            )
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE generation_tasks ADD COLUMN source_feed_task_id TEXT"
            )
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE generation_tasks ADD COLUMN billing_source TEXT DEFAULT 'credits'"
            )
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE generation_tasks ADD COLUMN subscription_usage_id INTEGER"
            )
        except aiosqlite.OperationalError:
            pass

        # Миграция: добавляем provider в transactions
        try:
            await db.execute(
                "ALTER TABLE transactions ADD COLUMN provider TEXT DEFAULT 'tbank'"
            )
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE transactions ADD COLUMN original_amount_rub REAL")
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE transactions ADD COLUMN promo_code TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE transactions ADD COLUMN promo_discount_percent INTEGER DEFAULT 0"
            )
        except aiosqlite.OperationalError:
            pass

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

        # Таблица настроек пользователя
        await db.execute(
            """
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
        """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS gpt55_conversations (
                user_id INTEGER PRIMARY KEY,
                messages_json TEXT NOT NULL DEFAULT '[]',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                credits INTEGER NOT NULL,
                promo_type TEXT NOT NULL DEFAULT 'discount',
                reward_credits INTEGER NOT NULL DEFAULT 0,
                discount_percent INTEGER NOT NULL DEFAULT 0,
                max_uses INTEGER NOT NULL DEFAULT 1,
                used_count INTEGER NOT NULL DEFAULT 0,
                expires_at TIMESTAMP,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        try:
            await db.execute(
                "ALTER TABLE promo_codes ADD COLUMN discount_percent INTEGER DEFAULT 0"
            )
        except aiosqlite.OperationalError:
            pass
        await _migrate_promo_codes_schema(db)
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS promo_redemptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                promo_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                telegram_id INTEGER NOT NULL,
                order_id TEXT,
                redeemed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (promo_id) REFERENCES promo_codes(id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(promo_id, order_id)
            )
        """
        )
        await _migrate_promo_redemptions_schema(db)

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

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
        await db.execute(
            """
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
        """
        )

        # Backfill missing referral codes for existing users later in get_or_create_user

        # Миграция: добавляем колонку image_service если её нет
        try:
            await db.execute(
                "ALTER TABLE user_settings ADD COLUMN image_service TEXT DEFAULT 'nanobanana'"
            )
        except aiosqlite.OperationalError:
            pass  # Колонка уже существует

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS partner_withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount_rub REAL NOT NULL,
                method TEXT NOT NULL,
                requisites TEXT,
                recipient_name TEXT,
                phone TEXT,
                card_mask TEXT,
                external_payment_id TEXT,
                external_contractor_id INTEGER,
                external_requisite_id INTEGER,
                external_status_id INTEGER,
                status_title TEXT,
                error_message TEXT,
                status TEXT DEFAULT 'requested',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """
        )
        for column_name, column_sql in (
            ("recipient_name", "TEXT"),
            ("phone", "TEXT"),
            ("card_mask", "TEXT"),
            ("external_payment_id", "TEXT"),
            ("external_contractor_id", "INTEGER"),
            ("external_requisite_id", "INTEGER"),
            ("external_status_id", "INTEGER"),
            ("status_title", "TEXT"),
            ("error_message", "TEXT"),
        ):
            try:
                await db.execute(
                    f"ALTER TABLE partner_withdrawals ADD COLUMN {column_name} {column_sql}"
                )
            except aiosqlite.OperationalError:
                pass

        # Таблица batch_jobs
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
            """
            CREATE TABLE IF NOT EXISTS credit_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                reason TEXT NOT NULL,
                external_id TEXT,
                metadata_json TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(reason, external_id)
            )
        """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_credit_transactions_user_id ON credit_transactions(user_id)"
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                package_id TEXT NOT NULL,
                package_name TEXT NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                image_limit INTEGER NOT NULL DEFAULT 0,
                video_limit INTEGER NOT NULL DEFAULT 0,
                includes_pro INTEGER NOT NULL DEFAULT 0,
                priority INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user_active ON user_subscriptions(user_id, status, expires_at)"
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS subscription_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                usage_type TEXT NOT NULL,
                model TEXT,
                external_id TEXT UNIQUE,
                metadata_json TEXT DEFAULT '{}',
                refunded INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                refunded_at TIMESTAMP,
                FOREIGN KEY (subscription_id) REFERENCES user_subscriptions(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_subscription_usage_subscription ON subscription_usage(subscription_id, usage_type, refunded)"
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS recurring_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                telegram_id INTEGER NOT NULL,
                provider TEXT NOT NULL DEFAULT 'tbank',
                package_id TEXT NOT NULL,
                package_name TEXT NOT NULL,
                amount_rub REAL NOT NULL,
                credits INTEGER NOT NULL DEFAULT 0,
                rebill_id TEXT,
                customer_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                next_charge_at TIMESTAMP,
                last_charge_at TIMESTAMP,
                last_order_id TEXT,
                last_error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_recurring_subscriptions_due ON recurring_subscriptions(status, next_charge_at)"
        )

        await db.commit()
        logger.info("Database initialized successfully")


async def get_or_create_user(
    telegram_id: int,
    *,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> User:
    """Получает или создаёт пользователя (thread-safe)"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Ищем пользователя
        cursor = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()

        if row:
            profile_updates = {
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
            }
            changed_fields = [
                key
                for key, value in profile_updates.items()
                if key in row.keys() and value is not None and row[key] != value
            ]
            if changed_fields:
                set_clause = ", ".join(f"{key} = ?" for key in changed_fields)
                values = [profile_updates[key] for key in changed_fields]
                await db.execute(
                    f"UPDATE users SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (*values, row["id"]),
                )
                await db.commit()
                cursor = await db.execute(
                    "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
                )
                row = await cursor.fetchone()

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
                username=row["username"] if "username" in row.keys() else None,
                first_name=row["first_name"] if "first_name" in row.keys() else None,
                last_name=row["last_name"] if "last_name" in row.keys() else None,
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
                is_banned=(
                    bool(row["is_banned"]) if "is_banned" in row.keys() else False
                ),
                free_generations=(
                    int(row["free_generations"] or 0)
                    if "free_generations" in row.keys()
                    else 0
                ),
            )

        # Создаём нового пользователя с бонусными BoomCoin
        # Используем INSERT OR IGNORE для защиты от race condition
        try:
            referral_code = await generate_referral_code(db)
            await db.execute(
                """
                INSERT INTO users (
                    telegram_id, credits, referral_code, username, first_name, last_name
                )
                VALUES (?, 10, ?, ?, ?, ?)
                """,
                (telegram_id, referral_code, username, first_name, last_name),
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
            username=row["username"] if "username" in row.keys() else None,
            first_name=row["first_name"] if "first_name" in row.keys() else None,
            last_name=row["last_name"] if "last_name" in row.keys() else None,
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
            is_banned=(
                bool(row["is_banned"]) if "is_banned" in row.keys() else False
            ),
            free_generations=(
                int(row["free_generations"] or 0)
                if "free_generations" in row.keys()
                else 0
            ),
        )


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
            is_banned=(
                bool(row["is_banned"]) if "is_banned" in row.keys() else False
            ),
            free_generations=(
                int(row["free_generations"] or 0)
                if "free_generations" in row.keys()
                else 0
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
    signup_bonus: int = 5,
) -> bool:
    """Обрабатывает реферальный переход и закрепляет пользователя за пригласившим."""
    referral_code = (referral_code or "").strip().upper()
    if not referral_code:
        return False

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        referrer_cursor = await db.execute(
            "SELECT id FROM users WHERE referral_code = ?", (referral_code,)
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
        if signup_bonus:
            await _record_credit_transaction(
                db,
                referred["id"],
                signup_bonus,
                "referral_signup_bonus",
                f"referral_signup:{referred_telegram_id}:{referrer['id']}",
                {"referrer_id": referrer["id"]},
            )
        await db.execute(
            "INSERT OR IGNORE INTO referrals (referrer_id, referred_id, bonus_credits) VALUES (?, ?, ?)",
            (referrer["id"], referred["id"], 0),
        )
        await db.commit()

        logger.info(
            "Referral processed: referred=%s, referrer_id=%s, signup_bonus=%s",
            referred_telegram_id,
            referrer["id"],
            signup_bonus,
        )
        return True


async def get_master_partner_user() -> User:
    """Return the configured master partner user, creating it if needed.

    Kept for backwards compatibility with referral/admin tests and older code.
    """
    return await get_or_create_user(MASTER_PARTNER_TELEGRAM_ID)


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
    bonus_percent: int = 10,
) -> dict:
    """Начисляет бонус по приглашённому пользователю за первую оплату."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, referred_by, has_paid FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        user = await cursor.fetchone()
        if not user or not user["referred_by"] or user["has_paid"]:
            return {"mode": "none", "value": 0, "percent": 0}

        chain: list[aiosqlite.Row] = []
        current_referrer_id = user["referred_by"]
        for _level in PARTNER_LEVEL_PERCENTS:
            ref_cursor = await db.execute(
                "SELECT id, telegram_id, referred_by, partner_agreed_at, partner_tier, partner_total_revenue_rub FROM users WHERE id = ?",
                (current_referrer_id,),
            )
            referrer = await ref_cursor.fetchone()
            if not referrer:
                break
            chain.append(referrer)
            current_referrer_id = referrer["referred_by"]
            if not current_referrer_id:
                break

        if not chain:
            return {"mode": "none", "value": 0, "percent": 0}

        result = {"mode": "none", "value": 0, "percent": 0}
        partner_results: list[dict] = []
        if chain[0]["partner_agreed_at"]:
            base_value = (
                float(transaction_amount_rub)
                if transaction_amount_rub is not None
                else float(transaction_credits)
            )
            for level, (referrer, percent) in enumerate(
                zip(chain, PARTNER_LEVEL_PERCENTS, strict=False),
                start=1,
            ):
                if not referrer["partner_agreed_at"]:
                    continue
                current_total = float(referrer["partner_total_revenue_rub"] or 0)
                bonus_rub = round(base_value * percent / 100.0, 2)
                next_total = current_total + (
                    float(transaction_amount_rub)
                    if transaction_amount_rub is not None
                    else 0.0
                )
                inserted_bonus = await _record_credit_transaction(
                    db,
                    referrer["id"],
                    int(round(bonus_rub * 100)),
                    "referral_first_payment_partner_bonus",
                    f"first_payment_partner:{telegram_id}:level{level}",
                    {
                        "referred_user_id": user["id"],
                        "transaction_amount_rub": transaction_amount_rub,
                        "bonus_rub": bonus_rub,
                        "percent": percent,
                        "level": level,
                    },
                )
                if inserted_bonus:
                    await db.execute(
                        "UPDATE users SET partner_total_revenue_rub = partner_total_revenue_rub + ?, partner_balance_rub = partner_balance_rub + ?, partner_tier = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (
                            float(transaction_amount_rub or 0),
                            bonus_rub,
                            get_partner_tier_by_total(next_total),
                            referrer["id"],
                        ),
                    )
                    partner_results.append(
                        {
                            "telegram_id": referrer["telegram_id"],
                            "level": level,
                            "value": bonus_rub,
                            "percent": percent,
                        }
                    )
            if partner_results:
                result = {
                    "mode": "partner",
                    "value": round(sum(item["value"] for item in partner_results), 2),
                    "percent": PARTNER_LEVEL_PERCENTS[0],
                    "levels": partner_results,
                }
        else:
            banana_bonus = max(
                1, round(float(transaction_credits) * bonus_percent / 100)
            )
            inserted_bonus = await _record_credit_transaction(
                db,
                chain[0]["id"],
                banana_bonus,
                "referral_first_payment_bonus",
                f"first_payment:{telegram_id}",
                {"referred_user_id": user["id"], "transaction_credits": transaction_credits},
            )
            if inserted_bonus:
                await db.execute(
                    "UPDATE users SET credits = credits + ?, referral_earned = referral_earned + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (banana_bonus, banana_bonus, chain[0]["id"]),
                )
                await db.execute(
                    "UPDATE referrals SET bonus_credits = bonus_credits + ? WHERE referrer_id = ? AND referred_id = ?",
                    (banana_bonus, chain[0]["id"], user["id"]),
                )
            result = {"mode": "banana", "value": banana_bonus, "percent": bonus_percent}

        await db.execute(
            "UPDATE users SET has_paid = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (user["id"],),
        )
        await db.commit()
        return result


def get_partner_percent_by_tier(tier: str) -> int:
    """Процент партнёрского вознаграждения по текущему уровню."""
    return PARTNER_LEVEL_PERCENTS[0]


def get_partner_percent_by_total(total_revenue_rub: float) -> int:
    """Процент партнёрского вознаграждения по обороту рефералов."""
    return PARTNER_LEVEL_PERCENTS[0]


def get_partner_tier_by_total(total_revenue_rub: float) -> str:
    """Возвращает уровень партнёра по обороту рефералов."""
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
        requested_user = await get_or_create_user(telegram_id)
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

        withdrawal_cursor = await db.execute(
            "SELECT COALESCE(SUM(amount_rub), 0) as total FROM partner_withdrawals WHERE user_id = ? AND status = 'completed'",
            (target_user_id,),
        )
        withdrawal_row = await withdrawal_cursor.fetchone()

        # Используем значения целевого пользователя для вычисления уровня/процента
        tier = get_partner_tier_by_total(target_user.partner_total_revenue_rub or 0)
        percent = get_partner_percent_by_total(target_user.partner_total_revenue_rub or 0)

        return {
            "is_partner": bool(target_user.partner_agreed_at),
            "partner_agreed_at": (
                target_user.partner_agreed_at.isoformat()
                if target_user.partner_agreed_at
                else None
            ),
            "referrals_count": referrals_row["count"] or 0,
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


async def get_admin_partner_summaries(limit: int = 10) -> list[dict]:
    """Return partner metrics for the admin dashboard."""
    limit = max(1, min(int(limit or 10), 50))
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                u.id,
                u.telegram_id,
                u.username,
                u.first_name,
                u.last_name,
                u.referral_code,
                u.partner_agreed_at,
                u.partner_total_revenue_rub,
                u.partner_balance_rub,
                u.partner_tier,
                COUNT(DISTINCT referred.id) AS users_count,
                COUNT(DISTINCT CASE WHEN t.status = 'completed' THEN t.id END) AS payments_count,
                COALESCE(SUM(CASE WHEN t.status = 'completed' THEN t.amount_rub ELSE 0 END), 0) AS revenue_rub,
                COALESCE(SUM(CASE WHEN t.status = 'completed' AND date(t.created_at) = date('now') THEN 1 ELSE 0 END), 0) AS today_payments,
                COALESCE(SUM(CASE WHEN t.status = 'completed' AND date(t.created_at) = date('now') THEN t.amount_rub ELSE 0 END), 0) AS today_revenue_rub,
                COALESCE(w.withdrawn_rub, 0) AS withdrawn_rub
            FROM users u
            LEFT JOIN users referred ON referred.referred_by = u.id
            LEFT JOIN transactions t ON t.user_id = referred.id
            LEFT JOIN (
                SELECT user_id, SUM(amount_rub) AS withdrawn_rub
                FROM partner_withdrawals
                WHERE status = 'completed'
                GROUP BY user_id
            ) w ON w.user_id = u.id
            WHERE u.partner_agreed_at IS NOT NULL
            GROUP BY u.id
            ORDER BY revenue_rub DESC, users_count DESC, u.partner_agreed_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()

    summaries: list[dict] = []
    for row in rows:
        stored_revenue = float(row["partner_total_revenue_rub"] or 0)
        actual_revenue = float(row["revenue_rub"] or 0)
        total_revenue = round(max(stored_revenue, actual_revenue), 2)
        balance_rub = round(float(row["partner_balance_rub"] or 0), 2)
        withdrawn_rub = round(float(row["withdrawn_rub"] or 0), 2)
        summaries.append(
            {
                "telegram_id": row["telegram_id"],
                "username": row["username"],
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "referral_code": row["referral_code"] or "",
                "partner_agreed_at": row["partner_agreed_at"],
                "users_count": row["users_count"] or 0,
                "payments_count": row["payments_count"] or 0,
                "revenue_rub": total_revenue,
                "commission_rub": round(balance_rub + withdrawn_rub, 2),
                "balance_rub": balance_rub,
                "withdrawn_rub": withdrawn_rub,
                "tier": get_partner_tier_by_total(total_revenue),
                "percent": get_partner_percent_by_total(total_revenue),
                "today_payments": row["today_payments"] or 0,
                "today_revenue_rub": round(float(row["today_revenue_rub"] or 0), 2),
            }
        )
    return summaries


async def create_partner_withdrawal(
    telegram_id: int,
    amount_rub: float,
    method: str,
    requisites: str,
    recipient_name: str | None = None,
    phone: str | None = None,
    card_mask: str | None = None,
    external_payment_id: str | None = None,
    external_contractor_id: int | None = None,
    external_requisite_id: int | None = None,
    external_status_id: int | None = None,
    status_title: str | None = None,
    error_message: str | None = None,
    status: str = "requested",
) -> int | None:
    """Создаёт запись о выводе партнёрского заработка."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        user = await get_or_create_user(telegram_id)
        if not user.partner_agreed_at:
            return None
        if amount_rub <= 0:
            return None

        try:
            balance_update = await db.execute(
                """
                UPDATE users
                SET partner_balance_rub = partner_balance_rub - ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND partner_balance_rub >= ?
                """,
                (amount_rub, user.id, amount_rub),
            )
            if balance_update.rowcount != 1:
                await db.rollback()
                return None

            cursor = await db.execute(
                """
                INSERT INTO partner_withdrawals (
                    user_id, amount_rub, method, requisites, recipient_name, phone,
                    card_mask, external_payment_id, external_contractor_id,
                    external_requisite_id, external_status_id, status_title,
                    error_message, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user.id,
                    amount_rub,
                    method,
                    requisites,
                    recipient_name,
                    phone,
                    card_mask,
                    external_payment_id,
                    external_contractor_id,
                    external_requisite_id,
                    external_status_id,
                    status_title,
                    error_message,
                    status,
                ),
            )
            await db.commit()
            return cursor.lastrowid
        except Exception:
            await db.rollback()
            raise


async def convert_partner_balance_to_credits(
    telegram_id: int,
    credits: int,
    rub_per_credit: int,
) -> dict | None:
    """Переводит партнёрский рублёвый баланс в BoomCoin."""
    if credits <= 0 or rub_per_credit <= 0:
        return None

    amount_rub = round(float(credits * rub_per_credit), 2)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, partner_agreed_at, partner_balance_rub
            FROM users
            WHERE telegram_id = ?
            """,
            (telegram_id,),
        )
        user = await cursor.fetchone()
        if not user:
            await get_or_create_user(telegram_id)
            cursor = await db.execute(
                """
                SELECT id, partner_agreed_at, partner_balance_rub
                FROM users
                WHERE telegram_id = ?
                """,
                (telegram_id,),
            )
            user = await cursor.fetchone()

        if not user or not user["partner_agreed_at"]:
            return None

        try:
            balance_update = await db.execute(
                """
                UPDATE users
                SET partner_balance_rub = partner_balance_rub - ?,
                    credits = credits + ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND partner_balance_rub >= ?
                """,
                (amount_rub, credits, user["id"], amount_rub),
            )
            if balance_update.rowcount != 1:
                await db.rollback()
                return None

            await _record_credit_transaction(
                db,
                user["id"],
                credits,
                "partner_balance_conversion",
                None,
                {"amount_rub": amount_rub, "rub_per_credit": rub_per_credit},
            )
            await db.commit()
            return {"credits": credits, "amount_rub": amount_rub}
        except Exception:
            await db.rollback()
            raise


async def update_partner_withdrawal_status(
    withdrawal_id: int,
    *,
    status: str,
    status_title: str | None = None,
    external_status_id: int | None = None,
    error_message: str | None = None,
) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT user_id, amount_rub, status FROM partner_withdrawals WHERE id = ?",
            (withdrawal_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return False

        await db.execute(
            """
            UPDATE partner_withdrawals
            SET status = ?, status_title = COALESCE(?, status_title),
                external_status_id = COALESCE(?, external_status_id),
                error_message = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, status_title, external_status_id, error_message, withdrawal_id),
        )

        if status == "completed" and row["status"] != "completed":
            await db.execute(
                "UPDATE users SET partner_withdrawn_rub = partner_withdrawn_rub + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (row["amount_rub"], row["user_id"]),
            )
        if status in {"failed", "cancelled"} and row["status"] not in {
            "failed",
            "cancelled",
        }:
            await db.execute(
                "UPDATE users SET partner_balance_rub = partner_balance_rub + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (row["amount_rub"], row["user_id"]),
            )

        await db.commit()
        return True


async def get_recent_partner_withdrawals(
    telegram_id: int, limit: int = 5
) -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        user = await get_or_create_user(telegram_id)
        cursor = await db.execute(
            """
            SELECT id, amount_rub, method, requisites, recipient_name, phone, card_mask,
                   external_payment_id, external_status_id, status_title, error_message,
                   status, created_at, updated_at
            FROM partner_withdrawals
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user.id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


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
    """Получает баланс BoomCoin пользователя"""
    user = await get_or_create_user(telegram_id)
    return user.credits


async def _record_credit_transaction(
    db: aiosqlite.Connection,
    user_id: int,
    amount: int,
    reason: str,
    external_id: str | None = None,
    metadata: dict | None = None,
) -> bool:
    try:
        await db.execute(
            """
            INSERT INTO credit_transactions (user_id, amount, reason, external_id, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, amount, reason, external_id, json.dumps(metadata or {}, ensure_ascii=False)),
        )
        return True
    except aiosqlite.IntegrityError:
        return False


async def add_credits(
    telegram_id: int,
    amount: int,
    reason: str = "manual_add",
    external_id: str | None = None,
    metadata: dict | None = None,
) -> bool:
    """Добавляет BoomCoin пользователю и пишет audit ledger entry."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        user = await cursor.fetchone()
        if not user:
            await get_or_create_user(telegram_id)
            cursor = await db.execute(
                "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
            )
            user = await cursor.fetchone()
        if external_id:
            inserted = await _record_credit_transaction(db, user["id"], amount, reason, external_id, metadata)
            if not inserted:
                await db.rollback()
                logger.info("Skipped duplicate credit add reason=%s external_id=%s", reason, external_id)
                return False
        await db.execute(
            "UPDATE users SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (amount, telegram_id),
        )
        if not external_id:
            await _record_credit_transaction(db, user["id"], amount, reason, external_id, metadata)
        await db.commit()
        logger.info(f"Added {amount} credits to user {telegram_id}")
        return True


async def add_credits_once(
    telegram_id: int,
    amount: int,
    reason: str,
    external_id: str,
    metadata: dict | None = None,
) -> bool:
    """Idempotently add credits once for a reason/external id pair."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        user = await cursor.fetchone()
        if not user:
            await get_or_create_user(telegram_id)
            cursor = await db.execute(
                "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
            )
            user = await cursor.fetchone()
        inserted = await _record_credit_transaction(db, user["id"], amount, reason, external_id, metadata)
        if not inserted:
            await db.rollback()
            logger.info("Skipped duplicate credit transaction reason=%s external_id=%s", reason, external_id)
            return False
        await db.execute(
            "UPDATE users SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (amount, telegram_id),
        )
        await db.commit()
        logger.info("Idempotently added %s credits to user %s (%s/%s)", amount, telegram_id, reason, external_id)
        return True


PROMO_CODE_TRANSLATION = str.maketrans(
    {
        "А": "A",
        "Б": "B",
        "В": "V",
        "Г": "G",
        "Д": "D",
        "Е": "E",
        "Ё": "E",
        "Ж": "ZH",
        "З": "Z",
        "И": "I",
        "Й": "Y",
        "К": "K",
        "Л": "L",
        "М": "M",
        "Н": "N",
        "О": "O",
        "П": "P",
        "Р": "R",
        "С": "S",
        "Т": "T",
        "У": "U",
        "Ф": "F",
        "Х": "H",
        "Ц": "TS",
        "Ч": "CH",
        "Ш": "SH",
        "Щ": "SCH",
        "Ъ": "",
        "Ы": "Y",
        "Ь": "",
        "Э": "E",
        "Ю": "YU",
        "Я": "YA",
    }
)


def normalize_promo_code(code: str) -> str:
    normalized = (code or "").upper().translate(PROMO_CODE_TRANSLATION)
    return re.sub(r"[^A-Z0-9_-]", "", normalized)


async def create_promo_code(
    code: str,
    discount_percent: int,
    max_uses: int,
    expires_at: str | None,
    created_by: int,
    promo_type: str = "discount",
    reward_credits: int = 0,
) -> tuple[bool, str]:
    normalized = normalize_promo_code(code)
    if not normalized:
        return False, "empty_code"
    promo_type = (promo_type or "discount").strip().lower()
    if promo_type in {"generation", "free_generation", "generations"}:
        promo_type = "generation"
    if promo_type not in {"discount", "bananas", "generation"}:
        return False, "bad_type"
    if promo_type == "discount" and (discount_percent <= 0 or discount_percent >= 100):
        return False, "bad_discount"
    if promo_type in {"bananas", "generation"} and reward_credits <= 0:
        return False, "bad_reward"
    if max_uses <= 0:
        return False, "bad_max_uses"

    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            await db.execute(
                """
                INSERT INTO promo_codes (
                    code, credits, promo_type, reward_credits, discount_percent,
                    max_uses, expires_at, created_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized,
                    reward_credits if promo_type in {"bananas", "generation"} else discount_percent,
                    promo_type,
                    reward_credits if promo_type in {"bananas", "generation"} else 0,
                    discount_percent,
                    max_uses,
                    expires_at,
                    created_by,
                ),
            )
            await db.commit()
            return True, normalized
        except aiosqlite.IntegrityError:
            return False, "exists"


async def get_promo_codes(limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                code,
                COALESCE(promo_type, 'discount') AS promo_type,
                COALESCE(reward_credits, 0) AS reward_credits,
                COALESCE(NULLIF(discount_percent, 0), credits) AS discount_percent,
                max_uses,
                used_count,
                expires_at,
                is_active,
                created_at
            FROM promo_codes
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def validate_promo_code(telegram_id: int, code: str) -> tuple[bool, str, dict]:
    normalized = normalize_promo_code(code)
    if not normalized:
        return False, "empty", {}

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                *,
                COALESCE(promo_type, 'discount') AS effective_type,
                COALESCE(reward_credits, 0) AS effective_reward,
                COALESCE(NULLIF(discount_percent, 0), credits) AS effective_discount
            FROM promo_codes
            WHERE code = ? AND is_active = 1
            """,
            (normalized,),
        )
        promo = await cursor.fetchone()
        if not promo:
            return False, "not_found", {}

        if promo["expires_at"]:
            cursor = await db.execute(
                "SELECT CURRENT_TIMESTAMP > ? AS expired", (promo["expires_at"],)
            )
            expired = await cursor.fetchone()
            if expired and expired["expired"]:
                return False, "expired", {}

        if int(promo["used_count"]) >= int(promo["max_uses"]):
            return False, "used_up", {}

        promo_type = promo["effective_type"] or "discount"
        discount = int(promo["effective_discount"] or 0)
        reward_credits = int(promo["effective_reward"] or 0)
        if promo_type in {"bananas", "generation"}:
            if reward_credits <= 0:
                return False, "bad_reward", {}
        elif discount <= 0 or discount >= 100:
            return False, "bad_discount", {}
        return (
            True,
            "ok",
            {
                "code": normalized,
                "promo_type": promo_type,
                "reward_credits": reward_credits,
                "discount_percent": discount,
                "max_uses": int(promo["max_uses"]),
                "used_count": int(promo["used_count"]),
                "expires_at": promo["expires_at"],
            },
        )


async def mark_promo_code_used(
    telegram_id: int,
    code: str,
    order_id: str | None = None,
) -> tuple[bool, str]:
    normalized = normalize_promo_code(code)
    if not normalized:
        return False, "empty"

    user = await get_or_create_user(telegram_id)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute(
            """
            SELECT *
            FROM promo_codes
            WHERE code = ? AND is_active = 1
            """,
            (normalized,),
        )
        promo = await cursor.fetchone()
        if not promo:
            await db.rollback()
            return False, "not_found"
        if promo["expires_at"]:
            cursor = await db.execute(
                "SELECT CURRENT_TIMESTAMP > ? AS expired", (promo["expires_at"],)
            )
            expired = await cursor.fetchone()
            if expired and expired["expired"]:
                await db.rollback()
                return False, "expired"
        if int(promo["used_count"]) >= int(promo["max_uses"]):
            await db.rollback()
            return False, "used_up"
        try:
            await db.execute(
                """
                INSERT INTO promo_redemptions (promo_id, user_id, telegram_id, order_id)
                VALUES (?, ?, ?, ?)
                """,
                (promo["id"], user.id, telegram_id, order_id),
            )
            await db.execute(
                """
                UPDATE promo_codes
                SET used_count = used_count + 1
                WHERE id = ?
                """,
                (promo["id"],),
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            await db.rollback()
            return False, "already_used"
        logger.info("Promo %s marked used by user %s", normalized, telegram_id)
        return True, "ok"


async def deactivate_promo_code(code: str) -> bool:
    normalized = normalize_promo_code(code)
    if not normalized:
        return False
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "UPDATE promo_codes SET is_active = 0 WHERE code = ? AND is_active = 1",
            (normalized,),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_user_promo_redemptions(telegram_id: int) -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT pc.code,
                   COALESCE(pc.promo_type, 'discount') AS promo_type,
                   COALESCE(pc.reward_credits, 0) AS reward_credits,
                   COALESCE(NULLIF(pc.discount_percent, 0), pc.credits) AS discount_percent,
                   pr.redeemed_at
            FROM promo_redemptions pr
            JOIN promo_codes pc ON pc.id = pr.promo_id
            WHERE pr.telegram_id = ?
            ORDER BY pr.id DESC
            LIMIT 10
            """,
            (telegram_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]


async def set_user_banned(telegram_id: int, is_banned: bool) -> bool:
    await get_or_create_user(telegram_id)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "UPDATE users SET is_banned = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (1 if is_banned else 0, telegram_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def is_user_banned(telegram_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT is_banned FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()
        return bool(row and row[0])


async def set_bot_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT INTO bot_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """,
            (key, value),
        )
        await db.commit()


async def get_bot_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return str(row[0]) if row else default


async def is_maintenance_mode() -> bool:
    return (await get_bot_setting("maintenance_mode", "0")) == "1"


async def export_users() -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT telegram_id, credits, is_banned, has_paid, referral_code,
                   referral_earned, created_at, updated_at
            FROM users
            ORDER BY id ASC
            """
        )
        return [dict(row) for row in await cursor.fetchall()]


async def get_credit_transactions(telegram_id: int) -> list[dict]:
    """Return credit ledger entries for a Telegram user."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT ct.*
            FROM credit_transactions ct
            JOIN users u ON u.id = ct.user_id
            WHERE u.telegram_id = ?
            ORDER BY ct.id ASC
            """,
            (telegram_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]


async def deduct_credits(
    telegram_id: int,
    amount: int,
    check_balance: bool = True,
    reason: str = "generation_charge",
    external_id: str | None = None,
    metadata: dict | None = None,
) -> bool:
    """Списывает BoomCoin с проверкой баланса"""
    from bot.config import config

    # Админы не платят
    if config.is_admin(telegram_id):
        logger.info(f"Admin {telegram_id} - free access (skipped {amount} credits)")
        return True

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        if amount < 0:
            return False

        user_cursor = await db.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        user_row = await user_cursor.fetchone()
        if not user_row:
            return False

        if external_id and user_row:
            inserted = await _record_credit_transaction(db, user_row["id"], -amount, reason, external_id, metadata)
            if not inserted:
                await db.rollback()
                logger.info("Skipped duplicate credit deduction reason=%s external_id=%s", reason, external_id)
                return False

        update = await db.execute(
            """
            UPDATE users
            SET credits = credits - ?, updated_at = CURRENT_TIMESTAMP
            WHERE telegram_id = ? AND (? = 0 OR credits >= ?)
            """,
            (amount, telegram_id, 1 if check_balance else 0, amount),
        )
        if update.rowcount != 1:
            await db.rollback()
            return False

        if user_row and not external_id:
            await _record_credit_transaction(db, user_row["id"], -amount, reason, external_id, metadata)
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


async def activate_user_subscription(
    telegram_id: int,
    *,
    package_id: str,
    package_name: str,
    days: int,
    image_limit: int,
    video_limit: int = 0,
    includes_pro: bool = False,
    priority: bool = False,
) -> dict:
    """Activates a paid subscription and returns the stored subscription."""
    if days <= 0 or (image_limit <= 0 and video_limit <= 0):
        raise ValueError("subscription days and at least one usage limit must be positive")

    user = await get_or_create_user(telegram_id)
    expires_at = datetime.utcnow() + timedelta(days=days)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """
            UPDATE user_subscriptions
            SET status = 'replaced'
            WHERE user_id = ? AND status = 'active' AND datetime(expires_at) > datetime('now')
            """,
            (user.id,),
        )
        cursor = await db.execute(
            """
            INSERT INTO user_subscriptions (
                user_id, package_id, package_name, expires_at, image_limit,
                video_limit, includes_pro, priority, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            (
                user.id,
                package_id,
                package_name,
                expires_at.isoformat(timespec="seconds"),
                int(image_limit),
                int(video_limit or 0),
                1 if includes_pro else 0,
                1 if priority else 0,
            ),
        )
        subscription_id = cursor.lastrowid
        await db.commit()

        cursor = await db.execute(
            "SELECT * FROM user_subscriptions WHERE id = ?", (subscription_id,)
        )
        return dict(await cursor.fetchone())


async def get_active_subscription(telegram_id: int) -> dict | None:
    user = await get_or_create_user(telegram_id)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                s.*,
                COALESCE(SUM(CASE WHEN u.usage_type = 'image' AND u.refunded = 0 THEN 1 ELSE 0 END), 0) AS images_used,
                COALESCE(SUM(CASE WHEN u.usage_type = 'video' AND u.refunded = 0 THEN 1 ELSE 0 END), 0) AS videos_used
            FROM user_subscriptions s
            LEFT JOIN subscription_usage u ON u.subscription_id = s.id
            WHERE s.user_id = ?
              AND s.status = 'active'
              AND datetime(s.expires_at) > datetime('now')
            GROUP BY s.id
            ORDER BY datetime(s.expires_at) DESC, s.id DESC
            LIMIT 1
            """,
            (user.id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def consume_subscription_usage(
    telegram_id: int,
    *,
    usage_type: str,
    model: str,
    external_id: str,
    requires_pro: bool = False,
    metadata: dict | None = None,
) -> tuple[bool, str, dict | None]:
    """Consumes one subscription slot if the active subscription covers it."""
    if usage_type not in {"image", "video"}:
        return False, "unsupported_usage_type", None

    user = await get_or_create_user(telegram_id)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        try:
            await db.execute("BEGIN IMMEDIATE")

            cursor = await db.execute(
                """
                SELECT u.id, u.subscription_id, s.package_name
                FROM subscription_usage u
                JOIN user_subscriptions s ON s.id = u.subscription_id
                WHERE u.external_id = ? AND u.refunded = 0
                """,
                (external_id,),
            )
            existing = await cursor.fetchone()
            if existing:
                await db.commit()
                return True, "already_consumed", dict(existing)

            cursor = await db.execute(
                """
                SELECT *
                FROM user_subscriptions
                WHERE user_id = ?
                  AND status = 'active'
                  AND datetime(expires_at) > datetime('now')
                ORDER BY datetime(expires_at) DESC, id DESC
                LIMIT 1
                """,
                (user.id,),
            )
            subscription = await cursor.fetchone()
            if not subscription:
                await db.rollback()
                return False, "no_active_subscription", None
            if requires_pro and not bool(subscription["includes_pro"]):
                await db.rollback()
                return False, "pro_not_included", dict(subscription)

            limit_column = "image_limit" if usage_type == "image" else "video_limit"
            cursor = await db.execute(
                """
                SELECT COUNT(*) AS used
                FROM subscription_usage
                WHERE subscription_id = ?
                  AND usage_type = ?
                  AND refunded = 0
                """,
                (subscription["id"], usage_type),
            )
            used = int((await cursor.fetchone())["used"] or 0)
            limit = int(subscription[limit_column] or 0)
            if limit <= 0 or used >= limit:
                await db.rollback()
                return False, "limit_exhausted", dict(subscription)

            cursor = await db.execute(
                """
                INSERT INTO subscription_usage (
                    subscription_id, user_id, usage_type, model, external_id, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    subscription["id"],
                    user.id,
                    usage_type,
                    model,
                    external_id,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            usage = {
                "id": cursor.lastrowid,
                "subscription_id": subscription["id"],
                "package_name": subscription["package_name"],
                "used": used + 1,
                "limit": limit,
            }
            await db.commit()
            return True, "ok", usage
        except aiosqlite.IntegrityError:
            await db.rollback()
            return False, "duplicate_external_id", None
        except Exception:
            await db.rollback()
            raise


async def refund_subscription_usage(usage_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE subscription_usage
            SET refunded = 1, refunded_at = CURRENT_TIMESTAMP
            WHERE id = ? AND refunded = 0
            """,
            (usage_id,),
        )
        await db.commit()
        return cursor.rowcount == 1


async def upsert_recurring_subscription(
    telegram_id: int,
    *,
    provider: str,
    package_id: str,
    package_name: str,
    amount_rub: float,
    credits: int,
    customer_key: str,
    rebill_id: str | None = None,
    status: str = "pending",
    next_charge_at: str | None = None,
) -> dict:
    user = await get_or_create_user(telegram_id)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """
            INSERT INTO recurring_subscriptions (
                user_id, telegram_id, provider, package_id, package_name,
                amount_rub, credits, customer_key, rebill_id, status,
                next_charge_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                telegram_id = excluded.telegram_id,
                provider = excluded.provider,
                package_id = excluded.package_id,
                package_name = excluded.package_name,
                amount_rub = excluded.amount_rub,
                credits = excluded.credits,
                customer_key = excluded.customer_key,
                rebill_id = COALESCE(excluded.rebill_id, recurring_subscriptions.rebill_id),
                status = excluded.status,
                next_charge_at = excluded.next_charge_at,
                last_error = NULL,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                user.id,
                telegram_id,
                provider,
                package_id,
                package_name,
                float(amount_rub),
                int(credits),
                customer_key,
                rebill_id,
                status,
                next_charge_at,
            ),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM recurring_subscriptions WHERE user_id = ?", (user.id,)
        )
        return dict(await cursor.fetchone())


async def confirm_recurring_subscription(
    telegram_id: int,
    *,
    rebill_id: str,
    next_charge_at: str,
    last_order_id: str | None = None,
) -> bool:
    user = await get_or_create_user(telegram_id)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE recurring_subscriptions
            SET rebill_id = ?,
                status = 'active',
                next_charge_at = ?,
                last_order_id = COALESCE(?, last_order_id),
                last_error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (rebill_id, next_charge_at, last_order_id, user.id),
        )
        await db.commit()
        return cursor.rowcount == 1


async def disable_recurring_subscription(
    telegram_id: int,
    *,
    reason: str = "user_disabled",
) -> bool:
    user = await get_or_create_user(telegram_id)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE recurring_subscriptions
            SET status = 'disabled',
                last_error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND status != 'disabled'
            """,
            (reason, user.id),
        )
        await db.commit()
        return cursor.rowcount == 1


async def get_recurring_subscription(telegram_id: int) -> dict | None:
    user = await get_or_create_user(telegram_id)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM recurring_subscriptions WHERE user_id = ?", (user.id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_due_recurring_subscriptions(limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT *
            FROM recurring_subscriptions
            WHERE status = 'active'
              AND rebill_id IS NOT NULL
              AND next_charge_at IS NOT NULL
              AND datetime(next_charge_at) <= datetime('now')
            ORDER BY datetime(next_charge_at) ASC, id ASC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        )
        return [dict(row) for row in await cursor.fetchall()]


async def mark_recurring_charge_success(
    recurring_id: int,
    *,
    order_id: str,
    next_charge_at: str,
) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE recurring_subscriptions
            SET last_charge_at = CURRENT_TIMESTAMP,
                last_order_id = ?,
                next_charge_at = ?,
                last_error = NULL,
                status = 'active',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (order_id, next_charge_at, recurring_id),
        )
        await db.commit()
        return cursor.rowcount == 1


async def mark_recurring_charge_failed(
    recurring_id: int,
    *,
    error: str,
    next_charge_at: str | None = None,
) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE recurring_subscriptions
            SET last_error = ?,
                next_charge_at = COALESCE(?, next_charge_at),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (error[:500], next_charge_at, recurring_id),
        )
        await db.commit()
        return cursor.rowcount == 1


async def refund_generation_billing(
    task_id: str,
    *,
    reason: str = "generation_refund",
    metadata: dict | None = None,
) -> bool:
    """Refunds whatever resource was used for a generation task."""
    task = await get_task_by_id(task_id)
    if not task:
        return False
    if task.billing_source == "subscription":
        return await refund_subscription_usage(task.subscription_usage_id or 0)
    if task.cost and task.cost > 0 and task.telegram_id:
        return await add_credits_once(
            task.telegram_id,
            task.cost,
            reason=reason,
            external_id=str(task_id),
            metadata=metadata or {},
        )
    return False


async def add_free_generations(
    telegram_id: int,
    amount: int,
) -> bool:
    """Начисляет пользователю бесплатные генерации."""
    if amount <= 0:
        return False
    await get_or_create_user(telegram_id)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            UPDATE users
            SET free_generations = COALESCE(free_generations, 0) + ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE telegram_id = ?
            """,
            (amount, telegram_id),
        )
        await db.commit()
        return True


async def consume_free_generation(telegram_id: int) -> bool:
    """Списывает один бесплатный запуск генерации, если он есть."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE users
            SET free_generations = free_generations - 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE telegram_id = ? AND COALESCE(free_generations, 0) > 0
            """,
            (telegram_id,),
        )
        await db.commit()
        return cursor.rowcount == 1


async def refund_free_generation(telegram_id: int) -> bool:
    """Возвращает один бесплатный запуск генерации."""
    return await add_free_generations(telegram_id, 1)


async def create_transaction(
    order_id: str,
    user_id: int,
    payment_id: str,
    provider: str,
    credits: int,
    amount_rub: float,
    status: str = "pending",
    original_amount_rub: float | None = None,
    promo_code: str | None = None,
    promo_discount_percent: int = 0,
) -> bool:
    """Создаёт транзакцию платежа"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            await db.execute(
                """INSERT INTO transactions 
                   (
                       order_id, user_id, payment_id, provider, credits, amount_rub,
                       original_amount_rub, promo_code, promo_discount_percent, status
                   )
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order_id,
                    user_id,
                    payment_id,
                    provider,
                    credits,
                    amount_rub,
                    original_amount_rub,
                    promo_code,
                    promo_discount_percent,
                    status,
                ),
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
                else "tbank"
            ),
            user_id=row["user_id"],
            payment_id=row["payment_id"],
            credits=row["credits"],
            amount_rub=row["amount_rub"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            promo_code=row["promo_code"] if "promo_code" in row.keys() else None,
            promo_discount_percent=(
                int(row["promo_discount_percent"] or 0)
                if "promo_discount_percent" in row.keys()
                else 0
            ),
            original_amount_rub=(
                row["original_amount_rub"]
                if "original_amount_rub" in row.keys()
                else None
            ),
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
    reference_images: Optional[str] = None,
    source_feed_task_id: Optional[str] = None,
    billing_source: str = "credits",
    subscription_usage_id: Optional[int] = None,
) -> bool:
    """Создаёт задачу генерации"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        result = await db.execute(
            """INSERT OR IGNORE INTO generation_tasks 
               (user_id, telegram_id, task_id, type, preset_id, model,
                duration, aspect_ratio, prompt, cost, reference_images,
                source_feed_task_id, billing_source, subscription_usage_id, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
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
                reference_images,
                source_feed_task_id,
                billing_source,
                subscription_usage_id,
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
            reference_images=(
                row["reference_images"] if "reference_images" in row.keys() else None
            ),
            created_at=datetime.fromisoformat(row["created_at"]),
            is_public_feed=bool(row["is_public_feed"]) if "is_public_feed" in row.keys() else False,
            likes_count=int(row["likes_count"] or 0) if "likes_count" in row.keys() else 0,
            shares_count=int(row["shares_count"] or 0) if "shares_count" in row.keys() else 0,
            source_feed_task_id=(
                row["source_feed_task_id"] if "source_feed_task_id" in row.keys() else None
            ),
            billing_source=(
                row["billing_source"]
                if "billing_source" in row.keys() and row["billing_source"]
                else "credits"
            ),
            subscription_usage_id=(
                row["subscription_usage_id"]
                if "subscription_usage_id" in row.keys()
                else None
            ),
        )


async def share_task_to_feed(task_id: str, telegram_id: int) -> tuple[bool, str]:
    """Publishes an owned completed image task to the bot feed."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM generation_tasks WHERE task_id = ?",
            (task_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return False, "not_found"
        if int(row["telegram_id"] or 0) != telegram_id:
            return False, "forbidden"
        if row["type"] != "image" or row["status"] != "completed" or not row["result_url"]:
            return False, "not_ready"

        source_task_id = row["source_feed_task_id"] if "source_feed_task_id" in row.keys() else None
        if source_task_id:
            source_cursor = await db.execute(
                "SELECT telegram_id FROM generation_tasks WHERE task_id = ?",
                (source_task_id,),
            )
            source = await source_cursor.fetchone()
            if source and int(source["telegram_id"] or 0) != telegram_id:
                return False, "foreign_source"

        await db.execute(
            "UPDATE generation_tasks SET is_public_feed = 1 WHERE task_id = ? AND telegram_id = ?",
            (task_id, telegram_id),
        )
        await db.commit()
        return True, "ok"


async def remove_task_from_feed(task_id: str, telegram_id: int) -> bool:
    """Removes an owned task from the public feed without deleting the task."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "UPDATE generation_tasks SET is_public_feed = 0 WHERE task_id = ? AND telegram_id = ?",
            (task_id, telegram_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_feed_tasks(limit: int = 30) -> list[GenerationTask]:
    """Returns public completed image tasks for bot-side feed cards."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT *
            FROM generation_tasks
            WHERE is_public_feed = 1
              AND type = 'image'
              AND status = 'completed'
              AND result_url IS NOT NULL
              AND result_url != ''
            ORDER BY
              (COALESCE(likes_count, 0) + COALESCE(shares_count, 0) * 3) DESC,
              COALESCE(completed_at, created_at) DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        tasks = []
        for row in rows:
            tasks.append(
                GenerationTask(
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
                    reference_images=row["reference_images"] if "reference_images" in row.keys() else None,
                    created_at=datetime.fromisoformat(row["created_at"]),
                    is_public_feed=bool(row["is_public_feed"]),
                    likes_count=int(row["likes_count"] or 0),
                    shares_count=int(row["shares_count"] or 0),
                    source_feed_task_id=row["source_feed_task_id"] if "source_feed_task_id" in row.keys() else None,
                )
            )
        return tasks


async def get_public_feed_task(task_id: str) -> Optional[GenerationTask]:
    """Returns a task only if it is visible as a public feed card."""
    task = await get_task_by_id(task_id)
    if (
        task
        and task.is_public_feed
        and task.type == "image"
        and task.status == "completed"
        and task.result_url
    ):
        return task
    return None


async def like_feed_task(task_id: str) -> Optional[int]:
    """Increments feed likes and returns the new value."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE generation_tasks
            SET likes_count = COALESCE(likes_count, 0) + 1
            WHERE task_id = ?
              AND is_public_feed = 1
              AND type = 'image'
              AND status = 'completed'
              AND result_url IS NOT NULL
            """,
            (task_id,),
        )
        if cursor.rowcount == 0:
            await db.commit()
            return None
        value_cursor = await db.execute(
            "SELECT likes_count FROM generation_tasks WHERE task_id = ?",
            (task_id,),
        )
        row = await value_cursor.fetchone()
        await db.commit()
        return int(row[0] or 0) if row else None


async def increment_feed_share(task_id: str) -> Optional[int]:
    """Increments feed share counter and returns the new value."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE generation_tasks
            SET shares_count = COALESCE(shares_count, 0) + 1
            WHERE task_id = ?
              AND is_public_feed = 1
              AND type = 'image'
              AND status = 'completed'
              AND result_url IS NOT NULL
            """,
            (task_id,),
        )
        if cursor.rowcount == 0:
            await db.commit()
            return None
        value_cursor = await db.execute(
            "SELECT shares_count FROM generation_tasks WHERE task_id = ?",
            (task_id,),
        )
        row = await value_cursor.fetchone()
        await db.commit()
        return int(row[0] or 0) if row else None


async def complete_video_task(task_id: str, result_url: str) -> bool:
    """Отмечает задачу как выполненную"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """UPDATE generation_tasks 
               SET status = 'completed', result_url = ?, completed_at = CURRENT_TIMESTAMP 
               WHERE task_id = ?""",
            (result_url, task_id),
        )
        cursor = await db.execute(
            "SELECT * FROM generation_tasks WHERE task_id = ?",
            (task_id,),
        )
        row = await cursor.fetchone()
        await db.commit()
        if row:
            await _notify_tma_task_update(dict(row))
        return True


async def fail_generation_task(task_id: str) -> bool:
    """Отмечает задачу как завершённую с ошибкой."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """UPDATE generation_tasks
               SET status = 'failed', completed_at = CURRENT_TIMESTAMP
               WHERE task_id = ?""",
            (task_id,),
        )
        cursor = await db.execute(
            "SELECT * FROM generation_tasks WHERE task_id = ?",
            (task_id,),
        )
        row = await cursor.fetchone()
        await db.commit()
        if row:
            await _notify_tma_task_update(dict(row))
        return True


async def _notify_tma_task_update(row: dict) -> None:
    try:
        from bot.tma_realtime import notify_task_update

        await notify_task_update(
            int(row.get("telegram_id") or 0),
            {
                "task_id": row.get("task_id"),
                "telegram_id": row.get("telegram_id"),
                "type": row.get("type"),
                "preset_id": row.get("preset_id"),
                "model": row.get("model"),
                "duration": row.get("duration"),
                "aspect_ratio": row.get("aspect_ratio"),
                "prompt": row.get("prompt"),
                "cost": row.get("cost"),
                "status": row.get("status"),
                "result_url": row.get("result_url"),
                "reference_images": row.get("reference_images"),
                "created_at": row.get("created_at"),
                "is_public_feed": row.get("is_public_feed"),
                "likes_count": row.get("likes_count"),
                "shares_count": row.get("shares_count"),
            },
        )
    except Exception:
        logger.exception("Failed to notify TMA task update for %s", row.get("task_id"))


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
            "SELECT COUNT(*) as count FROM generation_tasks WHERE user_id = ? AND status = 'completed'",
            (user.id,),
        )
        gen_row = await cursor.fetchone()

        # Считаем потраченные BoomCoin
        cursor = await db.execute(
            "SELECT SUM(cost) as total FROM generation_tasks WHERE user_id = ? AND status = 'completed'",
            (user.id,),
        )
        cost_row = await cursor.fetchone()

        referral_stats = await get_referral_stats(telegram_id)
        promo_rows = await get_user_promo_redemptions(telegram_id)
        subscription = await get_active_subscription(telegram_id)
        banned = bool(getattr(user, "is_banned", False))

        return {
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "credits": user.credits,
            "generations": gen_row["count"] or 0,
            "total_spent": cost_row["total"] or 0,
            "member_since": user.created_at.strftime("%d.%m.%Y"),
            "referral_code": referral_stats["referral_code"],
            "referrals_count": referral_stats["referrals_count"],
            "referral_earned": referral_stats["referral_earned"],
            "is_banned": banned,
            "promos": promo_rows,
            "subscription": subscription,
        }


async def get_admin_stats() -> dict:
    """Получает общую статистику для админа"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Всего пользователей
        cursor = await db.execute("SELECT COUNT(*) as count FROM users")
        users_row = await cursor.fetchone()
        cursor = await db.execute("SELECT COUNT(*) as count FROM users WHERE is_banned = 1")
        banned_row = await cursor.fetchone()
        cursor = await db.execute("SELECT COALESCE(SUM(credits), 0) as total FROM users")
        balance_row = await cursor.fetchone()
        cursor = await db.execute(
            "SELECT COUNT(*) as count FROM users WHERE datetime(created_at) >= datetime('now', '-7 days')"
        )
        active_row = await cursor.fetchone()

        # Всего генераций
        cursor = await db.execute(
            "SELECT COUNT(*) as count FROM generation_tasks WHERE status = 'completed'"
        )
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
            "active_users": active_row["count"] or 0,
            "banned_users": banned_row["count"] or 0,
            "total_user_balance": balance_row["total"] or 0,
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
    await db.execute(
        """
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
    """
    )
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


async def get_gpt55_history(telegram_id: int, limit: int = 20) -> list[dict]:
    """Возвращает последние сообщения GPT 5.5 чата пользователя."""
    user = await get_or_create_user(telegram_id)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT messages_json FROM gpt55_conversations WHERE user_id = ?",
            (user.id,),
        )
        row = await cursor.fetchone()
        if not row:
            return []
        try:
            messages = json.loads(row[0] or "[]")
        except json.JSONDecodeError:
            logger.warning("Invalid GPT 5.5 history JSON for user %s", telegram_id)
            return []
        if not isinstance(messages, list):
            return []
        return messages[-limit:]


async def append_gpt55_history(
    telegram_id: int,
    user_content: list[dict],
    assistant_text: str,
    limit: int = 20,
) -> bool:
    """Добавляет пару user/assistant в историю GPT 5.5."""
    user = await get_or_create_user(telegram_id)
    messages = await get_gpt55_history(telegram_id, limit=limit)
    messages.extend(
        [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_text},
        ]
    )
    messages = messages[-limit:]

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT INTO gpt55_conversations (user_id, messages_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                messages_json = excluded.messages_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user.id, json.dumps(messages, ensure_ascii=False)),
        )
        await db.commit()
        return True


async def clear_gpt55_history(telegram_id: int) -> bool:
    """Очищает историю GPT 5.5 чата пользователя."""
    user = await get_or_create_user(telegram_id)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "DELETE FROM gpt55_conversations WHERE user_id = ?",
            (user.id,),
        )
        await db.commit()
        return True
