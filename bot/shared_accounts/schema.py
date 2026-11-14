"""Additive preview schema; deliberately independent from legacy user wallets."""
from bot import db as db_backend

SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS shared_accounts (
        id TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'blocked', 'merged')),
        merged_into TEXT REFERENCES shared_accounts(id),
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS shared_account_identities (
        platform TEXT NOT NULL CHECK(platform IN ('telegram', 'vk')),
        external_id BIGINT NOT NULL CHECK(external_id > 0),
        account_id TEXT NOT NULL REFERENCES shared_accounts(id),
        verified_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(platform, external_id), UNIQUE(account_id, platform))''',
    '''CREATE TABLE IF NOT EXISTS shared_account_legacy_links (
        source TEXT NOT NULL CHECK(source IN ('telegram', 'vk')),
        legacy_user_id BIGINT NOT NULL,
        account_id TEXT NOT NULL REFERENCES shared_accounts(id),
        PRIMARY KEY(source, legacy_user_id))''',
    '''CREATE TABLE IF NOT EXISTS shared_account_sessions (
        token_hash TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES shared_accounts(id),
        platform TEXT NOT NULL,
        external_id BIGINT NOT NULL,
        created_at_epoch BIGINT NOT NULL,
        expires_at_epoch BIGINT NOT NULL,
        policy_revision BIGINT NOT NULL,
        revoked_at_epoch BIGINT,
        FOREIGN KEY(platform, external_id)
            REFERENCES shared_account_identities(platform, external_id))''',
    '''CREATE TABLE IF NOT EXISTS shared_vk_saved_references (
        reference_id TEXT PRIMARY KEY,
        vk_user_id BIGINT NOT NULL CHECK(vk_user_id > 0),
        url_hash TEXT NOT NULL,
        file_url TEXT NOT NULL,
        display_name TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(vk_user_id, url_hash))''',
    '''CREATE INDEX IF NOT EXISTS shared_vk_saved_references_owner
        ON shared_vk_saved_references(vk_user_id, created_at DESC)''',
    'CREATE INDEX IF NOT EXISTS shared_account_sessions_expiry ON shared_account_sessions(expires_at_epoch)',
    '''CREATE TABLE IF NOT EXISTS shared_account_policy_audit (
        id TEXT PRIMARY KEY, actor_telegram_id BIGINT NOT NULL,
        before_state TEXT NOT NULL, after_state TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)''',
)


async def ensure_schema(db) -> None:
    # Serialize first-use DDL across processes as well as asyncio tasks.
    if db_backend.is_postgres():
        await db.execute('SELECT pg_advisory_xact_lock(?)', (80420161105,))
    else:
        await db.execute('BEGIN IMMEDIATE')
    try:
        execute = getattr(db, 'execute_native_ddl', db.execute)
        for statement in SCHEMA:
            await execute(statement)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
