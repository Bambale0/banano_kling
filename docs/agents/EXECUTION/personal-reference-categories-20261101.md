# Personal reference categories

User extends repeat personalization: save several personal outfits/objects in named
categories and select again without uploading. This is a personal library, not the
author's public choice catalog. Existing repeat preview remains admin-only.

Baseline: tanyapi 5cf06b0 (merged PR #387). Existing SavedReference is deduplicated per user/kind/hash,
pruned per kind and by age. Mini App only shows a bounded recent list. Telegram has
its own saved reference picker. Existing reference files and media-retention ownership
queries can be reused, but category membership must protect rows from BOTH cleaners.

Implementation: additive portable category/membership tables in SQLite and native
PostgreSQL bootstrap + canonical schema. Owner-scoped API; category uploads atomically
save membership before pruning. Category deletion removes memberships, not media.
No invented business quota; existing media size/format limits remain. Lists paginated.
Shared Mini App category manager/picker in upload and repeat choice screens. Telegram
category discovery and picker remain consistent with the same ownership rules.

Tests: private ownership, idempotency, categorized refs beyond recent cap, age cleanup,
atomic category upload, JSON/multipart paths, React create/select/upload errors,
PostgreSQL schema/transactions and mobile browser. No paid provider calls.

Implemented:
- Owner-scoped category/item API with independent labels and idempotent save/create.
- Category upload is assigned inside SavedReference save before recent pruning; JSON and multipart carry the category.
- Count and age cleanup exclude categorized rows; PostgreSQL cleanup locks all reference owners before reading candidates,
  including owners whose files were all categorized at the initial snapshot. Parent locks serialize remove/re-pin.
- Shared library in own profile, generic upload and custom repeat choices. Quick picker starts with images; management can be expanded.
- Telegram category/file pagination, existing input selection preserved when another category item is deleted.
- SQLite/native PostgreSQL/schema SQL updated. Runtime PostgreSQL fixture accounts for additive FK relationships;
  existing dedicated CI suite now covers native bootstrap and controlled remove/cleanup/re-pin locking.

Verification:
- Initial RED: missing reference_library module; domain/retention then first GREEN: 4 passed.
- HTTP/ownership/category uploads (JSON + multipart) + Telegram deletion/pagination: 10 passed.
- Core/reference/runtime/mobile transport selection: 17 passed, 3 PostgreSQL-only skipped locally.
- Full Mini App Jest: 76 suites, 581 tests passed; new library UI tests 3 passed.
- Production Next export + TypeScript passed; Ruff/compile/diff checks passed.
- Mobile E2E: 8 admin/ordinary cases across photo/Seedance/WAN passed, including personal-library selection without re-upload.
  Mobile screenshot inspected. Local packaged Chromium adaptation used because normal browser archive is unavailable.
- Review found cross-category draft deletion and hidden Telegram limits: reproduced deletion RED, fixed + paginated.
  PostgreSQL all-categorized-owner locking coverage fixed; controlled interleaving test is required in real PG CI.

Remaining: final re-review, exact-head CI (including real PostgreSQL), autodeploy and authenticated production smoke.
No paid generation, business price changes, or production data mutations.

Final pagination hardening: unavailable files are skipped while counting Telegram page
offsets over available files. Regressions cover one or21missingfiles before lateroutfits.
Actual categorized image files survive count/age rotation and physical orphan cleanup.
Latest category-domain/file tests: 7 passed. PR #388 created against tanyapi5cf06b0;
real PostgreSQL runtime CI passed initial feature head, including native schema bootstrap
and controlled remove/cleanup/re-pin locking; final-head checks remain required.
