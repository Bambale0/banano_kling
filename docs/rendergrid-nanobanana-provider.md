# RenderGrid provider for Nano Banana 2 / Pro

This integration changes only the internal provider routing. Telegram bot UX, Mini App UX, model names, callbacks, prices, FSM and user-facing generation flow remain unchanged.

## Runtime contract

When RenderGrid routing is enabled:

```text
Nano Banana 2 / Nano Banana Pro
        |
        v
RenderGrid primary
        |
        +-- success --> existing image_bytes result contract
        |
        +-- technical failure --> existing KIE queued fallback
```

Nano Banana 2 Lite is not changed and stays on its dedicated KIE Market route.

Explicit RenderGrid policy/safety refusals are terminal and do not silently switch provider. Network errors, timeouts, invalid provider responses, missing output URLs, result-download failures and other technical provider failures fall back to KIE.

## Environment

Required for RenderGrid:

```dotenv
RENDERGRID_API_KEY=rg_live_xxx
NANOBANANA_RENDERGRID_ENABLED=1
```

Optional:

```dotenv
RENDERGRID_BASE_URL=https://api.rendergrid.io/api/public/v1
RENDERGRID_TIMEOUT_SECONDS=60
RENDERGRID_GENERATION_TIMEOUT_SECONDS=600
RENDERGRID_POLL_INTERVAL_SECONDS=5
RENDERGRID_REFERENCE_GUIDANCE_ENABLED=1

RENDERGRID_NANO_BANANA_2_MODEL=nano-banana-2
RENDERGRID_NANO_BANANA_PRO_MODEL=nano-banana-pro
```

The polling interval has a hard floor of five seconds.

## Canary / per-model rollout

The global switch can be overridden independently:

```dotenv
NANOBANANA_RENDERGRID_ENABLED=0
NANOBANANA2_RENDERGRID_ENABLED=1
NANOBANANAPRO_RENDERGRID_ENABLED=0
```

or the inverse for Nano Banana Pro only.

If a RenderGrid flag is enabled but `RENDERGRID_API_KEY` is absent, that model fails safe to KIE-only routing.

## Rollback

No code rollback is required. Disable the feature flag and restart the backend container:

```dotenv
NANOBANANA_RENDERGRID_ENABLED=0
```

With RenderGrid disabled, the previous KIE-primary / Nexus-fallback routing remains intact.

## References

The adapter reuses the bot's existing media normalization and converts local uploads to provider-safe public PNG URLs when needed. RenderGrid receives public URLs in `reference_images`.

If a reference cannot be represented as a public HTTP(S) URL, RenderGrid is treated as technically unavailable for that request and the service falls back to KIE instead of silently dropping the reference.

## Result compatibility

RenderGrid is asynchronous internally, but the adapter polls the creation and downloads the first output image. It returns the same shape already handled by the bot:

```python
{
    "image_bytes": b"...",
    "mime_type": "image/png",
    "provider": "rendergrid",
    "provider_model": "nano-banana-2",
    "creation_id": "...",
    "result_url": "https://...",
    "retryable": False,
}
```

Therefore no handler, keyboard or UI changes are required.
