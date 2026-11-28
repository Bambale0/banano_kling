import json
import os
import uuid

import pytest

from scripts import migrate_legacy_media_origin as migration

OLD = "https://tanyapp.chillcreative.ru/uploads/feed/example.png"
OLD_ALT = "https://tanyapp.xn--e1aikcel5c5a.online/uploads/refs/image/example.png"
ORIGIN = "https://neuromixbot.com"
NEW = ORIGIN + "/uploads/feed/example.png"
NEW_ALT = ORIGIN + "/uploads/refs/image/example.png"


@pytest.mark.parametrize("old,new", [
    (OLD, NEW), (OLD_ALT, NEW_ALT), (OLD + "?download=1#x", NEW + "?download=1#x"),
    ("https://tanyapp.chillcreative.ru.evil.invalid/uploads/x", "https://tanyapp.chillcreative.ru.evil.invalid/uploads/x"),
    ("https://example.invalid/?redirect=" + OLD, "https://example.invalid/?redirect=" + OLD),
    ("https://tanyapp.chillcreative.ru/genjutsu/media/x?signature=abc", "https://tanyapp.chillcreative.ru/genjutsu/media/x?signature=abc"),
    ("https://user@tanyapp.chillcreative.ru/uploads/x", "https://user@tanyapp.chillcreative.ru/uploads/x"),
    ("https://tanyapp.chillcreative.ru/uploads/../x", "https://tanyapp.chillcreative.ru/uploads/../x"),
    ("https://tanyapi.chillcreative.ru/webhook/kie_ai", "https://tanyapi.chillcreative.ru/webhook/kie_ai"),
    (NEW, NEW),
])
def test_canonicalize_exact_owned_upload(old, new):
    assert migration.canonical_url(old, ORIGIN) == new


def test_nested_json_only_rewrites_standalone_urls_not_keys_or_prompt_text():
    obj = {"references": [OLD, {"url": OLD_ALT}], OLD: OLD,
           "prompt": "Please use " + OLD, "redirect": "https://external.invalid/?url=" + OLD}
    result = json.loads(migration.rewrite_value(json.dumps(obj), ORIGIN, True))
    assert result == {"references": [NEW, {"url": NEW_ALT}], OLD: NEW,
                      "prompt": obj["prompt"], "redirect": obj["redirect"]}
    assert migration.rewrite_value("not JSON " + OLD, ORIGIN, True) == "not JSON " + OLD


@pytest.mark.skipif(not os.getenv("MEDIA_ORIGIN_TEST_DSN"), reason="isolated PostgreSQL fixture only")
def test_batch_journal_idempotency_terminal_status_and_compare_swap_rollback():
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict

    dsn = os.environ["MEDIA_ORIGIN_TEST_DSN"]
    assert conninfo_to_dict(dsn).get("dbname") == "media_origin_test"
    schema = "test_media_origin_" + uuid.uuid4().hex
    target = migration.TARGETS[0]
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            conn.execute("""CREATE TABLE generation_tasks(
                id bigint PRIMARY KEY, status text, result_url text, result_urls text,
                request_data text, feed_reference_selection text, feed_repeat_reference_selection text
            )""")
            conn.execute("INSERT INTO generation_tasks VALUES (%s,%s,%s,%s,%s,NULL,NULL)",
                         (1, "completed", OLD, json.dumps([OLD_ALT]), json.dumps({"reference_images":[OLD]})))
            conn.execute("INSERT INTO generation_tasks VALUES (%s,%s,%s,NULL,NULL,NULL,NULL)",
                         (2, "processing", OLD))
            conn.execute("INSERT INTO generation_tasks VALUES (%s,%s,%s,NULL,NULL,NULL,NULL)",
                         (3, "failed", OLD_ALT))
            assert migration.scan_target(conn, target, ORIGIN, batch=1)[0] == 2
            assert conn.execute("SELECT result_url FROM generation_tasks WHERE id=1").fetchone()[0] == OLD
            migration.create_journal(conn)
            rows, counts = migration.scan_target(conn, target, ORIGIN, apply=True, run_id="run", batch=1, sleep_ms=0)
            assert rows == 2 and sum(counts.values()) == 4
            assert migration.scan_target(conn, target, ORIGIN, batch=1)[0] == 0
            assert conn.execute("SELECT result_url FROM generation_tasks WHERE id=2").fetchone()[0] == OLD
            assert conn.execute("SELECT count(*) FROM ops_media_origin_migration_journal").fetchone()[0] == 4
            conn.execute("UPDATE generation_tasks SET result_url=%s WHERE id=3", ("https://example.invalid/new",))
            assert migration.rollback_run(conn, "run", batch=1) == (3, 1)
            assert conn.execute("SELECT result_url FROM generation_tasks WHERE id=1").fetchone()[0] == OLD
            assert conn.execute("SELECT result_url FROM generation_tasks WHERE id=3").fetchone()[0] == "https://example.invalid/new"
        finally:
            conn.execute("SET search_path TO public")
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_retired_nginx_origins_only_redirect_except_historical_genjutsu():
    from pathlib import Path
    root = Path("ops/nginx")
    for host in sorted(migration.LEGACY_HOSTS):
        config = (root / f"{host}.conf").read_text()
        assert config.count("return 307 https://neuromixbot.com$request_uri;") == 2
        assert config.count("return 307 https://neuromixbot.com/mini-app/$is_args$args;") == 2
        assert "try_files" not in config
        assert "location /uploads/" not in config
        assert "location ^~ /mini-app/api/" not in config
        assert config.count("proxy_pass") == int(host.endswith("online"))
