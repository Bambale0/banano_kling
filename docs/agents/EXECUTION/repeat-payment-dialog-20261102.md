# Repeat checkout overlay regression — 2026-11-02

Baseline: tanyapi@5dfcb30e48f212f3ea2050ec958544dfe0da9b76.
User symptom: Buy bananas does not react in video trend repeat.

Diagnosis: three candidates were checkout API failure, native navigation failure, and overlay stacking.
A mobile Chromium reproduction through the actual trend dialog, photo upload, quote and inline buy button fails before any invoice request:
`Repeat dialog must not cover the checkout button: false !== true`.
The BalanceSheet and Radix dialog both used z-50, but the Radix content was portalled above the in-tree sheet. Existing payment E2E covered the normal video form only and DOM visibility missed occlusion.

Fix: render BalanceSheet through a document.body portal, with an explicit z-70 checkout layer above the existing z-50 editors. Preserve the editor, uploads and quote, existing checkout locks, signed links and late-response protection.

Regression: extend payment-browser.mjs with the real trend repeat path, mocked upload/quote/payment, actual hit testing and real click, one invoice only after user action, then close payment and verify uploaded photo and quote survive. Run Android Chromium and iOS WebKit including unavailable native bridge.
No backend, prices, provider routing, database, configuration or migration changes. No real payment or generation.

Plan: focused Jest/lint/build and browser regression; protected PR to tanyapi; exact merge/deploy SHA and health/revision smoke.
Skills: Bambale0/skills diagnosing-bugs, Bambale0/claw review checklist, anthropics/skills webapp-testing.

## Local evidence
- Before fix: Android browser regression fails on checkout hit test (covered by repeat).
- After fix: Android Chromium full payment-browser scenario PASS, including actual trend checkout click, one invoice and preserved photo/quote.
- Jest: 2 suites, 26 tests passed (balance-sheet-payment, generation-funding-offer).
- ESLint for balance-sheet.tsx passed. Production static build and TypeScript passed.
- Local WebKit launch blocked by missing system libraries; iOS WebKit verification must run in the existing CI browser environment. This is not an application test failure.
- Self-review: portal retains context and editor state, all hooks stay unconditional, SSR guards document, no backend/financial mutations changed.
