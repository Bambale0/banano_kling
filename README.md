## Kie.ai Nano Banana 2 Integration

### Environment Variables
```
KIE_AI_API_KEY=your_api_key_here
KIE_AI_WEBHOOK_PATH=/webhook/kie_ai  # Default: /webhook/kie_ai, must match nginx reverse proxy
```

### Usage
- Model "banana_2" in image generation UI triggers Kie.ai nano-banana-2.
- Tasks created with `callBackUrl` = `config.kie_notification_url` (webhook).
- Webhook route: POST `{WEBHOOK_HOST}{KIE_AI_WEBHOOK_PATH}` (e.g. https://domain.com/webhook/kie_ai)
- Fallback polling: /api/v1/jobs/recordInfo?taskId= (state: success/fail, resultJson.resultUrls[0])

### Webhook Payload Example
```
{
  "data": {
    "taskId": "task_123",
    "state": "success",
    "resultJson": "{\"resultUrls\": [\"https://...png\"]}"
  }
}
```

### Test Webhook
```
curl -X POST "$KIE_AI_WEBHOOK_PATH" -H "Content-Type: application/json" -d '{"data":{"taskId":"test","state":"success","resultJson":"{\"resultUrls\":[\"https://example.com/test.png\"]}"}}'
```

Polling fixed for 404 errors. Primary: webhook (no polling needed).