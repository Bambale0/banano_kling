#!/usr/bin/env python3
"""Read-only, privacy-safe Lava payment cohort audit.

Produces aggregate counts only: no order IDs, payment IDs, customer details,
API calls, refunds or credits. The database transaction is repeatable-read
and read-only, including when called by an operator on production.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import sys

STATUS_SQL = """
SELECT status, count(*)
FROM transactions
WHERE provider = 'lava'
GROUP BY status ORDER BY status
"""

AGE_SQL = """
SELECT bucket, count(*) FROM (
    SELECT CASE
        WHEN created_at > (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') - interval '1 hour' THEN 'lt_1h'
        WHEN created_at > (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') - interval '1 day' THEN 'h1_to_d1'
        WHEN created_at > (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') - interval '7 days' THEN 'd1_to_d7'
        ELSE 'gte_d7'
    END AS bucket
    FROM transactions WHERE provider = 'lava' AND status = 'pending'
) ages GROUP BY bucket ORDER BY bucket
"""

ANOMALIES_SQL = """
SELECT
    (SELECT count(*) FROM transactions
     WHERE provider='lava' AND status='pending'
       AND (payment_id IS NULL OR btrim(payment_id)='')),
    (SELECT count(*) FROM
        (SELECT payment_id FROM transactions
         WHERE provider='lava' AND status='pending'
         GROUP BY payment_id HAVING count(*)>1) d),
    (SELECT count(*) FROM
        (SELECT order_id FROM transactions WHERE provider='lava'
         GROUP BY order_id HAVING count(*)>1
         AND count(*) FILTER (WHERE status='pending')>0) d),
    (SELECT count(*) FROM transactions p
     WHERE p.provider='lava' AND p.status='pending'
       AND EXISTS (SELECT 1 FROM transactions c
                   WHERE c.provider='lava' AND c.status='completed'
                     AND c.payment_id=p.payment_id AND c.id<>p.id)),
    (SELECT count(*) FROM transactions
     WHERE provider='lava' AND status='pending'
       AND (amount_rub<=0 OR credits<=0)),
    (SELECT count(*) FROM transactions p
     WHERE p.provider='lava' AND p.status='pending'
       AND NOT EXISTS
           (SELECT 1 FROM lava_payment_bindings b
            WHERE b.contract_id=p.payment_id OR b.invoice_id=p.payment_id)),
    (SELECT round((extract(epoch FROM (
       (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') - min(created_at)
     )) / 86400)::numeric, 2)
     FROM transactions WHERE provider='lava' AND status='pending')
"""

BINDINGS_SQL = """
SELECT count(*), count(*) FILTER (WHERE contract_id=invoice_id)
FROM lava_payment_bindings
"""

AGE_BUCKETS = ("lt_1h", "h1_to_d1", "d1_to_d7", "gte_d7")
ANOMALY_NAMES = (
    "pending_empty_payment_id",
    "duplicate_pending_payment_id_groups",
    "duplicate_order_groups_with_pending",
    "pending_sharing_payment_id_with_completed",
    "pending_invalid_amount_or_credits",
    "pending_unmapped_to_bindings",
)


def report_from_rows(status_rows, age_rows, anomaly_row, binding_row) -> dict:
    statuses = {str(key): int(value) for key, value in status_rows}
    ages = {key: 0 for key in AGE_BUCKETS}
    for key, value in age_rows:
        if key not in ages:
            raise ValueError("Unknown age bucket")
        ages[key] = int(value)
    if sum(ages.values()) != statuses.get("pending", 0):
        raise ValueError("Inconsistent pending totals from database snapshot")
    if len(anomaly_row) != 7 or len(binding_row) != 2:
        raise ValueError("Unexpected audit query shape")
    return {
        "audit": "lava_pending_readonly_v1",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "database_repeatable_read_read_only",
        "provider_status_checked": False,
        "payment_credits_modified": False,
        "statuses": statuses,
        "pending_age": ages,
        "checks": {
            key: int(anomaly_row[i])
            for i, key in enumerate(ANOMALY_NAMES)
        },
        "oldest_pending_days": (
            float(anomaly_row[6]) if anomaly_row[6] is not None else None
        ),
        "bindings": {
            "total": int(binding_row[0]),
            "same_contract_and_invoice_id": int(binding_row[1]),
        },
        "interpretation": (
            "Pending or unmapped does not prove paid-but-uncredited. "
            "Confirm provider payment state before any financial mutation."
        ),
    }


def audit_database(database_url: str) -> dict:
    # Import only when actually running the operational audit.
    import psycopg

    dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    with psycopg.connect(
        dsn, connect_timeout=8, autocommit=True,
        options="-c default_transaction_read_only=on",
    ) as db:
        db.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        try:
            with db.cursor() as cursor:
                cursor.execute("SHOW transaction_read_only")
                if cursor.fetchone()[0] != "on":
                    raise RuntimeError("Refusing audit without read-only transaction")
                cursor.execute(STATUS_SQL)
                status_rows = cursor.fetchall()
                cursor.execute(AGE_SQL)
                age_rows = cursor.fetchall()
                cursor.execute(ANOMALIES_SQL)
                anomalies = cursor.fetchone()
                cursor.execute(BINDINGS_SQL)
                bindings = cursor.fetchone()
            return report_from_rows(status_rows, age_rows, anomalies, bindings)
        finally:
            db.execute("ROLLBACK")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pretty", action="store_true", help="Indent JSON report")
    args = parser.parse_args(argv)
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2
    try:
        result = audit_database(dsn)
    except Exception as exc:
        # Database connection exception strings can contain server details.
        print(f"ERROR: audit failed ({type(exc).__name__})", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
