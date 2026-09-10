# GPT Image 2.5 — admin test via KIE

The Telegram `🧪 Test` lab exposes GPT Image 2.5 only to configured bot admins. It is a no-billing test surface: it does not deduct bananas or publish generations to the public feed.

## KIE models

The current KIE Market exposes four model IDs:

- `gpt-image-2-5-flare-text-to-image`
- `gpt-image-2-5-flare-image-to-image`
- `gpt-image-2-5-sunburst-text-to-image`
- `gpt-image-2-5-sunburst-image-to-image`

The test UI asks for the Flare/Sunburst variant and automatically selects text-to-image or image-to-image according to whether references are attached.

## Current KIE request contract

Create task: `POST https://api.kie.ai/api/v1/jobs/createTask` with Bearer auth.

Common `input` fields:

- `prompt`: required, maximum 20,000 characters;
- text-to-image `aspect_ratio`: `auto`, `1:1`, `3:2`, `2:3`, `4:3`, `3:4`, `16:9`, `9:16`, `21:9`, `27:16`, `16:27`, `9:8`, `8:9`;
- image-to-image supports all of the above plus `5:4`, `4:5`, `2:1`, `1:2`, `3:1`, `1:3`, `9:21`;
- `resolution`: `1K`, `2K`, `4K`.

Image-to-image adds `input_urls`, maximum 16 images. KIE's GPT Image 2.5 model page lists JPEG/JPG, PNG and WEBP uploads, up to 30 MB each.

`callBackUrl` is supported by KIE. The isolated admin test currently uses the unified task-status endpoint because it does not create normal generation rows in the bot database. Production integrations should prefer callbacks where the result can be reconciled idempotently with a persisted task.

The current KIE request schema does **not** expose a separate `background` field in the expected input form. Transparent-background intent can still be expressed in the prompt, but the test client deliberately does not invent an undocumented API parameter.

## Sources checked

- https://docs.kie.ai/market/quickstart
- https://docs.kie.ai/43283988e0 — Flare text-to-image
- https://docs.kie.ai/43285205e0 — Flare image-to-image
- https://docs.kie.ai/43286810e0 — Sunburst text-to-image
- https://docs.kie.ai/43286923e0 — Sunburst image-to-image
- https://kie.ai/gpt-image-2-5

## Telegram flow

`Main menu -> 🧪 Test -> GPT Image 2.5`

The screen supports variant, prompt, up to 16 references, aspect ratio and resolution. Every callback and message-state handler rechecks `config.is_admin(...)`. The KIE key stays on the backend.
