from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from scripts import audit_lava_pending_readonly as audit


def _rows():
    return (
        [("completed", 11), ("failed", 8), ("pending", 7)],
        [("lt_1h", 1), ("h1_to_d1", 2), ("gte_d7", 4)],
        (0, 0, 0, 0, 0, 7, 81.75),
        (20, 20),
    )


def test_aggregated_report_is_safe_and_does_not_claim_paid_status():
    report = audit.report_from_rows(*_rows())
    assert report["statuses"]["pending"] == 7
    assert report["pending_age"]["d1_to_d7"] == 0
    assert report["pending_age"]["gte_d7"] == 4
    assert report["checks"]["pending_unmapped_to_bindings"] == 7
    assert report["oldest_pending_days"] == 81.75
    assert report["provider_status_checked"] is False
    assert report["payment_credits_modified"] is False
    assert report["mode"] == "database_repeatable_read_read_only"
    payload = json.dumps(report)
    assert "order_id" not in payload
    assert "user_id" not in payload
    assert "payment_id=" not in payload
    assert "api_key" not in payload


def test_report_rejects_inconsistent_snapshot():
    statuses, ages, anomalies, bindings = _rows()
    with pytest.raises(ValueError, match="Inconsistent"):
        audit.report_from_rows(statuses, [("lt_1h", 2)], anomalies, bindings)
    with pytest.raises(ValueError, match="Unknown age"):
        audit.report_from_rows(statuses, [("unknown", 7)], anomalies, bindings)


def test_database_transaction_is_repeatable_read_and_only_selects(monkeypatch):
    class Cursor:
        query: str = ""

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def execute(self, query):
            q = query.strip()
            assert q.upper().startswith(("SELECT", "SHOW"))
            self.query = query

        def fetchall(self):
            if self.query == audit.STATUS_SQL:
                return _rows()[0]
            if self.query == audit.AGE_SQL:
                return _rows()[1]
            raise AssertionError("Unexpected query")

        def fetchone(self):
            if self.query == "SHOW transaction_read_only":
                return ("on",)
            if self.query == audit.ANOMALIES_SQL:
                return _rows()[2]
            if self.query == audit.BINDINGS_SQL:
                return _rows()[3]
            raise AssertionError("Unexpected query")

    class Connection:
        def __init__(self):
            self.statements = []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def execute(self, query):
            assert query in (
                "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
                "ROLLBACK",
            )
            self.statements.append(query)

        def cursor(self):
            return Cursor()

    conn = Connection()
    def fake_connect(dsn, **kwargs):
        assert dsn == "postgresql://redacted"
        assert kwargs["options"] == "-c default_transaction_read_only=on"
        assert kwargs["autocommit"] is True
        return conn

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=fake_connect))
    report = audit.audit_database("postgresql+psycopg://redacted")
    assert report["statuses"]["pending"] == 7
    assert conn.statements == [
        "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
        "ROLLBACK",
    ]


def test_missing_connection_string_fails_closed(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert audit.main([]) == 2
    assert "DATABASE_URL not set" in capsys.readouterr().err


def test_readonly_requirement_is_enforced(monkeypatch):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def execute(self, query):
            self.query = query

        def fetchone(self):
            return ("off",)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def execute(self, query):
            assert query in ("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY", "ROLLBACK")

        def cursor(self):
            return Cursor()

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(
        connect=lambda *args, **kwargs: Connection()
    ))
    with pytest.raises(RuntimeError, match="read-only"):
        audit.audit_database("postgresql://redacted")
