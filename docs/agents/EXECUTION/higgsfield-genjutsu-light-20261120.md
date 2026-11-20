# Higgsfield Genjutsu Light — execution ledger (2026-11-20)

## Preflight
- Baseline: `tanyapi` at `e9f5cfdb6737bbaf8691e4b0957da0c6afda2bf4` (refresh before merge).
- User wording: “Higgsfield 2.5 Lite.” No official Higgsfield endpoint with this exact product name was verified. The implementation covers the **official Genjutsu Light** family, not Seedance 2.5, and must be presented as such.
- Official contracts: [Motion Transfer Light](https://open.higgsfield.ai/models/higgsfield/genjutsu-light/motion-transfer/v1.0/api-reference) and [Object Swap Light](https://open.higgsfield.ai/models/higgsfield/genjutsu-light/object-swap/v1.0/api-reference). Both use `prompt`, `video_url`, `image_urls`, `resolution` and the exact model path. Source clip up to 15 seconds; original sound preserved. Media/reference constraints in this change reuse the stricter existing local validation as a product policy, not a newly invented provider requirement.
- Existing source of truth: `bot/genjutsu/catalog.json`, `contract.py`, `defaults.json`, `provider.py`, `pipeline.py`, `repository.py`, `api.py`, `frontend/miniapp-v0/lib/genjutsu-api.ts`, `components/genjutsu-{studio,admin}.tsx`.
- Existing durable client and lifecycle: one provider POST with Idempotency-Key, no blind retry for ambiguous submission, status polling / webhook, durable storage, charge/refund, notification and Telegram delivery. No replacement adapter or new DB schema is needed.
- Critical compatibility risk: persisted `genjutsu.config.prices` contains only three original operation keys; strict validation of all `CATALOG` keys would otherwise reject production settings. Existing public release gate also required *all* model operations to be verified/priced; adding two new unverified operations would block existing public configuration edits.

## Implementation
1. Add `motion_transfer_light` and `object_swap_light` to model-specific catalog, with official provider paths, 480p/720p/1080p and source-clip duration bounded to 4–15 sec. No Light restyle operation is invented.
2. Add separate Light prices as `null` by default and preserve old saved prices by a migration-on-read compatibility guard. Existing names and quoted-price semantics remain unchanged.
3. Keep the existing provider adapter, async lifecycle, idempotency, media signing, run history, delivery, and ledger. No new credential type.
4. Permit public Genjutsu to stay on with previously verified operations while Light remains unavailable until verified for every offered resolution, with non-null admin rates and an actual successful admin test.
5. Add typed UI labels and operation picker controls, reuse video trimming and quote confirmation, keep unverified Light hidden from public operation selection. Admin sees all and edits Light tariffs.
6. Add tests at contract, provider submission, legacy pricing compatibility, API catalog, and frontend mode-selection seams.

## Financial and release safeguards
- Existing formula (reference video seconds + generated seconds) × configured rate is **preserved**, not renegotiated here. Higgsfield documentation now describes provider output-second charges; confirm desired NEUROMIX retail policy before enabling Light for real users.
- No `.env`, secret, payment setting, database mutation or live paid provider request in this change.
- Old public operations must stay available with their own valid configuration even though Light rates are unset.
- If provider submit is ambiguous (timeout/5xx), retain the existing `submission_unknown` and recovery_review behavior without launching duplicate charged requests.
- Public Light rollout needs manual pricing, real admin coverage at 480p/720p/1080p for both Light modes, authenticated Mini App smoke and exact-SHA production checks.
- CI gates required: Python/deploy validation, safe regression suite, Mini App browser E2E, production Docker image; add frontend Jest regression and targeted Python tests.

## Skills
- `Bambale0/.agents/skills/agents-global-router` for skill discovery.
- `Bambale0/skills/engineering/implement`, `tdd`, and `code-review` for bounded vertical slice and regression contract.
- `Bambale0/.agents/skills/api-integration`, `code-audit` for async provider boundary and financial/privacy risks.
- `Bambale0/claw/AGENTS.md` for safe repository operations.

## Verification record
- GitHub branch edits created through connected GitHub repository operations.
- GitHub Actions / local pytest / frontend Jest / actual provider submission / production deploy: **pending verification**. Do not label this complete until the exact-head CI and subsequent production smoke results are observed.
