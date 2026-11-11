# VK standalone Mini App — audited contracts and production release gates

Scope: `Bambale0/banano_kling` branch `tanyapi`, native VK bot `Bambale0/tanyavk`.
Baseline: `tanyapi@8507fd05f164159276e0fde0feb509562f2b1ebe`, native VK
`master@1cb9a84543cb5feceace561e7fe7d6d2d90a0d8e`.

## User-facing goal

VK-only customers must be able to **browse and repeat trends, upload references,
pay, track jobs, receive results and view their history entirely within the VK
Mini App**. A Telegram account is optional and a linking prompt is not the
VK-only onboarding flow. Account linking is by two verified consents.

## Reproduced architecture gap

- Signed VK launch/session already works. The common app bootstrap and paid
  operations call `_get_vk_session_user_context` in `bot/miniapp.py`, which
  requires a persisted legacy Telegram link and a Telegram-created `users`
  row. A VK-only identity is rejected before trends, tasks or payments.
- The existing legacy `users.telegram_id` is required, and generation, upload,
  pricing, task history and refund flows repeatedly use Telegram IDs. A fake
  Telegram ID is prohibited: it would create a second money source and bypass
  task/reference ownership checks.
- Native VK independently stores its balances, tasks, payments and deliveries
  in `vkbanana.db`, including atomic charge and once-only refund routines.
  Its existing `internal_api.py` exposes authenticated health/statistics
  only. The legacy GET HMAC implementation signs an empty body; it is not a
  financial POST protocol.
- Real financial migration still has un-fenced writers, cross-DB snapshot
  uncertainty and historical pending settlements. See the already-deployed
  read-only preflight, `docs/adr/20261106-opening-balance-readiness.md`,
  and #408/#410/#414. Neither a browser UI nor a sandbox wallet reconciles
  these liabilities.

## Independently useful read-only release slice

The new `GET /mini-app/api/account-preview/trends` is gated by a **signed,
unexpired, revocable VK session**. There is no Telegram user lookup.

- Default: public editorial trend categories, with the established public
  recipe sanitizer and an additional small response-field allowlist.
- `?view=category&category_id=...&page=...`: visible category pagination,
  read-only; no unrestricted query/filter input.
- `?view=feed`: public non-adult completed feed via existing
  `get_feed_generations(viewer_user_id=None)`, then a separate allowlist of
  display-only fields. Private prompts, reference links, task ownership,
  internal user IDs and admin metadata never reach the response.
- No payment, source-image upload, task creation, money mutation or provider
  call occurs in the new route. `can_generate_in_app: false` is explicit.
- Linked users retain the existing full Telegram-backed studio; VK-only users
  see the real public catalog and an explicit route to their working VK bot.
  The link to Telegram remains optional.
- A 401/403/400/404 does not fall through to a guest account or a made-up
  Telegram user. No synthetic balance or unknown task ownership is created.
- Actual read-only production counts at baseline: 350 approved public trend
  prompts tagged trend, 17 visible categories, 16,961 completed non-adult
  public feed items. Counts can change.

**This is not the complete requested release.** Full paid repeat inside VK
Mini App remains blocked and must not be represented as completed.

## Required next vertical slices for full VK-only parity

1. **One account-native owner:** transactionally associate verified VK identity
   with an internal product owner. Preserve existing linked Telegram owner and
   legacy VK identity; reject collisions or ambiguous ownership. No numerical
   ID aliasing across platforms. Add concurrent sign-in/link tests.
2. **Single financial authority and cutover:** evidence-backed opening for both
   legacy sources; precision decisions, pending settlement and capture/refund
   reconciliation, strict writer fencing, atomic source-event idempotency and
   recoverable activation. Verify one common wallet immediately after
   voluntary linking. Never double-credit old payment webhooks.
3. **VK Mini App generation API:** authenticated model/config catalog, exact
   price quotation, per-task idempotent reserve and capture, once-only refund,
   generation task/actor persistence, input/reference ownership, public
   trend variable binding without leaking source recipes, and server-authorized
   access to trend source references. No pass-through user-selected prices.
4. **Native VK delivery:** body-bound HMAC/mTLS authenticated bridge, an
   explicit deduplication key and source identity, timeout/retry reconciliation,
   media durability and actual VK permission-aware message sending. A failed
   send never creates a second paid generation; expose task state to the Mini App.
5. **Production acceptance:** fresh VK user without TG, linked VK+TG user,
   single-account balance/history, normal image/video, reference edit, curated
   trend, repeat and cancel/refund, unavailable provider, duplicate callbacks,
   slow upload, back/forward WebView lifecycle, TG regression. Inspect payment
   and refund state in DB, not only a 200 response. Require protected PR,
   exact SHA CI and server/frontend/live-account checks.

Three implementation options were considered: (a) force hidden Telegram
users, rejected for identity/billing integrity; (b) naïve dual-wallet proxy,
rejected for link-time double payment exposure; (c) persisted platform-neutral
owner and single writer after audited cutover, recommended. A read-only catalog
is releasable before (c) because it performs no financial or identity mutation.

## Test evidence and permission boundaries

- Red-capable regression: signed unlinked VK public trend call initially 404,
  then green; explicit TLS/auth session and hidden recipe fixtures.
- The public trend serializer never sends the secret recipe, author ID,
  editable private anchor values, or billing price.
- Public feed includes only display-safe fields and cannot claim another
  user's task or access admin/private feed.
- Frontend displays genuine trends and feed, category pagination and retry;
  it must never show fake 'generation completed' or trigger a debit.
- No paid provider smoke is permitted for this read-only slice.
- End-to-end VK launch in a native VK mobile WebView with a real signed launch
  is a distinct operator acceptance gate; Playwright's signed-auth fixtures
  are not a replacement.
