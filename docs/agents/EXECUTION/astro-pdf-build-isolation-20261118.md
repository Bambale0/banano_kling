# Astro PDF shared-font build isolation — 2026-11-18

Baseline `tanyapi`: `6d75db5ea847eeba0067186b51ccf6ea71e3ef1a` (includes PDF #600 and section quality #601).

## Preflight and contract

The installed ReportLab 4.4.9 TTFont class documentation explicitly prohibits using one TTFont object for simultaneous documents. Astro registers process-global fonts; the existing two-thread Unicode extraction test passes but does not override that supported contract. Production's delivery loop is normally sequential; timeout cleanup or future same-process workers can overlap. No document corruption or cross-owner disclosure has been observed.

Prevent unsupported concurrent font-subset use with a separate process-wide lock covering the entire `document.build`, including save/font embedding. Keep registration and immutable paragraph preparation outside. Acquire in 50ms intervals, check cooperative cancellation/deadline while waiting and immediately after acquisition, always release in finally and check budget after build. A canceled waiter must not enter later.

No queue, outbox, encrypted payload, owner authorization, delivery filename, Telegram retry, schema, model/provider, payments or configuration changes. Lock waiting consumes the existing render/send deadline and lease budget; this is cooperative cancellation, not forced thread termination.

## Verification and rollout

- Public export tests instrument the actual library build entry while still producing real parsed PDFs. RED observed: peak concurrent builds2, and both canceled/deadline waiters entered and returned rather than timing out. No corruption claim is inferred from this observation.
- Verify peak1 and distinct real Unicode documents, promptly canceled/expired waiters without build entry, successful subsequent rendering, and lock release after a synthetic build exception. Existing full PDF/delivery/owner/retry suites remain required.
- Both standards/spec reviewers independently recommended this bounded separate-lock approach. Final implementation review, Linux Astro regression, protected CI, native squash merge to `tanyapi`, exact-SHA production CI/autodeploy and smoke remain required.
- Keep separate from report UI #599, quality #601, lazy-preview test follow-up #602 and build dependency #603. Rollback is reverting this isolated renderer/test change; do not alter queues or data to roll back.
