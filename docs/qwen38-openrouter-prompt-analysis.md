# Qwen 3.8 prompt analysis via OpenRouter

`qwen/qwen3.8-max-0902` is the primary multimodal analyzer for the regular **Промпт по фото** and **Промпт по видео** flows when OpenRouter is configured.

## Runtime routing

- Photo without voice: OpenRouter `qwen/qwen3.8-max-0902` first; the existing KIE/Gemini/Claude chain remains a fallback.
- Video: OpenRouter `qwen/qwen3.8-max-0902` receives the video URL natively first; the existing KIE direct-video and sampled-frame path remains a fallback.
- Photo + voice and voice-only: unchanged, because this migration only targets photo/video visual analysis.
- The explicit VK-compatible photo-analysis mode remains independent. It does not override the regular photo flow while OpenRouter Qwen is enabled.

## API contract

The adapter uses the OpenAI-compatible OpenRouter endpoint:

- Base URL: `https://openrouter.ai/api/v1`
- Endpoint: `POST /chat/completions`
- Model: `qwen/qwen3.8-max-0902`
- Image input: `image_url`
- Video input: `video_url`
- Output: JSON object parsed into the existing photo/video result schemas.

## Configuration

Required to activate Qwen as primary:

```env
OPENROUTER_API_KEY=...
```

Optional overrides:

```env
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
QWEN38_PROMPT_MODEL=qwen/qwen3.8-max-0902
QWEN38_PROMPT_REASONING_EFFORT=medium
QWEN38_PROMPT_MAX_TOKENS=4096
QWEN38_PROMPT_TIMEOUT_SECONDS=180
QWEN38_PROMPT_MAX_ATTEMPTS=2
```

Secrets must remain in runtime environment configuration and must never be committed.

## Failure handling

The client retries only transient HTTP/network failures, with a small bounded retry count. Invalid requests and other non-retryable 4xx errors immediately fall through to the existing analyzer chain. Provider error bodies are truncated in logs, and API keys are never logged.
