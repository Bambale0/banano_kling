# Astro: preserve bounded rewrite after rejected sentence repair

- Baseline: `435dd6b8c8d623bf35f357e13d388dea7c7b1166` (`tanyapi`, PR #619).
- Review found that a mixed ordinary unsupported degree and a line-wrapped degree can survive individual fragment checks, then fail the final joined-text proof. That final exception escaped the repair helper and skipped the configured model rewrite, increasing whole-job retries.
- Public regression seam: `compose_report` with synthetic facts and provider text, mixed `299\n°` and `298°`, enough valid filler to pass length and the 20% repair threshold. Test both rewrite budgets 0 and 1.
- Red verified at `e922709f`: the enabled-rewrite case failed at final repaired-text proof; the zero-rewrite control passed (1 failed, 1 passed). User explicitly confirmed preserving full report length; no shortening is permitted by this fix.
- Fix only the repair fallback: failed final proof returns no repair, so the original bounded rewrite/error path runs. Do not weaken proof checks, accept unsupported numbers, add retries beyond the configured budget, change content/model/concurrency/identity or mutate data.
- No schema, configuration or frontend changes. Existing checkpoints and pending jobs remain compatible.
- Verify red baseline, focused and full Astro regressions, Ruff; then protected PR to `tanyapi`, native squash auto-merge, exact-SHA CI/autodeploy and live smoke.
