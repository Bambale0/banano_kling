# Smart repeat release audit — 2026-10-19

## Baseline and scope

Inspected production `tanyapi` at `9c253009f1f5f56542216e81f4425ebd04469d1a`.
The attached specification describes eight **proposed** smart-repeat epics; it
explicitly says they were not registered as GitHub issues. The eight actually
open GitHub epics, issues #60–#67, concern security, billing and architecture.
They are different backlogs. The user confirmed that the selected scope is the eight smart-repeat epics
from the attachment. Security epics #60–#67 remain a separate backlog.

The production checkout contains local edits to `bot/database.py` and the
admin-managed `data/price.json`. Audit work uses a separate worktree. No prices,
customer media, balances or provider settings are changed by this audit.

## Attached smart-repeat backlog

| Proposed epic | Existing implementation | Remaining release acceptance |
| --- | --- | --- |
| EPIC-01 — Paid launch safety | Video repeat restoration and consent recheck; typed-repeat durable receipts; Wan quote, idempotency and transactional lifecycle | One documented launch contract across image/video/repeat modes, including uploads in progress; durable client operation keys; all no-debit and replay cases |
| EPIC-02 — Universal slots | `video_repeat_reference_contract.py`; legacy bridge; Wan keyed replacements and private source compiler | Stable public slot and asset identities shared across models/surfaces; immutable input snapshot; strict typed binding without relying on upload order |
| EPIC-03 — Upload persistence | Saved references; Wan upload sessions; Seedance upload/chunk paths; ownership-aware retention | Shared per-repeat slot state machine and server recovery; stale upload response fencing; draft/snapshot retention roots and deletion-race tests |
| EPIC-04 — Author constructor | Owner publication reference visibility and fixed/upload permission controls; curated trend editors | General author-managed slot labels, hints, requirements and validated limits, with server-side ownership and model compatibility |
| EPIC-05 — Repeat interface | Ordinary video numbered upload fields; Wan per-key replacement fields | Shared named cards, persisted per-slot progress/error/reload handling, authoritative readiness and server-confirmed pricing |
| EPIC-06 — Personalization presets | Existing trend user fields and specialized recipe features | Versioned author-configured variants with prompt-compatible slot selections; no automatically invented presets |
| EPIC-07 — Compatibility | Existing version-1 video grant and legacy slot inference | Immutable template revisions, reversible migration/audit for unambiguous cases, explicit review state for ambiguous publications |
| EPIC-08 — QA and release | Python/domain, SQLite/PostgreSQL, mobile browser and protected production CI/CD gates | End-to-end coverage of the new complete workflow; structured slot/asset/task telemetry; exact-SHA deploy and production acceptance |

These rows record reuse opportunities and missing acceptance criteria. They do
not claim that the eight proposed epics are implemented or released.

## Existing open epics

| GitHub epic | Audit finding at baseline |
| --- | --- |
| #60 — Telegram webhook authentication and queue | `handle_telegram_webhook` reads JSON before any secret validation and creates a task per request before its semaphore; configured `TELEGRAM_WEBHOOK_SECRET` is absent. Acceptance remains open. |
| #61 — Atomic generation lifecycle | Wan and typed video repeats have stronger receipts/lifecycle controls; generic paths still have distinct checks, debit and refund orchestration. Do not infer global atomicity from specialized tests. |
| #62 — Payment orchestration | Lava authentication/reconciliation fixes exist in history, but the complete cross-provider checklist needs a fresh transaction and route audit. No payment mutation performed. |
| #63 — Private storage | Reusable reference URLs still use `/uploads/refs/<kind>/<telegram_id>/...`; publication consent does not itself close direct storage access. Namespace/signed-delivery migration remains material work. |
| #64 — SSRF and provider callbacks | Existing adapters and fetchers need a call-site inventory against the epic's shared policy. No claim of complete verification. |
| #65 — DoS and degraded policy | Webhook admission is still unbounded before the semaphore. Pagination/proxy/access/Redis/container acceptance must be checked separately. |
| #66 — Mini App sessions and lifecycle | `_validate_init_data` accepts a one-day absolute clock difference; CORS reflects arbitrary Origin with credentials. Session and lifecycle acceptance remains open. |
| #67 — Architecture and supply chain | CI has four strict mandatory gates and builds the frontend, but Python dependencies retain version ranges and the modules remain broad. CI improvements alone do not close this epic. |

No open epic may be closed merely because a related patch or CI job exists.

## Immediate reference safety PRs

- PR #325: functional canonicalizer change is already in `tanyapi`, introduced
  by release #326 (`63d6e8b2164de223f80ca950460c697e123237c1`). Comparison against
  the PR head shows no functional delta in
  `bot/services/seedance_reference_binding.py`; its test delta is formatting.
  Avoid merging the stale/conflicting branch to ship the same fix twice.
- PR #328: fail closed when saved-reference storage validation raises.
  Reviewed head: `9328ed4bc1fd12274f38b5bca709aca60aa6ba9b`.
  Independent standards and spec reviews reported zero findings. Native squash
  auto-merge armed; all four required PR gates passed, including 3864 safe
  regression tests (115 skipped, 76 subtests passed). Merged as
  `6566eb26eb4b102197a2c7610cf0723d98920a8a`; exact post-merge CI, deployment
  and production health/static revision/storage-error smoke were verified. This is a prerequisite, not the whole smart-repeat
  feature.

## Release safeguards

Use the existing quote, permission, provider and financial lifecycle seams;
do not create a second repeat engine or bypass strict branch protection.
Retain current prices and source media. Preserve legacy requests and immutable
accepted task snapshots. No live paid generation, balance correction, webhook
secret change or destructive storage cleanup is part of this audit.

Production read-only baseline: backend health `status=ok`; Docker OCI revision
matches `9c253009f1f5f56542216e81f4425ebd04469d1a`; exact-SHA production CI and
reliable deployment runs report success. Disk has approximately 25 GiB free
(98% used); issue #323 tracks capacity and does not authorize data deletion.

## Verification record

The audit used current `Bambale0/skills` wayfinder, diagnosing-bugs, implement,
tdd and code-review guidance; `Bambale0/claw` PR review checklist;
`anthropics/skills` webapp-testing guidance. All three local playbook checkouts
were refreshed successfully.

Execution progress and exact test/release outcomes are recorded in
`docs/agents/EXECUTION.md`.
