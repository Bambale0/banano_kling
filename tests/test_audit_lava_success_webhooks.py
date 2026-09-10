from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_lava_success_webhooks.py"
SPEC = importlib.util.spec_from_file_location("audit_lava_success_webhooks", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _write_log(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "bot.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _success_lines(contract_id: str = "contract-1", host: str = "tanyapi.chillcreative.ru") -> list[str]:
    return [
        (
            "2026-07-24 20:05:33,391 - bot.handlers.payments - INFO - "
            f"Lava webhook raw headers: {{'Host': '{host}'}} raw_body: b'{{}}'"
        ),
        (
            "2026-07-24 20:05:33,393 - bot.handlers.payments - INFO - "
            "Lava webhook parsed event_type=payment.success status=completed data="
            "{\"eventType\": \"payment.success\", "
            f"\"contractId\": \"{contract_id}\", "
            "\"buyer\": {\"email\": \"buyer@example.com\"}, "
            "\"product\": {\"title\": \"Тариф мини\"}, "
            "\"amount\": 150.0, \"currency\": \"RUB\", "
            "\"status\": \"completed\"}"
        ),
        (
            "2026-07-24 20:05:33,394 - bot.handlers.payments - INFO - "
            "Lava webhook received event=payment.success status=completed "
            f"order_id= contract_id={contract_id}"
        ),
    ]


def test_parse_success_webhook_and_host(tmp_path: Path):
    log_path = _write_log(tmp_path, _success_lines())

    events, diagnostics = MODULE.parse_logs([log_path], since=None, until=None)

    assert diagnostics.invalid_json_lines == 0
    assert set(events) == {"contract-1"}
    event = events["contract-1"]
    assert event.host == "tanyapi.chillcreative.ru"
    assert event.amount == 150.0
    assert event.currency == "RUB"
    assert event.buyer_email == "buyer@example.com"
    assert event.product_title == "Тариф мини"


def test_duplicate_success_delivery_is_deduplicated(tmp_path: Path):
    first = _success_lines()
    second = [line.replace("20:05:33", "20:06:33") for line in _success_lines()]
    log_path = _write_log(tmp_path, first + second)

    events, _ = MODULE.parse_logs([log_path], since=None, until=None)

    assert len(events) == 1
    assert events["contract-1"].deliveries == 2


def test_completed_transaction_from_wrong_host_is_flagged(tmp_path: Path):
    log_path = _write_log(
        tmp_path,
        _success_lines(host="tanyavk.chillcreative.ru"),
    )
    events, diagnostics = MODULE.parse_logs([log_path], since=None, until=None)

    rows = MODULE.build_rows(
        events.values(),
        diagnostics,
        {
            "contract-1": {
                "order_id": "order-1",
                "status": "completed",
                "amount_rub": 150.0,
                "credits": 15,
                "user_id": 10,
                "created_at": "2026-07-24 20:05:30",
            }
        },
        {},
        expected_host="tanyapi.chillcreative.ru",
        show_email=False,
    )

    assert rows[0].result == "HOST_MISMATCH_COMPLETED"
    assert rows[0].buyer_email == "bu****@example.com"
    assert "ожидался tanyapi.chillcreative.ru" in rows[0].details[0]
