# Higgsfield Genjutsu integration

This integration is a dedicated asynchronous pipeline. It does not reuse Seedance
or Kling request builders.

## Supported operations

The provider catalog is pinned in `bot/genjutsu/catalog.json` and verified
against the saved API schema snapshots in this directory:

- `higgsfield/genjutsu/motion-transfer/v1.0`;
- `higgsfield/genjutsu/object-swap/v1.0`;
- `higgsfield/genjutsu/restyle/v1.0`.

The older `higgsfiled/...` spelling remains a legacy provider alias, but new
integrations must use the canonical `higgsfield/...` namespace documented on
2026-10-03.

The product surface supports projects/drafts, video trimming, ordered reference
roles, Restyle presets, multiple variants, multi-step chains, exact server quotes,
history, cancellation, redelivery, private trend recipes and admin recovery.

## Required runtime configuration

No secret is committed to Git. Production reads these values from the existing
backend `.env`:

```dotenv
HIGGSFIELD_API_KEY=
HIGGSFIELD_API_BASE_URL=https://api.higgsfield.ai

# Must be a public HTTPS origin that routes /genjutsu/media/* and
# /genjutsu/callback/* to the backend.
GENJUTSU_PUBLIC_BASE_URL=https://api.example.com

# Random high-entropy secret used only for signed private media/callback URLs.
GENJUTSU_MEDIA_SIGNING_KEY=

# Private durable directory. compose.backend.yml already persists /app/data.
GENJUTSU_MEDIA_ROOT=/app/data/genjutsu_media
```

`Authorization: Key ...` is generated only by the backend provider adapter.
Keys and signed private URLs must never be logged or returned through the public
trend API.

## Safe enablement

Genjutsu starts fail-closed:

- `public_enabled=false`;
- all per-operation/per-resolution prices are `null`;
- `verified_operations=[]`.

The admin control plane can change mutable limits and prices without a deploy.
Public enable is rejected until provider/media configuration exists, all three
operations have completed a real admin verification run, and every advertised
resolution has a configured price.

A successful HTTP request is not sufficient verification. Admin verification is
recorded only from a completed result stored by our pipeline.

### Why live coverage is mandatory

Higgsfield's public pages have had conflicting capability statements (for
example API reference-image limits and 1080p availability). The repository keeps
the documented API contract, but release enablement requires a real request on
our account for every operation/resolution actually exposed to users. Unsupported
account capabilities must be disabled in managed settings rather than silently
downgraded.

## Task lifecycle

```text
project/version
  -> quote
  -> atomic reservation/start
  -> ready
  -> submitting
       -> queued/in_progress
       -> submission_unknown  (ambiguous POST; never blind-retry)
       -> recovery_review     (accepted task needs operator recovery; no refund/regeneration)
  -> storing
  -> completed
  -> independent Telegram delivery
```

Webhook callbacks contain our HMAC-signed callback URL and only wake
reconciliation. They do not establish success/failure: the worker performs an
authenticated provider status request before result persistence or financial
mutation.

A completed provider result is downloaded with SSRF/redirect/size protection and
stored privately before delivery. Telegram delivery failures never regenerate or
double-charge the video.

## Private Trends recipes

An admin can mark each image reference as:

- **user** — the person repeating the Trend must provide that slot;
- **fixed** — the original private reference stays server-side.

The recipe snapshots the exact project revision and can be published only after
a completed admin-free provider run of that same revision. Public Trend payloads
expose only the opaque `genjutsu_recipe_id`, input labels/roles, user-editable
field schema and current server price. Hidden prompts, source video identifiers,
fixed reference identifiers and project IDs are not returned.

Repeating a Trend instantiates an archived private project, applies validated
user values server-side, produces a normal quote and then uses the same
idempotent generation pipeline as ordinary Genjutsu work.

## Recovery / admin operations

The admin panel exposes:

- upstream reconciliation;
- adoption of a known provider request ID after an ambiguous submit;
- controlled per-step refund;
- redelivery without regeneration;
- provider verification runs;
- live settings and pricing with optimistic config versioning;
- event history with local run/step/attempt/provider correlation IDs.

Never resolve `submission_unknown` by issuing a second provider POST without
first reconciling or explicitly adopting the known request ID. An accepted task
that cannot be polled or persisted past its recovery deadline enters
`recovery_review`; this state intentionally keeps the user's debit and never
creates another provider generation. Admin reconciliation resumes polling or
result storage once the underlying issue is fixed.

## Verification

Focused tests:

```bash
python -m pytest \
  tests/test_genjutsu_contract.py \
  tests/test_genjutsu_repository.py \
  tests/test_genjutsu_provider.py \
  tests/test_genjutsu_recipes.py \
  tests/test_genjutsu_runtime.py \
  tests/test_trend_visibility.py \
  tests/test_trend_api.py -q
```

Frontend gates:

```bash
cd frontend/miniapp-v0
npm test -- --runInBand components/__tests__/genjutsu-studio.test.tsx
npm run lint -- --max-warnings=0
npm run build
```

Production enablement additionally requires a real admin smoke for Motion
Transfer, Object Swap and Restyle, output persistence, Telegram/Mini App delivery,
and a log scan using the exact deployed SHA.
