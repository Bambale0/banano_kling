# Security: revocable website-issued Mini App studio sessions

Date: 2026-11-20. Target production branch: tanyapi, base merge SHA 6d021656e280b7313c2d23a5c60e5a35db05b2a2 from #647.

## Incident path and fix

Before this change, the independent website could mint bot-token-signed Telegram-compatible credentials with query_id browser_*. Existing Mini App generation handlers accepted these for up to 24 hours even after the issuing website cookie was revoked. The new read-only AccountActor shipped in #647 protected its own endpoints against a stale browser_ token, but the older Mini App handlers still validated only the Telegram-style HMAC and time.

The safe backward-compatible change introduces a new webstudio_ query_id (the old browser_ default stays unchanged for other clients), stored only by SHA-256 digest in web_auth_studio_tokens. The DB record binds the issued token to: the verified browser session's token hash, canonical account UUID, signed Telegram user ID and an expiry no later than 24 hours or parent session expiry.

Issuance: web_auth_studio and web_auth.telegram_login verify the website cookie and Telegram identity before storing the token. A confirmed account owner receives the signed webstudio_ initData. Any lost/revoked session at issuance fails HTTP 401.

Consumption: miniapp._get_user_context verifies the HMAC then verifies the webstudio_ DB binding BEFORE doing legacy user initialization, payment or generation. shared_accounts.unified_actor reports new webstudio_ credentials as web_live, never telegram_legacy, after validating the DB binding. Any linked identity removed or parent cookie logged out immediately invalidates the studio credential. A wrong account/Telegram ID fails.

## Scope and deliberately retained compatibility

- No changes to existing native Telegram WebView initData or Telegram Stars.
- No changes to user funds, storage, provider models, task schema or paid web feature flags.
- The **older** browser_auth.py browser_ credential flow and already issued browser_ tokens remain under their old HMAC + time validation in legacy Mini App. They are not made revocable by this change. A further, separately gated migration is required before claiming universal browser logout revocation.
- The foreign-VK production contour is not enabled or modified.

## Verification

Regressions: tests/test_web_studio_revocation.py (linked account, wrong Telegram ID, unrelated HMAC, valid token, revoked cookie, race at issuance -> 401, shared ActorContext wallet authority). Browser_auth + shared_accounts legacy tests also run. Local isolated backend: 156 passed, 73 skipped. Targeted Ruff and diff check passed. Full GitHub Safe Regression, PostgreSQL, browser E2E and Docker deploy gates must finish green before auto-merge. After deployment: exact SHA and docker health; anonymous GET actor=401, bad-Origin POST actor=403, website origin smoke and native TG app authentication without new login.

## Rollback

Revert this isolated commit if legacy Telegram Mini App login regresses. The new table is additive, and no existing funds/task data were changed. Rollback restores original browser_ signed login credentials. Reverting does not retroactively revoke old credentials; never claim it does.
