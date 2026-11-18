# Astro — bounded concurrent generation and numeric-proof salvage (2026-11-18)

## Diagnosis / baseline

- Production evidence: report `d52bea42a08c43f8b3e43e97d9fcd737`, natal, 18 planned sections, started at 2026-11-18 17:43:27 UTC and failed at 18:04:21 UTC after two job attempts with `section_validation_failed`. Last three checkpointed sections were `section_03`–`section_05`.
- Each serial GPT-6/KIE call took 65–199 seconds. The `section_06` unsupported numeric claims triggered expensive repeat calls. Effective serial throughput was ~3 completed sections in 21 minutes.
- Existing `compose_report` iterated sections sequentially; `ASTRO_REPORT_WORKERS=1` runs one report worker, **not concurrent sections within one report**.
- Baseline for change: `8ba493696aa83d030bf75636b23290662e00936a` on branch `tanyapi`.

## Intended behavior and implementation

1. `ASTRO_REPORT_SECTION_CONCURRENCY` accepts **1–4** and defaults to **1** for backward-compatible deployments; production will explicitly set **3** in operator-managed `.env.astro` and release the exact merge SHA. No other provider/model/payment settings change.
2. Each report's sections run in bounded 3-way waves. Successful individual sections are checkpointed atomically and encrypted as before. Failed sibling calls do not discard successfully checkpointed sections; after a failed wave no further paid wave is scheduled. On retry only missing sections are regenerated. Final report and PDF still require all sections and target words, in plan order.
3. For `unsupported_claim` errors, try **deterministic deletion of whole sentences containing unsupported numeric claims** and re-check the full candidate against the unchanged deterministic numeric fact gate and minimum word count. Refuse repair if it would remove more than 20% of words; preserve the original bounded LLM rewrite otherwise. Never synthesize or silently alter numerical evidence. Do not weaken proof checks.
4. Log safe section identifiers, word counts and safe-repair occurrence without user birth data, raw content or KIE keys. Correlation is retained in existing per-job worker logs.
5. The same owner/consent, full-report requirement, provider adapter, leases, delivery and unlimited fresh-report contract from #618 remain unchanged.

## Test/release plan

- Tight red test: sequential baseline times out waiting for three simultaneously started mock provider calls; invalid parallelism config is not validated; unsupported claims trigger repeated paid vendor calls even when safe portions suffice.
- Green tests: bounded parallelism (3 simultaneous, not 4), partial checkpoint recovery, per-section ordering, validation safeguards, verified numeric values retained across line breaks, full seven-service E2E and worker integration with `ASTRO_REPORT_SECTION_CONCURRENCY=3`, whole Astro regression set and lint.
- Production: arm native GitHub auto-merge into `tanyapi`; ensure four protected gates, production image and backend exact SHA. Update `.env.astro` atomically (restricted permissions, keep secure rollback copy) with the concurrency value before the next normal deploy. Do not restart production outside normal deployment. Verify actual running env after rollout.
- Smoke: health 200, worker started, section checkpoint logs, progress over multiple sections, correct report status and Telegram delivery where authorized. Avoid duplicating already-paid failures solely for speed benchmarking.
- Rollback: set concurrency to 1 for immediate safe serialized behavior on next container recreation; revert PR for code issues. No DB schema migration.

## Risks

- Vendor throughput/rate limits and costs: three concurrent KIE calls per report may increase peak load. Runtime param can be rolled back to 1 or adjusted to 2 without code changes; circuit breaker and retry/error handling remain.
- This improves report wall-clock time but cannot guarantee a fixed SLA from third-party KIE; no real-provider latency benchmark until deployment.
- A failed section may still need a full rewrite if safe sentence deletion breaches minimum size, quality threshold, or numeric proof. Never mark partial reports complete.

## Evidence

- First red TDD run: 6 failures (sequential test timeout, missing concurrency validation, unsalvaged invalid numeric assertions), 2 green controls.
- Targeted fixes: 42 pipeline tests passing and Ruff clean at `c053497cbfcc4e4f78dff628792db21efc08d9ff`.
- Broad pre-final baseline: 328 Astro tests passed, 9 environment-skipped; seven-service/worker integrations with concurrency=3: 14 passed at `b972241c1a00059e22756d1317d24722ad1730ca`.
- Update verification and post-deploy evidence after production release before claiming real-world improvement.
