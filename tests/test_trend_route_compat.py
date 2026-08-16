from aiohttp import web

from bot import miniapp as miniapp_module
from bot.handlers import trend_route_compat as compat


def test_trend_route_is_registered_before_miniapp_catch_all(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_setup_trend_routes(_app: web.Application, root: str) -> None:
        calls.append(("trend", root))

    def fake_setup_miniapp_routes(_app: web.Application) -> None:
        calls.append(("miniapp", None))

    monkeypatch.setattr(compat, "setup_trend_routes", fake_setup_trend_routes)
    monkeypatch.setattr(miniapp_module, "setup_miniapp_routes", fake_setup_miniapp_routes)
    monkeypatch.setattr(
        miniapp_module,
        "_trend_route_compat_installed",
        False,
        raising=False,
    )

    compat.install_trend_route_compat()
    miniapp_module.setup_miniapp_routes(web.Application())

    assert calls == [("trend", compat._miniapp_root()), ("miniapp", None)]
