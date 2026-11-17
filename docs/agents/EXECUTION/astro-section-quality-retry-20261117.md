# Bounded Astro section validation rewrites — 2026-11-17

## Scope and preflight

- Continue the existing `fix/astro-section-quality-retry-20261117` work, separately from #599 UI and #600 PDF delivery. Baseline is current protected `tanyapi` `f5d48fde89dc9b2ba32107c363bf44608c734ceb`.
- Preserve the earlier uncommitted pipeline/test work from `/root/tanya-ops/astro-section-validation-20261117`; the original worktree remains unchanged. Its unsupported-claim feedback test was RED (`invalid_section` instead of `unsupported_claim`), while the short-section rewrite test already passed.
- Existing production evidence: two failed reports returned no validated checkpoint sections despite successful HTTP responses. This change handles rejected section content; it does not prove the original responses' exact failure reason, automatically requeue old jobs or claim a live paid report succeeded.
- Reuse the existing versioned plans, fact allowlist, numeric/date proof gate, encrypted owner-scoped checkpoints, worker authorization/heartbeat and job-level retries. No DB/schema, payments, model, provider adapter or Mini App contract change.

## Implementation and acceptance

1. Give generated-section validation errors safe typed reasons (format, section ID, length, damaged text, unsupported claim); existing callers still receive `AstroReportError`.
2. Permit a bounded section rewrite using `ASTRO_REPORT_SECTION_VALIDATION_RETRIES` (default 1, range 0–2), validated before any external call. Transport errors still follow the existing job/provider policy.
3. Send only reason, required word count and attempt number as feedback; never include the rejected response or weaken the original facts/word-count/schema validators. Only a fully valid candidate can enter a checkpoint.
4. Log safe service/section/reason/retry metadata, no report text, facts or credentials. Checkpoint resume does not regenerate accepted sections; the worker checks authorization and lease for every provider call, including rewrites.
5. Verify retry bounds/exhaustion, unsupported-claim removal, checkpoint reuse, malformed config before external requests and no raw rejected text in logs or feedback; include worker/revocation regressions and full Linux Astro suite.

## Verification and rollout

- Focused pipeline/fact-guard/worker/revocation tests: 40 passed. Ruff and diff checks clear. Linux Astro suite: 283 passed. Standards/spec review found no blocking issue; corrected the stale no-retries docstring. Remaining release gates: protected CI, native squash auto-merge into `tanyapi`, exact-SHA autodeploy and smoke.
- No live provider calls, charges or user messages in these synthetic tests. No failed historical job is silently retried. User initiates retry from existing owner-scoped Mini App flow.
- Rollback: revert this isolated code change or set validation rewrites to 0; accepted encrypted checkpoints and original report identity remain compatible. Never disable the fact gate to make a report finish.
