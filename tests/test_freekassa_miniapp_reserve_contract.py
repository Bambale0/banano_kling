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


def test_miniapp_uses_robokassa_primary_then_freekassa_reserve_then_lava() -> None:
    source = _read("frontend/miniapp-v0/components/balance-sheet.tsx")

    assert "Robokassa · основной способ" in source
    assert "Резерв · Robokassa" not in source
    assert "Резерв · KASSA" in source
    assert "Lava · дополнительный способ" in source
    assert "handleTopup(pkg.id, 'freekassa_card')" in source
    assert "handleTopup(pkg.id, 'freekassa_sbp')" in source
    assert "handleTopup(pkg.id, 'lava_card')" in source
    assert "handleTopup(pkg.id, 'lava_sbp')" in source
    assert "freekassa_enabled" in source

    robokassa = source.index("Robokassa · основной способ")
    robokassa_button = source.index("handleTopup(pkg.id, 'robokassa')")
    kassa_reserve = source.index("Резерв · KASSA")
    tribute = source.index("handleTopup(pkg.id, 'tribute' as PaymentProvider)")
    lava_label = source.index("Lava · дополнительный способ")
    lava_card = source.index("handleTopup(pkg.id, 'lava_card')")
    lava_sbp = source.index("handleTopup(pkg.id, 'lava_sbp')")
    assert robokassa < robokassa_button < kassa_reserve
    assert kassa_reserve < tribute < lava_label
    assert lava_label < lava_card
    assert lava_label < lava_sbp


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
    assert "except ConnectionResetError:" in checkout
    assert 'web.Response(status=499, text="Client closed request")' in checkout


def test_miniapp_places_robokassa_then_kassa_then_tribute_then_lava() -> None:
    source = _read("frontend/miniapp-v0/components/balance-sheet.tsx")

    robokassa = source.index("Robokassa · основной способ")
    kassa_reserve = source.index("Резерв · KASSA")
    tribute = source.index("handleTopup(pkg.id, 'tribute' as PaymentProvider)")
    lava = source.index("Lava · дополнительный способ")
    assert robokassa < kassa_reserve < tribute < lava


def test_payment_provider_type_includes_freekassa_methods() -> None:
    source = _read("frontend/miniapp-v0/lib/types.ts")

    assert "| 'freekassa_card'" in source
    assert "| 'freekassa_sbp'" in source
