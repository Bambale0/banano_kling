# Gemini Omni on Kie.ai

Source docs checked on 2026-05-21:

- Marketplace: https://kie.ai/gemini-omni
- Video API: https://docs.kie.ai/market/gemini-omni-video
- Audio API: https://docs.kie.ai/market/gemini-omni-audio
- Character API: https://docs.kie.ai/market/gemini-omni-character
- Task status: https://docs.kie.ai/market/common/get-task-detail

## Video

Endpoint: `POST https://api.kie.ai/api/v1/jobs/createTask`

Payload:

```json
{
  "model": "gemini-omni-video",
  "callBackUrl": "https://example.com/webhook",
  "input": {
    "prompt": "Create a futuristic night city short film...",
    "image_urls": ["https://example.com/scene.png"],
    "audio_ids": ["audio_..."],
    "video_list": [{"url": "https://example.com/source.mp4", "start": 0, "ends": 10}],
    "character_ids": ["character_..."],
    "duration": "4",
    "aspect_ratio": "16:9",
    "resolution": "720p",
    "seed": 123
  }
}
```

Supported video parameters used in the bot:

- `prompt`: required.
- `image_urls`: optional, JPEG/PNG/WEBP/JPG references.
- `video_list`: optional, maximum 1 video. The bot sends `start=0`, `ends=10`.
- `audio_ids`: optional, maximum 3 IDs from Omni Audio.
- `character_ids`: optional, maximum 3 IDs from Omni Character.
- `duration`: `4`, `6`, `8`, `10`. Ignored by the model when a video input is provided.
- `aspect_ratio`: `16:9`, `9:16`.
- `resolution`: `720p`, `1080p`, `4k`.
- `seed`: optional integer.

Quota rule from Kie: `images + videos * 2 + character_ids <= 7`.

Best practice for the bot:

- Treat Gemini Omni as multimodal, not as mutually exclusive text/image/video modes.
- Send saved `image_urls` and `video_list` together whenever both exist in state.
- Do not depend on `v_type` to decide whether to include `video_list`; `v_type` is only a UI hint for Omni.
- If a video reference exists, explain in UX that duration is controlled by the video/model and the seconds selector does not affect the result.
- Count effective inputs before launch, including auto-added character source images.

## Audio

Endpoint: `POST https://api.kie.ai/api/v1/omni/audio/create`

Payload:

```json
{
  "audio_id": "achernar",
  "name": "Calm narrator",
  "voice_description": "A calm, clear, friendly voice.",
  "example_dialogue": "Hello, I am your narrator."
}
```

Response contains `data.audioId` (older docs/examples may refer to `kieAudioId`), which can be passed to video generation as `audio_ids`.

## Character

Endpoint: `POST https://api.kie.ai/api/v1/omni/character/create`

Payload:

```json
{
  "descriptions": "A young female character with short silver hair...",
  "image_urls": ["https://example.com/character.png"],
  "audio_ids": ["audio_..."],
  "character_name": "Jenny"
}
```

Constraints:

- `image_urls`: exactly one character reference image, up to 20 MB.
- `audio_ids`: optional IDs created by Gemini Omni Audio. The bot sends up to 3.

Response contains `data.characterId`, which can be passed to video generation as `character_ids`.

Implementation notes:

- The current Kie OpenAPI marks `descriptions` as the required character field.
- Some Kie examples still show `description`; the bot sends both fields for compatibility.
- When a character is created through the bot, its source image is remembered and added to the later Omni Video request automatically.

## Task Status

Endpoint: `GET https://api.kie.ai/api/v1/jobs/recordInfo?taskId=...`

States documented by Kie: `waiting`, `queuing`, `generating`, `success`, `fail`.
