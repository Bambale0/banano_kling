"""Read-only operational gates complement the existing precision audit.

No user rows, balances per identity, provider secrets or migrations are involved.
"""
import pytest

from scripts.audit_shared_account_migration import _operational_snapshot, _status_counts


class Rows:
    def __init__(self, values):
        self.values = values

    def fetchall(self):
        return self.values

    def fetchone(self):
        return self.values[0]


class ReadOnlyConnection:
    def __init__(self, *, wallet_tables=True):
        self.queries = []
        self.wallet_tables = wallet_tables

    def execute(self, query, params=None):
        self.queries.append((query, params))
        assert query.lstrip().upper().startswith("SELECT")
        if "information_schema.tables" in query:
            return Rows([(self.wallet_tables,)])
        if "FROM generation_tasks" in query and "GROUP BY status, model" in query:
            return Rows([
                ("processing", "wan_3", 2, 2),
                ("pending", "banana_2", 1, 0),
                ("recovering", "unknown_model", 3, 3),
            ])
        if "FROM generation_tasks" in query:
            return Rows([
                ("completed", 500), ("failed", 50),
                ("processing", 2), ("pending", 1), ("recovering", 3),
            ])
        if "FROM transactions" in query and "GROUP BY COALESCE(provider" in query:
            return Rows([
                ("robokassa", 20, 20, 18, 10),
                ("telegram_stars", 3, 1, 1, 0),
            ])
        if "FROM transactions" in query:
            return Rows([("completed", 200), ("failed", 10), ("pending", 23)])
        if "FROM shared_wallets" in query:
            return Rows([("live", 40, 0, 0), ("sandbox", 40, 0, 0)])
        if "FROM shared_wallet_opening_claims" in query:
            return Rows([])
        raise AssertionError(f"Unexpected query: {query!r}")


def test_preflight_blocks_uncertain_payment_and_generation_without_database_writes():
    db = ReadOnlyConnection()
    report = _operational_snapshot(db)
    assert report["legacy_generation_status_counts"] == {
        "completed": 500, "failed": 50, "processing": 2,
        "pending": 1, "recovering": 3,
    }
    assert report["legacy_transaction_status_counts"]["pending"] == 23
    assert report["nonterminal_generations"] == 6
    assert report["unreconciled_transaction_statuses"] == 23
    assert report["pending_transactions_by_provider_age"] == [
        {"provider": "robokassa", "pending": 20, "older_1d": 20,
         "older_7d": 18, "older_30d": 10},
        {"provider": "telegram_stars", "pending": 3, "older_1d": 1,
         "older_7d": 1, "older_30d": 0},
    ]
    assert report["unresolved_generations_by_model_age"] == [
        {"status": "processing", "model": "wan_3", "count": 2, "older_1d": 2},
        {"status": "pending", "model": "banana_2", "count": 1, "older_1d": 0},
        {"status": "recovering", "model": "unknown_model",
         "count": 3, "older_1d": 3},
    ]
    assert report["wallet_scopes"]["live"] == {
        "wallets": 40, "available_units": "0", "reserved_units": "0",
    }
    assert report["wallet_scopes"]["sandbox"]["wallets"] == 40
    assert report["opening_claims_by_scope"] == {}
    assert report["production_cutover_authorized"] is False
    blockers = report["cutover_blockers"]
    assert "legacy_writers_not_fenced" in blockers
    assert "unresolved_generation_jobs" in blockers
    assert "unreconciled_legacy_transactions" in blockers
    assert "opening_snapshot_not_approved" in blockers
    assert all(sql.lstrip().upper().startswith("SELECT") for sql, _ in db.queries)
    assert "provider_secret" not in str(report)
    assert "account_id" not in str(report)


def test_preflight_requires_evidence_even_when_all_legacy_statuses_terminal():
    db = ReadOnlyConnection()
    original = db.execute

    def terminal_only(query, params=None):
        if "FROM generation_tasks" in query and "GROUP BY status, model" in query:
            return Rows([])
        if "FROM generation_tasks" in query:
            return Rows([("completed", 99), ("failed", 1)])
        if "FROM transactions" in query and "GROUP BY COALESCE(provider" in query:
            return Rows([])
        if "FROM transactions" in query:
            return Rows([("completed", 88), ("failed", 12)])
        return original(query, params)

    db.execute = terminal_only
    report = _operational_snapshot(db)
    assert report["nonterminal_generations"] == 0
    assert report["unreconciled_transaction_statuses"] == 0
    assert report["production_cutover_authorized"] is False
    assert "legacy_writers_not_fenced" in report["cutover_blockers"]
    assert "opening_snapshot_not_approved" in report["cutover_blockers"]


def test_preflight_fails_closed_when_shared_wallet_schema_is_not_present():
    db = ReadOnlyConnection(wallet_tables=False)
    report = _operational_snapshot(db)
    assert report["wallet_scopes"] is None
    assert report["opening_claims_by_scope"] is None
    assert "shared_wallet_schema_unverified" in report["cutover_blockers"]
    assert report["production_cutover_authorized"] is False


def test_status_table_name_is_hard_whitelisted_before_any_sql():
    db = ReadOnlyConnection()
    with pytest.raises(ValueError):
        _status_counts(db, "users; DELETE FROM shared_wallets")
    assert db.queries == []


def test_preflight_fails_closed_on_inconsistent_payment_or_job_status_totals():
    db = ReadOnlyConnection()
    original = db.execute

    def missing_provider_events(query, params=None):
        if "FROM transactions" in query and "GROUP BY COALESCE(provider" in query:
            return Rows([("robokassa", 22, 22, 22, 22)])
        return original(query, params)

    db.execute = missing_provider_events
    with pytest.raises(RuntimeError, match="Inconsistent pending transaction"):
        _operational_snapshot(db)

    another = ReadOnlyConnection()
    original = another.execute

    def missing_unfinished_task(query, params=None):
        if "FROM generation_tasks" in query and "GROUP BY status, model" in query:
            return Rows([("processing", "wan_3", 2, 2)])
        return original(query, params)

    another.execute = missing_unfinished_task
    with pytest.raises(RuntimeError, match="Inconsistent generation"):
        _operational_snapshot(another)
