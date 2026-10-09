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
    credits NUMERIC(12, 4) DEFAULT 0,
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
-- SEEDANCE CREATOR TARIFF (independent of users/admin privileges)
-- ============================================================
CREATE TABLE IF NOT EXISTS creator_tariff_memberships (
    telegram_id BIGINT PRIMARY KEY REFERENCES users(telegram_id),
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    updated_by_telegram_id BIGINT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS creator_tariff_audit (
    id TEXT PRIMARY KEY,
    actor_telegram_id BIGINT NOT NULL,
    target_telegram_id BIGINT,
    event_type TEXT NOT NULL,
    before_state TEXT NOT NULL,
    after_state TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_creator_tariff_audit_target
    ON creator_tariff_audit(target_telegram_id, created_at);
CREATE OR REPLACE FUNCTION creator_tariff_audit_append_only()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'creator tariff audit is append-only';
END;
$$;
DO $$ BEGIN
IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'creator_tariff_audit_append_only_guard'
    AND tgrelid = 'creator_tariff_audit'::regclass
) THEN
    CREATE TRIGGER creator_tariff_audit_append_only_guard
    BEFORE UPDATE OR DELETE OR TRUNCATE ON creator_tariff_audit
    FOR EACH STATEMENT EXECUTE FUNCTION creator_tariff_audit_append_only();
END IF;
END $$;

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
    is_profile_visible BOOLEAN DEFAULT FALSE,
    is_adult_content BOOLEAN DEFAULT FALSE,
    is_prompt_library BOOLEAN DEFAULT FALSE,
    source_feed_gen_id BIGINT,
    parent_generation_id BIGINT,
    action_type TEXT,
    likes_count INTEGER DEFAULT 0,
    shares_count INTEGER DEFAULT 0,
    feed_prompt_visible BOOLEAN DEFAULT FALSE,
    feed_references_visible BOOLEAN DEFAULT FALSE,
    feed_repeat_reference_selection TEXT,
    feed_blurred BOOLEAN DEFAULT FALSE,
    feed_published_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    updated_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_generation_tasks_user_created ON generation_tasks(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_generation_tasks_feed ON generation_tasks(is_public_feed, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_generation_tasks_feed_safe ON generation_tasks(is_public_feed, is_adult_content, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_generation_tasks_profile ON generation_tasks(user_id, is_profile_visible, status, created_at DESC);
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

-- ============================================================
-- PROMO REDEMPTIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS promo_redemptions (
    id BIGSERIAL PRIMARY KEY,
    promo_code_id BIGINT NOT NULL REFERENCES promo_codes(id),
    transaction_id BIGINT UNIQUE NOT NULL REFERENCES transactions(id),
    user_id BIGINT NOT NULL REFERENCES users(id),
    amount_rub REAL NOT NULL,
    bonus_credits INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_promo_redemptions_promo ON promo_redemptions(promo_code_id, created_at);

-- ============================================================
-- USER PROMPTS (feed)
-- ============================================================
CREATE TABLE IF NOT EXISTS user_prompts (
    id BIGSERIAL PRIMARY KEY,
    author_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    category TEXT DEFAULT 'other',
    prompt_text TEXT NOT NULL,
    preview_url TEXT,
    model TEXT,
    tags TEXT DEFAULT '[]',
    generation_settings TEXT DEFAULT '{}',
    likes INTEGER DEFAULT 0,
    uses_count INTEGER DEFAULT 0,
    is_public BOOLEAN DEFAULT TRUE,
    status TEXT DEFAULT 'pending',
    reject_reason TEXT,
    ai_moderation_decision TEXT,
    ai_moderation_risk TEXT,
    ai_moderation_reason TEXT,
    ai_moderation_recommendation TEXT,
    ai_moderation_raw TEXT,
    ai_moderated_at TIMESTAMP,
    source_generation_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_user_prompts_status ON user_prompts(status, is_public, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_prompts_author_status ON user_prompts(author_id, status);
CREATE INDEX IF NOT EXISTS idx_user_prompts_source_generation ON user_prompts(source_generation_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_prompts_seedance_trend_source_unique
    ON user_prompts(source_generation_id)
    WHERE source_generation_id IS NOT NULL
      AND status != 'deactivated'
      AND tags LIKE '%"seedance-private-references"%';

CREATE TABLE IF NOT EXISTS trend_reference_assets (
    id BIGSERIAL PRIMARY KEY,
    prompt_id BIGINT NOT NULL REFERENCES user_prompts(id) ON DELETE CASCADE,
    media_type TEXT NOT NULL,
    position INTEGER NOT NULL,
    source_position INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'fixed_hidden',
    file_url TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    mime_type TEXT,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    label TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    UNIQUE(prompt_id, media_type, position),
    UNIQUE(prompt_id, media_type, file_hash)
);
CREATE INDEX IF NOT EXISTS idx_trend_reference_assets_prompt_type_position
    ON trend_reference_assets(prompt_id, media_type, position);

CREATE TABLE IF NOT EXISTS trend_run_claims (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    trend_id BIGINT NOT NULL REFERENCES user_prompts(id) ON DELETE CASCADE,
    client_request_id TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'processing',
    task_id TEXT,
    http_status INTEGER,
    response_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, trend_id, client_request_id)
);
CREATE INDEX IF NOT EXISTS idx_trend_run_claims_status_updated
    ON trend_run_claims(status, updated_at);

-- ============================================================
-- PROMPT LIKES
-- ============================================================
CREATE TABLE IF NOT EXISTS prompt_likes (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    prompt_id BIGINT NOT NULL REFERENCES user_prompts(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, prompt_id)
);

-- ============================================================
-- FEED GENERATION LIKES
-- ============================================================
CREATE TABLE IF NOT EXISTS feed_generation_likes (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    generation_task_id BIGINT NOT NULL REFERENCES generation_tasks(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, generation_task_id)
);

-- ============================================================
-- FEED REMIX EVENTS
-- ============================================================
CREATE TABLE IF NOT EXISTS feed_remix_events (
    id BIGSERIAL PRIMARY KEY,
    source_generation_task_id BIGINT NOT NULL,
    remix_generation_task_id BIGINT NOT NULL,
    source_author_id BIGINT NOT NULL,
    remix_author_id BIGINT NOT NULL,
    credits_spent INTEGER DEFAULT 0,
    royalty_credits INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_generation_task_id, remix_generation_task_id)
);

-- ============================================================
-- PROMPT REPEAT EVENTS
-- ============================================================
CREATE TABLE IF NOT EXISTS prompt_repeat_events (
    id BIGSERIAL PRIMARY KEY,
    author_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    repeater_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_id BIGINT NOT NULL,
    repeat_task_id TEXT,
    credits_spent INTEGER DEFAULT 0,
    amount_rub REAL NOT NULL DEFAULT 10,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_prompt_repeat_events_author ON prompt_repeat_events(author_id, created_at DESC);

-- ============================================================
-- SAVED REFERENCES
-- ============================================================
CREATE TABLE IF NOT EXISTS saved_references (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    file_url TEXT NOT NULL,
    file_hash TEXT,
    original_filename TEXT,
    content_type TEXT,
    source TEXT DEFAULT 'telegram',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_saved_references_user_kind_last_used ON saved_references(user_id, kind, last_used_at DESC, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_references_user_kind_hash ON saved_references(user_id, kind, file_hash);

-- ============================================================
-- FEED COMMENTS
-- ============================================================
CREATE TABLE IF NOT EXISTS feed_comments (
    id BIGSERIAL PRIMARY KEY,
    generation_id BIGINT NOT NULL REFERENCES generation_tasks(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id),
    text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_feed_comments_generation_created ON feed_comments(generation_id, created_at DESC);

-- ============================================================
-- BATCH JOBS
-- ============================================================
CREATE TABLE IF NOT EXISTS batch_jobs (
    id BIGSERIAL PRIMARY KEY,
    job_id TEXT UNIQUE NOT NULL,
    user_id BIGINT NOT NULL REFERENCES users(id),
    mode TEXT NOT NULL,
    total_cost INTEGER NOT NULL,
    results_count INTEGER DEFAULT 0,
    duration REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- MINIAPP NOTIFICATIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS miniapp_notifications (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- HIGGSFIELD GENJUTSU
-- ============================================================
CREATE TABLE IF NOT EXISTS genjutsu_control (
    id INTEGER PRIMARY KEY,
    config_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS genjutsu_assets (
    id TEXT PRIMARY KEY, owner BIGINT NOT NULL, kind TEXT NOT NULL,
    storage_key TEXT NOT NULL UNIQUE, metadata TEXT NOT NULL,
    size_bytes BIGINT NOT NULL DEFAULT 0, created_ms BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS genjutsu_uploads (
    id TEXT PRIMARY KEY, owner BIGINT NOT NULL,
    reserved_bytes BIGINT NOT NULL, expires_ms BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS genjutsu_projects (
    id TEXT PRIMARY KEY, owner BIGINT NOT NULL, title TEXT NOT NULL,
    revision INTEGER NOT NULL, plan TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    created_ms BIGINT NOT NULL, updated_ms BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS genjutsu_versions (
    project_id TEXT NOT NULL REFERENCES genjutsu_projects(id),
    revision INTEGER NOT NULL, plan TEXT NOT NULL, title TEXT NOT NULL,
    created_ms BIGINT NOT NULL, PRIMARY KEY(project_id, revision)
);
CREATE TABLE IF NOT EXISTS genjutsu_quotes (
    id TEXT PRIMARY KEY, owner BIGINT NOT NULL, project_id TEXT NOT NULL,
    revision INTEGER NOT NULL, plan TEXT NOT NULL, quote TEXT NOT NULL,
    config_version INTEGER NOT NULL, config_hash TEXT NOT NULL,
    settings TEXT NOT NULL, expires_ms BIGINT NOT NULL, used_by TEXT,
    private_recipe INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS genjutsu_runs (
    id TEXT PRIMARY KEY, owner BIGINT NOT NULL, project_id TEXT NOT NULL,
    quote_id TEXT NOT NULL UNIQUE, request_key TEXT NOT NULL,
    plan TEXT NOT NULL, settings TEXT NOT NULL, state TEXT NOT NULL,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    admin_free INTEGER NOT NULL DEFAULT 0,
    private_recipe INTEGER NOT NULL DEFAULT 0,
    created_ms BIGINT NOT NULL, updated_ms BIGINT NOT NULL,
    UNIQUE(owner, request_key)
);
CREATE TABLE IF NOT EXISTS genjutsu_steps (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES genjutsu_runs(id),
    variant INTEGER NOT NULL, ordinal INTEGER NOT NULL, spec TEXT NOT NULL,
    status TEXT NOT NULL, source_asset_id TEXT, output_asset_id TEXT,
    provider_request_id TEXT UNIQUE, provider_status_url TEXT,
    provider_cancel_url TEXT, provider_correlation_id TEXT, attempt_id TEXT,
    reserved_credits INTEGER NOT NULL, actual_credits INTEGER,
    refunded_credits INTEGER NOT NULL DEFAULT 0, rate INTEGER NOT NULL,
    lease_token TEXT, lease_until_ms BIGINT NOT NULL DEFAULT 0,
    next_poll_ms BIGINT NOT NULL, poll_count INTEGER NOT NULL DEFAULT 0,
    error_code TEXT, remote_result_url TEXT,
    created_ms BIGINT NOT NULL, updated_ms BIGINT NOT NULL,
    UNIQUE(run_id, variant, ordinal)
);
CREATE TABLE IF NOT EXISTS genjutsu_finance (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_id TEXT,
    owner BIGINT NOT NULL, kind TEXT NOT NULL, amount INTEGER NOT NULL,
    created_ms BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS genjutsu_events (
    id TEXT PRIMARY KEY, run_id TEXT, step_id TEXT, actor BIGINT,
    event TEXT NOT NULL, details TEXT NOT NULL, created_ms BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS genjutsu_deliveries (
    step_id TEXT PRIMARY KEY REFERENCES genjutsu_steps(id), status TEXT NOT NULL,
    lease_token TEXT, lease_until_ms BIGINT NOT NULL DEFAULT 0,
    next_ms BIGINT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
    message_id TEXT, error_code TEXT
);
CREATE TABLE IF NOT EXISTS genjutsu_notifications (
    run_id TEXT PRIMARY KEY REFERENCES genjutsu_runs(id), summary TEXT NOT NULL,
    status TEXT NOT NULL, created_ms BIGINT NOT NULL, deadline_ms BIGINT NOT NULL,
    max_attempts INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
    next_ms BIGINT NOT NULL, lease_token TEXT, lease_until_ms BIGINT NOT NULL DEFAULT 0,
    message_id TEXT, error_code TEXT
);
CREATE INDEX IF NOT EXISTS genjutsu_notifications_due ON genjutsu_notifications(status, next_ms);
CREATE INDEX IF NOT EXISTS genjutsu_projects_owner ON genjutsu_projects(owner, updated_ms);
CREATE INDEX IF NOT EXISTS genjutsu_runs_owner ON genjutsu_runs(owner, created_ms);
CREATE INDEX IF NOT EXISTS genjutsu_steps_due ON genjutsu_steps(status, next_poll_ms, lease_until_ms);
CREATE INDEX IF NOT EXISTS genjutsu_assets_owner ON genjutsu_assets(owner, created_ms);
CREATE INDEX IF NOT EXISTS genjutsu_events_run ON genjutsu_events(run_id, created_ms);
CREATE TABLE IF NOT EXISTS genjutsu_recipes (
    id TEXT PRIMARY KEY, owner BIGINT NOT NULL, project_id TEXT NOT NULL,
    revision INTEGER NOT NULL, verification_run_id TEXT NOT NULL,
    title TEXT NOT NULL, plan TEXT NOT NULL, user_fields TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_ms BIGINT NOT NULL, updated_ms BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS genjutsu_recipe_projects (
    project_id TEXT PRIMARY KEY REFERENCES genjutsu_projects(id),
    recipe_id TEXT NOT NULL REFERENCES genjutsu_recipes(id)
);
CREATE INDEX IF NOT EXISTS genjutsu_recipes_owner ON genjutsu_recipes(owner, updated_ms);

-- Final owned Genjutsu results published through ordinary Feed.
CREATE TABLE IF NOT EXISTS genjutsu_feed_publications (
    step_id TEXT PRIMARY KEY REFERENCES genjutsu_steps(id),
    run_id TEXT NOT NULL REFERENCES genjutsu_runs(id),
    recipe_id TEXT NOT NULL UNIQUE REFERENCES genjutsu_recipes(id),
    task_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    source_binding TEXT NOT NULL,
    created_ms BIGINT NOT NULL
);

COMMIT;
