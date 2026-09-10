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


def test_miniapp_uses_freekassa_as_primary_and_lava_as_reserve() -> None:
    source = _read("frontend/miniapp-v0/components/balance-sheet.tsx")

    assert "KASSA · основной способ" in source
    assert "Резерв · Lava" in source
    assert "Lava · Карта" in source
    assert "Lava · СБП" in source
    assert "handleTopup(pkg.id, 'freekassa_card')" in source
    assert "handleTopup(pkg.id, 'freekassa_sbp')" in source
    assert "handleTopup(pkg.id, 'lava_card')" in source
    assert "handleTopup(pkg.id, 'lava_sbp')" in source
    assert "freekassa_enabled" in source

    primary_label = source.index("KASSA · основной способ")
    primary_card = source.index("handleTopup(pkg.id, 'freekassa_card')")
    primary_sbp = source.index("handleTopup(pkg.id, 'freekassa_sbp')")
    reserve_label = source.index("Резерв · Lava")
    reserve_card = source.index("handleTopup(pkg.id, 'lava_card')")
    reserve_sbp = source.index("handleTopup(pkg.id, 'lava_sbp')")
    assert primary_label < primary_card < reserve_label
    assert primary_label < primary_sbp < reserve_label
    assert reserve_label < reserve_card
    assert reserve_label < reserve_sbp


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


def test_miniapp_places_primary_kassa_before_foreign_and_lava_reserves() -> None:
    source = _read("frontend/miniapp-v0/components/balance-sheet.tsx")

    freekassa = source.index("KASSA · основной способ")
    lava_reserve = source.index("Резерв · Lava")
    tribute = source.index("handleTopup(pkg.id, 'tribute' as PaymentProvider)")
    assert freekassa < lava_reserve < tribute


def test_payment_provider_type_includes_freekassa_methods() -> None:
    source = _read("frontend/miniapp-v0/lib/types.ts")

    assert "| 'freekassa_card'" in source
    assert "| 'freekassa_sbp'" in source
