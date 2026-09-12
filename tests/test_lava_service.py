"""Tests for bot.services.lava_service — Lava API client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.services.lava_service import LavaService


@pytest.fixture
def service():
    return LavaService(api_key="test_key", base_url="https://test.lava.top")


class TestLavaWebhookParsing:
    """Static webhook payload parsing — no HTTP calls needed."""

    def test_webhook_event_type_direct(self):
        payload = {"eventType": "payment.success"}
        assert LavaService.webhook_event_type(payload) == "payment.success"

    def test_webhook_event_type_nested(self):
        payload = {"data": {"eventType": "PAYMENT.FAILED"}}
        assert LavaService.webhook_event_type(payload) == "payment.failed"

    def test_webhook_event_type_empty(self):
        assert LavaService.webhook_event_type({}) == ""

    def test_webhook_status_direct(self):
        payload = {"status": "completed"}
        assert LavaService.webhook_status(payload) == "completed"

    def test_webhook_status_contract_status(self):
        payload = {"contractStatus": "succeeded"}
        assert LavaService.webhook_status(payload) == "succeeded"

    def test_webhook_status_nested(self):
        payload = {"data": {"status": "cancelled"}}
        assert LavaService.webhook_status(payload) == "cancelled"

    def test_is_success_webhook_by_event(self):
        assert LavaService.is_success_webhook({"eventType": "payment.success"}) is True

    def test_is_success_webhook_by_status(self):
        assert LavaService.is_success_webhook({"status": "paid"}) is True

    def test_is_success_webhook_false(self):
        assert LavaService.is_success_webhook({"status": "expired"}) is False

    def test_is_failed_webhook_by_event(self):
        assert LavaService.is_failed_webhook({"eventType": "payment.failed"}) is True

    def test_is_failed_webhook_by_status(self):
        for s in ("cancelled", "canceled", "failed", "expired"):
            assert LavaService.is_failed_webhook({"status": s}) is True

    def test_is_failed_webhook_false(self):
        assert LavaService.is_failed_webhook({"status": "success"}) is False

    def test_webhook_contract_id_direct(self):
        payload = {"contractId": "inv_123"}
        assert LavaService.webhook_contract_id(payload) == "inv_123"

    def test_webhook_contract_id_underscore(self):
        payload = {"contract_id": "inv_456"}
        assert LavaService.webhook_contract_id(payload) == "inv_456"

    def test_webhook_contract_id_invoice_id(self):
        payload = {"invoiceId": "inv_789"}
        assert LavaService.webhook_contract_id(payload) == "inv_789"

    def test_webhook_contract_id_missing(self):
        assert LavaService.webhook_contract_id({}) is None


class TestLavaInvoiceParsing:
    """Static invoice response parsing — no HTTP calls."""

    def test_extract_invoice_id_direct(self):
        assert LavaService("k").extract_invoice_id({"id": "inv_1"}) == "inv_1"

    def test_extract_invoice_id_data_nested(self):
        assert LavaService("k").extract_invoice_id({"data": {"id": "inv_2"}}) == "inv_2"

    def test_extract_invoice_id_result_nested(self):
        assert LavaService("k").extract_invoice_id({"result": {"id": "inv_3"}}) == "inv_3"

    def test_extract_invoice_id_missing(self):
        assert LavaService("k").extract_invoice_id({}) is None

    def test_extract_payment_url_direct(self):
        assert LavaService("k").extract_payment_url({"paymentUrl": "https://pay.me"}) == "https://pay.me"

    def test_extract_payment_url_url_key(self):
        assert LavaService("k").extract_payment_url({"url": "https://pay.me"}) == "https://pay.me"

    def test_extract_payment_url_data_nested(self):
        assert LavaService("k").extract_payment_url({"data": {"url": "https://pay.me"}}) == "https://pay.me"

    def test_extract_payment_url_missing(self):
        assert LavaService("k").extract_payment_url({}) is None


class TestLavaServiceEnabled:
    """Tests for enabled property and API key check."""

    def test_enabled_with_key(self):
        assert LavaService("some_key").enabled is True

    def test_disabled_without_key(self):
        assert LavaService("").enabled is False

    @pytest.mark.asyncio
    async def test_request_returns_error_when_disabled(self):
        svc = LavaService("")
        result = await svc._request("GET", "/test")
        assert result == {"ok": False, "error": "LAVA_API_KEY is not configured"}


class TestLavaCreateInvoice:
    """Tests for create_invoice payload construction."""

    @pytest.mark.asyncio
    async def test_create_invoice_minimal_payload(self, service):
        with patch.object(service, "_request", AsyncMock()) as mock_request:
            mock_request.return_value = {"ok": True, "id": "inv_1"}
            result = await service.create_invoice("test@test.com", "offer_1")
            mock_request.assert_awaited_once_with(
                "POST", "/api/v3/invoice",
                payload={
                    "email": "test@test.com",
                    "offerId": "offer_1",
                    "currency": "RUB",
                },
            )
            assert result["id"] == "inv_1"

    @pytest.mark.asyncio
    async def test_create_invoice_with_all_params(self, service):
        with patch.object(service, "_request", AsyncMock()) as mock_request:
            mock_request.return_value = {"ok": True}
            await service.create_invoice(
                email="test@test.com",
                offer_id="offer_1",
                amount=100.0,
                payment_provider="card",
                payment_method="sbp",
                buyer_language="ru",
            )
            payload = mock_request.call_args[1]["payload"]
            assert payload["amount"] == 100.0
            assert payload["paymentProvider"] == "card"
            assert payload["paymentMethod"] == "sbp"
            assert payload["buyerLanguage"] == "ru"

    @pytest.mark.asyncio
    async def test_create_invoice_with_utm(self, service):
        with patch.object(service, "_request", AsyncMock()) as mock_request:
            mock_request.return_value = {"ok": True}
            utm = {"source": "telegram", "campaign": "test"}
            await service.create_invoice("test@test.com", "offer_1", client_utm=utm)
            payload = mock_request.call_args[1]["payload"]
            assert payload["clientUtm"] == utm

    @pytest.mark.asyncio
    async def test_retries_transient_offer_404_when_catalog_still_contains_offer(
        self,
        service,
    ):
        not_found = {
            "ok": False,
            "status": 404,
            "error": "Product with offer id = 'offer_1' not found",
        }
        success = {"ok": True, "id": "inv_2"}
        request = AsyncMock(side_effect=[not_found, success])
        resolver = AsyncMock(return_value="offer_1")

        with (
            patch.object(service, "_request", request),
            patch.object(service, "resolve_offer_id_from_product_id", resolver),
            patch("bot.services.lava_service.asyncio.sleep", AsyncMock()) as sleep,
        ):
            result = await service.create_invoice(
                "test@test.com",
                "offer_1",
                payment_provider="PAY2ME",
                payment_method="SBP",
            )

        assert result["ok"] is True
        assert result["id"] == "inv_2"
        assert request.await_count == 2
        resolver.assert_awaited_once_with(product_id="offer_1", currency="RUB")
        sleep.assert_awaited_once()

    def test_catalog_lookup_accepts_existing_offer_id(self, service):
        items = [
            {
                "id": "product_1",
                "offers": [
                    {
                        "id": "offer_1",
                        "prices": [
                            {
                                "currency": "RUB",
                                "amount": 150,
                            }
                        ],
                    }
                ],
            }
        ]

        assert service._find_offer_id_in_products(
            items=items,
            product_id="offer_1",
            currency="RUB",
        ) == "offer_1"


class TestLavaGetInvoice:
    @pytest.mark.asyncio
    async def test_get_invoice_success(self, service):
        with patch.object(service, "_request", AsyncMock()) as mock_request:
            mock_request.return_value = {"ok": True, "id": "inv_1"}
            result = await service.get_invoice("inv_1")
            mock_request.assert_awaited_once_with("GET", "/api/v2/invoices/inv_1")
            assert result["id"] == "inv_1"

    @pytest.mark.asyncio
    async def test_get_invoice_not_ok_returns_none(self, service):
        with patch.object(service, "_request", AsyncMock()) as mock_request:
            mock_request.return_value = {"ok": False, "error": "not found"}
            result = await service.get_invoice("inv_missing")
            assert result is None


class TestLavaRequest:
    @pytest.mark.asyncio
    async def test_successful_request(self):
        svc = LavaService("test_key", "https://test.lava.top")
        mock_session = MagicMock()
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"id": "inv_1", "status": "active"})
        mock_resp.text = AsyncMock(return_value='{"id": "inv_1", "status": "active"}')
        mock_session.request.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session.request.return_value.__aexit__ = AsyncMock(return_value=False)
        svc._get_session = AsyncMock(return_value=mock_session)

        result = await svc._request("POST", "/api/v3/invoice", payload={"test": True})
        assert result["ok"] is True
        assert result["id"] == "inv_1"

    @pytest.mark.asyncio
    async def test_handles_400_error(self):
        svc = LavaService("test_key", "https://test.lava.top")
        mock_session = MagicMock()
        mock_resp = AsyncMock()
        mock_resp.status = 400
        mock_resp.json = AsyncMock(return_value={"error": "bad request"})
        mock_resp.text = AsyncMock(return_value='{"error": "bad request"}')
        mock_session.request.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session.request.return_value.__aexit__ = AsyncMock(return_value=False)
        svc._get_session = AsyncMock(return_value=mock_session)

        result = await svc._request("POST", "/api/v3/invoice")
        assert result["ok"] is False
        assert result["status"] == 400
