# Server-side website-studio payment gate — follow-up to PR #654

Date: 2026-11-20. Base: tanyapi 3ccfd5960674284bf2debde008391ce6bdf51798.

## Confirmed follow-up root cause

Frontend PR #654 is in production and classifies webstudio_* as browser. However the HTTP payment endpoint independently checks authenticated payment provenance in bot/payment_platform_policy.py, which only whitelisted browser_*; legitimate linked browser webstudio_* checkout could still fail HTTP 403 WEB_PAYMENT_REQUIRED. Live logs include surface=telegram 403 but no verified session correlation; never ascribe them to a particular user.

## Security-preserving fix

_get_user_context verifies HMAC-signed Telegram-shaped initData; webstudio_* additionally undergoes active, nonrevoked session and same-account Telegram-link validation through verify_studio_bridge. The server sets webstudio_session_verified=True ONLY after that awaited validation succeeds; the flag is never accepted from request JSON and defaults false in native Telegram.

The payment guard permits fiat only for original browser_* or a structurally valid webstudio_* plus server-owned verified marker. Genuine Telegram remains Stars-only. Revoked/unregistered/forged/malformed studio tokens fail at verification or policy; VK restriction remains unchanged. No DB changes, wallet cutover, price/provider changes or finance mutations.

## Evidence and release gates

RED: verified-context webstudio_* got 403 before the change. GREEN: valid marker allowed; marker absent and genuine TG remain 403. Parametrized pytest covers five fiat providers, five denied cases and extended signed + revoked session test. Compileall and diff check passed. Local host Python lacks aiogram, so GitHub isolated CI must run full integration suite. After GitHub CI, exact SHA, healthy Docker, HTTP/health, public frontend and real authorized test account end-to-end payment flow must be checked. Never run an actual customer payment as smoke.

Rollback: revert backend-only change. Neither balances nor schema are modified.
