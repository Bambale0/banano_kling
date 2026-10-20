"""Minimal schema for the explicitly isolated runtime PostgreSQL CI service."""
import os
from contextlib import asynccontextmanager

import psycopg
from psycopg.conninfo import conninfo_to_dict

from bot import db as db_backend
from bot.postgres_pool import close_postgres_pool
from tests.test_partner_approval_postgres import (
    _bootstrap_production_like_partner_schema,
)


@asynccontextmanager
async def runtime_postgres_schema():
    if not db_backend.is_postgres():
        yield
        return

    dsn = os.environ['DATABASE_URL']
    parameters = conninfo_to_dict(dsn)
    assert os.environ.get('RUNTIME_POSTGRES_TEST') == '1'
    assert parameters.get('dbname') == 'banano_runtime_test'
    host = parameters.get('host', '')
    assert host in {'127.0.0.1', 'localhost'} or host.startswith('/')
    await _bootstrap_production_like_partner_schema()
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await connection.execute('''
            CREATE TABLE IF NOT EXISTS saved_references (
                id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id),
                kind TEXT NOT NULL, file_url TEXT NOT NULL, file_hash TEXT,
                original_filename TEXT, content_type TEXT, source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP, last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, kind, file_hash)
            )
        ''')
        await connection.execute('''
            CREATE TABLE IF NOT EXISTS user_prompts (
                id BIGSERIAL PRIMARY KEY, preview_url TEXT, status TEXT
            )
        ''')
        for name, definition in (
            ('task_id', 'TEXT UNIQUE'),
            ('user_id', 'BIGINT REFERENCES users(id)'),
            ('request_data', "TEXT DEFAULT '{}'"),
            ('updated_at', 'TIMESTAMP'),
            ('completed_at', 'TIMESTAMP'),
        ):
            await connection.execute(
                f'ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS {name} {definition}'
            )
        await connection.execute('TRUNCATE saved_references, generation_tasks')
        await connection.commit()
    try:
        yield
    finally:
        await close_postgres_pool()
