-- PostgreSQL schema draft for Banano Kling.
-- Not applied to production automatically. Review before migration.

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL UNIQUE,
    referral_code TEXT UNIQUE,
    referred_by BIGINT REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    has_paid BOOLEAN NOT NULL DEFAULT false,
    partner_agreed_at TIMESTAMPTZ,
    partner_total_revenue_rub NUMERIC(12,2) NOT NULL DEFAULT 0,
    partner_balance_rub NUMERIC(12,2) NOT NULL DEFAULT 0,
    partner_withdrawn_rub NUMERIC(12,2) NOT NULL DEFAULT 0,
    partner_tier TEXT NOT NULL DEFAULT 'basic'
);

CREATE TABLE IF NOT EXISTS credit_transactions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    external_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(reason, external_id)
);

CREATE INDEX IF NOT EXISTS idx_credit_transactions_user_id ON credit_transactions(user_id);

CREATE TABLE IF NOT EXISTS payments (
    id BIGSERIAL PRIMARY KEY,
    order_id TEXT NOT NULL UNIQUE,
    user_id BIGINT NOT NULL REFERENCES users(id),
    provider TEXT NOT NULL,
    provider_payment_id TEXT,
    credits INTEGER NOT NULL,
    amount_rub NUMERIC(12,2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_provider_payment_id ON payments(provider, provider_payment_id);

CREATE TABLE IF NOT EXISTS generation_tasks (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    provider_task_id TEXT NOT NULL UNIQUE,
    generation_type TEXT NOT NULL,
    preset_id TEXT,
    model TEXT,
    cost INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    prompt TEXT,
    reference_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    result_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    refund_transaction_id BIGINT REFERENCES credit_transactions(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_generation_tasks_user_status ON generation_tasks(user_id, status);

CREATE TABLE IF NOT EXISTS provider_webhooks (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    event_id TEXT NOT NULL,
    provider_task_id TEXT,
    payload JSONB NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(provider, event_id)
);

CREATE TABLE IF NOT EXISTS telegram_updates (
    update_id BIGINT PRIMARY KEY,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS referrals (
    id BIGSERIAL PRIMARY KEY,
    referrer_id BIGINT NOT NULL REFERENCES users(id),
    referred_id BIGINT NOT NULL REFERENCES users(id),
    bonus_credits INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(referrer_id, referred_id)
);
