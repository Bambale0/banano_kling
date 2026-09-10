#!/usr/bin/env python3
"""Audit successful Lava webhooks in application logs against the transactions table.

Read-only utility. It never changes transaction state or user balances.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import gzip
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence


LOG_TIMESTAMP_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})"
)
RAW_HEADERS_RE = re.compile(
    r"Lava webhook raw headers: (?P<headers>.+?) raw_body:"
)
HOST_RE = re.compile(r"""['\"]Host['\"]\s*:\s*['\"](?P<host>[^'\"]+)['\"]""")
PARSED_RE = re.compile(
    r"Lava webhook parsed event_type=(?P<event>\S+) "
    r"status=(?P<status>\S+) data=(?P<data>\{.*\})$"
)
RECEIVED_RE = re.compile(
    r"Lava webhook received event=(?P<event>\S+)\s*"
    r"status=(?P<status>\S+)\s*"
    r"order_id=(?P<order>\S*)\s+contract_id=(?P<contract>\S*)"
)
NOT_FOUND_RE = re.compile(
    r"Lava transaction not found for order_id=(?P<order>\S*) "
    r"contract_id=(?P<contract>\S*)"
)
CANNOT_VERIFY_RE = re.compile(
    r"Lava webhook ignored: cannot verify provider status "
    r"order=(?P<order>\S+) contract_id=(?P<contract>\S*)"
)
IGNORED_STATUS_RE = re.compile(
    r"Lava success webhook ignored until provider status is completed "
    r"order=(?P<order>\S+) provider_status=(?P<status>\S+)"
)
ALREADY_COMPLETED_RE = re.compile(
    r"Lava webhook: order (?P<order>\S+) already processed, skipping"
)
FAILED_COMPLETE_RE = re.compile(
    r"Lava webhook: failed to complete order (?P<order>\S+) reason=(?P<reason>.*)$"
)

SUCCESS_EVENTS = {"payment.success", "payment_success", "success"}
SUCCESS_STATUSES = {"completed", "paid", "success", "succeeded"}


@dataclass
class SuccessWebhook:
    contract_id: str
    first_seen: datetime
    last_seen: datetime
    deliveries: int = 1
    event_type: str = ""
    provider_status: str = ""
    host: str = ""
    order_id_from_log: str = ""
    amount: float | None = None
    currency: str = ""
    buyer_email: str = ""
    product_title: str = ""
    source_files: set[str] = field(default_factory=set)
    parse_warning: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["first_seen"] = self.first_seen.isoformat(sep=" ")
        data["last_seen"] = self.last_seen.isoformat(sep=" ")
        data["source_files"] = sorted(self.source_files)
        return data


@dataclass
class LogDiagnostics:
    not_found_contracts: set[str] = field(default_factory=set)
    cannot_verify_contracts: set[str] = field(default_factory=set)
    ignored_provider_status_by_order: dict[str, str] = field(default_factory=dict)
    already_completed_orders: set[str] = field(default_factory=set)
    failed_completion_by_order: dict[str, str] = field(default_factory=dict)
    order_by_contract: dict[str, str] = field(default_factory=dict)
    invalid_json_lines: int = 0


@dataclass
class AuditRow:
    contract_id: str
    first_seen: str
    last_seen: str
    deliveries: int
    host: str
    event_type: str
    provider_status: str
    amount: float | None
    currency: str
    buyer_email: str
    product_title: str
    db_order_id: str
    db_status: str
    db_amount_rub: float | None
    db_credits: int | None
    db_user_id: int | None
    db_created_at: str
    result: str
    details: list[str]

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_timestamp(line: str) -> datetime | None:
    match = LOG_TIMESTAMP_RE.match(line)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("timestamp"), "%Y-%m-%d %H:%M:%S,%f")
    except ValueError:
        return None


def parse_cli_datetime(value: str) -> datetime:
    normalized = value.strip().replace("T", " ")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Дата должна быть в формате YYYY-MM-DD или YYYY-MM-DD HH:MM:SS"
        ) from exc


def recursive_first(value: Any, keys: Sequence[str]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if candidate not in (None, ""):
                return candidate
        for child in value.values():
            found = recursive_first(child, keys)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for child in value:
            found = recursive_first(child, keys)
            if found not in (None, ""):
                return found
    return None


def safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_success(event_type: str, status: str) -> bool:
    return event_type.lower() in SUCCESS_EVENTS or status.lower() in SUCCESS_STATUSES


def discover_log_files(patterns: Sequence[str]) -> list[Path]:
    discovered: dict[str, Path] = {}
    for pattern in patterns:
        matches = glob.glob(pattern)
        if not matches and Path(pattern).is_file():
            matches = [pattern]
        for match in matches:
            path = Path(match)
            if path.is_file():
                discovered[str(path.resolve())] = path

    return sorted(
        discovered.values(),
        key=lambda path: (path.stat().st_mtime, str(path)),
    )


def iter_log_lines(path: Path) -> Iterator[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
        yield from handle


def _new_event_key(contract_id: str, timestamp: datetime, payload: dict[str, Any]) -> str:
    if contract_id:
        return contract_id
    fallback = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return f"missing:{timestamp.isoformat()}:{hash(fallback)}"


def parse_logs(
    paths: Sequence[Path],
    *,
    since: datetime | None,
    until: datetime | None,
) -> tuple[dict[str, SuccessWebhook], LogDiagnostics]:
    events: dict[str, SuccessWebhook] = {}
    diagnostics = LogDiagnostics()

    recent_host = ""
    recent_host_at: datetime | None = None

    for path in paths:
        for line in iter_log_lines(path):
            timestamp = parse_timestamp(line)
            if timestamp is None:
                continue
            if since and timestamp < since:
                continue
            if until and timestamp > until:
                continue

            raw_match = RAW_HEADERS_RE.search(line)
            if raw_match:
                host_match = HOST_RE.search(raw_match.group("headers"))
                recent_host = host_match.group("host") if host_match else ""
                recent_host_at = timestamp
                continue

            parsed_match = PARSED_RE.search(line)
            if parsed_match:
                event_type = parsed_match.group("event")
                status = parsed_match.group("status")
                if not is_success(event_type, status):
                    continue

                try:
                    payload = json.loads(parsed_match.group("data"))
                except json.JSONDecodeError:
                    diagnostics.invalid_json_lines += 1
                    continue

                contract_id = str(
                    recursive_first(payload, ("contractId", "contract_id")) or ""
                )
                order_id = str(
                    recursive_first(payload, ("order_id", "orderId")) or ""
                )
                host = ""
                if recent_host_at and abs((timestamp - recent_host_at).total_seconds()) <= 5:
                    host = recent_host

                key = _new_event_key(contract_id, timestamp, payload)
                amount = safe_float(recursive_first(payload, ("amount",)))
                currency = str(recursive_first(payload, ("currency",)) or "")
                buyer_email = str(
                    recursive_first(payload.get("buyer", {}), ("email",)) or ""
                )
                product_title = str(
                    recursive_first(payload.get("product", {}), ("title",)) or ""
                )

                existing = events.get(key)
                if existing:
                    existing.deliveries += 1
                    existing.first_seen = min(existing.first_seen, timestamp)
                    existing.last_seen = max(existing.last_seen, timestamp)
                    existing.source_files.add(str(path))
                    if host:
                        existing.host = host
                    if order_id:
                        existing.order_id_from_log = order_id
                    continue

                events[key] = SuccessWebhook(
                    contract_id=contract_id,
                    first_seen=timestamp,
                    last_seen=timestamp,
                    event_type=event_type,
                    provider_status=status,
                    host=host,
                    order_id_from_log=order_id,
                    amount=amount,
                    currency=currency,
                    buyer_email=buyer_email,
                    product_title=product_title,
                    source_files={str(path)},
                    parse_warning="" if contract_id else "contractId отсутствует",
                )
                continue

            received_match = RECEIVED_RE.search(line)
            if received_match:
                contract_id = received_match.group("contract")
                order_id = received_match.group("order")
                if contract_id and order_id:
                    diagnostics.order_by_contract[contract_id] = order_id
                continue

            match = NOT_FOUND_RE.search(line)
            if match:
                contract_id = match.group("contract")
                if contract_id:
                    diagnostics.not_found_contracts.add(contract_id)
                continue

            match = CANNOT_VERIFY_RE.search(line)
            if match:
                contract_id = match.group("contract")
                if contract_id:
                    diagnostics.cannot_verify_contracts.add(contract_id)
                continue

            match = IGNORED_STATUS_RE.search(line)
            if match:
                diagnostics.ignored_provider_status_by_order[
                    match.group("order")
                ] = match.group("status")
                continue

            match = ALREADY_COMPLETED_RE.search(line)
            if match:
                diagnostics.already_completed_orders.add(match.group("order"))
                continue

            match = FAILED_COMPLETE_RE.search(line)
            if match:
                diagnostics.failed_completion_by_order[
                    match.group("order")
                ] = match.group("reason").strip()
                continue

    return events, diagnostics


def mask_email(value: str) -> str:
    if not value or "@" not in value:
        return value
    local, domain = value.split("@", 1)
    if len(local) <= 2:
        masked_local = local[:1] + "*"
    else:
        masked_local = local[:2] + "*" * min(6, len(local) - 2)
    return f"{masked_local}@{domain}"


async def fetch_transactions(
    payment_ids: Sequence[str],
    order_ids: Sequence[str],
) -> tuple[str, dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    from bot.env import load_project_env

    load_project_env()

    from bot import db as db_backend

    by_payment: dict[str, dict[str, Any]] = {}
    by_order: dict[str, dict[str, Any]] = {}

    payment_ids = sorted({value for value in payment_ids if value})
    order_ids = sorted({value for value in order_ids if value})

    clauses: list[str] = []
    params: list[Any] = []

    if payment_ids:
        clauses.append(
            "payment_id IN (" + ", ".join("?" for _ in payment_ids) + ")"
        )
        params.extend(payment_ids)
    if order_ids:
        clauses.append("order_id IN (" + ", ".join("?" for _ in order_ids) + ")")
        params.extend(order_ids)

    if not clauses:
        return db_backend.backend_name(), by_payment, by_order

    query = f"""
        SELECT
            order_id,
            payment_id,
            status,
            amount_rub,
            credits,
            user_id,
            created_at
        FROM transactions
        WHERE provider = 'lava'
          AND ({' OR '.join(clauses)})
        ORDER BY created_at DESC
    """

    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        rows = await (await db.execute(query, tuple(params))).fetchall()

    for row in rows:
        data = dict(row)
        payment_id = str(data.get("payment_id") or "")
        order_id = str(data.get("order_id") or "")
        if payment_id:
            by_payment[payment_id] = data
        if order_id:
            by_order[order_id] = data

    return db_backend.backend_name(), by_payment, by_order


def classify(
    event: SuccessWebhook,
    transaction: dict[str, Any] | None,
    diagnostics: LogDiagnostics,
    *,
    expected_host: str,
) -> tuple[str, list[str]]:
    details: list[str] = []
    order_id = str((transaction or {}).get("order_id") or event.order_id_from_log or "")
    db_status = str((transaction or {}).get("status") or "")

    host_mismatch = bool(
        expected_host and event.host and event.host.lower() != expected_host.lower()
    )
    if host_mismatch:
        details.append(f"host={event.host}, ожидался {expected_host}")

    if event.contract_id in diagnostics.not_found_contracts:
        details.append("в логе есть transaction not found")
    if event.contract_id in diagnostics.cannot_verify_contracts:
        details.append("провайдерный статус не удалось проверить")
    if order_id in diagnostics.ignored_provider_status_by_order:
        details.append(
            "provider_status="
            + diagnostics.ignored_provider_status_by_order[order_id]
            + " ещё не был completed"
        )
    if order_id in diagnostics.failed_completion_by_order:
        details.append(
            "complete_payment_atomic: "
            + diagnostics.failed_completion_by_order[order_id]
        )
    if order_id in diagnostics.already_completed_orders:
        details.append("повторный webhook: заказ уже был обработан")

    if not transaction:
        return (
            "HOST_MISMATCH_MISSING_DB" if host_mismatch else "MISSING_DB",
            details or ["транзакция не найдена в БД"],
        )

    if db_status != "completed":
        return (
            "HOST_MISMATCH_NOT_COMPLETED"
            if host_mismatch
            else "NOT_COMPLETED",
            details or [f"статус БД={db_status or 'пусто'}"],
        )

    if host_mismatch:
        return "HOST_MISMATCH_COMPLETED", details

    return "OK", details


def build_rows(
    events: Iterable[SuccessWebhook],
    diagnostics: LogDiagnostics,
    by_payment: dict[str, dict[str, Any]],
    by_order: dict[str, dict[str, Any]],
    *,
    expected_host: str,
    show_email: bool,
) -> list[AuditRow]:
    rows: list[AuditRow] = []

    for event in sorted(events, key=lambda item: item.first_seen):
        logged_order = (
            event.order_id_from_log
            or diagnostics.order_by_contract.get(event.contract_id, "")
        )
        transaction = by_payment.get(event.contract_id)
        if not transaction and logged_order:
            transaction = by_order.get(logged_order)

        result, details = classify(
            event,
            transaction,
            diagnostics,
            expected_host=expected_host,
        )
        if event.parse_warning:
            details.append(event.parse_warning)

        buyer_email = (
            event.buyer_email if show_email else mask_email(event.buyer_email)
        )

        rows.append(
            AuditRow(
                contract_id=event.contract_id,
                first_seen=event.first_seen.isoformat(sep=" "),
                last_seen=event.last_seen.isoformat(sep=" "),
                deliveries=event.deliveries,
                host=event.host,
                event_type=event.event_type,
                provider_status=event.provider_status,
                amount=event.amount,
                currency=event.currency,
                buyer_email=buyer_email,
                product_title=event.product_title,
                db_order_id=str((transaction or {}).get("order_id") or ""),
                db_status=str((transaction or {}).get("status") or ""),
                db_amount_rub=safe_float((transaction or {}).get("amount_rub")),
                db_credits=(
                    int((transaction or {}).get("credits"))
                    if (transaction or {}).get("credits") is not None
                    else None
                ),
                db_user_id=(
                    int((transaction or {}).get("user_id"))
                    if (transaction or {}).get("user_id") is not None
                    else None
                ),
                db_created_at=str((transaction or {}).get("created_at") or ""),
                result=result,
                details=details,
            )
        )

    return rows


def print_text_report(
    rows: Sequence[AuditRow],
    *,
    backend: str,
    paths: Sequence[Path],
    since: datetime | None,
    until: datetime | None,
    invalid_json_lines: int,
) -> None:
    print("Аудит успешных Lava webhook")
    print(f"База: {backend}")
    print(
        "Период: "
        + (since.isoformat(sep=" ") if since else "начало логов")
        + " — "
        + (until.isoformat(sep=" ") if until else "сейчас")
    )
    print("Логи: " + ", ".join(str(path) for path in paths))
    print()

    if not rows:
        print("Успешные webhook за выбранный период не найдены.")
        if invalid_json_lines:
            print(f"Не удалось разобрать JSON-строк: {invalid_json_lines}")
        return

    for row in rows:
        amount = (
            f"{row.amount:g} {row.currency}".strip()
            if row.amount is not None
            else "сумма неизвестна"
        )
        print(
            f"[{row.result}] {row.first_seen} "
            f"contract={row.contract_id or '-'} "
            f"{amount} deliveries={row.deliveries}"
        )
        print(
            f"  host={row.host or '-'} buyer={row.buyer_email or '-'} "
            f"product={row.product_title or '-'}"
        )
        print(
            f"  order={row.db_order_id or '-'} db_status={row.db_status or '-'} "
            f"credits={row.db_credits if row.db_credits is not None else '-'} "
            f"user_id={row.db_user_id if row.db_user_id is not None else '-'}"
        )
        if row.details:
            print("  детали: " + "; ".join(row.details))
        print()

    summary: dict[str, int] = defaultdict(int)
    for row in rows:
        summary[row.result] += 1

    print("Итого:")
    print(f"  уникальных успешных платежей: {len(rows)}")
    print(f"  доставок webhook: {sum(row.deliveries for row in rows)}")
    for result in sorted(summary):
        print(f"  {result}: {summary[result]}")
    if invalid_json_lines:
        print(f"  JSON parse errors: {invalid_json_lines}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Находит успешные Lava webhook в логах и сверяет их "
            "с production-таблицей transactions. Только чтение."
        )
    )
    parser.add_argument(
        "--log",
        action="append",
        default=[],
        help=(
            "Путь или glob логов. Можно повторять. "
            "По умолчанию: logs/bot.log*"
        ),
    )
    period = parser.add_mutually_exclusive_group()
    period.add_argument(
        "--hours",
        type=float,
        default=24.0,
        help="Проверять последние N часов (по умолчанию 24)",
    )
    period.add_argument(
        "--since",
        type=parse_cli_datetime,
        help="Начало периода: YYYY-MM-DD или YYYY-MM-DD HH:MM:SS",
    )
    period.add_argument(
        "--all",
        action="store_true",
        help="Проверить все доступные логи",
    )
    parser.add_argument(
        "--until",
        type=parse_cli_datetime,
        help="Конец периода: YYYY-MM-DD или YYYY-MM-DD HH:MM:SS",
    )
    parser.add_argument(
        "--expected-host",
        default="tanyapi.chillcreative.ru",
        help=(
            "Ожидаемый Host для этого приложения. "
            "По умолчанию tanyapi.chillcreative.ru"
        ),
    )
    parser.add_argument(
        "--show-email",
        action="store_true",
        help="Не маскировать email покупателей",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Не подключаться к БД; вывести только события из логов",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Вывести результат в JSON",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Вернуть exit code 1 при любом результате, отличном от OK. "
            "Удобно для cron/мониторинга."
        ),
    )
    return parser


async def async_main(args: argparse.Namespace) -> int:
    patterns = args.log or ["logs/bot.log*"]
    paths = discover_log_files(patterns)
    if not paths:
        print(
            "Логи не найдены. Передай путь через --log, например "
            "--log 'logs/bot.log*'",
            file=sys.stderr,
        )
        return 2

    until = args.until
    if args.all:
        since = None
    elif args.since:
        since = args.since
    else:
        reference = until or datetime.now()
        since = reference - timedelta(hours=max(args.hours, 0))

    events_map, diagnostics = parse_logs(paths, since=since, until=until)
    events = list(events_map.values())

    backend = "disabled"
    by_payment: dict[str, dict[str, Any]] = {}
    by_order: dict[str, dict[str, Any]] = {}

    if not args.no_db:
        payment_ids = [event.contract_id for event in events if event.contract_id]
        order_ids = [
            event.order_id_from_log
            or diagnostics.order_by_contract.get(event.contract_id, "")
            for event in events
        ]
        backend, by_payment, by_order = await fetch_transactions(
            payment_ids,
            order_ids,
        )

    rows = build_rows(
        events,
        diagnostics,
        by_payment,
        by_order,
        expected_host=args.expected_host,
        show_email=args.show_email,
    )

    if args.no_db:
        for row in rows:
            if row.result in {"MISSING_DB", "HOST_MISMATCH_MISSING_DB"}:
                row.result = (
                    "HOST_MISMATCH_LOG_ONLY"
                    if row.result.startswith("HOST_MISMATCH")
                    else "LOG_ONLY"
                )
                row.details = [
                    detail
                    for detail in row.details
                    if detail != "транзакция не найдена в БД"
                ]

    if args.json:
        print(
            json.dumps(
                {
                    "backend": backend,
                    "period": {
                        "since": since.isoformat(sep=" ") if since else None,
                        "until": until.isoformat(sep=" ") if until else None,
                    },
                    "logs": [str(path) for path in paths],
                    "invalid_json_lines": diagnostics.invalid_json_lines,
                    "rows": [row.to_json_dict() for row in rows],
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    else:
        print_text_report(
            rows,
            backend=backend,
            paths=paths,
            since=since,
            until=until,
            invalid_json_lines=diagnostics.invalid_json_lines,
        )

    if args.strict and any(row.result != "OK" for row in rows):
        return 1
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Ошибка аудита: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
