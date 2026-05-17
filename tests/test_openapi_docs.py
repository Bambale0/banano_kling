import json

from aiohttp import web

from bot.openapi import OPENAPI_PATH, setup_openapi_routes


def test_openapi_document_is_valid_json_and_covers_core_groups():
    spec = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))

    assert spec["openapi"].startswith("3.")
    assert spec["info"]["title"] == "2Loop API"
    assert "/api/site/cabinet" in spec["paths"]
    assert "/api/shop/order" in spec["paths"]
    assert "/api/miniapp/generate" in spec["paths"]
    assert "/api/shop/admin/overview" in spec["paths"]
    assert "/webhook" in spec["paths"]
    assert "TelegramInitData" in spec["components"]["securitySchemes"]
    assert "SiteSession" in spec["components"]["securitySchemes"]


def test_openapi_routes_registered():
    app = web.Application()
    setup_openapi_routes(app)

    paths = {route.resource.canonical for route in app.router.routes()}
    assert "/api/openapi.json" in paths
    assert "/api/docs" in paths
    assert "/api/redoc" in paths
