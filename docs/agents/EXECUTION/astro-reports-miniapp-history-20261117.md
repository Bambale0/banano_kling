# Astro report UI, owner history and consent — production acceptance

## Dependency graph

This changes the Telegram-only Mini App on top of #583 (full synastry UI),
which depends on #582 (full API). Backend GPT-6/KIE queue is already in
#587. PostgreSQL native Astro schema creation is corrected separately in
#588. Do NOT merge this stacked PR into `tanyapi` before its dependencies
and all protected CI checks are green; never bypass branch protection.

## User flow

1. An authorized Telegram admin opens any of the seven Astro services.
2. They enter date/time, choose verified GeoNames city IDs for one or both
   participants, and select the requested calendar period. For lunar
   calendar, a separate optional city picker updates the IANA timezone.
3. Under the astronomical form, they explicitly opt in to send the calculated
   astronomical facts for interpretation and store an encrypted result. The checkbox
   defaults unchecked; third-party data requires explicit consent.
4. A separate action posts only canonical IDs, date/time, period and signed
   Telegram initData to `/mini-app/api/astro/reports/start`; untrusted client
   timezone, coordinates, arbitrary claims and prompts are not forwarded.
   Duplicate requests return the same owner-scoped HMAC task ID.
5. An admin may close Mini App. The DB worker continues. Opening "Мои
   предыдущие отчёты" calls signed `/reports/history`, listing metadata
   only for that owner/service; clicking "Открыть" polls signed `/status`
   and displays all returned long-form sections.
6. The UI handles queued/running/completed/failed, transient HTTP failure,
   missing/expired jobs, revoked permissions and disabled provider configuration.
   It must not claim a server accepted, charged or completed anything before
   a confirmed response.

## Security and privacy boundaries

- Backend checks signed Telegram initData and **current** admin privileges
  for start, list and status; history SQL filters owner_id and expiry.
- History does not contain birth dates, city coordinates, prompts, ciphertext
  or full text. Report content only via separately authorized owner/status.
- No payments or price constants; no VK contour; no editing another account.
- No automatic expensive query on Astro page open: history is loaded on demand.
- `ASTRO_REPORTS_ENABLED=0` remains the default until stable encryption
  secrets, KIE GPT-6 model, billing budget and deployment checks are approved.
- Configurable history cap `ASTRO_REPORT_HISTORY_LIMIT` default 30, max 50.

## Verification evidence

- TDD red -> green for owner-scoped `list_owner` and authenticated
  `/reports/history` route.
- 7 report-panel tests: input schemas for all services, explicit consent,
  completed result display, history recovery without regeneration, disabled
  backend and untrusted coordinate omission.
- Cross-feature Astro React regression, TypeScript, ESLint, production build
  and actual Chromium E2E must pass before release. The E2E uses a synthetic
  admin + mock report API and must never be represented as a real GPT-6 run.
- Final production acceptance requires exact backend/static SHA, signed
  admin/nonadmin 200/401/403, one budgeted provider request, actual token
  accounting and real mobile Telegram WebView. Seven large provider-backed
  documents remain an explicit separate costly acceptance gate.

## Additional browser and stale-form evidence (17 November)

- 272 Astro/backend pytest regressions green in isolated container.
- 26 Astro React tests (including stale-form and consent regressions),
  272 Astro backend tests, TypeScript, ESLint, Ruff and static Next.js build
  green after the final stale-form test and accessibility fix.
- Actual local Chromium Mini App critical browser E2E PASSED: tested
  birthplace selection, report consent, start endpoint request, full report
  rendering and opening history via synthetic signed admin. No KIE call.
- The report text is now invalidated whenever the birth form or verified city
  selection changes. Polling old job stops; durable server job remains
  recoverable through owner-scoped history. Consent resets unchecked. A new
  regression proves editing a completed card cannot leave old birth data
  presented as if it belonged to the new form. History can re-open it.
- The report-history button is on-demand: does not auto-query or load personal
  records at initial Astro page mount, including when reports are disabled.
- Full suite rerun and Chromium critical browser E2E PASSED after the
  form-revision fence, using a synthetic signed admin and mocked transport.
  Protected GitHub CI and exact-SHA production acceptance remain required. This PR is stacked and deliberately not deployed yet.

## Verification supplement — form edit/accessibility regression

A targeted user regression exposed that the informational "birth inputs
changed" message introduced a second `role=status`, causing 3 existing
Astro React tests to fail due competing live regions. The form-revision
notice now uses ordinary text while actual API errors keep `role=status`.
The full 26 Astro frontend Jest tests are green; this is a UX and
accessibility correction, not a test relaxation. The revision counter also
invalidates pending old job responses, removes stale rendered text and resets
consent whenever a real field or selected GeoNames city changes.

The protected #588 PostgreSQL schema fix has merged into `tanyapi`;
the worktree remains stacked on #583 until both #582 and #583 merge.
Do not enable `ASTRO_REPORTS_ENABLED` without operator-managed Fernet
secrets and KIE budget approval.

## 2026-11-17 follow-up — PR #599

- User requested removing technical/provider/model details from the Astro UI. Consent now describes processing for the personal report and temporary storage; compatibility still explicitly requires consent from both people. Consent remains unchecked and the server-side authorization/payload contract is unchanged.
- Removed provider/model names, server configuration, queue implementation, and task wording from report descriptions, loading/error/success states and privacy copy. Keep useful user actions, owner privacy, storage consent and factual no-debit wording. Existing spinner and reduced-motion CSS remain; no fabricated completion percentage.
- Existing 503 recovery/start/history/retry and running-animation tests updated to the new user-facing wording. This PR remains independent of PDF outbox #600 and section-quality retries.
- Acceptance: all Astro UI tests, TypeScript, focused ESLint, locked production build, browser flow and protected CI; then verify exact `tanyapi` deployed revision and frontend asset content. Do not bypass audit gates.

- Copy revision validation: 42/42 Astro frontend tests passed; TypeScript and focused ESLint passed. Final changed Astro tab/panel subset: 34/34 passed. Updated old copy assertion in the existing natal integration test. Removed stale coming-soon descriptions from natal/compatibility cards. Production build/browser and protected CI remain release requirements.
