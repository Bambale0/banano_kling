# Agent Guide: Add Gemini Omni Photo + Video

Use this guide when adding Kie.ai Gemini Omni multimodal video generation to another project that already has its own UX and state model.

The goal is not to copy this bot's screens. The goal is to preserve the host project's UX while adding a reliable flow where users can combine:

- prompt text
- optional image references
- optional one video reference
- optional audio IDs
- optional character IDs

## Core Rule

Treat Gemini Omni as a multimodal composer, not as mutually exclusive modes.

Many projects model video generation as separate modes:

- text to video
- image + text to video
- video + text to video

Gemini Omni can use image and video inputs together. Do not let a UI field like `mode`, `type`, or `v_type` decide which saved media is sent. For Gemini Omni, the source of truth must be the stored media collections:

- send `image_urls` when images exist
- send `video_list` when video references exist
- send both when both exist

## Kie API Contract

Endpoint:

```text
POST https://api.kie.ai/api/v1/jobs/createTask
```

Payload shape:

```json
{
  "model": "gemini-omni-video",
  "callBackUrl": "https://example.com/webhook",
  "input": {
    "prompt": "Create a short product teaser...",
    "image_urls": ["https://example.com/product.png"],
    "video_list": [
      {
        "url": "https://example.com/motion.mp4",
        "start": 0,
        "ends": 10
      }
    ],
    "audio_ids": ["audio_..."],
    "character_ids": ["character_..."],
    "duration": "4",
    "aspect_ratio": "16:9",
    "resolution": "720p",
    "seed": 123
  }
}
```

Limits:

- `image_urls`: images consume 1 unit each.
- `video_list`: maximum 1 video; video consumes 2 units.
- `character_ids`: maximum 3; each consumes 1 unit.
- Total quota: `images + videos * 2 + character_ids <= 7`.
- If `video_list` exists, duration is controlled by the video/model behavior; do not promise that the seconds selector affects output length.

## Integration Plan

1. Locate the host project's generation state.

Find where it stores:

- prompt
- selected model
- image references
- video references
- audio/voice references
- character references
- duration/resolution/aspect ratio

Do not invent a parallel state system unless the project has no state abstraction.

2. Add a Gemini Omni capability layer.

Create or update a service with a method like:

```python
async def generate_gemini_omni_video(
    prompt: str,
    image_urls: list[str] | None = None,
    video_urls: list[str] | None = None,
    audio_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    duration: int = 4,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    seed: int | None = None,
    callback_url: str | None = None,
) -> dict | None:
    ...
```

The service must validate Kie invariants even if the handler already validates them:

```python
video_count = min(len(video_urls or []), 1)
image_count = len(image_urls or [])
character_count = len(character_ids or [])

if len(video_urls or []) > 1:
    return {"error": "Gemini Omni supports maximum 1 video reference"}

if image_count + video_count * 2 + character_count > 7:
    return {"error": "Gemini Omni input quota exceeded"}
```

3. Fit into the existing UX.

Do not force this exact button layout. Instead, add an entry point that matches the host product:

- If the app has a wizard, add Gemini Omni as a model that can accept both image and video steps.
- If the app has a composer, add media chips/counts for images and video.
- If the app has separate tabs, keep the tabs but make Gemini Omni collect all saved media before launch.
- If the app has command-style input, support attachments in any order.

Recommended user-facing concept:

```text
Photo + video:
Use photos for object, character, product, scene, or style.
Use one video for motion, camera movement, gesture, or atmosphere.
Then write the prompt.
```

4. Preserve order independence.

This must work:

- photo -> video -> prompt
- video -> photo -> prompt
- prompt after previously saved media

Avoid this bug:

```python
video_urls = state.video_refs if state.mode == "video" else None
```

Use this instead for Gemini Omni:

```python
if selected_model == "gemini_omni":
    image_urls = collect_all_saved_images(state)
    video_urls = state.video_refs
else:
    video_urls = state.video_refs if state.mode == "video" else None
```

5. Count effective inputs, not only visible uploads.

If the project creates Character IDs from images and later auto-adds the source image, include those source images in quota counting.

Show the user a count like:

```text
Inputs: 5/7
Images: 2
Video: 1 (counts as 2)
Characters: 1
```

6. Handle duration honestly.

When no video reference exists, the normal duration selector can stay.

When a video reference exists:

- keep the selector only if it is part of the host UX, but label it as not affecting video-reference mode
- or hide/disable it for Gemini Omni with a video reference
- or charge using a fixed/default duration if the billing model depends on duration

Never tell the user that `8s` or `10s` is guaranteed when `video_list` is sent.

7. Use callbacks or polling consistently.

If the host project already has webhook completion flow, wire Gemini Omni into that flow. Otherwise, add polling through:

```text
GET https://api.kie.ai/api/v1/jobs/recordInfo?taskId=...
```

Normalize statuses into the project's existing job states:

- waiting / queuing / generating -> processing
- success -> completed
- fail -> failed

## UX Copy Blocks

Use these as source material, not mandatory text.

Short menu description:

```text
Gemini Omni can combine text, photos, one video reference, voices, and characters in one video task.
```

Photo + video flow:

```text
Add photos for object, scene, style, or first-frame guidance.
Add one video for motion, camera behavior, gesture, or atmosphere.
Then send the prompt.
```

Quota hint:

```text
Inputs: photo=1, video=2, Character ID=1. Maximum 7 total.
```

Duration hint:

```text
When a video reference is added, the seconds setting does not control the final length.
```

Error messages:

```text
Gemini Omni accepts only one video reference. Remove the current video or replace it.
```

```text
Too many inputs for Gemini Omni. Limit: images + video*2 + characters <= 7.
```

## Testing Checklist

Before finishing, test these cases in the host project's UX:

- Text only submits a valid Gemini Omni task.
- Photo + prompt sends `image_urls`.
- Video + prompt sends `video_list`.
- Photo + video + prompt sends both `image_urls` and `video_list`.
- Video first, then photo, then prompt still sends both.
- Photo first, then video, then prompt still sends both.
- More than one video is rejected visibly.
- Over-quota input is rejected before charging or task creation.
- Duration UI does not make false promises when video is present.
- Failed Kie task returns/refunds according to the host project's existing billing rules.

## Agent Guardrails

- Read the host project's existing UX before editing.
- Do not replace the whole flow if a small model-specific branch is enough.
- Keep media state additive for Gemini Omni.
- Keep service-level validation even if handler validation exists.
- Do not silently truncate user media without a visible warning.
- Reuse existing upload/storage/webhook/job abstractions.
- Keep copy short and fitted to the product's tone.
- Verify with syntax checks and at least one dry-run/unit path where possible.

