from pathlib import Path

from aiohttp import web

from bot.handlers import robokassa_payments

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_robokassa_route_setup_registers_resulturl_and_is_idempotent():
    app = web.Application()
    robokassa_payments.setup_robokassa_routes(app)
    first_count = len(list(app.router.routes()))

    robokassa_payments.setup_robokassa_routes(app)

    paths = {route.resource.canonical for route in app.router.routes()}
    assert "/robokassa/result" in paths
    assert "/webhook/robokassa" in paths
    assert len(list(app.router.routes())) == first_count


def test_telegram_payment_router_places_robokassa_before_freekassa():
    source = _read("bot/handlers/__init__.py")
    robokassa = source.index("payments_router.include_router(robokassa_payments_router)")
    freekassa = source.index("payments_router.include_router(freekassa_payments_router)")
    legacy = source.index("payments_router.include_router(legacy_payments_router)")
    assert robokassa < freekassa < legacy


def test_miniapp_hides_robokassa_and_shows_lava_primary():
    source = _read("frontend/miniapp-v0/components/balance-sheet.tsx")
    assert "Robokassa · основной способ" not in source
    assert "handleTopup(pkg.id, 'robokassa')" not in source
    lava_label = source.index("Lava.top · основной способ")
    lava_card = source.index("handleTopup(pkg.id, 'lava_card')")
    lava_sbp = source.index("handleTopup(pkg.id, 'lava_sbp')")
    kassa_reserve = source.index("Резерв · KASSA")
    tribute = source.index("handleTopup(pkg.id, 'tribute' as PaymentProvider)")
    assert lava_label < lava_card < kassa_reserve
    assert lava_label < lava_sbp < kassa_reserve < tribute
    assert "handleTopup(pkg.id, 'freekassa_card')" in source
    assert "handleTopup(pkg.id, 'freekassa_sbp')" in source


def test_miniapp_provider_contract_contains_robokassa():
    types_source = _read("frontend/miniapp-v0/lib/types.ts")
    handler_source = _read("bot/handlers/robokassa_payments.py")

    assert "| 'robokassa'" in types_source
    assert "robokassa_enabled?: boolean" in types_source
    assert 'payload["robokassa_enabled"] = bool(robokassa_service.enabled)' in handler_source
    assert 'provider="robokassa"' in handler_source


def test_main_registers_robokassa_before_freekassa_routes():
    source = _read("bot/main.py")
    robokassa = source.index("setup_robokassa_routes(app)")
    freekassa = source.index("setup_freekassa_routes(app)")
    assert robokassa < freekassa


def test_text_bot_hides_robokassa_button_but_keeps_old_invoice_callbacks() -> None:
    from bot.handlers.robokassa_payments import _provider_keyboard

    keyboard = _provider_keyboard(
        "pro", robokassa=True, freekassa=True, stars=True, crypto=True, lava=True
    )
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert callbacks[0] == "buy_lava_pro"
    assert "buy_robokassa_pro" not in callbacks
    source = _read("bot/handlers/robokassa_payments.py")
    assert 'F.data.startswith("buy_robokassa_")' in source
    assert 'F.data.startswith("check_robokassa_")' in source
    assert "async def handle_robokassa_result" in source


def test_text_bot_lava_is_first_and_robokassa_is_hidden() -> None:
    from bot.handlers.lava_checkout import _payment_options_keyboard

    keyboard = _payment_options_keyboard(
        "pro", stars=True, lava_card=True, lava_sbp=True,
        lava_foreign=False, lava_foreign_price_usd=None,
        crypto=True, freekassa=True, robokassa=True,
    )
    callbacks = [
        button.callback_data for row in keyboard.inline_keyboard for button in row
        if button.callback_data
    ]
    assert callbacks[:4] == [
        "buy_lava_card_pro", "buy_lava_sbp_pro",
        "freekassa_card_pro", "freekassa_sbp_pro",
    ]
    assert "buy_robokassa_pro" not in callbacks
    source = _read("bot/handlers/lava_checkout.py")
    assert "has_robokassa" not in source
    assert "Lava.top · карта" in source
    assert "Lava.top · СБП" in source
