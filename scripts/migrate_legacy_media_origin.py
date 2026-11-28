"""Rewrite live NEUROMIX media locators, not provider/payment snapshots.

Dry-run by default; apply in small transactions with a database rollback journal.
Execute with the production application's environment; never put the DSN in CLI/logs.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit, urlunsplit

from psycopg import sql

LEGACY_HOSTS = frozenset({"tanyapp.chillcreative.ru", "tanyapp.xn--e1aikcel5c5a.online"})
PATTERNS = tuple(f"%://{host}/uploads/%" for host in sorted(LEGACY_HOSTS))
JOURNAL = "ops_media_origin_migration_journal"


@dataclass(frozen=True)
class Target:
    table: str
    pk: str
    pk_type: str
    fields: tuple[tuple[str, bool], ...]
    terminal_only: bool = False


TARGETS = (
    Target("generation_tasks", "id", "bigint", (
        ("result_url", False), ("result_urls", True), ("request_data", True),
        ("feed_reference_selection", True), ("feed_repeat_reference_selection", True),
    ), True),
    Target("saved_references", "id", "bigint", (("file_url", False),)),
    Target("generation_repeat_personalization", "generation_id", "bigint", (("fields_json", True),)),
    Target("user_prompts", "id", "bigint", (("preview_url", False),)),
    Target("trend_reference_assets", "id", "bigint", (("file_url", False),)),
    Target("trend_catalog_preview_assets", "source_key", "text", (("thumbnail_url", False),)),
    Target("trend_catalog_live_video_assets", "source_key", "text", (("preview_url", False),)),
    Target("wan3_prime_media", "id", "bigint", (("public_url", False),)),
    Target("wan3_prime_intents", "id", "bigint", (("result_url", False),)),
    Target("wan3_prime_upload_sessions", "upload_id", "text", (("completed_result", True),)),
    Target("seedance_provider_routes", "task_id", "text", (("result_url", False),)),
    Target("kling4_intents", "task_id", "text", (("result_url", False),)),
    Target("genjutsu_steps", "id", "text", (("remote_result_url", False),)),
    Target("users", "id", "bigint", (("photo_url", False),)),
    Target("web_generation_tasks", "task_id", "text", (
        ("result_url", False), ("bundle_url", False), ("outputs_json", True),
    )),
    Target("web_generation_references", "reference_id", "text", (("url", False),)),
)


def validate_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or parsed.port not in (None, 443) or parsed.hostname in LEGACY_HOSTS):
        raise ValueError("STATIC_BASE_URL must be a non-legacy HTTPS origin")
    return origin.rstrip("/")


def canonical_url(value: str, origin: str) -> str:
    if not isinstance(value, str) or not any(host in value for host in LEGACY_HOSTS):
        return value
    try:
        p = urlsplit(value)
        if (p.scheme not in ("http", "https") or p.hostname not in LEGACY_HOSTS
                or p.username or p.password or p.port is not None
                or not p.path.startswith("/uploads/") or p.path == "/uploads/"
                or any(part in (".", "..") for part in unquote(p.path).split("/"))):
            return value
        base = urlsplit(origin)
        return urlunsplit((base.scheme, base.netloc, p.path, p.query, p.fragment))
    except ValueError:
        return value


def rewrite_value(value, origin: str, structured: bool):
    if not isinstance(value, str):
        return value
    if not structured:
        return canonical_url(value, origin)
    if not any(host in value for host in LEGACY_HOSTS):
        return value
    try:
        obj = json.loads(value)
    except (ValueError, TypeError):
        return value

    def walk(item):
        if isinstance(item, str):
            return canonical_url(item, origin)
        if isinstance(item, list):
            return [walk(v) for v in item]
        if isinstance(item, dict):
            return {k: walk(v) for k, v in item.items()}
        return item

    updated = walk(obj)
    return json.dumps(updated, ensure_ascii=False, separators=(",", ":")) if updated != obj else value


def create_journal(conn):
    conn.execute(sql.SQL("""
        CREATE TABLE IF NOT EXISTS {} (
            id bigserial PRIMARY KEY, run_id text NOT NULL,
            table_name text NOT NULL, row_id text NOT NULL, column_name text NOT NULL,
            old_value text NOT NULL, new_value text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            restored_at timestamptz,
            UNIQUE (run_id, table_name, row_id, column_name)
        )""").format(sql.Identifier(JOURNAL)))


def scan_target(conn, target, origin, *, apply=False, run_id="", batch=500, sleep_ms=25):
    """Keyset batches; skip busy rows, rerun dry-run to detect residuals."""
    fields = [name for name, _ in target.fields]
    pk = sql.Identifier(target.pk)
    table = sql.Identifier(target.table)
    identifiers = [sql.Identifier(name) for name in fields]
    predicates = sql.SQL(" OR ").join(
        sql.SQL("{} LIKE ANY(%s)").format(name) for name in identifiers
    )
    last_pk = None
    counts = dict.fromkeys(fields, 0)
    rows_changed = 0
    while True:
        params = [list(PATTERNS)] * len(fields)
        where = sql.SQL("({})").format(predicates)
        if target.terminal_only:
            where += sql.SQL(" AND status IN ('completed','failed')")
        if last_pk is not None:
            where += sql.SQL(" AND {} > %s").format(pk)
            params.append(last_pk)
        params.append(batch)
        query = sql.SQL("SELECT {},{} FROM {} WHERE {} ORDER BY {} LIMIT %s").format(
            pk, sql.SQL(",").join(identifiers), table, where, pk,
        )
        if apply:
            query += sql.SQL(" FOR UPDATE SKIP LOCKED")
        with conn.transaction():
            conn.execute("SET LOCAL lock_timeout = '2s'")
            conn.execute("SET LOCAL statement_timeout = '20s'")
            rows = conn.execute(query, params).fetchall()
            if not rows:
                break
            last_pk = rows[-1][0]
            changed_rows = []
            journal_rows = []
            for row in rows:
                row_id, *values = row
                updated = [rewrite_value(v, origin, structured) for v, (_, structured) in zip(values, target.fields)]
                if updated == values:
                    continue
                rows_changed += 1
                changed_rows.append((row_id, *updated))
                for field, old, new in zip(fields, values, updated):
                    if old != new:
                        counts[field] += 1
                        journal_rows.append((str(row_id), field, old, new))
            if apply and changed_rows:
                conn.execute(sql.SQL("""
                    INSERT INTO {} (run_id,table_name,row_id,column_name,old_value,new_value)
                    SELECT %s,%s,* FROM unnest(%s::text[],%s::text[],%s::text[],%s::text[])
                """).format(sql.Identifier(JOURNAL)),
                    [run_id, target.table, *[list(col) for col in zip(*journal_rows)]])
                types = [target.pk_type] + ["text"] * len(fields)
                casts = sql.SQL(",").join(sql.SQL("%s::{}[]").format(sql.SQL(t)) for t in types)
                alias_fields = [sql.Identifier("row_pk")] + identifiers
                assignments = sql.SQL(",").join(
                    sql.SQL("{}=v.{}").format(f, f) for f in identifiers
                )
                updated_rows = conn.execute(sql.SQL("""
                    UPDATE {} AS t SET {} FROM unnest({}) AS v({})
                    WHERE t.{}=v.row_pk
                """).format(table, assignments, casts, sql.SQL(",").join(alias_fields), pk),
                    [list(col) for col in zip(*changed_rows)]).rowcount
                if updated_rows != len(changed_rows):
                    raise RuntimeError("row count mismatch: rolling back batch")
        if apply and sleep_ms:
            time.sleep(sleep_ms / 1000)
    return rows_changed, counts


def rollback_run(conn, run_id, *, batch=500):
    """Restore only cells still equal to the migrated value, never newer writes."""
    targets = {t.table: t for t in TARGETS}
    restored = conflicts = 0
    cursor = 0
    while True:
        with conn.transaction():
            conn.execute("SET LOCAL lock_timeout = '2s'")
            conn.execute("SET LOCAL statement_timeout = '20s'")
            rows = conn.execute(sql.SQL("""
                SELECT id,table_name,row_id,column_name,old_value,new_value FROM {}
                WHERE run_id=%s AND restored_at IS NULL AND id>%s
                ORDER BY id LIMIT %s FOR UPDATE
            """).format(sql.Identifier(JOURNAL)), (run_id, cursor, batch)).fetchall()
            if not rows:
                break
            cursor = rows[-1][0]
            groups = {}
            for jid, table_name, row_id, field, old, new in rows:
                target = targets.get(table_name)
                if target is None or field not in dict(target.fields):
                    raise RuntimeError("journal contains a field outside the migration allowlist")
                groups.setdefault((target, field), []).append((jid, row_id, old, new))
            for (target, field), group in groups.items():
                col = sql.Identifier(field)
                ids = [g[0] for g in group]
                updated = conn.execute(sql.SQL("""
                    UPDATE {} AS t SET {}=v.old_value
                    FROM unnest(%s::bigint[],%s::{}[],%s::text[],%s::text[])
                    AS v(jid,row_pk,old_value,new_value)
                    WHERE t.{}=v.row_pk AND t.{}=v.new_value RETURNING v.jid
                """).format(sql.Identifier(target.table), col, sql.SQL(target.pk_type),
                             sql.Identifier(target.pk), col),
                    [ids, [int(g[1]) if target.pk_type == "bigint" else g[1] for g in group],
                     [g[2] for g in group], [g[3] for g in group]]).fetchall()
                done = [r[0] for r in updated]
                if done:
                    conn.execute(sql.SQL("UPDATE {} SET restored_at=now() WHERE id=ANY(%s)").format(
                        sql.Identifier(JOURNAL)), (done,))
                restored += len(done)
                conflicts += len(group) - len(done)
    return restored, conflicts


def main():
    import psycopg

    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--rollback-run")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--batch", type=int, default=500)
    parser.add_argument("--sleep-ms", type=int, default=25)
    parser.add_argument("--table", action="append", choices=[t.table for t in TARGETS])
    args = parser.parse_args()
    if not 1 <= args.batch <= 2000 or not 0 <= args.sleep_ms <= 1000:
        parser.error("batch must be 1..2000, sleep-ms 0..1000")
    origin = validate_origin(os.environ["STATIC_BASE_URL"])
    dsn = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    run_id = args.run_id or uuid.uuid4().hex
    with psycopg.connect(dsn, connect_timeout=5, autocommit=True) as conn:
        if args.rollback_run:
            print("restored/conflicts:", rollback_run(conn, args.rollback_run, batch=args.batch), flush=True)
            return
        if args.apply:
            create_journal(conn)
            print("apply run_id:", run_id, flush=True)
        else:
            conn.execute("SET default_transaction_read_only = on")
            print("dry-run", flush=True)
        for target in TARGETS:
            if args.table and target.table not in args.table:
                continue
            rows, counts = scan_target(conn, target, origin, apply=args.apply,
                                       run_id=run_id, batch=args.batch, sleep_ms=args.sleep_ms)
            print(target.table, "rows=", rows, "fields=", counts, flush=True)


if __name__ == "__main__":
    main()
