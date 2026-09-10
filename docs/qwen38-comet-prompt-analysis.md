# Qwen 3.8 prompt analysis via CometAPI

`qwen3.8-max` is the primary multimodal analyzer for the regular **Промпт по фото** and **Промпт по видео** flows when CometAPI is configured.

## Runtime routing

- Photo without voice: CometAPI `qwen3.8-max` first; the existing KIE/Gemini/Claude chain remains a fallback.
- Video: CometAPI `qwen3.8-max` receives the video URL natively first; the existing KIE direct-video and sampled-frame path remains a fallback.
- Photo + voice and voice-only: unchanged, because this migration only targets photo/video visual analysis.
- The explicit VK-compatible photo-analysis mode remains independent. It does not override the regular photo flow while CometAPI Qwen is enabled.

## API contract

The adapter uses the OpenAI-compatible CometAPI endpoint:

- Base URL: `https://api.cometapi.com/v1`
- Endpoint: `POST /chat/completions`
- Model: `qwen3.8-max`
- Image input: `image_url`
- Video input: `video_url` with configurable `fps`
- Output: JSON object parsed into the existing photo/video result schemas.

## Configuration

Required to activate Qwen as primary:

```env
COMETAPI_KEY=...
```

Optional overrides:

```env
COMETAPI_BASE_URL=https://api.cometapi.com/v1
QWEN38_PROMPT_MODEL=qwen3.8-max
QWEN38_PROMPT_REASONING_EFFORT=medium
QWEN38_PROMPT_MAX_TOKENS=4096
QWEN38_PROMPT_TIMEOUT_SECONDS=180
QWEN38_PROMPT_MAX_ATTEMPTS=2
QWEN38_VIDEO_FPS=1.0
```

`COMET_API_KEY` is also accepted as a compatibility alias for the key. Secrets must remain in runtime environment configuration and must never be committed.

## Failure handling

The client retries only transient HTTP/network failures, with a small bounded retry count. Invalid requests and other non-retryable 4xx errors immediately fall through to the existing analyzer chain. Provider error bodies are truncated in logs, and API keys are never logged.
