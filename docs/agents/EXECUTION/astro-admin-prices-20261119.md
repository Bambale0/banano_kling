# Astro: price management in the existing Telegram admin panel

## Baseline and user intent
- Baseline: `31cd91ba3287056a6b9bd1eaeb443125a03d9412`, branch `tanyapi`.
- User asked to expose price management in admin after production launch of the seven Astro interpretation services.
- Existing Telegram admin price panel already edits packages, image/video prices, video prompts and creators via `AdminStates.waiting_price_value`, `preset_manager` and the persistent `data/price.json` volume.
- The dedicated Astro report path in `bot/astro_report_api.py` is **admin-only and free**: it does not debit user balances. Frontend explicitly says there are no deductions. Enabling payments is **not** part of this change.
- Existing internal HMAC-admin tariffs exposes `service_prices` as a versioned section, with a shared publish lock and atomic file replacement.

## Implemented
1. `bot/handlers/admin.py`: "Управление ценами" → "Astro — тарифы" → seven named services (natal, compatibility, karma, year, month, solar, lunar) → edit numeric price using the existing administrator-only Telegram FSM; show "не настроена" for absent prices and clearly explain that Astro deductions remain disabled.
2. `bot/services/astro_pricing.py`: the single source of service identifiers and labels; optional `service_prices.astro.<service_id>` catalog. Prices must be positive, finite, numeric and have at most two fractional digits. Existing price values are not invented, seeded, billed or overwritten on deployment.
3. Price update uses a compare-and-swap check against the price displayed on editor open, the same async lock as internal tariff publishing, atomic file write (fsync/rename), reloading the live preset manager, and rollback on reload failure. Security-sensitive admin IDs and all unrelated pricing settings are retained. Audit log records only actor ID, service, old/new values.
4. Internal HMAC tariff publishing validates the optional Astro pricing map. Legacy `service_prices` without Astro remain valid. No DB migration or user debit.
5. Unit/regression tests cover all 7 buttons, auth, editor state, save and live reload, stale admin edits, rollback, invalid values, unchanged other settings and signed tariff validation.

## Release plan and gates
- Focused pytest and Ruff changed lines first; whole `tests/test_astro_*.py` suite; existing admin/tariff/payment regression coverage; full CI + Mini App browser E2E; squash auto-merge to `tanyapi`.
- Production: verify exact SHA backend + Mini App, worker health, Telegram callback routing and volume-backed price catalog. Do **not** set actual user prices, charge accounts, publish Astro to users or mutate production prices during smoke.
- Smoke should be read-only for current values; prove saving with isolated test config and functional unit test (never alter real prices without explicit operator input).

## Risks, safeguards and follow-up
- Configured Astro prices are **catalog only**. Public pricing, actual quotes, atomic credit reservations/refunds and billing are a separate feature and must be built before exposing Astro to users.
- Existing Telegram admin price edits for other models retain their historical behavior; only Astro uses atomic CAS persistence in this change.
- If the admin opens one price and another administrator changes it, stale submission is rejected and must be reopened.
- Rollback: revert feature PR; optional catalog entries in persistent `data/price.json` are harmless while billing disabled.
