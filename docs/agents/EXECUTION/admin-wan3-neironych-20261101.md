# 2026-11-01 — WAN 3.0 native API in Telegram admin test lab

## Baseline and outcome
- Task: add Neironych `wan-3` (not `wan/3-0-video` KIE) to **🧪 Тест** for Telegram administrators.
- Baseline `tanyapi@5cf06b0044fa2c7d311c681285aa3471f338bb31`, branch
  `feature/admin-wan3-neironych-lab-20261101`.
- Read `AGENTS.md`, admin lab, Neironych Seedance adapter, WAN models/lifecycle,
  and `Bambale0/ooo` native video contract and examples.
- Checked live Neironych `GET /v1/models`: HTTP 200 and `wan-3`, `wan-3-prime`
  listed. Checked current production container (read-only):
  `NEIRONYCH_API_KEY` present; revision 5cf06b; public WAN via KIE stays intact.

## Scope / safety / architecture
- New route is Telegram admin lab only; server `config.is_admin` on every handler.
- Isolated service uses existing Neironych API host/key and existing bounded GET/
  POST-without-retry/status/download transport.
- Native request body has `model=wan-3` and upstream-specific fields, not KIE
  `{model,input}`. Edit removes duration/ratio. Full text/references/frames/edit
  modes and sound/seed settings are available.
- No pricing, public Mini App, creator tariff, WAN lifecycle, balance deductions,
  DB schema or provider routing changes. Vendor charges Neironych account directly.
- Use current Telegram reference saving; preserve order and @Image/@Video/@Audio.
- Generate explicit only; unknown POST acceptance retains same idempotency key;
  manual check/delivery restores without a second generation.

## Acceptance seams / tests
1. Native wire contract (backend validator) for all supported modes, limits,
   media URLs, edit exclusions, seed/audio, reference order and auth.
2. Admin menu and callbacks, submit authorization, unknown-acceptance replay,
   catalog gate, provider submission.
3. No regression in Seedance lab, existing WAN public KIE, Mini App.
4. Exact-head CI plus release SHA, container health, admin route smoke if deployed.

## Work evidence
- Initial test-first commit: `8c636664644d32d02f03620355f3799cfb2a44f5`
  (provider contract test against absent module).
- Implementation: `bot/services/neironych_wan3_admin_service.py`,
  `bot/handlers/admin_wan3_neironych_lab.py`.
- Registration: `bot/handlers/__init__.py` and `bot/handlers/admin_test_lab.py`.
- Shared Telegram media helper extended only to recognize WAN's 100 MiB upload
  ceiling, with 15s media duration unchanged.
- Tests: `tests/test_neironych_wan3_admin_service.py`,
  `tests/test_neironych_wan3_admin_lab.py`.
- Docs: `docs/ADMIN_WAN3_NEIRONYCH_TEST.md`.

## Verification / follow-up
- Await exact-head Python/test/CI verification and production smoke; do not mark
  deployed from a commit or a merged PR without verifying active revision.
- Live paid generation is not part of unit/CI; only run with explicit test budget
  and inspect end-to-end delivery, not merely provider acceptance.
- Known caveat: in-memory delivered-id suppression is process-local; manual
  delivery after a restart can resend a ready file, but cannot resubmit the job.

## PR review continuation
- Reproduced two outstanding review findings with focused failing tests: every
  `Wan3LabStates` message state was absent from the subscription middleware's
  administrator-test allowlist, and document media with no Telegram duration
  was persisted with duration zero.
- The middleware now recognizes all five WAN lab states. WAN video/audio with
  unknown duration fails closed before persistence or provider submission and
  asks the administrator to resend it as Telegram media.
- Existing callback ratio, uncertain-acceptance idempotency and aggregate
  reference-duration fixes remain covered by the focused WAN regression suite.
- The PR branch was updated without rewriting history by merging current
  `origin/tanyapi@41e72b7a`; the merge was conflict-free.
- Local post-merge focused verification: 144 tests passed across the native WAN
  lab/service, adjacent Neironych Seedance lab, public WAN service/lifecycle and
  release-menu seams. Changed Python files pass Ruff, Python compilation and
  `git diff --check`.
- The wider Linux workflow selection was also attempted on Windows/Python 3.14:
  382 passed and 15 skipped, while 80 failed on known non-production seams such
  as POSIX directory fsync, the Unix `resource` module, Windows default source
  encoding and environment-sensitive legacy fixtures. The protected Ubuntu
  full regression, PostgreSQL, browser and Docker jobs remain the release gate.
