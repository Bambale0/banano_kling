import json
from pathlib import Path

from aiohttp import web


OPENAPI_PATH = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"


async def openapi_json(_: web.Request) -> web.Response:
    return web.json_response(json.loads(OPENAPI_PATH.read_text(encoding="utf-8")))


async def swagger_ui(_: web.Request) -> web.Response:
    html = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>2Loop API Docs</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
  <style>
    body { margin: 0; background: #f3ede4; }
    .swagger-ui .topbar { display: none; }
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.ui = SwaggerUIBundle({
      url: "/api/openapi.json",
      dom_id: "#swagger-ui",
      deepLinking: true,
      persistAuthorization: true,
      displayRequestDuration: true
    });
  </script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


async def redoc_ui(_: web.Request) -> web.Response:
    html = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>2Loop API Reference</title>
</head>
<body>
  <redoc spec-url="/api/openapi.json"></redoc>
  <script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


def setup_openapi_routes(app: web.Application) -> None:
    app.router.add_get("/api/openapi.json", openapi_json)
    app.router.add_get("/api/docs", swagger_ui)
    app.router.add_get("/api/redoc", redoc_ui)
