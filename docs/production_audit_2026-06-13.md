# Production Audit 2026-06-13

## Scope

Audit target: Telegram bot, Telegram Mini App, generation flows, Kie.ai/Wan 2.7 integration, admin dashboard metrics, billing/refunds and production smoke.

Workspace:

```text
/root/bot/banano_kling
```

Current production process:

```bash
python -m bot.main
```

Managed by:

```bash
bot.service
```

## Checks Performed

Backend regression:

```bash
pytest -q
```

Result:

```text
228 passed
```

Python sanity:

```bash
python -m compileall -q bot tests
python -m pip check
```

Result:

```text
No broken requirements found.
```

TMA build:

```bash
cd tma
npm run build
```

Result:

```text
tsc -b && vite build
✓ built
```

TMA dependency audit:

```bash
npm audit --omit=dev --audit-level=high
```

Result:

```text
found 0 vulnerabilities
```

Production smoke:

```bash
systemctl is-active bot.service
curl -fsS -i http://127.0.0.1:8443/health
curl -fsS -I https://dev.chillcreative.ru/miniapp
```

Result:

- service: `active`;
- local health: `200 OK`;
- public miniapp: `200 OK`;
- miniapp assets: `200 OK`.

TMA auth smoke:

- `/api/tma/app/bootstrap` without `initData`: `401`;
- `/api/tma/admin/bootstrap` without `initData`: `401`;
- both endpoints with valid signed Telegram `initData`: `200`.

## Fixes Applied During Audit

### Admin Active Tasks Metric

Problem:

`active_tasks` in admin dashboard counted all historical `pending` and `processing` tasks. The production database had 191 old `pending` rows dating back to March-June, so the dashboard looked busy even when no active generation was running.

Fix:

`active_tasks` now counts only `pending`/`processing` tasks created in the last 24 hours.

Changed file:

```text
bot/tma_api.py
```

Regression test updated:

```text
tests/test_tma_api.py::test_tma_dashboard_does_not_multiply_today_revenue_by_tasks
```

Production smoke after restart:

```text
active_tasks: 0
```

### Vague Background Edit Prompt Guard

Problem:

For reference-based image editing, a prompt like `смени фон` is too vague. Kie.ai can return a result that visually looks like the original reference because the new background is not specified.

Fix:

The bot now stops before charging if a user sends a vague background-change prompt with references. It asks the user to specify the target background.

Regression test:

```text
tests/test_generation_prompt_guards.py
```

### Wan 2.7 Image Pro 4K Fallback

Observed live behavior:

Kie.ai can reject `wan/2-7-image-pro` with `resolution=4K` and `input_urls`, returning:

```text
resolution 4K is only supported for non-sequential text-to-image
```

Implementation:

- First request keeps the user-selected `4K`.
- If Kie.ai returns that specific 422, the service retries task creation in `2K`.
- Provider error dicts are handled as API errors and are not sent to Telegram as file bytes.
- Failed starts refund the resource and mark the task as `failed`.

Regression tests:

```text
tests/test_wan_kie_payload.py
```

## Current Known Risks

### Large Video Delivery

Observed:

Telegram can reject direct video URL sending, and file upload can fail with `Request Entity Too Large`. The bot then sends a fallback text link.

Impact:

Generation succeeds, but user UX is weaker for large videos.

Recommended next step:

Add stable CDN/proxy download handling, or document clear size limits and send large results as links with a better UI.

### Old Pending Payments

Observed:

The database contains old `transactions.status='pending'` rows. They are not counted as revenue, but they can clutter admin views.

Recommended next step:

Add admin filters and bulk cancellation/archive for old pending invoices.

### Heavy TMA Bootstrap

Observed:

`GET /api/tma/app/bootstrap` can return a large payload around hundreds of KB.

Recommended next step:

Paginate feed/history/admin collections and load secondary data lazily.

### Public Scanner Traffic

Observed:

External scanners hit `/miniapp` with suspicious query strings.

Recommended next step:

Add nginx rate limits and optional WAF rules for obvious exploit probes.

## Release Checklist Snapshot

- [x] Backend regression passed.
- [x] TMA production build passed.
- [x] Dependency sanity passed.
- [x] Production service active.
- [x] Health endpoint passed.
- [x] Mini App static route passed.
- [x] TMA auth smoke passed.
- [x] Admin active task metric corrected.

## Useful Commands

```bash
systemctl status bot.service --no-pager -l
journalctl -u bot.service -n 120 --no-pager
tail -n 180 logs/bot.log
curl -fsS -i http://127.0.0.1:8443/health
pytest -q
cd tma && npm run build
```
