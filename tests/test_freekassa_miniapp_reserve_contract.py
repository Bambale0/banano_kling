from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_miniapp_freekassa_uses_signed_server_checkout() -> None:
    source = _read("bot/handlers/miniapp_lava_payment_methods_compat.py")

    assert '"freekassa_card": FREEKASSA_CARD_RUB_METHOD_ID' in source
    assert '"freekassa_sbp": FREEKASSA_SBP_METHOD_ID' in source
    assert 'provider="freekassa"' in source
    assert 'payment_id=order_id' in source
    assert "from bot.handlers.freekassa_payments import _checkout_url" in source
    assert "payment_url = _checkout_url(order_id, payment_system_id)" in source
    assert 'payload["freekassa_enabled"] = bool(freekassa_service.api_enabled)' in source
    assert "freekassa_service.create_payment" not in source


def test_miniapp_shows_freekassa_only_as_reserve() -> None:
    source = _read("frontend/miniapp-v0/components/balance-sheet.tsx")

    assert "KASSA · резервная оплата" in source
    assert "KASSA · Карта РФ" in source
    assert "KASSA · СБП" in source
    assert "'freekassa_card' as PaymentProvider" in source
    assert "'freekassa_sbp' as PaymentProvider" in source
    assert "freekassa_enabled" in source

    primary_card = source.index("handleTopup(pkg.id, 'lava_card')")
    primary_sbp = source.index("handleTopup(pkg.id, 'lava_sbp')")
    reserve_label = source.index("KASSA · резервная оплата")
    assert primary_card < reserve_label
    assert primary_sbp < reserve_label


def test_freekassa_checkout_still_owns_email_ip_and_provider_creation() -> None:
    source = _read("bot/handlers/freekassa_payments.py")
    checkout = source.split("async def handle_freekassa_checkout", 1)[1].split(
        "def _payment_return_page", 1
    )[0]

    assert '_EMAIL_RE.fullmatch(email)' in checkout
    assert "customer_ip = _request_ip(request)" in checkout
    assert "freekassa_service.create_payment(" in checkout
    assert "payment_system_id=method_id" in checkout
    assert "HTTPSeeOther" in checkout
