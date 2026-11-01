# Seedance: Neironych primary, KIE fallback — 2026-11-02

Baseline: `da48cd126f279ef7da91c6c956268150029f88db`, production branch `tanyapi`.
Task branch: `feat/neironych-primary-kie-fallback-20261102`.

## Audit and acceptance

Both Telegram and Mini App call the shared Seedance services and Market polling seam. The existing durable routing table, provider client, reference binding, local video persistence, active-generation lock and watchdog protection can be reused. Primary selection and reverse fallback were absent; Seedance 2.5 rejected missing KIE keys even for Neironych. Existing production price JSON has unrelated local modifications and is not changed by this task.

Acceptance: Neironych first for Seedance 2.0/2.5; KIE on proven rejection/failure only; identical prompt/media order and user-facing task ID; one customer charge; durable polling/recovery; no second paid submit on unknown acceptance; existing tasks remain recoverable; exact-SHA CI/autodeploy and live smoke verified before release claim.

## Configuration and implementation

Managed env `SEEDANCE_PRIMARY_PROVIDER=neironych`, `SEEDANCE_FALLBACK_PROVIDER=kie`; historical defaults remain backward compatible. No prices, customer balances, schemas or UI fields change. Routing settings are server-side and never exposed to users. Neironych primary/fallback choice is frozen in the private route payload, which is scrubbed on completion/failure.

1. Reproduce with tests: 9 failures confirmed missing primary selection and Seedance 2.5 key gate.
2. Implement shared configurable routing and durable KIE phases using the existing table, owner checks, transaction claim and stable receipt. Strip KIE callback only for locally routed fallback; remote ID is polled internally.
3. Verify SQLite and PostgreSQL concurrency, no unowned/refunded submits, uncertain acceptance, reference preservation, polling, final failure, legacy recovery, and key independence.
4. Run full safe regression and deploy validation; review focused diff, private-data and no-hardcode checks.
5. PR to `tanyapi`, arm native squash auto-merge, verify required gates and exact production SHA.
6. Activate managed routing settings, run real API primary/fallback smokes in isolated state, verify persisted video and public content; check logs.

## Known provider boundary

KIE uncertain create has no verified idempotency contract. It is held for operator reconciliation without repeat submit or speculative refund. Neironych 409/5xx/transport uncertainty retries the same durable idempotency key. Compatibility fallback sends unsupported controls unchanged to KIE before any Neironych generation.

## Validation evidence

Focused SQLite/product regression: 191 passed. Real isolated PostgreSQL: 52 passed (temporary container, per-test schemas); container removed after tests. Ruff check and git diff --check passed. Candidate live smokes are running for both models through each provider; no release claim until CI, production revision and live results are recorded.

## Skills

Read current repository AGENTS/README and relevant service/tests/docs; used Bambale0/skills diagnosing-bugs and test-first loop; inspected Bambale0/claw kie-seedance lifecycle guidance and anthropics/skills webapp-testing. No frontend changes are required, but existing CI browser gate remains mandatory. Referenced claw bootstrap instruction files are absent in this repository, so local AGENTS governs. All three playbook checkouts updated successfully.
