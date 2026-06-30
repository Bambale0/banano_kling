from pathlib import Path

from scripts.migrate_sqlite_to_postgres import TABLES


def _columns_from_schema(schema: str, table_name: str) -> set[str]:
    marker = f"CREATE TABLE IF NOT EXISTS {table_name} ("
    start = schema.index(marker) + len(marker)
    end = schema.index("\n);", start)
    block = schema[start:end]
    columns: set[str] = set()
    for raw_line in block.splitlines():
        line = raw_line.strip().rstrip(",")
        if not line or line.startswith("--"):
            continue
        token = line.split()[0]
        if token.upper() in {"CONSTRAINT", "FOREIGN", "PRIMARY", "UNIQUE"}:
            continue
        columns.add(token)
    return columns


def test_generation_tasks_schema_covers_runtime_and_migration_columns():
    schema = Path("migrations/postgres_schema_v2.sql").read_text(encoding="utf-8")
    generation_spec = next(spec for spec in TABLES if spec.name == "generation_tasks")
    generation_columns = _columns_from_schema(schema, "generation_tasks")

    # Migration script must cover all declared source columns.
    assert set(generation_spec.columns) <= generation_columns

    # Regression guard: runtime SQLite schema has newer fields used by feed/subscription flows.
    assert {"published_at", "feed_status"} <= generation_columns
    # Current SQLite runtime writes these fields during post-migration app execution too.
    assert {"billing_source", "subscription_usage_id"} <= generation_columns


def test_feed_interactions_schema_exists_for_feed_metrics():
    schema = Path("migrations/postgres_schema_v2.sql").read_text(encoding="utf-8")
    feed_columns = _columns_from_schema(schema, "feed_interactions")

    assert {"task_id", "telegram_id", "action", "created_at"} <= feed_columns
