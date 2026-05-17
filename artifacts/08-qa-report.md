# QA Report

## Checks Run

- `node --check static/landing/js/site.js`
- `npm --prefix miniapp run build`
- `rg` scan for negative `letter-spacing`, viewport-scaled `clamp(...vw...)`, and orb/bokeh markers
- `./venv/bin/pytest -q`
- `./venv/bin/python scripts/build_landing_archive.py`
- Static smoke via `./venv/bin/python -m http.server 8787` + `curl -I` for landing HTML/CSS/JS

## Current Result

- Landing JavaScript syntax: passed.
- Mini App production build: passed.
- Design constraint scan: passed.
- Full pytest suite: `122 passed`.
- Landing archive: `build/2loop-landing-20260516-1913.zip`.
- Static smoke: HTML, CSS and JS returned `200 OK`.

## UX Simplification Pass

- Removed the always-on sidebar and KPI strip from public pages; dense workspace remains for dashboard/admin.
- Simplified home to one primary prompt flow and a compact shortcut row; product browsing moved out of the first screen.
- Simplified site creator to model + prompt + create; result panel appears only after generation starts.
- Simplified Mini App create flow: compact scenario selector, profile + input material, no extra tone/goal/reference fields on the first path.
- Rebuilt Mini App and synced `/static/landing` + `/static/miniapp` to production static.
- Latest landing archive: `build/2loop-landing-20260516-1913.zip`.
- Production smoke: `https://2loop.chillcreative.ru/` now references `site.css?v=20260516-lite2` and `site.js?v=20260516-lite2`; Mini App now serves `index-DeMeKT-U.js` and `index-CxUArCNs.css`.

## API Docs Pass

- Added `docs/openapi.json` as OpenAPI 3.1 contract for current aiohttp API.
- Added aiohttp docs routes in `bot/openapi.py`: `/api/openapi.json`, `/api/docs`, `/api/redoc`.
- Added analysis artifact: `artifacts/10-api-bot-capabilities.md`.
- Added route/spec tests: `tests/test_openapi_docs.py`.
- Validation: `./venv/bin/python -m json.tool docs/openapi.json` passed.
- Focused tests: `./venv/bin/pytest tests/test_openapi_docs.py tests/test_landing.py -q` passed.
- Full tests: `./venv/bin/pytest -q` -> `124 passed`.
- Production backend restarted: `2loop-bot.service` active.
- Nginx updated/reloaded for `/api/openapi.json`, `/api/docs`, `/api/redoc`.
- Production smoke: all three docs endpoints return `200 OK`; OpenAPI JSON parses successfully.

## Visual QA Notes

- Browser screenshot QA is still pending because no Chromium/Playwright browser executable has been available in this environment in prior checks.
- The redesign keeps existing API calls and route behavior intact while replacing the visual system.
