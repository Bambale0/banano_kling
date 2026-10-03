"""Transactional Genjutsu persistence using the existing SQLite/PostgreSQL seam.

No external I/O occurs inside transactions. A single control row serializes
admission and financial mutations on PostgreSQL; BEGIN IMMEDIATE does the same
on SQLite. Leases are fenced separately from durable provider attempt IDs.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from .contract import (
    CATALOG,
    PipelineError,
    default_settings,
    fingerprint,
    request_key,
    validate_settings,
)


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


async def one(db, sql: str, parameters=()) -> dict | None:
    row = await (await db.execute(sql, parameters)).fetchone()
    return dict(row) if row is not None else None


async def many(db, sql: str, parameters=()) -> list[dict]:
    return [dict(row) for row in await (await db.execute(sql, parameters)).fetchall()]


SCHEMA = [
    '''CREATE TABLE IF NOT EXISTS bot_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS genjutsu_control (id INTEGER PRIMARY KEY, config_version INTEGER NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS genjutsu_assets (
        id TEXT PRIMARY KEY, owner BIGINT NOT NULL, kind TEXT NOT NULL,
        storage_key TEXT NOT NULL UNIQUE, metadata TEXT NOT NULL, size_bytes BIGINT NOT NULL DEFAULT 0, created_ms BIGINT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS genjutsu_uploads (
        id TEXT PRIMARY KEY, owner BIGINT NOT NULL, reserved_bytes BIGINT NOT NULL, expires_ms BIGINT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS genjutsu_projects (
        id TEXT PRIMARY KEY, owner BIGINT NOT NULL, title TEXT NOT NULL, revision INTEGER NOT NULL,
        plan TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
        created_ms BIGINT NOT NULL, updated_ms BIGINT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS genjutsu_versions (
        project_id TEXT NOT NULL REFERENCES genjutsu_projects(id), revision INTEGER NOT NULL,
        plan TEXT NOT NULL, title TEXT NOT NULL, created_ms BIGINT NOT NULL,
        PRIMARY KEY(project_id,revision))''',
    '''CREATE TABLE IF NOT EXISTS genjutsu_quotes (
        id TEXT PRIMARY KEY, owner BIGINT NOT NULL, project_id TEXT NOT NULL,
        revision INTEGER NOT NULL, plan TEXT NOT NULL, quote TEXT NOT NULL,
        config_version INTEGER NOT NULL, config_hash TEXT NOT NULL,
        settings TEXT NOT NULL, expires_ms BIGINT NOT NULL, used_by TEXT,
        private_recipe INTEGER NOT NULL DEFAULT 0)''',
    '''CREATE TABLE IF NOT EXISTS genjutsu_runs (
        id TEXT PRIMARY KEY, owner BIGINT NOT NULL, project_id TEXT NOT NULL,
        quote_id TEXT NOT NULL UNIQUE, request_key TEXT NOT NULL,
        plan TEXT NOT NULL, settings TEXT NOT NULL,
        state TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0,
        admin_free INTEGER NOT NULL DEFAULT 0, private_recipe INTEGER NOT NULL DEFAULT 0,
        created_ms BIGINT NOT NULL, updated_ms BIGINT NOT NULL,
        UNIQUE(owner,request_key))''',
    '''CREATE TABLE IF NOT EXISTS genjutsu_steps (
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
        UNIQUE(run_id,variant,ordinal))''',
    '''CREATE TABLE IF NOT EXISTS genjutsu_finance (
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_id TEXT,
        owner BIGINT NOT NULL, kind TEXT NOT NULL, amount INTEGER NOT NULL,
        created_ms BIGINT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS genjutsu_events (
        id TEXT PRIMARY KEY, run_id TEXT, step_id TEXT, actor BIGINT,
        event TEXT NOT NULL, details TEXT NOT NULL, created_ms BIGINT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS genjutsu_deliveries (
        step_id TEXT PRIMARY KEY REFERENCES genjutsu_steps(id), status TEXT NOT NULL,
        lease_token TEXT, lease_until_ms BIGINT NOT NULL DEFAULT 0,
        next_ms BIGINT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        message_id TEXT, error_code TEXT)''',
    '''CREATE INDEX IF NOT EXISTS genjutsu_projects_owner ON genjutsu_projects(owner,updated_ms)''',
    '''CREATE INDEX IF NOT EXISTS genjutsu_runs_owner ON genjutsu_runs(owner,created_ms)''',
    '''CREATE INDEX IF NOT EXISTS genjutsu_steps_due ON genjutsu_steps(status,next_poll_ms,lease_until_ms)''',
    '''CREATE INDEX IF NOT EXISTS genjutsu_assets_owner ON genjutsu_assets(owner,created_ms)''',
    '''CREATE INDEX IF NOT EXISTS genjutsu_events_run ON genjutsu_events(run_id,created_ms)''',
]


class Repository:
    def __init__(self, connect: Callable, *, clock: Callable[[], int] | None = None):
        self.connect = connect
        self.clock = clock or (lambda: time.time_ns() // 1000000)

    async def migrate(self) -> None:
        async with self.connect() as db:
            execute_ddl = getattr(db, 'execute_native_ddl', db.execute)
            for sql in SCHEMA:
                await execute_ddl(sql)
            await db.execute('INSERT INTO genjutsu_control(id,config_version) VALUES(1,0) ON CONFLICT(id) DO NOTHING')
            await db.execute('INSERT INTO bot_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO NOTHING',
                             ('genjutsu.config', encode(default_settings())))
            await db.commit()

    @asynccontextmanager
    async def transaction(self):
        async with self.connect() as db:
            await db.execute('BEGIN IMMEDIATE')
            # Acquires the PostgreSQL row lock without changing config version.
            await db.execute('UPDATE genjutsu_control SET config_version=config_version WHERE id=1')
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def _event(self, db, event: str, *, run_id=None, step_id=None, actor=None, details=None):
        await db.execute('INSERT INTO genjutsu_events VALUES(?,?,?,?,?,?,?)',
                         (uuid4().hex, run_id, step_id, actor, event, encode(details or {}), self.clock()))

    async def _settings(self, db) -> tuple[dict, int]:
        row = await one(db, 'SELECT value FROM bot_settings WHERE key=?', ('genjutsu.config',))
        control = await one(db, 'SELECT config_version FROM genjutsu_control WHERE id=1')
        return validate_settings(json.loads(row['value'])), control['config_version']

    async def settings(self) -> tuple[dict, int]:
        async with self.connect() as db:
            return await self._settings(db)

    async def update_settings(self, actor: int, expected_version: int, value: dict) -> int:
        settings = validate_settings(value)
        async with self.transaction() as db:
            _, version = await self._settings(db)
            if version != expected_version:
                raise PipelineError('config_conflict', status=409)
            await db.execute('UPDATE bot_settings SET value=? WHERE key=?', (encode(settings), 'genjutsu.config'))
            await db.execute('UPDATE genjutsu_control SET config_version=config_version+1 WHERE id=1')
            await self._event(db, 'settings_updated', actor=actor,
                              details={'version': version + 1, 'settings_hash': fingerprint(settings)})
        return version + 1

    async def balance(self, owner: int) -> int | float:
        async with self.connect() as db:
            row = await one(db, 'SELECT credits FROM users WHERE telegram_id=?', (owner,))
            return row['credits'] if row else 0

    async def add_asset(self, owner: int, kind: str, storage_key: str, metadata: dict,
                        *, asset_id: str | None = None) -> dict:
        aid = asset_id or uuid4().hex
        async with self.transaction() as db:
            await db.execute('INSERT INTO genjutsu_assets(id,owner,kind,storage_key,metadata,size_bytes,created_ms) VALUES(?,?,?,?,?,?,?)',
                             (aid, owner, kind, storage_key, encode(metadata), metadata.get('size_bytes', 0), self.clock()))
        return {'id': aid, 'owner': owner, 'kind': kind, 'storage_key': storage_key, **metadata}

    async def get_assets(self, owner: int, ids: set[str], *, grants: set[str] | None = None) -> dict[str, dict]:
        if not ids:
            return {}
        if len(ids) > 200:
            raise PipelineError('too_many_assets')
        placeholders = ','.join('?' for _ in ids)
        async with self.connect() as db:
            rows = await many(db, f'SELECT * FROM genjutsu_assets WHERE id IN ({placeholders})', tuple(ids))
        result = {}
        for row in rows:
            if row['owner'] != owner and row['id'] not in (grants or set()):
                continue
            result[row['id']] = {**row, **json.loads(row['metadata'])}
        if set(result) != ids:
            raise PipelineError('asset_unavailable', status=404)
        return result

    async def get_asset_internal(self, aid: str) -> dict | None:
        async with self.connect() as db:
            row = await one(db, 'SELECT * FROM genjutsu_assets WHERE id=?', (aid,))
            return {**row, **json.loads(row['metadata'])} if row else None

    async def list_assets(self, owner: int) -> list[dict]:
        async with self.connect() as db:
            rows = await many(db, 'SELECT * FROM genjutsu_assets WHERE owner=? ORDER BY created_ms DESC LIMIT 100', (owner,))
            return [{**row, **json.loads(row['metadata'])} for row in rows]

    async def save_project(self, owner: int, title: str, plan: dict, *, project_id=None,
                           expected_revision=None) -> dict:
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
            raise PipelineError('invalid_title')
        serialized = encode(plan)
        if not isinstance(plan, dict) or len(serialized) > 150000:
            raise PipelineError('invalid_plan')
        now = self.clock()
        async with self.transaction() as db:
            if project_id:
                row = await one(db, 'SELECT * FROM genjutsu_projects WHERE id=? AND owner=?', (project_id, owner))
                if row is None:
                    raise PipelineError('project_unavailable', status=404)
                if type(expected_revision) is not int or expected_revision != row['revision']:
                    raise PipelineError('project_conflict', status=409)
                revision = row['revision'] + 1
                await db.execute('UPDATE genjutsu_projects SET title=?,plan=?,revision=?,updated_ms=? WHERE id=? AND owner=?',
                                 (title.strip(), serialized, revision, now, project_id, owner))
            else:
                project_id, revision = uuid4().hex, 1
                await db.execute('INSERT INTO genjutsu_projects(id,owner,title,revision,plan,created_ms,updated_ms) VALUES(?,?,?,?,?,?,?)',
                                 (project_id, owner, title.strip(), revision, serialized, now, now))
            await db.execute('INSERT INTO genjutsu_versions VALUES(?,?,?,?,?)',
                             (project_id, revision, serialized, title.strip(), now))
        return {'id': project_id, 'revision': revision, 'title': title.strip(), 'plan': plan}

    async def get_project(self, owner: int, project_id: str, revision: int | None = None) -> dict:
        async with self.connect() as db:
            row = await one(db, 'SELECT * FROM genjutsu_projects WHERE id=? AND owner=?', (project_id, owner))
            if row is None:
                raise PipelineError('project_unavailable', status=404)
            if revision is not None:
                snapshot = await one(db, 'SELECT * FROM genjutsu_versions WHERE project_id=? AND revision=?', (project_id, revision))
                if snapshot is None:
                    raise PipelineError('version_unavailable', status=404)
                row.update(snapshot)
            row['plan'] = json.loads(row['plan'])
            return row

    async def list_projects(self, owner: int) -> list[dict]:
        async with self.connect() as db:
            return await many(db, '''SELECT id,title,revision,updated_ms FROM genjutsu_projects
                WHERE owner=? AND archived=0 ORDER BY updated_ms DESC LIMIT 100''', (owner,))

    async def create_quote(self, owner: int, project_id: str, revision: int, plan: dict,
                           quote: dict, version: int, settings: dict, *, private_recipe=False) -> dict:
        qid, expires = uuid4().hex, self.clock() + settings['quote_ttl_seconds'] * 1000
        async with self.transaction() as db:
            project = await one(db, 'SELECT revision FROM genjutsu_projects WHERE id=? AND owner=?', (project_id, owner))
            if not project or project['revision'] != revision:
                raise PipelineError('project_conflict', status=409)
            await db.execute('''INSERT INTO genjutsu_quotes(id,owner,project_id,revision,plan,quote,
                config_version,config_hash,settings,expires_ms,private_recipe) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                (qid, owner, project_id, revision, encode(plan), encode(quote), version,
                 fingerprint(settings), encode(settings), expires, int(private_recipe)))
        return {'id': qid, 'expires_ms': expires, **quote}

    async def start(self, owner: int, key: str, quote_id: str, *, admin_free=False) -> dict:
        key = request_key(key)
        async with self.transaction() as db:
            existing = await one(db, 'SELECT id,quote_id FROM genjutsu_runs WHERE owner=? AND request_key=?', (owner, key))
            if existing:
                if existing['quote_id'] != quote_id:
                    raise PipelineError('idempotency_conflict', status=409)
                return existing
            q = await one(db, 'SELECT * FROM genjutsu_quotes WHERE id=? AND owner=?', (quote_id, owner))
            if q is None:
                raise PipelineError('quote_unavailable', status=404)
            if q['used_by']:
                return {'id': q['used_by'], 'quote_id': quote_id}
            settings, version = await self._settings(db)
            if not settings['admin_enabled' if admin_free else 'public_enabled']:
                raise PipelineError('feature_disabled', status=503)
            if q['expires_ms'] <= self.clock():
                raise PipelineError('quote_expired', status=409)
            if q['config_version'] != version or q['config_hash'] != fingerprint(settings):
                raise PipelineError('quote_changed', status=409)
            project = await one(db, 'SELECT revision FROM genjutsu_projects WHERE id=? AND owner=?', (q['project_id'], owner))
            if not project or project['revision'] != q['revision']:
                raise PipelineError('project_conflict', status=409)
            plan, quote = json.loads(q['plan']), json.loads(q['quote'])
            if not admin_free and any(s['operation'] not in settings['verified_operations'] for s in plan['steps']):
                raise PipelineError('operation_not_verified', status=503)
            active = await one(db, "SELECT COUNT(*) AS count FROM genjutsu_runs WHERE owner=? AND state IN ('running','waiting','review')", (owner,))
            if active['count'] >= settings['max_active_runs_per_user']:
                raise PipelineError('active_run_limit', status=429)
            cost = 0 if admin_free else quote['total_credits']
            if cost:
                cursor = await db.execute('UPDATE users SET credits=credits-? WHERE telegram_id=? AND credits>=?', (cost, owner, cost))
                if cursor.rowcount != 1:
                    raise PipelineError('insufficient_balance', status=402)
            now, run_id = self.clock(), uuid4().hex
            await db.execute('''INSERT INTO genjutsu_runs(id,owner,project_id,quote_id,request_key,
                plan,settings,state,admin_free,private_recipe,created_ms,updated_ms) VALUES(?,?,?,?,?,?,?,'running',?,?,?,?)''',
                (run_id, owner, q['project_id'], quote_id, key, q['plan'], q['settings'],
                 int(admin_free), q['private_recipe'], now, now))
            await db.execute('UPDATE genjutsu_quotes SET used_by=? WHERE id=?', (run_id, quote_id))
            for allocation in quote['allocations']:
                index = allocation['ordinal']
                step = plan['steps'][index]
                spec = {**step, 'provider_path': CATALOG[step['operation']]['provider_path']}
                await db.execute('''INSERT INTO genjutsu_steps(id,run_id,variant,ordinal,spec,status,
                    source_asset_id,reserved_credits,rate,next_poll_ms,created_ms,updated_ms)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (uuid4().hex, run_id, allocation['variant'], index, encode(spec),
                     'ready' if index == 0 else 'blocked', plan['source_asset_id'] if index == 0 else None,
                     0 if admin_free else allocation['reserved_credits'], allocation['credits_per_second'], now, now, now))
            await db.execute('INSERT INTO genjutsu_finance VALUES(?,?,?,?,?,?,?)',
                             ('reserve:' + run_id, run_id, None, owner, 'reserve', cost, now))
            await self._event(db, 'run_reserved', run_id=run_id, actor=owner, details={'credits': cost})
            return {'id': run_id, 'quote_id': quote_id}

    async def get_run(self, owner: int, run_id: str, *, admin=False) -> dict:
        async with self.connect() as db:
            run = await one(db, 'SELECT * FROM genjutsu_runs WHERE id=?' + ('' if admin else ' AND owner=?'),
                            (run_id,) if admin else (run_id, owner))
            if run is None:
                raise PipelineError('run_unavailable', status=404)
            run['plan'] = json.loads(run['plan'])
            run['steps'] = await many(db, '''SELECT s.*,d.status AS delivery_status,d.error_code AS delivery_error
                FROM genjutsu_steps s LEFT JOIN genjutsu_deliveries d ON d.step_id=s.id
                WHERE s.run_id=? ORDER BY s.variant,s.ordinal''', (run_id,))
            for step in run['steps']:
                step['spec'] = json.loads(step['spec'])
            return run

    async def list_runs(self, owner: int, *, project_id=None, admin=False) -> list[dict]:
        where, args = ('1=1', []) if admin else ('owner=?', [owner])
        if project_id:
            where += ' AND project_id=?'
            args.append(project_id)
        async with self.connect() as db:
            return await many(db, f'''SELECT id,project_id,state,created_ms,updated_ms FROM genjutsu_runs
                WHERE {where} ORDER BY created_ms DESC LIMIT 100''', tuple(args))

    async def _refresh_run(self, db, run_id: str) -> None:
        run = await one(db, 'SELECT cancel_requested FROM genjutsu_runs WHERE id=?', (run_id,))
        states = [r['status'] for r in await many(db, 'SELECT status FROM genjutsu_steps WHERE run_id=?', (run_id,))]
        terminal = {'completed', 'failed', 'canceled'}
        if all(state in terminal for state in states):
            if all(s == 'completed' for s in states):
                state = 'completed'
            elif 'completed' in states:
                state = 'partial'
            else:
                state = 'canceled' if run['cancel_requested'] else 'failed'
        elif 'submission_unknown' in states:
            state = 'review'
        elif all(s in terminal | {'awaiting_confirmation', 'blocked'} for s in states):
            state = 'waiting'
        else:
            state = 'running'
        await db.execute('UPDATE genjutsu_runs SET state=?,updated_ms=? WHERE id=?', (state, self.clock(), run_id))

    async def _refund(self, db, step: dict, owner: int, target: int) -> None:
        if not 0 <= target <= step['reserved_credits']:
            raise PipelineError('invalid_settlement')
        target = max(target, step['refunded_credits'])
        delta = target - step['refunded_credits']
        if delta:
            cursor = await db.execute('UPDATE users SET credits=credits+? WHERE telegram_id=?', (delta, owner))
            if cursor.rowcount != 1:
                raise PipelineError('refund_user_unavailable', status=500)
            await db.execute('INSERT INTO genjutsu_finance VALUES(?,?,?,?,?,?,?)',
                             (f"refund:{step['id']}:{target}", step['run_id'], step['id'], owner, 'refund', delta, self.clock()))
            await db.execute('UPDATE genjutsu_steps SET refunded_credits=? WHERE id=?', (target, step['id']))
            step['refunded_credits'] = target

    async def claim_step(self, settings: dict) -> dict | None:
        now = self.clock()
        async with self.transaction() as db:
            # A crashed submit cannot be distinguished from a lost response.
            stale = await many(db, "SELECT id,run_id FROM genjutsu_steps WHERE status='submitting' AND lease_until_ms<=?", (now,))
            for row in stale:
                await db.execute("UPDATE genjutsu_steps SET status='submission_unknown',lease_token=NULL,error_code='submit_outcome_unknown',updated_ms=? WHERE id=?", (now, row['id']))
                await self._event(db, 'submission_unknown', run_id=row['run_id'], step_id=row['id'])
                await self._refresh_run(db, row['run_id'])
            step = await one(db, '''SELECT s.*,r.owner,r.settings,r.cancel_requested,r.admin_free
                FROM genjutsu_steps s JOIN genjutsu_runs r ON r.id=s.run_id
                WHERE s.status IN ('queued','in_progress','storing')
                AND s.next_poll_ms<=? AND s.lease_until_ms<=?
                ORDER BY CASE WHEN s.status='storing' THEN 0 ELSE 1 END,s.next_poll_ms LIMIT 1''', (now, now))
            if step is None:
                count = await one(db, "SELECT COUNT(*) AS count FROM genjutsu_steps WHERE status IN ('submitting','submission_unknown','queued','in_progress') OR (status='ready' AND lease_until_ms>?)", (now,))
                if count['count'] >= settings['max_active_provider_tasks']:
                    return None
                step = await one(db, '''SELECT s.*,r.owner,r.settings,r.cancel_requested,r.admin_free
                    FROM genjutsu_steps s JOIN genjutsu_runs r ON r.id=s.run_id
                    WHERE s.status='ready' AND r.cancel_requested=0
                    AND s.lease_until_ms<=? AND s.next_poll_ms<=?
                    ORDER BY s.created_ms,s.variant,s.ordinal LIMIT 1''', (now, now))
            if step is None:
                return None
            token = uuid4().hex
            await db.execute('UPDATE genjutsu_steps SET lease_token=?,lease_until_ms=?,poll_count=poll_count+1 WHERE id=?',
                             (token, now + settings['lease_seconds'] * 1000, step['id']))
            step['lease_token'] = token
            step['spec'] = json.loads(step['spec'])
            step['settings'] = json.loads(step['settings'])
            return step

    async def _leased_step(self, db, step_id: str, token: str) -> dict:
        step = await one(db, '''SELECT s.*,r.owner,r.cancel_requested,r.admin_free,r.plan
            FROM genjutsu_steps s JOIN genjutsu_runs r ON r.id=s.run_id WHERE s.id=?''', (step_id,))
        if not step or step['lease_token'] != token or step['lease_until_ms'] <= self.clock():
            raise PipelineError('lease_lost', status=409)
        return step

    async def begin_submission(self, step_id: str, token: str, duration_ms: int) -> str:
        from .contract import validate_duration
        async with self.transaction() as db:
            step = await self._leased_step(db, step_id, token)
            if step['status'] != 'ready' or step['cancel_requested']:
                raise PipelineError('submission_not_allowed', status=409)
            validate_duration(duration_ms, json.loads(step['spec'])['operation'])
            actual = 0 if step['admin_free'] else ((duration_ms + 999) // 1000) * step['rate']
            if actual > step['reserved_credits']:
                raise PipelineError('quote_budget_exceeded')
            attempt = uuid4().hex
            await db.execute("UPDATE genjutsu_steps SET status='submitting',attempt_id=?,actual_credits=?,updated_ms=? WHERE id=?",
                             (attempt, actual, self.clock(), step_id))
            await self._event(db, 'submit_started', run_id=step['run_id'], step_id=step_id,
                              details={'attempt_id': attempt, 'billable_ms': duration_ms})
            return attempt

    async def accept_submission(
        self,
        step_id: str,
        attempt: str,
        provider_id: str,
        *,
        status_url: str | None = None,
        cancel_url: str | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        # Persist a late response with its durable attempt ID even if the lease
        # expired. Never create another attempt or overwrite a different ID.
        async with self.transaction() as db:
            step = await one(db, 'SELECT * FROM genjutsu_steps WHERE id=? AND attempt_id=?', (step_id, attempt))
            if not step:
                return False
            if step['provider_request_id']:
                if step['provider_request_id'] != provider_id:
                    raise PipelineError('provider_id_conflict', status=409)
                return True
            if step['status'] not in ('submitting', 'submission_unknown'):
                return False
            await db.execute("""UPDATE genjutsu_steps SET status='queued',provider_request_id=?,
                provider_status_url=?,provider_cancel_url=?,provider_correlation_id=?,
                lease_token=NULL,lease_until_ms=0,next_poll_ms=?,updated_ms=?,error_code=NULL
                WHERE id=?""",
                (provider_id, status_url, cancel_url, correlation_id,
                 self.clock(), self.clock(), step_id))
            await self._event(db, 'provider_accepted', run_id=step['run_id'], step_id=step_id,
                              details={
                                  'provider_request_id': provider_id,
                                  'provider_correlation_id': correlation_id,
                              })
            await self._refresh_run(db, step['run_id'])
            return True

    async def defer_step(self, step_id: str, token: str, *, status: str | None = None,
                          error_code: str | None = None, delay_seconds: int = 5,
                          remote_result_url: str | None = None) -> None:
        async with self.transaction() as db:
            step = await self._leased_step(db, step_id, token)
            next_status = status or step['status']
            if next_status not in ('ready', 'queued', 'in_progress', 'storing', 'submission_unknown'):
                raise PipelineError('invalid_transition')
            if next_status == 'ready' and step['attempt_id']:
                raise PipelineError('unsafe_resubmit')
            if step['status'] in ('completed', 'failed', 'canceled'):
                return
            await db.execute('''UPDATE genjutsu_steps SET status=?,error_code=?,lease_token=NULL,
                lease_until_ms=0,next_poll_ms=?,remote_result_url=COALESCE(?,remote_result_url),updated_ms=? WHERE id=?''',
                (next_status, error_code, self.clock() + delay_seconds * 1000,
                 remote_result_url, self.clock(), step_id))
            if error_code:
                await self._event(db, 'step_deferred', run_id=step['run_id'], step_id=step_id,
                                  details={'error_code': error_code, 'status': next_status})
            await self._refresh_run(db, step['run_id'])

    async def finish_step(self, step_id: str, token: str, status: str, *,
                           output_asset_id: str | None = None, error_code: str | None = None) -> None:
        if status not in ('completed', 'failed', 'canceled'):
            raise PipelineError('invalid_transition')
        async with self.transaction() as db:
            step = await self._leased_step(db, step_id, token)
            if step['status'] in ('completed', 'failed', 'canceled'):
                return
            if status == 'completed':
                asset = await one(db, 'SELECT id FROM genjutsu_assets WHERE id=? AND owner=? AND kind=?',
                                  (output_asset_id, step['owner'], 'video'))
                if not asset or step['actual_credits'] is None:
                    raise PipelineError('result_not_persisted')
            refund = (step['reserved_credits'] - step['actual_credits'] if status == 'completed'
                      else step['reserved_credits'])
            await self._refund(db, step, step['owner'], refund)
            await db.execute('''UPDATE genjutsu_steps SET status=?,output_asset_id=?,error_code=?,
                lease_token=NULL,lease_until_ms=0,updated_ms=? WHERE id=?''',
                (status, output_asset_id, error_code, self.clock(), step_id))
            plan = json.loads(step['plan'])
            if status == 'completed':
                await db.execute('INSERT INTO genjutsu_finance VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                                 ('capture:' + step_id, step['run_id'], step_id, step['owner'], 'capture',
                                  step['reserved_credits'] - step['refunded_credits'], self.clock()))
                if step['ordinal'] == len(plan['steps']) - 1 or plan['continuation'] == 'manual':
                    await db.execute("INSERT INTO genjutsu_deliveries(step_id,status,next_ms) VALUES(?,'pending',?) ON CONFLICT(step_id) DO NOTHING", (step_id, self.clock()))
                if not step['cancel_requested']:
                    next_state = 'ready' if plan['continuation'] == 'automatic' else 'awaiting_confirmation'
                    await db.execute("UPDATE genjutsu_steps SET status=?,source_asset_id=?,next_poll_ms=? WHERE run_id=? AND variant=? AND ordinal=? AND status='blocked'",
                                     (next_state, output_asset_id, self.clock(), step['run_id'], step['variant'], step['ordinal'] + 1))
            if status != 'completed' or step['cancel_requested']:
                remaining = await many(db, "SELECT * FROM genjutsu_steps WHERE run_id=? AND variant=? AND ordinal>? AND status IN ('blocked','ready','awaiting_confirmation')",
                                       (step['run_id'], step['variant'], step['ordinal']))
                for child in remaining:
                    await self._refund(db, child, step['owner'], child['reserved_credits'])
                    await db.execute("UPDATE genjutsu_steps SET status='canceled',error_code='upstream_step_stopped',updated_ms=? WHERE id=?", (self.clock(), child['id']))
            await self._event(db, 'step_' + status, run_id=step['run_id'], step_id=step_id,
                              details={'error_code': error_code})
            await self._refresh_run(db, step['run_id'])

    async def cancel(self, owner: int, run_id: str) -> None:
        async with self.transaction() as db:
            run = await one(db, 'SELECT id FROM genjutsu_runs WHERE id=? AND owner=?', (run_id, owner))
            if not run:
                raise PipelineError('run_unavailable', status=404)
            await db.execute('UPDATE genjutsu_runs SET cancel_requested=1 WHERE id=?', (run_id,))
            steps = await many(db, "SELECT * FROM genjutsu_steps WHERE run_id=? AND status IN ('ready','blocked','awaiting_confirmation')", (run_id,))
            for step in steps:
                await self._refund(db, step, owner, step['reserved_credits'])
                await db.execute("UPDATE genjutsu_steps SET status='canceled',lease_token=NULL,lease_until_ms=0,updated_ms=? WHERE id=?", (self.clock(), step['id']))
            await db.execute("UPDATE genjutsu_steps SET next_poll_ms=? WHERE run_id=? AND status IN ('queued','in_progress')", (self.clock(), run_id))
            await self._event(db, 'cancel_requested', run_id=run_id, actor=owner)
            await self._refresh_run(db, run_id)

    async def continue_run(self, owner: int, run_id: str, step_id: str) -> None:
        async with self.transaction() as db:
            run = await one(db, 'SELECT id,cancel_requested FROM genjutsu_runs WHERE id=? AND owner=?', (run_id, owner))
            if not run or run['cancel_requested']:
                raise PipelineError('run_unavailable', status=404)
            cursor = await db.execute("UPDATE genjutsu_steps SET status='ready',next_poll_ms=? WHERE id=? AND run_id=? AND status='awaiting_confirmation'",
                                      (self.clock(), step_id, run_id))
            if cursor.rowcount != 1:
                raise PipelineError('step_not_waiting', status=409)
            await self._event(db, 'step_confirmed', run_id=run_id, step_id=step_id, actor=owner)
            await self._refresh_run(db, run_id)

    async def wake_step(self, step_id: str, attempt_id: str, provider_id: str) -> None:
        await self.accept_submission(step_id, attempt_id, provider_id)
        async with self.transaction() as db:
            await db.execute('''UPDATE genjutsu_steps SET next_poll_ms=?
                WHERE id=? AND attempt_id=? AND provider_request_id=?
                AND status IN ('queued','in_progress')''',
                (self.clock(), step_id, attempt_id, provider_id))

    async def claim_delivery(self, settings: dict) -> dict | None:
        async with self.transaction() as db:
            # Telegram may have accepted a send whose response was lost.
            await db.execute("UPDATE genjutsu_deliveries SET status='delivery_unknown',error_code='delivery_outcome_unknown' WHERE status='sending' AND lease_until_ms<=?", (self.clock(),))
            row = await one(db, '''SELECT d.*,s.run_id,s.output_asset_id,r.owner FROM genjutsu_deliveries d
                JOIN genjutsu_steps s ON s.id=d.step_id JOIN genjutsu_runs r ON r.id=s.run_id
                WHERE d.status='pending' AND d.next_ms<=? ORDER BY d.next_ms LIMIT 1''', (self.clock(),))
            if not row:
                return None
            token = uuid4().hex
            await db.execute("UPDATE genjutsu_deliveries SET status='sending',lease_token=?,lease_until_ms=?,attempts=attempts+1 WHERE step_id=?",
                             (token, self.clock() + settings['lease_seconds'] * 1000, row['step_id']))
            row['lease_token'] = token
            return row

    async def finish_delivery(self, step_id: str, token: str, status: str, *,
                              message_id: str | None = None, error_code: str | None = None,
                              delay_seconds: int = 0) -> None:
        if status not in ('delivered', 'unavailable', 'delivery_unknown', 'pending'):
            raise PipelineError('invalid_delivery_status')
        async with self.transaction() as db:
            cursor = await db.execute('''UPDATE genjutsu_deliveries SET status=?,message_id=?,error_code=?,
                lease_token=NULL,lease_until_ms=0,next_ms=? WHERE step_id=? AND lease_token=?''',
                (status, message_id, error_code, self.clock() + delay_seconds * 1000, step_id, token))
            if cursor.rowcount != 1:
                raise PipelineError('lease_lost', status=409)

    async def redeliver(self, owner: int, run_id: str, step_id: str) -> None:
        async with self.transaction() as db:
            step = await one(db, '''SELECT s.id FROM genjutsu_steps s JOIN genjutsu_runs r ON r.id=s.run_id
                WHERE s.id=? AND s.run_id=? AND r.owner=? AND s.status='completed' ''', (step_id, run_id, owner))
            if not step:
                raise PipelineError('result_unavailable', status=404)
            delivery = await one(db, 'SELECT status FROM genjutsu_deliveries WHERE step_id=?', (step_id,))
            if delivery and delivery['status'] == 'sending':
                raise PipelineError('delivery_in_progress', status=409)
            await db.execute("INSERT INTO genjutsu_deliveries(step_id,status,next_ms) VALUES(?,'pending',?) ON CONFLICT(step_id) DO UPDATE SET status='pending',next_ms=excluded.next_ms", (step_id, self.clock()))
            await self._event(db, 'redelivery_requested', run_id=run_id, step_id=step_id, actor=owner)

    async def admin_refund(self, actor: int, run_id: str, step_id: str, reason: str) -> None:
        if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 200:
            raise PipelineError('refund_reason_required')
        async with self.transaction() as db:
            step = await one(db, '''SELECT s.*,r.owner FROM genjutsu_steps s JOIN genjutsu_runs r ON r.id=s.run_id
                WHERE s.id=? AND s.run_id=?''', (step_id, run_id))
            if not step:
                raise PipelineError('step_unavailable', status=404)
            await self._refund(db, step, step['owner'], step['reserved_credits'])
            # A goodwill refund must never falsely declare upstream failure.
            await self._event(db, 'admin_refund', run_id=run_id, step_id=step_id, actor=actor,
                              details={'reason': reason.strip()})

    async def events(self, run_id: str) -> list[dict]:
        async with self.connect() as db:
            return await many(db, 'SELECT event,details,actor,step_id,created_ms FROM genjutsu_events WHERE run_id=? ORDER BY created_ms LIMIT 500', (run_id,))


    async def reserve_upload(self, owner: int, size: int, settings: dict) -> str:
        from .contract import integer
        integer(size, 1, settings['result_max_bytes'], 'media_too_large')
        async with self.transaction() as db:
            await db.execute('DELETE FROM genjutsu_uploads WHERE expires_ms<=?', (self.clock(),))
            usage = await one(db, 'SELECT COALESCE(SUM(size_bytes),0) AS total,COALESCE(SUM(CASE WHEN owner=? THEN size_bytes ELSE 0 END),0) AS own FROM genjutsu_assets', (owner,))
            held = await one(db, 'SELECT COALESCE(SUM(reserved_bytes),0) AS total,COALESCE(SUM(CASE WHEN owner=? THEN reserved_bytes ELSE 0 END),0) AS own,SUM(CASE WHEN owner=? THEN 1 ELSE 0 END) AS parallel FROM genjutsu_uploads', (owner,owner))
            if usage['own'] + held['own'] + size > settings['owner_storage_bytes'] or usage['total'] + held['total'] + size > settings['total_storage_bytes']:
                raise PipelineError('storage_quota', status=409)
            if (held['parallel'] or 0) >= settings['max_parallel_uploads']:
                raise PipelineError('upload_limit', status=429)
            token = uuid4().hex
            await db.execute('INSERT INTO genjutsu_uploads VALUES(?,?,?,?)',
                             (token, owner, size, self.clock() + (settings['media_timeout_seconds'] * 4 + 60) * 1000))
            return token

    async def release_upload(self, token: str, owner: int) -> None:
        async with self.transaction() as db:
            await db.execute('DELETE FROM genjutsu_uploads WHERE id=? AND owner=?', (token, owner))

    async def commit_upload(self, token: str, owner: int, kind: str, storage_key: str, metadata: dict,
                            *, asset_id: str | None = None) -> dict:
        aid = asset_id or uuid4().hex
        if set(metadata) & {'id', 'owner', 'kind', 'metadata', 'storage_key'}:
            raise PipelineError('invalid_asset_metadata')
        async with self.transaction() as db:
            held = await one(db, 'SELECT * FROM genjutsu_uploads WHERE id=? AND owner=?', (token, owner))
            if not held or held['expires_ms'] <= self.clock():
                raise PipelineError('upload_expired', status=409)
            if type(metadata.get('size_bytes')) is not int or not 0 < metadata['size_bytes'] <= held['reserved_bytes']:
                raise PipelineError('media_too_large', status=413)
            await db.execute('INSERT INTO genjutsu_assets(id,owner,kind,storage_key,metadata,size_bytes,created_ms) VALUES(?,?,?,?,?,?,?)',
                             (aid, owner, kind, storage_key, encode(metadata), metadata['size_bytes'], self.clock()))
            await db.execute('DELETE FROM genjutsu_uploads WHERE id=?', (token,))
        return {'id': aid, 'owner': owner, 'kind': kind, 'storage_key': storage_key, **metadata}

    async def request_reconciliation(self, actor: int, run_id: str, step_id: str) -> None:
        async with self.transaction() as db:
            step = await one(db, 'SELECT id,status FROM genjutsu_steps WHERE id=? AND run_id=?', (step_id,run_id))
            if not step:
                raise PipelineError('step_unavailable', status=404)
            await db.execute('UPDATE genjutsu_steps SET next_poll_ms=? WHERE id=?', (self.clock(),step_id))
            await self._event(db, 'reconciliation_requested', run_id=run_id, step_id=step_id, actor=actor)

    async def project_versions(self, owner: int, project_id: str) -> list[dict]:
        await self.get_project(owner, project_id)
        async with self.connect() as db:
            return await many(db, 'SELECT revision,title,created_ms FROM genjutsu_versions WHERE project_id=? ORDER BY revision DESC LIMIT 100', (project_id,))

    async def existing_run(self, owner: int, key: str, quote_id: str) -> dict | None:
        async with self.connect() as db:
            row = await one(db, 'SELECT id,quote_id FROM genjutsu_runs WHERE owner=? AND request_key=?', (owner, key))
            if row and row['quote_id'] != quote_id:
                raise PipelineError('idempotency_conflict', status=409)
            return row

    async def asset_by_storage_key(self, key: str) -> dict | None:
        async with self.connect() as db:
            return await one(db, 'SELECT id FROM genjutsu_assets WHERE storage_key=?', (key,))

    async def verified_coverage(self) -> list[dict]:
        async with self.connect() as db:
            rows = await many(db, '''SELECT s.spec,s.id FROM genjutsu_steps s
                JOIN genjutsu_runs r ON r.id=s.run_id
                WHERE s.status='completed' AND s.output_asset_id IS NOT NULL
                AND s.provider_request_id IS NOT NULL AND r.admin_free=1''')
        result = {}
        for row in rows:
            spec = json.loads(row['spec'])
            result[(spec['operation'],spec['resolution'])] = {
                'operation':spec['operation'],'resolution':spec['resolution'],'step_id':row['id']}
        return list(result.values())
