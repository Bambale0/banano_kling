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


def test_miniapp_exposes_lava_primary_and_robokassa_reserve():
    source = _read("frontend/miniapp-v0/components/balance-sheet.tsx")
    lava_primary = source.index("Lava · основной способ")
    lava_card = source.index("handleTopup(pkg.id, 'lava_card')")
    lava_sbp = source.index("handleTopup(pkg.id, 'lava_sbp')")
    kassa_reserve = source.index("Резерв · KASSA")
    robokassa_reserve = source.index("Резерв · Robokassa")
    robokassa_button = source.index("handleTopup(pkg.id, 'robokassa')")

    assert lava_primary < lava_card < kassa_reserve
    assert lava_primary < lava_sbp < kassa_reserve
    assert kassa_reserve < robokassa_reserve < robokassa_button
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


def test_text_bot_marks_robokassa_as_reserve() -> None:
    source = _read("bot/handlers/robokassa_payments.py")
    assert 'text="↩️ Резерв · Robokassa"' in source
    assert '💳 <b>КАРТА | СБП</b>' in source
    assert 'Robokassa · основной способ' not in source


def test_text_bot_primary_payment_surface_is_lava() -> None:
    source = _read("bot/handlers/lava_checkout.py")

    assert 'from bot.services.robokassa_service import robokassa_service' in source
    assert 'has_robokassa = bool(robokassa_service.enabled)' in source
    assert 'text="💳 Карта · Lava"' in source
    assert 'text="⚡ СБП · Lava"' in source
    assert 'text="↩️ Резерв · Robokassa"' in source
    assert 'callback_data=f"buy_robokassa_{package_id}"' in source
    assert 'robokassa=has_robokassa' in source

