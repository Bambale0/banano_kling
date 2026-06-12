-- PostgreSQL runtime schema for Banano Kling.
-- Mirrors the current SQLite tables so data can be migrated without field renames.
-- Extra admin tables at the end cover packages, referral rules, push scenarios,
-- partner payouts, and anti-fraud settings.

BEGIN;

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    credits INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    referral_code TEXT,
    -- Legacy field from SQLite. Do not enforce FK here: old rows can contain
    -- stale ids. Canonical referral edges are stored in referrals.
    referred_by BIGINT,
    referral_earned INTEGER DEFAULT 0,
    has_paid BOOLEAN DEFAULT FALSE,
    partner_agreed_at TIMESTAMPTZ,
    partner_total_revenue_rub NUMERIC(14,2) DEFAULT 0,
    partner_balance_rub NUMERIC(14,2) DEFAULT 0,
    partner_withdrawn_rub NUMERIC(14,2) DEFAULT 0,
    partner_tier TEXT DEFAULT 'basic',
    is_banned BOOLEAN DEFAULT FALSE,
    free_generations INTEGER DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_referral_code
    ON users(referral_code)
    WHERE referral_code IS NOT NULL;

CREATE TABLE IF NOT EXISTS transactions (
    id BIGSERIAL PRIMARY KEY,
    order_id TEXT UNIQUE NOT NULL,
    user_id BIGINT NOT NULL,
    payment_id TEXT,
    credits INTEGER NOT NULL,
    amount_rub NUMERIC(14,2) NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    provider TEXT DEFAULT 'tbank',
    original_amount_rub NUMERIC(14,2),
    promo_code TEXT,
    promo_discount_percent INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(status);

CREATE TABLE IF NOT EXISTS generation_tasks (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    task_id TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL,
    preset_id TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    result_url TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    prompt TEXT,
    cost INTEGER,
    model TEXT,
    duration INTEGER,
    aspect_ratio TEXT,
    telegram_id BIGINT,
    reference_images TEXT,
    is_public_feed BOOLEAN DEFAULT FALSE,
    likes_count INTEGER DEFAULT 0,
    shares_count INTEGER DEFAULT 0,
    source_feed_task_id TEXT,
    published_at TIMESTAMPTZ,
    feed_status TEXT DEFAULT 'approved'
);

CREATE INDEX IF NOT EXISTS idx_generation_tasks_user_status ON generation_tasks(user_id, status);
CREATE INDEX IF NOT EXISTS idx_generation_tasks_task_id ON generation_tasks(task_id);
CREATE INDEX IF NOT EXISTS idx_generation_tasks_public_feed ON generation_tasks(is_public_feed, feed_status, created_at DESC);

CREATE TABLE IF NOT EXISTS feed_interactions (
    id BIGSERIAL PRIMARY KEY,
    task_id TEXT NOT NULL,
    telegram_id BIGINT NOT NULL,
    action TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_id, telegram_id, action)
);

CREATE INDEX IF NOT EXISTS idx_feed_interactions_task_action
    ON feed_interactions(task_id, action);

CREATE TABLE IF NOT EXISTS generation_history (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    preset_id TEXT NOT NULL,
    prompt TEXT,
    cost INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_settings (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT UNIQUE NOT NULL,
    preferred_model TEXT DEFAULT 'flash',
    preferred_video_model TEXT DEFAULT 'v3_std',
    preferred_i2v_model TEXT DEFAULT 'v3_std',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    image_service TEXT DEFAULT 'nanobanana'
);

CREATE TABLE IF NOT EXISTS gpt55_conversations (
    user_id BIGINT PRIMARY KEY,
    messages_json TEXT NOT NULL DEFAULT '[]',
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_assistant_conversations (
    user_id BIGINT PRIMARY KEY,
    messages_json TEXT NOT NULL DEFAULT '[]',
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS promo_codes (
    id BIGSERIAL PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    credits INTEGER NOT NULL,
    max_uses INTEGER NOT NULL DEFAULT 1,
    used_count INTEGER NOT NULL DEFAULT 0,
    expires_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by BIGINT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    discount_percent INTEGER DEFAULT 0,
    promo_type TEXT DEFAULT 'discount',
    reward_credits INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS promo_redemptions (
    id BIGSERIAL PRIMARY KEY,
    promo_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    telegram_id BIGINT NOT NULL,
    order_id TEXT,
    redeemed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(promo_id, order_id)
);

CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS referrals (
    id BIGSERIAL PRIMARY KEY,
    referrer_id BIGINT NOT NULL,
    referred_id BIGINT NOT NULL,
    bonus_credits INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(referrer_id, referred_id)
);

CREATE TABLE IF NOT EXISTS partner_withdrawals (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    amount_rub NUMERIC(14,2) NOT NULL,
    method TEXT NOT NULL,
    requisites TEXT,
    status TEXT DEFAULT 'requested',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    recipient_name TEXT,
    phone TEXT,
    card_mask TEXT,
    external_payment_id TEXT,
    external_contractor_id BIGINT,
    external_requisite_id BIGINT,
    external_status_id BIGINT,
    status_title TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS batch_jobs (
    id BIGSERIAL PRIMARY KEY,
    job_id TEXT UNIQUE NOT NULL,
    user_id BIGINT NOT NULL,
    mode TEXT NOT NULL,
    total_cost INTEGER NOT NULL,
    results_count INTEGER DEFAULT 0,
    duration NUMERIC(12,3),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS credit_transactions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    external_id TEXT,
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(reason, external_id)
);

CREATE INDEX IF NOT EXISTS idx_credit_transactions_user_id ON credit_transactions(user_id);

CREATE TABLE IF NOT EXISTS provider_webhooks (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    event_id TEXT NOT NULL,
    provider_task_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    processed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, event_id)
);

CREATE TABLE IF NOT EXISTS telegram_updates (
    update_id BIGINT PRIMARY KEY,
    received_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS payment_packages (
    id BIGSERIAL PRIMARY KEY,
    package_key TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    credits INTEGER NOT NULL,
    price_rub NUMERIC(14,2) NOT NULL,
    bonus_credits INTEGER NOT NULL DEFAULT 0,
    discount_percent INTEGER NOT NULL DEFAULT 0,
    is_popular BOOLEAN NOT NULL DEFAULT FALSE,
    is_visible BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 100,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS referral_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO referral_settings(key, value)
VALUES
    ('referrer_bonus_credits', '30'),
    ('friend_bonus_credits', '30'),
    ('bonus_trigger', 'first_payment'),
    ('daily_referral_limit', '20'),
    ('antifraud_rules', 'same_device_limit,referrals_without_payments,promo_abuse,free_generation_reuse,partner_fraud')
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS push_scenarios (
    id BIGSERIAL PRIMARY KEY,
    scenario_key TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    trigger_event TEXT NOT NULL,
    delay_seconds INTEGER NOT NULL DEFAULT 0,
    message_text TEXT NOT NULL,
    bonus_credits INTEGER NOT NULL DEFAULT 0,
    promo_code TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    max_sends_per_user INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS push_scenario_events (
    id BIGSERIAL PRIMARY KEY,
    scenario_id BIGINT NOT NULL REFERENCES push_scenarios(id),
    user_id BIGINT NOT NULL REFERENCES users(id),
    scheduled_at TIMESTAMPTZ NOT NULL,
    sent_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'scheduled',
    error_message TEXT,
    UNIQUE(scenario_id, user_id, scheduled_at)
);

CREATE TABLE IF NOT EXISTS partner_payouts (
    id BIGSERIAL PRIMARY KEY,
    partner_user_id BIGINT NOT NULL REFERENCES users(id),
    amount_rub NUMERIC(14,2) NOT NULL,
    commission_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
    revenue_rub NUMERIC(14,2) NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    external_payment_id TEXT,
    comment TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS antifraud_rules (
    id BIGSERIAL PRIMARY KEY,
    rule_key TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    threshold_value INTEGER,
    window_seconds INTEGER,
    action TEXT NOT NULL DEFAULT 'flag',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO antifraud_rules(rule_key, title, description, threshold_value, window_seconds, action)
VALUES
    ('same_device_accounts', 'Many accounts from one device', 'Detect many accounts linked to the same fingerprint/device.', 3, 86400, 'flag'),
    ('referrals_without_payments', 'Many referrals without payments', 'Detect referral growth without paid conversion.', 10, 604800, 'flag'),
    ('promo_abuse', 'Suspicious promo usage', 'Detect repeated promo activations by related accounts.', 5, 86400, 'flag'),
    ('free_generation_reuse', 'Repeated free generations', 'Detect repeated free generation attempts.', 3, 86400, 'limit'),
    ('partner_fraud', 'Partner traffic abuse', 'Detect low-quality partner traffic and payout abuse.', 20, 604800, 'freeze')
ON CONFLICT (rule_key) DO NOTHING;

COMMIT;
