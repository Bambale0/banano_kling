# Parameter Trace Map — Referral & Feed Flows

> Generated 2026-07-04 from `/root/tanya/banano_kling`
> Covers: banano_kling (Таня ТГ) referral and feed parameter chains.

---

## Flow 1: Registration with Referral Code

### 1a. Telegram `/start` Entry Point

| Flow | Parameter | Created at | Expected by | Actually passed | Lost? | Type mismatch? | Security/antifraud risk | Fix needed? | Test needed? |
|------|-----------|------------|-------------|-----------------|-------|----------------|------------------------|-------------|--------------|
| 1a: /start | `start_param` (raw arg from Telegram) | common.py:3484 (`cmd_start`, `args[0]`) | `_referral_code_from_start_param` (in miniapp.py), `process_referral_click` | `args[0]` (`str`) — e.g. `"ref_ABC123"` | No | No | low | none | yes |
| 1a: /start | `referral_code_from_args` | common.py:3498-3506 — strips prefix `"ref_"` from `args[0]` | `process_referral_click` (referral_service.py) | `str` — cleaned code, e.g. `"ABC123"` | No | No | low | none | yes |
| 1a: /start | `user` (existing or new) | common.py:3509 — `get_or_create_user(message.from_user.id)` | `process_referral_click`, UI rendering | `User` dataclass | No | No | low | `get_or_create_user` is called **twice** — once before and once after referral attach (line 3509 & 3526). Could be collapsed. | yes |
| 1a: /start | `ref_result` | common.py:3512 — `process_referral_click(...)` return | `_notify_partner_about_new_referral`, `user.referred_by` update | `ReferralResult` dataclass (`.attached`, `.notify_partner`, `.referrer_telegram_id`, `.clicked_code`) | No | No | **medium** — `ref_result.clicked_code` used to get referrer vs `referral_code_from_args`. Slight divergence potential if stripping differs. | Use `referral_code_from_args` consistently instead of `ref_result.clicked_code`. | yes |
| 1a: /start | `referrer` | common.py:3515 — `get_user_by_referral_code(ref_result.clicked_code or "")` | `_notify_partner_about_new_referral` | `User \| None` | Only if code empty | No | low | none | yes |
| 1a: /start | `main_menu_referral_code` | common.py:3693 — from `args[0]` `ref_` strip | `get_main_menu_keyboard(mini_app_referral_code=...)` | `str \| None` | No | No | low | none | no |

### 1b. Mini App Bootstrap Referral

| Flow | Parameter | Created at | Expected by | Actually passed | Lost? | Type mismatch? | Security/antifraud risk | Fix needed? | Test needed? |
|------|-----------|------------|-------------|-----------------|-------|----------------|------------------------|-------------|--------------|
| 1b: MiniApp bootstrap | `start_param` (raw) | frontend: `start-params.ts` — `getStartParamFallback()` | miniapp.py:1991 — `miniapp_bootstrap` | `str` from Telegram WebApp initData | No | No | low | none | no |
| 1b: MiniApp bootstrap | `start_param_fallback` | `api.ts:postJson` — auto-appended to all POST | `_get_user_context` (line 804) | `str` from `getStartParamFallback()` | No | No | low | none | no |
| 1b: MiniApp bootstrap | `referral_code` (extracted) | miniapp.py:709 — `_referral_code_from_start_param(start_param)` | `_get_user_context` → `get_or_create_user(telegram_id, referral_code=...)` | `str` — uppercase, prefix-stripped | No | No | low | `_referral_code_from_start_param` is duplicated logic from `cmd_start`. Can diverge. | Consolidate extraction into shared function. | yes |
| 1b: MiniApp bootstrap | `referrer` | miniapp.py:812 — `get_user_by_referral_code(referral_code)` | `process_referral` | `User \| None` | Results **not used** in fallback path (line 868-874), recalculated | No | low | See 1b "not applied" path below. | none | yes |
| 1b: MiniApp bootstrap | `processed` | miniapp.py:813 — `process_referral(telegram_id, referral_code)` | `_notify_partner_about_new_referral` (line 827) | `bool` | No | **No** — but `referrer` may be `None` while `processed` is `True` (processing uses `user.id`, referrer check uses `referral_code`). Safeguarded by `if processed and referrer`. | low | none | yes |

### 1c. referral_service.py — `process_referral_click` (THE Canonical Path)

| Flow | Parameter | Created at | Expected by | Actually passed | Lost? | Type mismatch? | Security/antifraud risk | Fix needed? | Test needed? |
|------|-----------|------------|-------------|-----------------|-------|----------------|------------------------|-------------|--------------|
| 1c: referral service | `code` | referral_service.py:295 — normalized `.strip().upper()` | Antifraud checks, DB | `str` — e.g. `"ABC123"` | No | No | **high** — code is the primary lookup key. Any divergence in stripping/uppercasing breaks attribution. | Verified: both entry points (cmd_start, miniapp `_referral_code_from_start_param`) `.strip().upper()`. Consistent. | yes |
| 1c: referral service | `visitor_telegram_id` | Passed as arg from handler | DB query, antifraud | `int` (Telegram ID) | No | No | low | none | no |
| 1c: referral service | `referrer_id` | referral_service.py:328 — `SELECT id FROM users WHERE referral_code = ?` | Antifraud checks, `set_user_referrer` | `int \| None` | No | No | **medium** — no multi-tenancy check; a code from any user is valid | Code lookup should perhaps include `partner_agreed_at IS NOT NULL` check? | no |
| 1c: referral service | `referrer_telegram_id` | From `referrer_row["telegram_id"]` | `ReferralResult.referrer_telegram_id` | `int` | No | No | low | none | no |
| 1c: referral service | `existing_referrer_id` | From `visitor_row["referred_by"]` | Used for deduplication decisions | `int \| None` | No | No | **medium** — returned as `int` (user `id`), not `telegram_id`. Must convert when comparing. | Checked: comparisons are at `user.id` level, consistent. | yes |
| 1c: referral service | `PARTNER_INVITER_BONUS` | referral_service.py:571 — hardcoded import from database.py | `UPDATE users SET credits = credits + ?` | `int` (3) | No | No | low | none | no |
| 1c: referral service | `result.attached` | Set `True` on success (line 580) | Handlers use for notification decision | `bool` | No | No | **high** — notification fires only if `attached=True AND notify_partner=True`. Bug: if `attached=True` but `notify_partner=False`, no notification. | Verified: `notify_partner=True` always when `attached=True` in current code. Safe. | yes |
| 1c: referral service | `result.reason` | One of `VALID_REASONS` enum | `record_referral_event`, logging | `str` — e.g. `"attached"`, `"hourly_limit"` | No | No | **medium** — `reason` is logged in `referral_events` table but not surfaced to user-facing error messages directly. Rate-limit "silent fail" could confuse users. | Add user-facing message for hourly/daily rate-limit cases. | yes |

---

## Flow 2: Feed Publish (Share Generation to Feed)

| Flow | Parameter | Created at | Expected by | Actually passed | Lost? | Type mismatch? | Security/antifraud risk | Fix needed? | Test needed? |
|------|-----------|------------|-------------|-----------------|-------|----------------|------------------------|-------------|--------------|
| 2: Publish | `gen_id` | `_miniapp_payload` (line 1964): normalized from `gen_id \| generation_id \| feed_id \| task_id` | `share_to_feed(gen_id, user.id, ...)` | `int \| str` — if numeric, treated as `id`; otherwise as `task_id` | No | **Yes — ambiguous**: `_miniapp_payload` sets `payload["gen_id"] = payload["generation_id"]` AND `payload["gen_id"] = payload["feed_id"]`, masking which field was sent. | **medium** — Could match wrong generation if both fields sent. | Alias resolution is helpful but should log the source field. | yes |
| 2: Publish | `prompt_visible` | miniapp.py:2715 — `_payload_bool(body.get("prompt_visible", body.get("feed_prompt_visible")), False)` | `share_to_feed` → DB column `feed_prompt_visible` | `bool` (default `False`) | No | No | low | `feed_prompt_visible` is the DB column but payload key is `prompt_visible`. Naming inconsistency is confusing. | Alias to `feed_prompt_visible` directly (both are accepted now). | no |
| 2: Publish | `references_visible` | miniapp.py:2719 — `_payload_bool(body.get("references_visible", body.get("feed_references_visible")), False)` | `share_to_feed` → DB column `feed_references_visible` | `bool` (default `False`) | No | No | low | Same naming inconsistency. | Same as above. | no |
| 2: Publish | `row.id` (internal) | database.py:6032 — from `_fetch_generation_row(db, gen_id, user_id)` | `share_to_feed`, `_generation_row_to_card` | `int` (the real `generation_tasks.id`) | No | No | **medium** — returned `gen_id` in card is `row["id"]` (line 6068), not the original `gen_id` parameter. If caller expected `gen_id == orig_gen_id`, mismatch. | Verified: `share_to_feed` returns `get_feed_generation_card(gen_id=row["id"])`, consistent. `gen_id` in response IS the DB PK. | yes |
| 2: Publish | `result_url` / `result_urls` | `_generation_result_urls(row)` → downloaded by `persist_feed_result_urls()` | DB update + card response | `list[str]` of URLs | **Potentially** — if `persist_feed_result_urls` fails for some URLs, they are silently dropped | No | **high** — Ephemeral URLs (tempfile.aiquickdraw.com) expire after 72h. If persist fails, feed card may show broken media. | The `persist_feed_result_urls` function in feed_persist.py logs "persisted=N" but there's no alert on partial failure. | yes |
| 2: Publish (frontend) | `taskId` | `api.ts:publishGeneration` → payload `task_id` | `_miniapp_payload` → resolves to `gen_id` | `str` | No | No | low | none | no |
| 2: Publish (frontend) | `promptVisible` | `api.ts:publishGeneration` → payload `prompt_visible` | `miniapp_generation_share` → `share_to_feed` | `bool` | No | No | low | none | no |
| 2: Publish (frontend) | `referencesVisible` | `api.ts:publishGeneration` → payload `references_visible` | `miniapp_generation_share` → `share_to_feed` | `bool` | No | No | low | none | no |

---

## Flow 3: Feed Browse

| Flow | Parameter | Created at | Expected by | Actually passed | Lost? | Type mismatch? | Security/antifraud risk | Fix needed? | Test needed? |
|------|-----------|------------|-------------|-----------------|-------|----------------|------------------------|-------------|--------------|
| 3: Browse | `source` | miniapp.py:2584 — `str(body.get("source", "recent") or "recent")` | `get_feed_generations(source=...)` | `"recent" \| "top_day" \| "top"` | No | No | low | none | no |
| 3: Browse | `limit` | miniapp.py:2585 — `_bounded_int(body.get("limit"), default=80, maximum=999999)` | SQL query | `int` (1..999999) | No | No | low | Default 80 for UI, 999999 maximum means no practical limit. | Deliberate — "no limits" feed per code comment. | no |
| 3: Browse | `viewer_user_id` | miniapp.py:2583 — from `ctx["user"].id` | `_generation_row_to_card` → sets `is_mine`, `is_liked`, etc. | `int` | No | No | low | none | no |
| 3: Browse | `author_referral_code` | database.py:5735 — `u.referral_code AS author_referral_code` (SQL JOIN) | Card payload → frontend | `str \| None` | No | No | **medium** — Exposed in all feed cards. Could enable referrer-impersonation by inspecting codes. | Low practical risk since codes are already public URLs. | no |
| 3: Browse | `remix_count` | database.py:5728-5732 — subquery `SELECT COUNT(*) FROM generation_tasks child WHERE child.parent_generation_id = gt.id` | Card payload | `int` | No | No | low | Counts only `status='completed'` children — correct for public display. | yes |
| 3: Browse | `comments_count` | database.py:5733-5737 — subquery on `feed_comments` | Card payload | `int` | No | No | low | none | no |
| 3: Browse | `score` | database.py:5656-5661 — `_calculate_feed_score(row)` | Sorting for `top`/`top_day` | `float` | Not in card payload (internal only) | No | low | none | no |
| 3: Browse | `prompt` | database.py:5676 — `"" if prompt_hidden else str(row["prompt"] or "")` | Frontend | `str` | **Deliberately hidden** if `source_feed_gen_id IS NOT NULL` or `feed_prompt_visible=0` | No | low | none | no |
| 3: Browse | `gen_type` | database.py:5674 — `row["type"]` | Frontend rendering | `"image" \| "video" \| "audio" \| "character"` | No | No | low | none | no |
| 3: Browse (frontend) | `source` | api.ts → `fetchFeed({source: 'recent'})` | POST /feed with `source` param | `"recent" \| "top_day" \| "top"` | No | No | low | none | no |
| 3: Browse (frontend) | `genId` | api.ts:fetchFeedItem → payload `gen_id` | `_miniapp_payload` → resolves via `gen_id \| task_id \| feed_id` | `int \| str` | No | No | low | Same alias ambiguity as Flow 2. | no |

---

## Flow 4: Feed Remix / Repeat

### 4a. Mini App Remix (Image)

| Flow | Parameter | Created at | Expected by | Actually passed | Lost? | Type mismatch? | Security/antifraud risk | Fix needed? | Test needed? |
|------|-----------|------------|-------------|-----------------|-------|----------------|------------------------|-------------|--------------|
| 4a: Remix | `gen_id` | miniapp.py:2899 — `body.get("gen_id") or body.get("task_id")` | `get_feed_generation_card(gen_id)` | `int \| str` | No | No | **medium** — Same alias ambiguity. | None immediate. | yes |
| 4a: Remix | `source["id"]` | From `get_feed_generation_card` result | Passed as `source_feed_gen_id` AND `parent_generation_id` | `int` (DB PK) | No | **No — but note**: `source_feed_gen_id` and `parent_generation_id` receive the SAME value (line 2973-2974): `source_feed_gen_id=int(source["id"]), parent_generation_id=int(source["id"])` | **high** — These are semantically different: `source_feed_gen_id` means "derived from this feed post", `parent_generation_id` means "this is a child generation". Setting both to same value conflates them. | `source_feed_gen_id` tracks attribution, `parent_generation_id` tracks lineage. They should not always be equal. When a remixed item is remixed again, `parent_generation_id` should point to the immediate parent, not the original source. | yes |
| 4a: Remix | `source_prompt` | miniapp.py:2910 — `source_task.get("prompt")` | Falls back to `prompt` if user doesn't provide one | `str` | No | No | **medium** — Prompt leakage: remix reveals the source prompt if `prompt_hidden=False` on source. | Design decision: prompt visibility is controlled by `source.feed_prompt_visible`. Works correctly via `_task_prompt_hidden` check. | yes |
| 4a: Remix | `unit_cost` | miniapp.py:2956-2960 — from `QUALITY_COSTS` or `preset_manager` | `check_can_afford`, `deduct_credits`, `credit_feed_prompt_repeat` | `int` | No | No | low | none | no |
| 4a: Remix | `action_type` | miniapp.py:2975 — hardcoded `"remix"` | `add_generation_task` → DB column `action_type` | `str` | No | No | low | none | no |
| 4a: Remix | `launch_result.task_id` | From `_start_image_generation_task` | Response + `credit_feed_prompt_repeat(repeat_task_id=...)` | `str` (KIE task ID or local UUID) | No | No | low | none | no |
| 4a: Remix (frontend) | `genId` | api.ts:remixFeedItem → payload `gen_id` | → `_miniapp_payload` → `miniapp_feed_remix` | `int` | No | No | low | none | no |
| 4a: Remix (frontend) | `source_feed_gen_id` | Response field `source_feed_gen_id: number` | Used in frontend to tag remix lineage | `int` | No | No | low | none | no |

### 4b. Remix Credits to Source Author

| Flow | Parameter | Created at | Expected by | Actually passed | Lost? | Type mismatch? | Security/antifraud risk | Fix needed? | Test needed? |
|------|-----------|------------|-------------|-----------------|-------|----------------|------------------------|-------------|--------------|
| 4b: Credit | `source_generation_id` | miniapp.py:2977 — `int(source["id"])` | `credit_feed_prompt_repeat(source_generation_id, ...)` | `int` | No | No | low | none | no |
| 4b: Credit | `repeater_user_id` | miniapp.py:2978 — `user.id` | `credit_feed_prompt_repeat` | `int` | No | No | **medium** — If user remixes own generation, reward should be skipped. | Verified: `credit_feed_prompt_repeat` checks `repeater_id == author_id` via `_credit_prompt_repeat_reward_in_db`. Needs confirmation this returns `False` for self-rewards. | yes |
| 4b: Credit | `credits_spent` | miniapp.py:2978 — `unit_cost` | `credit_feed_prompt_repeat` → reward calculation | `float` | No | No | low | none | no |
| 4b: Credit | `prompt_repeat_balance_rub` | database.py — `_credit_prompt_repeat_reward_in_db` updates `users.prompt_repeat_balance_rub` | Partner panel display | `float` | No | No | low | none | yes |
| 4b: Credit | `prompt_repeat_total_rub` | database.py — accumulated total | Partner panel display | `float` | No | No | low | none | yes |

---

## Flow 5: Partner Panel / Referrals

| Flow | Parameter | Created at | Expected by | Actually passed | Lost? | Type mismatch? | Security/antifraud risk | Fix needed? | Test needed? |
|------|-----------|------------|-------------|-----------------|-------|----------------|------------------------|-------------|--------------|
| 5: Partner | `referral_code` | database.py:1287 — `generate_referral_code(db)` → stored in `users.referral_code` | `build_referral_link(bot_username, referral_code)`, `build_referral_bot_link(...)` | `str` (8-char uppercase alphanumeric) | No | No | low | none | no |
| 5: Partner | `referral_bot_link_str` | common.py:3924 — `build_referral_bot_link(me.username, referral_code)` | Rendered to user as `ref_<CODE>` | `str` URL | No | No | low | none | no |
| 5: Partner | `referral_link` | common.py:3918 — `build_referral_link(me.username, referral_code)` | Rendered to user as `startapp=ref_<CODE>` | `str` URL | No | No | low | `ref_` prefix is embedded in URL. Consistent with `_referral_code_from_start_param` parsing. | no |
| 5: Partner | `stats` dict | `get_partner_overview(telegram_id)` → dictionary from database.py:2267 | `render_partner_program`, `miniapp_partner_overview` | `dict` with ~20 keys | No | No | **high** — `balance_rub` subtracts `pending_rub` for available balance, but `get_partner_overview` returns BOTH `balance_rub` (available) and `total_balance_rub` (raw). Frontend uses `balance_rub` — correct. | Verified `miniapp_partner_overview` (line 3836): returns `balance_rub = float(stats.get("balance_rub", 0))`. This is the available balance. Safe. | yes |
| 5: Partner | `prompt_repeat_balance_rub` | Returns `min(prompt_repeat_balance_rub, available_balance)` | Frontend | `float` | No | No | **high** — Caps `prompt_repeat_balance_rub` at `available_balance`. If prompt_repeat exceeds available, displayed value silently capped. | This is correct — prevents negative available balance. | yes |
| 5: Partner | `partner_balance_rub` | database.py:2317 — `round(max(0.0, raw_balance - pending_rub), 2)` | Frontend display | `float` | No | No | low | none | no |
| 5: Partner | `tier` | `get_partner_tier_by_total(partner_total_revenue_rub)` | Frontend display | `"basic" \| "silver" \| "gold" \| ...` | No | No | low | none | no |
| 5: Partner | `percent` | `get_partner_percent_by_tier(tier)` | Display only | `int` | No | No | low | none | no |
| 5: Partner | `is_partner` | `bool(target_user.partner_agreed_at)` | Frontend: gate for partner features | `bool` | No | No | **medium** — `partner_agreed_at` is set only after user accepts offer. Until then, `is_partner=False` even if they have referrals/earnings. | Design decision: requires explicit consent. Correct. | no |

---

## Flow 6: Mini App Referral Link (Frontend → Backend)

| Flow | Parameter | Created at | Expected by | Actually passed | Lost? | Type mismatch? | Security/antifraud risk | Fix needed? | Test needed? |
|------|-----------|------------|-------------|-----------------|-------|----------------|------------------------|-------------|--------------|
| 6: MA link | `referral_code` (URL param) | miniapp_links.py:64 — `referral_start_param(referral_code)` → `f"ref_{code}"` | Telegram deep-link → `parseMiniAppStartParam` | `str` prefixed `ref_` | No | No | low | none | no |
| 6: MA link | `startapp=ref_<CODE>` | miniapp_links.py:68 — `miniapp_startapp_link(bot_username, start_param)` | Telegram WebApp → `initDataUnsafe.start_param` | URL-encoded string | No | No | low | none | no |
| 6: MA link | `start_param_fallback` | api.ts:`getStartParamFallback()` → auto-appended to all POST requests | `_get_user_context` | `str` from URL hash/query/initData | No | No | **medium** — `getStartParamFallback` has multiple fallback sources (initDataUnsafe → tgWebAppStartParam → startapp → start → initData parsed → `ref` query). The order matters for which referral code is extracted. | Checked: `_referral_code_from_start_param` normalizes all variants. The layer works consistently. | yes |
| 6: MA link | `referralCodeForAttribution` | `parseMiniAppStartParam` → used when profile/feed/remix links have `_ref_` suffix | `_referral_code_from_start_param` extracts it from pattern `{prefix}_{id}_ref_{code}` | `str \| undefined` | **Possibly** — `referralCodeForAttribution` is in `MiniAppStartTarget` type but the API layer sends start_param, not the parsed attribution code separately. | No | **high** — Attribution code might not be applied if it's in profile/feed URL but `_get_user_context` extracts it from raw `start_param` rather than the parsed object. | Verified: `_referral_code_from_start_param` handles `profile_`, `feed_`, `remix_`, `prompt_` prefixes with `_ref_` suffix (lines 720-729). The extraction occurs server-side from raw `start_param`, so it's fine. | yes |
| 6: MA link | `user.referred_by` | Set by `process_referral` / `set_user_referrer` | Partner stats queries | `int \| None` (user ID of referrer) | No | No | **high** — `referred_by` is `user.id`, not `telegram_id`. All joins must use `referred_by = u.id`, not `referred_by = u.telegram_id`. | Checked all partner queries: they join `users u2 ON u2.referred_by = u1.id` — consistent. | yes |

---

## Cross-Cutting Naming Issues

### `referral_code` vs `ref_code` vs `code`

| Context | Name used | Location | Consistency |
|---------|-----------|----------|-------------|
| DB column | `referral_code` | `users.referral_code` | ✅ Consistent |
| URL prefix | `ref_` | `referral_start_param`, `parseMiniAppStartParam` | ✅ Consistent |
| Service parameter | `referral_code` / `code` | `process_referral(referred_telegram_id, referral_code, ...)` → normalizes to `code` internally | ⚠️ Mixed — parameter name differs from internal var |
| Mini App extraction | variable `referral_code` | `_referral_code_from_start_param` → `.strip().upper()` | ✅ Consistent |
| `cmd_start` extraction | `referral_code_from_args` | common.py:3492 | ⚠️ Different variable name but same semantic |

### `user_id` vs `referrer_id` vs `partner_id`

| Context | Name | Means | Table |
|---------|------|-------|-------|
| `user_id` | The performing user's DB PK | `users.id` | ✅ Consistent |
| `referred_by` | The referrer's `users.id` | Stored on the referred user's row | ✅ Consistent |
| `referrer_id` | The referrer's `users.id` | Used in `referrals` table | ✅ Consistent across all joins |
| `partner_id` | Not used as a distinct ID | N/A | ✅ Not an issue |

### `referral_bonus` / `bonus_credits` / `reward`

| Context | Name | Value | Location |
|---------|------|-------|----------|
| New user signup | `PARTNER_NEW_USER_BONUS` | `15` (hardcoded in `users.credits`) | database.py:84 — `INSERT INTO users (...) VALUES (..., 15, ...)` |
| Inviter bonus | `PARTNER_INVITER_BONUS` | `3` (hardcoded) | database.py:85 — used in `process_referral_click` |
| `referrals.bonus_credits` | Set to `0` on creation | Not the inviter bonus (that goes to `users.credits`) | database.py:1688 — `INSERT INTO referrals (...) VALUES (..., 0)` |
| Bot display text | `"🍌 бананов"` | User-facing name | ✅ Consistent branding |

### `status` — Antifraud Rate-Limit Statuses

All defined in `VALID_REASONS` (referral_service.py:30-47):

| Status | Meaning | Security Implication |
|--------|---------|---------------------|
| `attached` | Successful referral bind | ✅ Normal |
| `empty_code` | No code provided | ✅ Safe |
| `code_not_found` | Invalid referral code | ✅ Safe |
| `self_ref` | User tried own code | ✅ Blocked |
| `already_has_referrer_same` | Already referred by same person | ✅ Idempotent |
| `already_has_referrer_other` | Already has a different referrer | ✅ Protected |
| `already_paid` / `completed_payment_exists` | Paid users can't be referred (retroactively) | ⚠️ Users who paid THROUGH referral flow won't count? Needs verification. |
| `blocked_code` | Code in `REFERRAL_ANTIFRAUD_BLOCK_CODES` | ✅ Active antifraud |
| `blocked_referrer` | Referrer in `REFERRAL_ANTIFRAUD_BLOCK_REFERRER_IDS` | ✅ Active antifraud |
| `hourly_limit` | Exceeded `REFERRAL_ANTIFRAUD_MAX_PER_HOUR` (30) | ✅ Rate limiting |
| `daily_limit` | Exceeded `REFERRAL_ANTIFRAUD_MAX_PER_DAY` (120) | ✅ Rate limiting |
| `cycle_detected` | Referral loop detected | ✅ Protected |
| `db_race_lost` | Concurrent referral bind won by another request | ✅ Safe |

### `feed_item` / `gen_id` / `generation_id` / `task_id`

| Context | Name | Meaning | Location |
|---------|------|---------|----------|
| DB PK | `generation_tasks.id` | Internal integer auto-increment | DB |
| External ID | `generation_tasks.task_id` | String UUID / KIE task ID | DB |
| API param | `gen_id` | Accepts either `id` or `task_id` | `_miniapp_payload` (line 1964-1968) |
| API param alias | `generation_id` → `gen_id` | Normalized in `_miniapp_payload` | miniapp.py:1966 |
| API param alias | `feed_id` → `gen_id` | Normalized in `_miniapp_payload` | miniapp.py:1968 |
| Frontend type | `FeedItem.id` | Maps to `generation_tasks.id` | ⚠️ Type is `number` |
| Frontend type | `Task.task_id` | Maps to `generation_tasks.task_id` | Type is `string` |

**Issue:** `gen_id` is overloaded — can be numeric `id` or string `task_id`. Resolution happens in `_fetch_generation_row(db, gen_id, user_id)` and `_miniapp_payload` separately. This could cause mismatches if payload-level normalization and DB-level resolution diverge.

### `result_url` / `image_url` / `video_url`

| Context | Name | Format | Location |
|---------|------|--------|----------|
| DB primary | `generation_tasks.result_url` | Single string URL | DB |
| DB secondary | `generation_tasks.result_urls` | JSON array of URLs | DB |
| Card output | `result_url` | `feed_urls[0]` (first available URL) | `_generation_row_to_card` |
| Card output | `result_urls` | All available URLs (filtered) | `_generation_row_to_card` |
| Frontend API | `saved_url` | Single URL (for immediate result) | Mini App response |
| Frontend API | `result_url` | Single URL (for task status) | Task list response |

✅ Consistent — `result_url` always HTTP URL, `result_urls` always list of HTTP URLs.

### `is_public_feed` / `is_prompt_library`

| Context | Name | Meaning | DB Column | Notes |
|---------|------|---------|-----------|-------|
| Feed publish | `is_public_feed = 1` | Visible in feed | `generation_tasks.is_public_feed` | Set by `share_to_feed()` |
| Prompt library | `is_prompt_library = 1` | Prompt shared to library | `generation_tasks.is_prompt_library` | Set by `share_to_library()` |
| Guard | `source_feed_gen_id IS NOT NULL` | A remix — can't re-share to feed | Checked in `share_to_feed` | ✅ |
| Guard | `source_feed_gen_id IS NOT NULL` | A remix — can't share to library | Checked in `share_to_library` | ✅ |
| Prompt visibility | `feed_prompt_visible` | Whether prompt shown in feed card | `generation_tasks.feed_prompt_visible` | Set during `share_to_feed` |
| References visibility | `feed_references_visible` | Whether references shown in feed card | `generation_tasks.feed_references_visible` | Set during `share_to_feed` |

### `source_feed_gen_id` vs `parent_generation_id`

| Context | Meaning | Set when |
|---------|---------|----------|
| `source_feed_gen_id` | "Which feed post was this derived from" | Any generation initiated from feed context (remix, generate-image with source) |
| `parent_generation_id` | "Which generation is the direct parent" | Remixes — should point to immediate parent |
| Current behavior | Both set to SAME value | `miniapp_feed_remix` line 2973-2974 |
| **Problem** | `parent_generation_id` used for lineage counting (remix_count subquery), `source_feed_gen_id` used for hiding prompt/actions | ⚠️ If user remixes a remix, both IDs point to the ORIGINAL source, breaking parent-child chain |

---

## Top Risks Summary

| # | Risk | Severity | Flows affected |
|---|------|----------|---------------|
| 1 | `source_feed_gen_id` == `parent_generation_id` always — breaks multi-hop remix lineage | **high** | 4a |
| 2 | Ephemeral result URLs may expire silently if `persist_feed_result_urls` partially fails | **high** | 2 |
| 3 | `gen_id` overloaded (numeric id / string task_id) with resolution in 2 separate places | **medium** | 2, 3, 4a |
| 4 | `get_or_create_user` called twice in `cmd_start` (before and after referral attach) | **medium** | 1a |
| 5 | Antifraud hourly/daily limits produce silent failures — no user-facing message | **medium** | 1c |
| 6 | `feed_prompt_visible` DB column vs `prompt_visible` API key naming inconsistency | **low** | 2 |
| 7 | `_referral_code_from_start_param` duplicates some logic from `cmd_start` extraction | **low** | 1a, 1b |
| 8 | `referrals.bonus_credits` always set to 0 — column appears unused for actual bonuses | **low** | 1c, 5 |

---

## Recommendations

1. **Fix `parent_generation_id` chain** — When remixing a remix, `parent_generation_id` should point to the immediate parent (the remix being remixed), not the original source. `source_feed_gen_id` should stay pointing to the original.
2. **Add alerting for failed feed persist** — Log a warning-level message and surface to admin when `persist_feed_result_urls` returns fewer URLs than input.
3. **Unify `gen_id` resolution** — Make `_miniapp_payload` and `_fetch_generation_row` use a single shared resolver function.
4. **Add user-facing messages for rate-limited referrals** — When a referral is blocked by hourly/daily limit, show a user-friendly message instead of silently ignoring.
5. **Audit `referrals.bonus_credits` column** — Either populate it with actual bonus values or remove it if unused.
