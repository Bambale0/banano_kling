# Testing and Smoke Runbook

Last updated: 2026-06-13.

## Purpose

This document describes the checks that must pass before considering the bot and Telegram Mini App production-ready after code changes.

## Backend Regression

Run from the project root:

```bash
cd /root/bot/banano_kling
source venv/bin/activate
pytest -q
```

Expected result on 2026-06-13:

```text
228 passed
```

Run targeted tests after touching generation, Wan/Kie.ai, TMA or admin metrics:

```bash
pytest \
  tests/test_wan_kie_payload.py \
  tests/test_generation_prompt_guards.py \
  tests/test_tma_api.py::test_tma_dashboard_does_not_multiply_today_revenue_by_tasks \
  -q
```

## Python Sanity

```bash
python -m compileall -q bot tests
python -m pip check
```

Expected:

```text
No broken requirements found.
```

## Telegram Mini App Build

```bash
cd /root/bot/banano_kling/tma
npm run build
npm audit --omit=dev --audit-level=high
```

Expected:

```text
✓ built
found 0 vulnerabilities
```

The production build is served from `tma/dist` through:

- `GET /miniapp`
- `GET /miniapp/assets/...`

## Production Smoke

After deploy or restart:

```bash
systemctl restart bot.service
sleep 4
systemctl is-active bot.service
curl -fsS -i http://127.0.0.1:8443/health
curl -fsS -I https://dev.chillcreative.ru/miniapp
```

Expected:

- systemd status: `active`
- local health: `200 OK`
- public miniapp: `200 OK`

## TMA Auth Smoke

Protected TMA endpoints must reject requests without Telegram `initData`:

```bash
curl -i http://127.0.0.1:8443/api/tma/app/bootstrap
curl -i http://127.0.0.1:8443/api/tma/admin/bootstrap
```

Expected:

```text
401 Telegram initData is required
```

With valid signed `X-Telegram-Init-Data`, both endpoints should return JSON:

- `GET /api/tma/app/bootstrap`
- `GET /api/tma/admin/bootstrap` for admins

Admin dashboard sanity after 2026-06-13 fix:

- `active_tasks` must count only `pending`/`processing` tasks created in the last 24 hours.
- Old `pending` rows must not inflate active work counters.

## Kie.ai / Wan 2.7 Smoke Notes

Wan 2.7 models are sent through Kie.ai:

- `wan_27_image`
- `wan_27_image_pro`
- `wan_27_t2v`
- `wan_27_i2v`
- `wan_27_r2v`
- `wan_27_videoedit`

Important behavior observed on live Kie.ai on 2026-06-13:

- `wan_27_image_pro` with `resolution=4K` and `input_urls` can return `422`.
- The code first sends the requested `4K`.
- If Kie.ai returns `resolution 4K is only supported for non-sequential text-to-image`, the service retries task creation in `2K`.
- Provider error dicts must never be treated as image bytes.
- Failed provider starts must refund credits/subscription usage and mark `generation_tasks.status='failed'`.

## Data Smoke

Useful SQLite checks:

```bash
sqlite3 -header -column bot.db "
select status, count(*) as cnt from generation_tasks group by status order by cnt desc;
select status, count(*) as cnt, round(sum(amount_rub),2) as total_rub from transactions group by status order by cnt desc;
select refunded, count(*) as cnt from subscription_usage group by refunded;
select id,task_id,model,status,created_at,completed_at
from generation_tasks
order by id desc
limit 10;
"
```

Interpretation:

- `transactions.status='completed'` is the source for revenue.
- Old `transactions.status='pending'` are unpaid invoices and should not be counted as revenue.
- `subscription_usage.refunded=1` means the generation resource was returned.

## Log Smoke

```bash
journalctl -u bot.service -n 120 --no-pager
tail -n 180 logs/bot.log
```

After restart, startup should show:

- database initialized;
- webhook set;
- push scenario loop scheduled;
- recurring payments loop scheduled;
- server started on `127.0.0.1:8443`.

Known non-critical log patterns:

- Internet scanners can hit `/miniapp` with suspicious query strings.
- Large generated videos may fail Telegram URL delivery and file upload, then fall back to a text link.

Critical log patterns:

- `NameError` in handlers;
- provider response dict sent as file bytes;
- payment completion without ledger entry;
- repeated webhook failures for the same provider task.

## Release Checklist

- [ ] `pytest -q` passes.
- [ ] `python -m compileall -q bot tests` passes.
- [ ] `python -m pip check` passes.
- [ ] `cd tma && npm run build` passes.
- [ ] `cd tma && npm audit --omit=dev --audit-level=high` reports no high vulnerabilities.
- [ ] `bot.service` is active after restart.
- [ ] `/health` returns `200 OK`.
- [ ] `/miniapp` and assets return `200 OK`.
- [ ] TMA protected endpoints reject missing `initData`.
- [ ] Admin bootstrap works for an admin and dashboard counters look realistic.
