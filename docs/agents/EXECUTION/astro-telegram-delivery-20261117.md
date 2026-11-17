# Astro Telegram report delivery — guarded production rollout

Baseline `tanyapi`: `586cb93be84a98e3e5133995a85bab02f784ef5a`.

## Incident and change

- Live report jobs existed and the KIE Responses adapter returned successfully, but two Nov 17 jobs ended `failed`, `temporary_provider_failure`, with **zero checkpoint sections**. A provider response returning HTTP 200 does **not** prove that the report section passes the min-word/schema/numeric-proof gates. This backend PR does not change those correctness validators or claim the two reports recovered.
- Existing Astro Mini App returns a completed report through owner-scoped signed status API, but had no Telegram delivery integration. A user closing Mini App could receive no push outcome. The new SQL outbox is inserted **in the same database transaction** as completed or terminal failed state, without modifying wallet/payment data.
- Outbox contains only `job_id`, owner ID, state, timestamp, attempt count and Telegram message metadata. All completed content remains encrypted in the report jobs schema. A private in-memory `astro_neuromix.pdf` document contains every validated section; no public CDN URL, local export, group chat or birth facts in logs. The recipient is the exact Telegram owner, and authorization is rechecked just before send.
- Telegram failures/uncertain timeouts use a bounded env-configured exponential backoff and persisted lease; `message_id > 0` is required before marking delivered. Terminal generation errors send a safe short message instead of silently disappearing.
- Exactly-once message delivery is **not guaranteed** if Telegram accepts a document but its response is lost. The system provides exclusive claims, persisted acknowledgment and at-least-once recovery. Workflows are idempotent at the outbox/lease level, not at Telegram transport.
- Owner history and status remain owner-scoped; successful reports expose `telegram_delivery` metadata only to their owner. Revoked admins never receive the report. Privacy erasure and retention purge remove outbox metadata.

## TDD and verification evidence

- RED: new delivery module absent. GREEN: 5 dedicated fake-bot tests plus original Astro queue/worker suites; transient error, terminal failure notice, role revocation, owner erasure, restart recovery.
- Full local Astro suite: **271 passed, 9 skipped**, Ruff clean. Environment used isolated QA venv; initial missing numpy/psycopg imports fixed *only* in QA venv.
- Real disposable PostgreSQL 16 on localhost, ephemeral `astro_delivery_qa` database and synthetic credentials, no production data: native DDL, 2 concurrent claims => 1 delivery, delivered status, owner scope, deletion passed. Script `scripts/astro_telegram_delivery_pg_smoke.py` refuses any non-disposable/non-local DB target.
- No live paid KIE run or Telegram push attempted by this PR's tests. Protected CI and exact-SHA production deploy required; after deploy verify queue task, job/email logs (without content) and one signed admin result.
- Two already-failed reports are not silently requeued, and no historical notifications are backfilled. User must explicitly retry failed report after provider quality fix / safe configuration acceptance.

## Rollout / rollback

- Deployment only to protected `tanyapi`, no main/dev/VK/payment changes.
- New DDL is additive native PostgreSQL/SQLite CREATE TABLE + index, no destructive migration.
- Operational controls: `ASTRO_TELEGRAM_DELIVERY_MAX_ATTEMPTS`, `ASTRO_TELEGRAM_DELIVERY_TIMEOUT_SECONDS`, `ASTRO_TELEGRAM_DELIVERY_LEASE_SECONDS`, `ASTRO_TELEGRAM_DELIVERY_RETRY_BASE_SECONDS`, `ASTRO_TELEGRAM_DELIVERY_RETRY_MAX_SECONDS`, `ASTRO_TELEGRAM_DELIVERY_POLL_SECONDS`.
- Roll back the code release to stop new notifications; encrypted reports and unprocessed outbox metadata remain in PostgreSQL for later reconciliation.

## PDF format follow-up (2026-11-17, PR #600)

- User acceptance: Telegram receives exactly `astro_neuromix.pdf` instead of TXT; Mini App retains the same full owner-scoped report/history. No generation retry/quality changes from the separate branch, no unrelated preview/UI commits.
- Preflight: source PR head `04af9f91b50f6fcf301578ece6bd434ab587c5cb`; live image/checkout `586cb93be84a98e3e5133995a85bab02f784ef5a`, healthy, HTTP 200. Upstream `tanyapi` subsequently includes #598 at `f5d48fde89dc9b2ba32107c363bf44608c734ceb`; that is not evidence it is deployed. Production price/operator files are dirty and must be preserved by the existing deployment script.
- Existing encrypted job row/outbox transaction, leases, owner scoping, retention and retry remain the source of truth. No plaintext exports are persisted by the application. ReportLab runs off the async event loop, with a combined render/send timeout inside the existing lease; ownership/deletion/authorization is checked again after rendering.
- Renderer explicitly uses only service label, section title/text and disclaimer. Other job/facts/profile/OAuth/attachment fields never become PDF content or metadata. All text is XML-escaped, with no interpretation of links/images/embedded files. It does not fetch or incorporate external material. The existing completed-report pipeline remains responsible for content validation.
- Embedded Noto Sans Regular/Bold from official `notofonts/noto-fonts`, SIL OFL 1.1 bundled at `bot/assets/fonts/OFL.txt`. No runtime font download, OS font dependency, or system package needed. `reportlab>=4.4.9,<5` added to runtime requirements; existing Docker COPY includes fonts.
- Input bound matches the existing 3 MB encrypted envelope. Output is rejected above 49,000,000 bytes, conservatively below the official Bot API sendDocument multipart limit (https://core.telegram.org/bots/api#senddocument). No truncation or TXT fallback. Captions remain short. Single large sections are split into bounded layout paragraphs and flow across pages.
- Skills: `.agents` router/PDF/TDD/deployment-procedures; project engineering `tdd`, Claw architecture/release guidance and Anthropic PDF guidance. User-requested seams are PDF bytes, Telegram delivery and owner-scoped status/API, already authorized by the request.
- RED observed: delivery regression expected `astro_neuromix.pdf` but received the original `.txt`. Initial PDF/delivery tests: 23 passed. Visual review of synthetic 114-page export: embedded Cyrillic, headings, footer and final section render correctly. Tests independently parse real PDF bytes, check exact Cyrillic, embedded fonts, all seven services and dynamic sections, 10k/30k-word single sections, all words/end markers, nonempty pages, PDF filename/retry, metadata exclusion, inert markup, invalid/oversized input, authorization revocation/deletion and group rejection.
- Full all-repository test collection on Windows cannot import the Linux-only `resource` module; no production workaround added. Run focused Astro suite locally and require the full Linux CI gates before release.
- Windows Astro run: 271 passed, 27 fixture errors from the pre-existing city importer replacing an open SQLite file (WinError 32). PDF/delivery suite: 27 passed; Ruff clean. Linux CI is the authoritative full regression gate.
- Release: leave PR draft during format revision; then ready/arm native squash auto-merge only after local checks and review. Preserve strict protected gates. Verify exact merge SHA CI, exact deployed image revision, health, queue startup, authenticated owner status and signed user report before claiming end-to-end production delivery. No paid generation or live user message initiated by synthetic tests.
- Rollback: previous exact-SHA image; additive outbox schema and encrypted reports remain. No new business/runtime settings, wallet changes or destructive migrations. Disclosed OAuth client secret requires revocation/reissue through its provider; never include its value or the client ID in docs/logs/PDF. Real Telegram transport may duplicate after accepted-but-lost responses; at-least-once limitation remains.

### Readiness review follow-up

- Two-axis code review identified and fixed: cooperative render cancellation/deadline plus hard page/block budgets (no partial PDF returned); an expired final-attempt delivery lease is reconciled to safe terminal `failed`/uncertain instead of hanging forever as `sending`. The latter had an observed RED restart regression before the fix. Encrypted job storage and metadata-only outbox schema remain unchanged.
- Rendering checks its cancellation/deadline between bounded blocks and on every page. 31 dedicated PDF/delivery regressions passed, including stopped-render-before-retry, deadline, pathological page/block limit and crash-on-final-attempt recovery. Removed task IDs from user-facing Telegram copy while retaining operational correlation logs.
- Linux QA at e7a15db0: 302 Astro tests passed; disposable PostgreSQL 16 smoke passed actual PDF/Cyrillic/name, concurrent claim, owner scope and erasure. Final revised SHA must repeat affected checks and protected CI.
- Synced current protected `tanyapi` target (includes #598); these target commits are not part of this PR's feature diff. Strict branch protection and all four required gates verified read-only through GitHub CLI (connector lacks administration permission).
- Glyph review found actual null/missing glyphs for common planetary/zodiac signs and arrows in the original Noto Sans-only PDF (observed RED). Bundled SIL-OFL Noto Sans Symbols, Symbols 2 and monochrome Noto Emoji fallbacks; escape all text before selecting glyph runs. Preserve Unicode extraction for non-BMP emoji by converting ReportLab 4 scalar ToUnicode entries to PDF UTF-16BE surrogate pairs in document-local streams only. Unsupported characters fail closed rather than silently corrupting text. Independent parser, concurrent-document regression and Poppler visual review confirm Cyrillic, planets/zodiac/arrows/emoji and no cross-document text leakage. Licenses are bundled; no runtime font fetching.
