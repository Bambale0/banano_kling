# Astro report latency — bounded parallel sections

## Baseline / user-visible problem

- Current production/tanyapi: `8ba493696aa83d030bf75636b23290662e00936a` (PR #618).
- Real same-input smoke jobs `0ef43c778ca16aa460dfba5b8ee109f5` and `f11734020574dbfa2c8173b2dfe09fea` were created independently through the authenticated production API. HTTP replay did not duplicate either job.
- At about 10 minutes the first job had only 3/18 validated checkpoints; the second waited for the one configured worker. Observed successful KIE calls took 54–160 seconds; rejected numerical claims added rewrites.
- User explicitly reports the waiting time as unacceptable. Do not create more paid smoke jobs while investigating.
- `compose_report` serializes all independent sections. They depend on the same verified facts, never on previously generated text. This is the main avoidable wall-clock cost.

## Design / invariants

1. Generate independent missing sections with a bounded, validated managed setting `ASTRO_REPORT_SECTION_CONCURRENCY` (default 4, accepted 1–8).
2. Share one provider semaphore between all runtime workers. Authorization and fenced lease must be checked after acquiring a slot, before sending facts.
3. Preserve section order in the finished report, all word/fact gates, model, prompts, plan identity, per-job fingerprint, encrypted checkpoints and consent. No schema, pricing or balance changes.
4. On a section failure, stop scheduling new sections and allow already-started calls to finish validation/checkpointing before propagating the error. Resume must reuse those checkpoints.
5. On actual cancellation/timeout, cancel and await all section tasks; no orphan background generation.
6. Do not change existing production data or manually restart the live worker. Release only by protected PR back to `tanyapi`, native auto-merge, exact-SHA CI and automatic deploy.

## Verification plan / progress

- Add red-capable async barrier tests: overlap/bound/order, failure drain/resume, cancellation cleanup, invalid configuration, shared cross-worker provider budget.
- Run them against the unchanged serial baseline first.
- Red baseline verified at `10bcd578309409d0a19b8288ce83352b0c99c76b`: **8 failed** in 6.17s. The serial pipeline cannot reach the three-call barrier; invalid budget is ignored; no shared provider limiter exists. Tests ran with synthetic actors and isolated SQLite, never production credentials/data.
- Implement the minimum concurrency change; run all Astro regressions and changed-file lint.
- Implementation at `74dd81ff`: the 8 new regression cases passed (3.21s); all **336 Astro tests passed** (20.11s) in the isolated QA checkout. Additional checks cover role revocation while waiting for a shared slot and checkpoint identity across a concurrency change.
- Verify revocation while waiting for a provider slot and unchanged legacy/checkpoint identity.
- Run the four protected CI gates, native auto-merge, exact merge-SHA production CI/deploy and health/frontend revision checks.
- Continue monitoring the already-created smoke jobs. Verify PDF/Telegram from real completed reports, and preserve all unrelated jobs, including the preexisting administrator failed report and the other owner's job.

## Risks / rollout

- Parallelism reduces serial waiting, not the latency of an individual model response. Real improvement must be measured after deploy.
- Active requests may still be charged by the provider after a process crash/cancellation; no vendor exactly-once guarantee is claimed.
- KIE's general documentation permits concurrent tasks, but account/model-specific limits can still return 429. Keep bounded retry/backoff and allow rollback to concurrency 1.
- Full report content and numerical-claim verification must not be reduced to achieve speed.
