-- Native PostgreSQL schema for clean deployments
-- Run once on an empty Postgres database before starting the bot
-- Usage: psql "$DATABASE_URL" -f schema_postgres.sql

BEGIN;

-- ============================================================
-- USERS
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    credits INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    referral_code TEXT,
    referred_by BIGINT REFERENCES users(id),
    referral_earned INTEGER DEFAULT 0,
    has_paid BOOLEAN DEFAULT FALSE,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    channel_url TEXT,
    photo_url TEXT,
    partner_agreed_at TIMESTAMP,
    partner_total_revenue_rub REAL DEFAULT 0,
    partner_balance_rub REAL DEFAULT 0,
    partner_withdrawn_rub REAL DEFAULT 0,
    prompt_repeat_balance_rub REAL DEFAULT 0,
    prompt_repeat_total_rub REAL DEFAULT 0,
    partner_tier TEXT DEFAULT 'basic',
    is_banned INTEGER DEFAULT 0,
    banned_at TIMESTAMP,
    banned_by_telegram_id BIGINT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code);

-- ============================================================
-- INTERNAL ADMIN COMMAND LEDGER
-- ============================================================
CREATE TABLE IF NOT EXISTS internal_admin_commands (
    id BIGSERIAL PRIMARY KEY,
    idempotency_key TEXT UNIQUE NOT NULL,
    action TEXT NOT NULL,
    target_user_id BIGINT NOT NULL,
    admin_user_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    request_payload JSONB NOT NULL,
    response_payload JSONB,
    status TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_internal_admin_commands_request_id
    ON internal_admin_commands(request_id);
CREATE INDEX IF NOT EXISTS idx_internal_admin_commands_target
    ON internal_admin_commands(target_user_id, created_at DESC);

-- ============================================================
-- TRANSACTIONS (payments)
-- ============================================================
CREATE TABLE IF NOT EXISTS transactions (
    id BIGSERIAL PRIMARY KEY,
    order_id TEXT UNIQUE NOT NULL,
    user_id BIGINT NOT NULL REFERENCES users(id),
    payment_id TEXT,
    provider TEXT DEFAULT 'cryptobot',
    credits INTEGER NOT NULL,
    amount_rub REAL NOT NULL,
    promo_code_id BIGINT,
    promo_code TEXT,
    promo_bonus_credits INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- GENERATION TASKS
-- ============================================================
CREATE TABLE IF NOT EXISTS generation_tasks (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    telegram_id BIGINT,
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
    result_urls TEXT,
    is_public_feed BOOLEAN DEFAULT FALSE,
    is_prompt_library BOOLEAN DEFAULT FALSE,
    source_feed_gen_id BIGINT,
    parent_generation_id BIGINT,
    action_type TEXT,
    likes_count INTEGER DEFAULT 0,
    shares_count INTEGER DEFAULT 0,
    feed_prompt_visible BOOLEAN DEFAULT FALSE,
    feed_references_visible BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    updated_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_generation_tasks_user_created ON generation_tasks(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_generation_tasks_feed ON generation_tasks(is_public_feed, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_generation_tasks_source_feed ON generation_tasks(source_feed_gen_id);
CREATE INDEX IF NOT EXISTS idx_generation_tasks_parent_status ON generation_tasks(parent_generation_id, status);

-- ============================================================
-- GENERATION HISTORY
-- ============================================================
CREATE TABLE IF NOT EXISTS generation_history (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    preset_id TEXT NOT NULL,
    prompt TEXT,
    cost INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- USER SETTINGS
-- ============================================================
CREATE TABLE IF NOT EXISTS user_settings (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    preferred_model TEXT DEFAULT 'flash',
    preferred_video_model TEXT DEFAULT 'v3_std',
    preferred_i2v_model TEXT DEFAULT 'v3_std',
    image_service TEXT DEFAULT 'nanobanana',
    referral_purchase_notifications_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- BOT SETTINGS (key-value)
-- ============================================================
CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_by_telegram_id BIGINT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- REFERRALS
-- ============================================================
CREATE TABLE IF NOT EXISTS referrals (
    id BIGSERIAL PRIMARY KEY,
    referrer_id BIGINT NOT NULL REFERENCES users(id),
    referred_id BIGINT NOT NULL REFERENCES users(id),
    bonus_credits INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(referrer_id, referred_id)
);

-- ============================================================
-- REFERRAL EVENTS (transition tracking)
-- ============================================================
CREATE TABLE IF NOT EXISTS referral_events (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    visitor_user_id BIGINT,
    visitor_telegram_id BIGINT NOT NULL,
    clicked_code TEXT,
    clicked_referrer_id BIGINT,
    existing_referrer_id BIGINT,
    attached BOOLEAN DEFAULT FALSE,
    reason TEXT NOT NULL,
    source TEXT,
    start_param TEXT,
    is_self_click BOOLEAN DEFAULT FALSE,
    is_repeat_click BOOLEAN DEFAULT FALSE,
    metadata JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_referral_events_created_at ON referral_events(created_at);
CREATE INDEX IF NOT EXISTS idx_referral_events_visitor_telegram_id ON referral_events(visitor_telegram_id);
CREATE INDEX IF NOT EXISTS idx_referral_events_clicked_referrer_id ON referral_events(clicked_referrer_id);
CREATE INDEX IF NOT EXISTS idx_referral_events_reason ON referral_events(reason);
CREATE INDEX IF NOT EXISTS idx_referral_events_attached ON referral_events(attached);
CREATE INDEX IF NOT EXISTS idx_referral_events_clicked_code ON referral_events(clicked_code);

-- ============================================================
-- PARTNER COMMISSIONS LEDGER
-- ============================================================
CREATE TABLE IF NOT EXISTS partner_commissions (
    id BIGSERIAL PRIMARY KEY,
    transaction_id BIGINT NOT NULL REFERENCES transactions(id),
    order_id TEXT NOT NULL,
    referrer_id BIGINT NOT NULL REFERENCES users(id),
    referred_id BIGINT NOT NULL REFERENCES users(id),
    level INT NOT NULL CHECK (level IN (1, 2)),
    base_amount_rub NUMERIC(12,2) NOT NULL,
    percent NUMERIC(5,2) NOT NULL,
    amount_rub NUMERIC(12,2) NOT NULL,
    tier TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(transaction_id, referrer_id, level)
);
CREATE INDEX IF NOT EXISTS idx_partner_commissions_referrer ON partner_commissions(referrer_id, created_at DESC);

-- ============================================================
-- PARTNER WITHDRAWALS
-- ============================================================
CREATE TABLE IF NOT EXISTS partner_withdrawals (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    amount_rub REAL NOT NULL,
    method TEXT NOT NULL,
    requisites TEXT,
    status TEXT DEFAULT 'requested',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- PROMO CODES
-- ============================================================
CREATE TABLE IF NOT EXISTS promo_codes (
    id BIGSERIAL PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    partner_name TEXT,
    partner_telegram_id BIGINT,
    partner_user_id BIGINT REFERENCES users(id),
    is_active BOOLEAN DEFAULT TRUE,
    usage_count INTEGER DEFAULT 0,
    total_bonus_credits INTEGER DEFAULT 0,
    total_amount_rub REAL DEFAULT 0,
    created_by_telegram_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_promo_codes_code ON promo_codes(code);

COMMIT;
