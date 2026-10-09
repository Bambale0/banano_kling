# Seedance creator pricing

Ordinary Seedance 2.0 launches currently use provider resolution 720p. Their
server quote therefore uses the configured ordinary 720p per-second rate even
when the caller omits quality. If that rate is absent, existing legacy duration
prices remain the fallback. This does not add a resolution selector or change
provider capabilities. Creator rates still override only for eligible creators;
administrators retain free access and see the ordinary quote. Existing accepted
task quotes and refund amounts are never recalculated after a price edit.

## Admin workflow

Open the Telegram admin panel → Prices → «🎬 Тариф креатора · Seedance».

1. Open «💰 Цены креатора». Enter independent banana-per-second rates for Seedance 2.0 and each Seedance 2.5 quality. There is no common discount percentage and no prefilled creator price.
2. Fill every required rate, then select «Включить…» and confirm. Configured ordinary quality keys are retained, including a runtime 1080p price; this does not enable unsupported provider resolutions or change model capabilities.
3. Open «👤 Найти пользователя по ID», enter the Telegram ID of an existing user, and confirm grant or revoke. This changes only price-profile membership. It never grants admin rights or changes the balance.
4. Disable the profile to return assigned users to ordinary prices without losing their membership. Missing, invalid or incomplete configuration also uses ordinary prices. The admin screen explicitly shows this state.

Existing admin-free generation remains free. Enabling or editing the creator profile does not change ordinary rates, other models, packages or image generation. Ordinary Seedance 2 quotes honor their own configured 720p rate as described above. Existing per-launch video-reference pricing remains ×2 once, regardless of the number of video references. Total base prices retain existing half-banana rounding; Mini App metadata supplies server-rounded totals to prevent browser rounding differences.

Seedance 2.5 Auto and ordinary video-editing keep the existing five-second estimate; identity transfer retains its measured-duration billing. This change does not alter duration/provider policy.

## Storage and billing

- Rates use the existing runtime price configuration under `creator_tariff.enabled` and `creator_tariff.video_models.<model>.quality_costs.<quality>`.
- No creator section is seeded into `data/price.json`, no economic rate is hardcoded, and no user is enrolled by deployment.
- `creator_tariff_memberships` stores Telegram ID, enabled state, updating admin and timestamp independently of administrative roles.
- `creator_tariff_audit` stores immutable membership/configuration event records with actor, target, before/after data and timestamp. Membership and its audit record share one DB transaction. Configuration uses audited intent/result events because the JSON file and DB cannot form one transaction.
- Membership changes are serialized on the target user; admin confirmation detects stale membership/configuration and duplicate clicks.
- Every paid Seedance launch derives its profile from the authenticated actor. Client tariff/price fields are ignored. The server captures one immutable `billing_quote` before debit/provider submission and persists it with the accepted task.
- Accepted-job charge/refund amounts remain fixed after rate edits, grants, revocations or admin-role changes. An accepted provider job is not refunded merely because subsequent persistence/UI transport fails. Failure refunds use the original amount and existing idempotent task/refund markers.
- Bootstrap and repeat/catalog metadata are personalized after authentication without modifying shared model definitions or cached public cards. Historical task cost remains the original debit.

## Migration and rollout

Startup adds the two tables, audit index and append-only audit guards idempotently. PostgreSQL DDL goes through the existing native-DDL adapter; schema is also included in `schema_postgres.sql`. No existing table data or balances are rewritten.

Deploy only after normal repository CI and release approval. Preserve the runtime price volume/file using the existing deployment procedure; do not replace it with repository defaults. Initially the profile remains inactive. Tanya must set rates and explicitly enable/assign it in admin.

Rollback can disable the profile through admin immediately. A code rollback may leave the additive membership/audit tables in place; do not delete audit records. In-flight task quote metadata is retained. No production migration, activation, assignment, paid generation or deployment was performed during this implementation.

Release verification adds `creator-tariff-postgres.yml` with a disposable loopback-only PostgreSQL16 database and randomized schemas. Creator browser fixtures run in the required main CI browser gate; all requests are intercepted and no paid generation is made. Baseline Handlebars critical advisories are fixed by the compatible4.7.10 lockfile update;20 moderate test-dependency advisories remain below the unchanged high-severity audit threshold.
