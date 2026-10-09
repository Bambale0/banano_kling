# Partner policy update (prepared branch, not deployed)

## Economics and eligibility

The first-line default remains30%. An authorized administrator assigns each existing partner a personal0–100% rate with at most two decimal places by Telegram ID, with quick0/30/40 choices and explicit confirmation. No account is automatically promoted to40%, and there is no hardcoded recipient exception. A0% assignment disables only first-line purchase commission; second-line7%, repeat5 RUB and inviter3 bananas remain independent. New invoices freeze the explicit per-partner rates, so later administrative changes do not alter accepted terms. The paid calculation base remains the stored transaction.amount_rub, with the existing rounding and commission ledger. Tier labels do not increase these rates.

New repeat tasks snapshot 5 RUB for the original author in the existing prompt_repeat_events ledger. This is a ruble partner balance reward, not five generation credits. New-user registration still grants 5 bananas. The inviter's 3 bananas are deferred until the invited account's first server-accepted generation (image, video, motion, audio or character) after attachment, including a launch funded by starter bananas.

Partner access no longer requires submitting or approving an activation application or recording agreement consent. Historical applications and consent timestamps are retained unchanged; old activation controls open the cabinet. Existing authentication, bans, admin authorization, referral guards, withdrawal minimum and pending-withdrawal balance reservations remain enforced.

## Configuration

Generation prices remain owned by the existing admin price system; this feature never writes data/price.json. First-line rates are database-backed and managed in the Telegram admin partner section. Settings are revision-checked, atomic with an append-only audit (actor, target, before/after), and require backend administrator authorization. Unknown users, stale confirmations, invalid numbers and failed audit writes cannot mutate a rate or balance. Other future partner terms retain typed configuration:

- PARTNER_LEVEL1_PERCENT is retired for future invoices; the unassigned baseline is30%, never an automatic global40%
- PARTNER_LEVEL2_PERCENT: 7 by default, finite 0–100
- PARTNER_LEVEL1_OVERRIDES_JSON defaults to{}; existing explicit per-ID configuration is preserved as a fallback, below a saved administrator assignment
- PARTNER_REPEAT_REWARD_RUB: 5 by default, finite non-negative rubles

The previous PROMPT_REPEAT_REWARD_RUB variable does not override the new versioned policy. Deployment preparation must verify the intended new policy settings without copying or replacing live generation prices. No runtime settings were changed while preparing this branch.

## New additive tables and historical compatibility

- partner_commission_settings stores explicit per-recipient rates as exact integer hundredths of a percent and revision numbers; partner_commission_audit is append-only
- partner_payment_terms snapshots the rates and all explicit recipient overrides when an invoice is created, including a partner who is attached after that invoice was created
- Canonical generation_tasks.request_data snapshots versioned repeat economics and eligibility; provider acceptance is persisted atomically with the task/provider-ID binding, with no ancillary generation-policy table
- referral_activation_bonuses stores pending and granted one-time invite claims; only a newly attached referral creates a row

Schema creation is idempotent, via init_db and schema_postgres.sql. There is no historical data backfill, referral-link rewrite or repricing. Pre-existing pending invoices without a policy snapshot retain 30%/7%. Pre-existing generation tasks without a repeat snapshot retain 10 RUB when their existing completion/credit path runs. Existing commission/repeat ledger entries are untouched. Refund/debit amounts retain their original stored generation cost; no live refunds or balance actions are performed by this branch preparation.

## Acceptance and retries

A click, start parameter, menu, price quote, upload, local job placeholder, rejected validation or failed provider submission cannot credit the inviter. Supported server paths explicitly mark provider acceptance only after their debit/validation and positive provider response. Synchronous successful generation also supplies acceptance proof through completion. Administrative/free replays do not qualify. Paid audio/character generation qualifies when the server has accepted-provider or successful-result proof.

The canonical acceptance proof is committed with the task identity before bonus bookkeeping. Policy fields supplied by a client or copied source recipe are ignored; server-owned previous receipt terms are preserved. The grant and inviter credit are in one transaction, guarded by a conditional claim per invited account. Retry/concurrent callbacks cannot grant twice. Bookkeeping failure never makes an accepted provider job look failed or triggers an automatic refund. The existing watchdog parses canonical JSON independent of formatting and fairly retries one accepted candidate per pending referral, including a job which was accepted and later failed. This reflects the approved launch-based qualification, not completion-based qualification.

Only newly attached referrals can qualify. A generation made before attachment is excluded using its stored generation ID. Self-referrals, cyclic ancestry and banned inviter/invited accounts fail closed. This does not identify one human across multiple Telegram accounts and is not a complete anti-fraud system.

## Verification and release limits

Run the focused tests/test_partner_policy.py plus referral, payment, generation, private-repeat, partner API/bot/UI and auth suites. A dedicated disposable PostgreSQL test and CI hook are included but cannot run in this local environment. Browser E2E is blocked before launch by Chromium socket permissions. Both remain release gates and must pass for the exact published candidate in GitHub. The requested release order is the ordinary Seedance 2 pricing correction first, then this policy after complete publication, CI and independent review. The release candidate must include the manual per-partner editor; the earlier global-rate draft is superseded.

The combined share-link regression uses the authenticated sharer's referral code while keeping the original author's repeat reward. It verifies starter-funded acceptance grants the sharer 3 bananas once, the author receives 5 RUB once, and manual 0/30/40% purchase terms remain frozen after a later rate change. Upstream share-link and attribution fixes are retained.

Prompt/trend reward callers now pass the accepted task identity. Repeat ledger claims use a stable numeric generation identity, recognize pre-existing alias-based events, and read the frozen reward across provider-ID retries. Completed commission exports read actual ledger values, then invoice terms, then documented legacy rates. No historical amount is recalculated using the current default.
