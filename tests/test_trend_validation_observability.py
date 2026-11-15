"""Regression contract for non-sensitive trend launch validation diagnostics."""
import logging
from unittest.mock import AsyncMock

import pytest

from bot import miniapp as miniapp_module
from bot import trend_api


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "authentication_error", "expected_stage"),
    [
        ({"init_data": "secret-initdata", "reference_urls": []}, False, "parse_request"),
        (
            {"init_data": "secret-initdata", "trend_id": 7, "reference_urls": ["/uploads/ref.jpg"]},
            True,
            "authenticate",
        ),
        (
            {"init_data": "secret-initdata", "trend_id": 7, "reference_urls": ["/uploads/ref.jpg"]},
            False,
            "resolve_trend",
        ),
    ],
)
async def test_trend_rejection_logs_validation_stage_without_sensitive_input(
    monkeypatch, caplog, payload, authentication_error, expected_stage
):
    """Invalid trend launches must not expose initData or user input in logs."""
    if authentication_error:
        auth = AsyncMock(side_effect=trend_api.TrendRunValidationError("not authorized"))
    else:
        auth = AsyncMock(return_value=(42, {"user": object()}))
    monkeypatch.setattr(miniapp_module, "_get_user_context", auth)
    monkeypatch.setattr(trend_api, "get_prompt_by_id", AsyncMock(return_value=None))

    class Request:
        def __init__(self):
            self.app = {}

        async def json(self):
            return payload

    with caplog.at_level(logging.WARNING, logger="bot.trend_api"):
        response = await trend_api.miniapp_run_trend(Request())

    assert response.status == 400
    records = [record.getMessage() for record in caplog.records if "Trend request rejected" in record.getMessage()]
    assert records
    assert any(f"validation_stage={expected_stage}" in record for record in records)
    assert all("secret-initdata" not in record for record in records)
