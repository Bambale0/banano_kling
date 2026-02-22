> ## Documentation Index
> Fetch the complete documentation index at: https://docs.freepik.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Webhooks

> Webhooks are a powerful way to connect different systems and services. Learn about webhooks and how to integrate them securely.

### What are webhooks?

Webhooks are a way for one system to send real-time data to another system. They are a powerful tool for integrating different services and automating workflows. With webhooks, you can receive notifications, updates, and data from external systems without having to poll for changes.

### How do webhooks work?

Webhooks work by allowing you to register a URL with a service that supports them. When an event occurs in the service, it sends an HTTP POST request to the registered URL with relevant data. The receiving system can then process the data and take appropriate actions based on the event.

### Why use webhooks?

Webhooks offer several advantages over traditional polling-based methods:

* **Real-time updates**: Webhooks provide instant notifications, allowing you to react to events as they happen.
* **Efficiency**: They reduce the overhead of constant requests by delivering data only when an event occurs.
* **Automation**: Webhooks trigger automatic workflows, reducing manual processes and streamlining tasks.
* **Seamless integration**: They facilitate easy data exchange between systems, enabling efficient communication between different platforms.

### Common use cases for webhooks

Webhooks are widely used in the following scenarios:

* **Notifications**: Sending real-time alerts and updates to users or systems.
* **Data synchronization**: Ensuring that data remains consistent across multiple platforms.
* **Workflow automation**: Initiating tasks like sending emails, updating databases, or processing transactions based on specific events.

By using webhooks, you can streamline your workflows, improve efficiency, and create seamless integrations between different systems.

## Webhook security

### Why webhook security is important?

Webhooks are a powerful way to connect different systems and services. They allow you to send real-time data from one system to another. However, with great power comes great responsibility. Webhooks can be a security risk if not implemented correctly, as they can be exploited by attackers to send malicious data to your system.

### Webhook security headers

To ensure the integrity and authenticity of incoming webhook requests, we deliver three headers with each request:

* `webhook-id`: A unique identifier for the webhook request. This helps to detect and prevent replay attacks.
* `webhook-timestamp`: A timestamp indicating when the webhook request was sent. This is used to ensure that the request is recent and prevents replay attacks within a specific time window.
* `webhook-signature`: A signature generated using a secret key. This is used to verify the authenticity of the request, ensuring that it was sent by a trusted source.

### Generating the string to sign for verification

You must generate a content string that will be signed and verified. This content is created by concatenating the `webhook-id`, `webhook-timestamp`, and the request body with a period (`.`) separator. You can do this by following these steps:

1. **Retrieve the headers**: Extract the `webhook-id` and `webhook-timestamp` from the request headers.
2. **Access the request body**: Obtain the raw body of the webhook request.
3. **Concatenate the values**: Combine the `webhook-id`, `webhook-timestamp`, and body into a single string using the format mentioned earlier.

Here is an example of how you can generate the content to sign in Python:

<CodeGroup>
  ```python python.py theme={null}
  content_to_sign = f"{webhook_id}.{webhook_timestamp}.{body}"
  ```

  ```javascript javascript.js theme={null}
  const contentToSign = `${webhookId}.${webhookTimestamp}.${body}`;
  ```

  ```php php.php theme={null}
  $content_to_sign = "$webhook_id.$webhook_timestamp.$body";
  ```

  ```java java.java theme={null}
  String contentToSign = webhookId + "." + webhookTimestamp + "." + body;
  ```
</CodeGroup>

### Obtaining the secret key

The secret key is a shared secret between your system and the webhook provider. It is used to generate the signature and verify the authenticity of the request. Make sure to keep the secret key secure and never expose it in your code or configuration files.

To obtain the secret key, you can go to the [User Dashboard](https://www.freepik.com/developers/dashboard/api-key) and generate a new secret key. Copy the secret key and store it securely in your system.

### Generating the signature

For the webhook signature, we use HMAC-SHA256 as the hashing algorithm. You can generate the signature by following these steps:

1. Encode the secret key as bytes.
2. Obtain the HMAC-SHA256 hash as bytes of the content to sign using the secret key.
3. Encode the hash in base64 to get the signature.

Here is an example of how you can generate the signature in Python:

<CodeGroup>
  ```python python.py theme={null}
  import hmac
  import hashlib
  import base64

  def generate_signature(secret_key, content_to_sign):
      secret_key_bytes = secret_key.encode()

      hmac_bytes = hmac.new(secret_key_bytes, content_to_sign.encode(), hashlib.sha256).digest()

      signature = base64.b64encode(hmac_bytes).decode()

      return signature
  ```

  ```javascript javascript.js theme={null}
  const crypto = require('crypto');

  function generateSignature(secretKey, contentToSign) {
      const secretKeyBytes = Buffer.from(secretKey, 'utf-8');

      const hmac = crypto.createHmac('sha256', secretKeyBytes);

      hmac.update(contentToSign);

      const signature = hmac.digest('base64');

      return signature;
  }
  ```

  ```php php.php theme={null}
  function generateSignature($secretKey, $contentToSign) {
      $secretKey = base64_decode($secretKey);

      $hmac = hash_hmac(
          'sha256',
          $contentToSign,
          $secretKey,
          true
      );

      $signature = base64_encode($hmac);

      return $signature;
  }
  ```

  ```java java.java theme={null}
  import javax.crypto.Mac;
  import javax.crypto.spec.SecretKeySpec;
  import java.util.Base64;


  public static String generateSignature(String secretKey, String contentToSign) throws Exception {
      byte[] secretKeyBytes = secretKey.getBytes("UTF-8");

      Mac mac = Mac.getInstance("HmacSHA256");
      SecretKeySpec secretKeySpec = new SecretKeySpec(secretKeyBytes, "HmacSHA256");
      mac.init(secretKeySpec);

      byte[] hmacBytes = mac.doFinal(contentToSign.getBytes("UTF-8"));

      String signature = Base64.getEncoder().encodeToString(hmacBytes);

      return signature;
  }
  ```
</CodeGroup>

The obtained signature must be compared with the `webhook-signature` header in the incoming request to verify the authenticity of the request. If the signatures match, the request is considered valid, and you can process it further.

The `webhook-signature` header is composed of a list of space-delimited signatures and their corresponding version identifiers. This allows you to rotate the secret key without breaking existing webhook integrations. For example, the header might look like this:

```
v1,signature1 v2,signature2
```

You should iterate over the list of signatures and verify each one using the corresponding secret key version. If any of the signatures match, the request is considered valid. For example, you can implement this logic in Python as follows:

<CodeGroup>
  ```python python.py theme={null}
  def verify_signature(generated_signature, header_signatures):
      for signature in header_signatures.split():
          version, expected_signature = signature.split(',')
          if expected_signature == generated_signature:
              return True
      return False
  ```

  ```javascript javascript.js theme={null}
  function verifySignature(generatedSignature, headerSignatures) {
      const signatures = headerSignatures.split(' ');

      for (const signature of signatures) {
          const [version, expectedSignature] = signature.split(',');

          if (expectedSignature === generatedSignature) {
              return true;
          }
      }

      return false;
  }
  ```

  ```php php.php theme={null}
  function verifySignature($generatedSignature, $headerSignatures) {
      $signatures = explode(' ', $headerSignatures);

      foreach ($signatures as $signature) {
          list($version, $expectedSignature) = explode(',', $signature);

          if ($expectedSignature === $generatedSignature) {
              return true;
          }
      }

      return false;
  }
  ```

  ```java java.java theme={null}
  public static boolean verifySignature(String generatedSignature, String headerSignatures) {
      String[] signatures = headerSignatures.split(" ");

      for (String signature : signatures) {
          String[] parts = signature.split(",");
          String version = parts[0];
          String expectedSignature = parts[1];

          if (expectedSignature.equals(generatedSignature)) {
              return true;
          }
      }

      return false;
  }
  ```
</CodeGroup>

By following these steps, you can ensure the security of your webhook implementation and protect your system from unauthorized access and data tampering.

> ## Documentation Index
> Fetch the complete documentation index at: https://docs.freepik.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Authentication

> Learn how to authenticate your requests to the Freepik API

## API Key Authentication

Freepik API uses API keys to authenticate requests. You need to include your API key in the header of every API request to access the Freepik resources.

Currently, private API keys are the only way to authenticate with the Freepik API. This means that only server-to-server calls can be made to the API

All API endpoints are authenticated using API keys and picked up from the specification file.

<div className="my-11">
  <Columns>
    <Card title="Freepik API" icon="leaf" href="https://storage.googleapis.com/fc-freepik-pro-rev1-eu-api-specs/freepik-api-v1-openapi.yaml">
      Download the OpenAPI specification file
    </Card>
  </Columns>
</div>

## Obtaining an API Key

To get an API key:

1. Sign up for a Freepik account at [freepik.com/api](https://www.freepik.com/api)
2. If you are already registered, visit the API dashboard at [freepik.com/developers/dashboard](https://www.freepik.com/developers/dashboard)
3. Look for the API key section and generate a new API key

<div className="my-11">
  <Card icon="circle-exclamation" title="Keep your API key secure and do not share it publicly.">
    If you believe your key has been compromised, please contact us and we will generate a new one for you.
  </Card>
</div>

## Using the API Key

Include your API key in the `x-freepik-api-key` header of your HTTP requests:

```bash  theme={null}
curl -H "x-freepik-api-key: YOUR_API_KEY" https://api.freepik.com/v1/resources
```

<CodeGroup>
  ```javascript JavaScript theme={null}
  const axios = require('axios');

  const response = await axios.get('https://api.freepik.com/v1/resources', {
    headers: {
      'x-freepik-api-key': 'YOUR_API_KEY'
    }
  });
  ```

  ```python Python theme={null}
  import requests

  headers = {
      'x-freepik-api-key': 'YOUR_API_KEY'
  }

  response = requests.get('https://api.freepik.com/v1/resources', headers=headers)
  ```

  ```ruby Ruby theme={null}
  require 'net/http'
  require 'uri'

  uri = URI.parse('https://api.freepik.com/v1/resources')
  request = Net::HTTP::Get.new(uri)
  request['x-freepik-api-key'] = 'YOUR_API_KEY'

  response = Net::HTTP.start(uri.hostname, uri.port, use_ssl: uri.scheme == 'https') do |http|
    http.request(request)
  end
  ```
</CodeGroup>

## Rate limiting

Be aware that API requests are subject to [rate limiting](/ratelimits). The specific limits may vary based on your account type and agreement with Freepik. Always check the API response headers for rate limit information.

> ## Documentation Index
> Fetch the complete documentation index at: https://docs.freepik.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Kling 3 API

> Generate AI videos from text or images with Kling 3. Multi-shot support, first/end frame control, and durations from 3-15 seconds. Pro and Standard tiers for creative video production.

<Card title="Kling 3 integration" icon="video">
  Generate high-quality videos from text prompts or images using Kling's latest V3 model with multi-shot support and advanced frame control.
</Card>

Kling 3 is a dual-mode video generation API that creates professional-grade videos from either text descriptions or source images. It supports multi-shot mode for creating complex narratives with up to 6 scenes, first and end frame image control, and flexible durations from 3 to 15 seconds. Available in Pro and Standard tiers to balance quality and cost.

### Key capabilities

* **Text-to-Video (T2V)**: Generate videos from text prompts up to 2500 characters
* **Image-to-Video (I2V)**: Use first\_frame and/or end\_frame images to control video start and end points
* **Multi-shot mode**: Create videos with up to 6 scenes, each with custom prompts and durations (max 15 seconds total)
* **Flexible durations**: 3-15 seconds with per-shot duration control in multi-shot mode
* **Element consistency**: Pre-registered element IDs for consistent characters/styles across videos
* **CFG scale control**: Adjust prompt adherence from 0 (creative) to 1 (strict), default 0.5
* **Negative prompts**: Exclude unwanted elements, styles, or artifacts
* **Async processing**: Webhook notifications or polling for task completion

### Pro vs Standard

| Feature  | Kling 3 Pro                    | Kling 3 Standard             |
| -------- | ------------------------------ | ---------------------------- |
| Quality  | Higher fidelity, richer detail | Good quality, cost-effective |
| Speed    | Standard processing            | Faster processing            |
| Best for | Premium content, marketing     | High-volume, testing         |

### Use cases

* **Marketing and advertising**: Create multi-scene product narratives with consistent branding
* **Social media content**: Generate vertical videos for TikTok, Instagram Reels, and YouTube Shorts
* **E-commerce**: Animate product images with controlled start and end frames
* **Storyboarding**: Turn scripts into multi-shot video sequences
* **Creative storytelling**: Build narratives with scene-by-scene control

### Generate videos with Kling 3

Create videos by submitting a text prompt (T2V) or images with prompt (I2V) to the API. The service returns a task ID for async polling or webhook notification.

<div className="my-11">
  <Columns cols={2}>
    <Card title="POST /v1/ai/video/kling-v3-pro" icon="video" href="/api-reference/video/kling-v3/generate-pro">
      Generate video with Kling 3 Pro
    </Card>

    <Card title="POST /v1/ai/video/kling-v3-std" icon="video" href="/api-reference/video/kling-v3/generate-std">
      Generate video with Kling 3 Standard
    </Card>

    <Card title="GET /v1/ai/video/kling-v3" icon="list" href="/api-reference/video/kling-v3/kling-v3-tasks">
      List all Kling 3 tasks
    </Card>

    <Card title="GET /v1/ai/video/kling-v3/{task-id}" icon="magnifying-glass" href="/api-reference/video/kling-v3/task-by-id">
      Get task status by ID
    </Card>
  </Columns>
</div>

### Parameters

| Parameter         | Type      | Required | Default | Description                                                            |
| ----------------- | --------- | -------- | ------- | ---------------------------------------------------------------------- |
| `prompt`          | `string`  | No       | -       | Text prompt describing the video (max 2500 chars). Required for T2V.   |
| `negative_prompt` | `string`  | No       | -       | Text describing what to avoid (max 2500 chars)                         |
| `image_list`      | `array`   | No       | -       | Reference images with `image_url` and `type` (first\_frame/end\_frame) |
| `multi_shot`      | `boolean` | No       | `false` | Enable multi-shot mode for multi-scene videos                          |
| `shot_type`       | `string`  | No       | -       | Use `customize` for custom shot definitions                            |
| `multi_prompt`    | `array`   | No       | -       | Shot definitions: `index` (0-5), `prompt`, `duration` (min 3s)         |
| `element_list`    | `array`   | No       | -       | Pre-registered element IDs for character/style consistency             |
| `aspect_ratio`    | `string`  | No       | `16:9`  | Video ratio: `16:9`, `9:16`, `1:1`                                     |
| `duration`        | `integer` | No       | `5`     | Duration in seconds: 3-15 (default 5)                                  |
| `cfg_scale`       | `number`  | No       | `0.5`   | Prompt adherence: 0 (creative) to 1 (strict)                           |
| `webhook_url`     | `string`  | No       | -       | URL for task completion notification                                   |

### Image list item

| Field       | Type     | Description                                                         |
| ----------- | -------- | ------------------------------------------------------------------- |
| `image_url` | `string` | Publicly accessible image URL (300x300 min, 10MB max, JPG/JPEG/PNG) |
| `type`      | `string` | Image role: `first_frame` or `end_frame`                            |

### Multi-prompt item

| Field      | Type      | Description                                |
| ---------- | --------- | ------------------------------------------ |
| `index`    | `integer` | Shot order (0-5)                           |
| `prompt`   | `string`  | Text prompt for this shot (max 2500 chars) |
| `duration` | `number`  | Shot duration (minimum 3 seconds)          |

## Frequently Asked Questions

<AccordionGroup>
  <Accordion title="What is Kling 3 and how does it work?">
    Kling 3 is an AI video generation model that creates videos from text prompts (T2V) or images (I2V). You submit your request via the API, receive a task ID immediately, then poll for results or receive a webhook notification when processing completes. Typical generation takes 30-120 seconds depending on duration and complexity.
  </Accordion>

  <Accordion title="What is multi-shot mode?">
    Multi-shot mode lets you create videos with up to 6 distinct scenes. Each scene can have its own prompt and duration. The total duration across all shots cannot exceed 15 seconds, and each shot must be at least 3 seconds. Enable with `multi_shot: true` and define scenes in `multi_prompt`.
  </Accordion>

  <Accordion title="How do first_frame and end_frame work?">
    Use the `image_list` parameter to provide reference images. Set `type: "first_frame"` to use an image as the video's starting point, or `type: "end_frame"` for the ending point. You can use both to create a transition from one image to another.
  </Accordion>

  <Accordion title="What image formats does Kling 3 support?">
    Kling 3 accepts JPG, JPEG, and PNG images via publicly accessible URLs. Requirements: minimum 300x300 pixels, maximum 10MB file size, aspect ratio between 1:2.5 and 2.5:1.
  </Accordion>

  <Accordion title="What is cfg_scale and how should I set it?">
    CFG scale controls how closely the model follows your prompt. Use 0 for maximum creativity and artistic interpretation, 0.5 (default) for balanced results, or 1 for strict adherence to your prompt with less creative variation.
  </Accordion>

  <Accordion title="What is the difference between Pro and Standard?">
    Pro delivers higher fidelity with richer detail, ideal for premium content and marketing. Standard offers good quality with faster processing, suitable for high-volume generation and testing. Both share the same parameters and capabilities.
  </Accordion>

  <Accordion title="What are the rate limits for Kling 3?">
    Rate limits vary by subscription tier. See [Rate Limits](/ratelimits) for current limits and quotas.
  </Accordion>

  <Accordion title="How much does Kling 3 cost?">
    Pricing varies based on model tier (Pro vs Standard) and video duration. See the [Pricing](/pricing) page for current rates.
  </Accordion>
</AccordionGroup>

## Best practices

* **Prompt clarity**: Write detailed prompts specifying subject, action, camera movement, and atmosphere
* **Start simple**: Begin with single-shot mode before attempting multi-shot sequences
* **Image quality**: For I2V, use high-resolution source images with clear subjects (min 300x300)
* **Duration planning**: For multi-shot, plan scene durations to stay within 15-second total limit
* **Element consistency**: Use pre-registered elements for recurring characters across multiple videos
* **CFG tuning**: Start with 0.5, decrease for more creativity, increase for prompt precision
* **Production integration**: Use webhooks instead of polling for scalable applications
* **Error handling**: Implement retry logic with exponential backoff for 503 errors

## Related APIs

* **[Kling 3 Omni](/api-reference/video/kling-v3-omni/overview)**: Kling 3 with video reference support for motion/style guidance
* **[Kling 2.6 Pro](/api-reference/image-to-video/kling-v2-6-pro)**: Previous generation with motion control capabilities
* **[Kling O1](/api-reference/image-to-video/kling-o1/overview)**: High-performance video generation
* **[Runway Gen 4.5](/api-reference/video/runway-gen-4-5/overview)**: Alternative video generation model


> ## Documentation Index
> Fetch the complete documentation index at: https://docs.freepik.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Kling 3 API

> Generate AI videos from text or images with Kling 3. Multi-shot support, first/end frame control, and durations from 3-15 seconds. Pro and Standard tiers for creative video production.

<Card title="Kling 3 integration" icon="video">
  Generate high-quality videos from text prompts or images using Kling's latest V3 model with multi-shot support and advanced frame control.
</Card>

Kling 3 is a dual-mode video generation API that creates professional-grade videos from either text descriptions or source images. It supports multi-shot mode for creating complex narratives with up to 6 scenes, first and end frame image control, and flexible durations from 3 to 15 seconds. Available in Pro and Standard tiers to balance quality and cost.

### Key capabilities

* **Text-to-Video (T2V)**: Generate videos from text prompts up to 2500 characters
* **Image-to-Video (I2V)**: Use first\_frame and/or end\_frame images to control video start and end points
* **Multi-shot mode**: Create videos with up to 6 scenes, each with custom prompts and durations (max 15 seconds total)
* **Flexible durations**: 3-15 seconds with per-shot duration control in multi-shot mode
* **Element consistency**: Pre-registered element IDs for consistent characters/styles across videos
* **CFG scale control**: Adjust prompt adherence from 0 (creative) to 1 (strict), default 0.5
* **Negative prompts**: Exclude unwanted elements, styles, or artifacts
* **Async processing**: Webhook notifications or polling for task completion

### Pro vs Standard

| Feature  | Kling 3 Pro                    | Kling 3 Standard             |
| -------- | ------------------------------ | ---------------------------- |
| Quality  | Higher fidelity, richer detail | Good quality, cost-effective |
| Speed    | Standard processing            | Faster processing            |
| Best for | Premium content, marketing     | High-volume, testing         |

### Use cases

* **Marketing and advertising**: Create multi-scene product narratives with consistent branding
* **Social media content**: Generate vertical videos for TikTok, Instagram Reels, and YouTube Shorts
* **E-commerce**: Animate product images with controlled start and end frames
* **Storyboarding**: Turn scripts into multi-shot video sequences
* **Creative storytelling**: Build narratives with scene-by-scene control

### Generate videos with Kling 3

Create videos by submitting a text prompt (T2V) or images with prompt (I2V) to the API. The service returns a task ID for async polling or webhook notification.

<div className="my-11">
  <Columns cols={2}>
    <Card title="POST /v1/ai/video/kling-v3-pro" icon="video" href="/api-reference/video/kling-v3/generate-pro">
      Generate video with Kling 3 Pro
    </Card>

    <Card title="POST /v1/ai/video/kling-v3-std" icon="video" href="/api-reference/video/kling-v3/generate-std">
      Generate video with Kling 3 Standard
    </Card>

    <Card title="GET /v1/ai/video/kling-v3" icon="list" href="/api-reference/video/kling-v3/kling-v3-tasks">
      List all Kling 3 tasks
    </Card>

    <Card title="GET /v1/ai/video/kling-v3/{task-id}" icon="magnifying-glass" href="/api-reference/video/kling-v3/task-by-id">
      Get task status by ID
    </Card>
  </Columns>
</div>

### Parameters

| Parameter         | Type      | Required | Default | Description                                                            |
| ----------------- | --------- | -------- | ------- | ---------------------------------------------------------------------- |
| `prompt`          | `string`  | No       | -       | Text prompt describing the video (max 2500 chars). Required for T2V.   |
| `negative_prompt` | `string`  | No       | -       | Text describing what to avoid (max 2500 chars)                         |
| `image_list`      | `array`   | No       | -       | Reference images with `image_url` and `type` (first\_frame/end\_frame) |
| `multi_shot`      | `boolean` | No       | `false` | Enable multi-shot mode for multi-scene videos                          |
| `shot_type`       | `string`  | No       | -       | Use `customize` for custom shot definitions                            |
| `multi_prompt`    | `array`   | No       | -       | Shot definitions: `index` (0-5), `prompt`, `duration` (min 3s)         |
| `element_list`    | `array`   | No       | -       | Pre-registered element IDs for character/style consistency             |
| `aspect_ratio`    | `string`  | No       | `16:9`  | Video ratio: `16:9`, `9:16`, `1:1`                                     |
| `duration`        | `integer` | No       | `5`     | Duration in seconds: 3-15 (default 5)                                  |
| `cfg_scale`       | `number`  | No       | `0.5`   | Prompt adherence: 0 (creative) to 1 (strict)                           |
| `webhook_url`     | `string`  | No       | -       | URL for task completion notification                                   |

### Image list item

| Field       | Type     | Description                                                         |
| ----------- | -------- | ------------------------------------------------------------------- |
| `image_url` | `string` | Publicly accessible image URL (300x300 min, 10MB max, JPG/JPEG/PNG) |
| `type`      | `string` | Image role: `first_frame` or `end_frame`                            |

### Multi-prompt item

| Field      | Type      | Description                                |
| ---------- | --------- | ------------------------------------------ |
| `index`    | `integer` | Shot order (0-5)                           |
| `prompt`   | `string`  | Text prompt for this shot (max 2500 chars) |
| `duration` | `number`  | Shot duration (minimum 3 seconds)          |

## Frequently Asked Questions

<AccordionGroup>
  <Accordion title="What is Kling 3 and how does it work?">
    Kling 3 is an AI video generation model that creates videos from text prompts (T2V) or images (I2V). You submit your request via the API, receive a task ID immediately, then poll for results or receive a webhook notification when processing completes. Typical generation takes 30-120 seconds depending on duration and complexity.
  </Accordion>

  <Accordion title="What is multi-shot mode?">
    Multi-shot mode lets you create videos with up to 6 distinct scenes. Each scene can have its own prompt and duration. The total duration across all shots cannot exceed 15 seconds, and each shot must be at least 3 seconds. Enable with `multi_shot: true` and define scenes in `multi_prompt`.
  </Accordion>

  <Accordion title="How do first_frame and end_frame work?">
    Use the `image_list` parameter to provide reference images. Set `type: "first_frame"` to use an image as the video's starting point, or `type: "end_frame"` for the ending point. You can use both to create a transition from one image to another.
  </Accordion>

  <Accordion title="What image formats does Kling 3 support?">
    Kling 3 accepts JPG, JPEG, and PNG images via publicly accessible URLs. Requirements: minimum 300x300 pixels, maximum 10MB file size, aspect ratio between 1:2.5 and 2.5:1.
  </Accordion>

  <Accordion title="What is cfg_scale and how should I set it?">
    CFG scale controls how closely the model follows your prompt. Use 0 for maximum creativity and artistic interpretation, 0.5 (default) for balanced results, or 1 for strict adherence to your prompt with less creative variation.
  </Accordion>

  <Accordion title="What is the difference between Pro and Standard?">
    Pro delivers higher fidelity with richer detail, ideal for premium content and marketing. Standard offers good quality with faster processing, suitable for high-volume generation and testing. Both share the same parameters and capabilities.
  </Accordion>

  <Accordion title="What are the rate limits for Kling 3?">
    Rate limits vary by subscription tier. See [Rate Limits](/ratelimits) for current limits and quotas.
  </Accordion>

  <Accordion title="How much does Kling 3 cost?">
    Pricing varies based on model tier (Pro vs Standard) and video duration. See the [Pricing](/pricing) page for current rates.
  </Accordion>
</AccordionGroup>

## Best practices

* **Prompt clarity**: Write detailed prompts specifying subject, action, camera movement, and atmosphere
* **Start simple**: Begin with single-shot mode before attempting multi-shot sequences
* **Image quality**: For I2V, use high-resolution source images with clear subjects (min 300x300)
* **Duration planning**: For multi-shot, plan scene durations to stay within 15-second total limit
* **Element consistency**: Use pre-registered elements for recurring characters across multiple videos
* **CFG tuning**: Start with 0.5, decrease for more creativity, increase for prompt precision
* **Production integration**: Use webhooks instead of polling for scalable applications
* **Error handling**: Implement retry logic with exponential backoff for 503 errors

## Related APIs

* **[Kling 3 Omni](/api-reference/video/kling-v3-omni/overview)**: Kling 3 with video reference support for motion/style guidance
* **[Kling 2.6 Pro](/api-reference/image-to-video/kling-v2-6-pro)**: Previous generation with motion control capabilities
* **[Kling O1](/api-reference/image-to-video/kling-o1/overview)**: High-performance video generation
* **[Runway Gen 4.5](/api-reference/video/runway-gen-4-5/overview)**: Alternative video generation model
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.freepik.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Kling 3 API

> Generate AI videos from text or images with Kling 3. Multi-shot support, first/end frame control, and durations from 3-15 seconds. Pro and Standard tiers for creative video production.

<Card title="Kling 3 integration" icon="video">
  Generate high-quality videos from text prompts or images using Kling's latest V3 model with multi-shot support and advanced frame control.
</Card>

Kling 3 is a dual-mode video generation API that creates professional-grade videos from either text descriptions or source images. It supports multi-shot mode for creating complex narratives with up to 6 scenes, first and end frame image control, and flexible durations from 3 to 15 seconds. Available in Pro and Standard tiers to balance quality and cost.

### Key capabilities

* **Text-to-Video (T2V)**: Generate videos from text prompts up to 2500 characters
* **Image-to-Video (I2V)**: Use first\_frame and/or end\_frame images to control video start and end points
* **Multi-shot mode**: Create videos with up to 6 scenes, each with custom prompts and durations (max 15 seconds total)
* **Flexible durations**: 3-15 seconds with per-shot duration control in multi-shot mode
* **Element consistency**: Pre-registered element IDs for consistent characters/styles across videos
* **CFG scale control**: Adjust prompt adherence from 0 (creative) to 1 (strict), default 0.5
* **Negative prompts**: Exclude unwanted elements, styles, or artifacts
* **Async processing**: Webhook notifications or polling for task completion

### Pro vs Standard

| Feature  | Kling 3 Pro                    | Kling 3 Standard             |
| -------- | ------------------------------ | ---------------------------- |
| Quality  | Higher fidelity, richer detail | Good quality, cost-effective |
| Speed    | Standard processing            | Faster processing            |
| Best for | Premium content, marketing     | High-volume, testing         |

### Use cases

* **Marketing and advertising**: Create multi-scene product narratives with consistent branding
* **Social media content**: Generate vertical videos for TikTok, Instagram Reels, and YouTube Shorts
* **E-commerce**: Animate product images with controlled start and end frames
* **Storyboarding**: Turn scripts into multi-shot video sequences
* **Creative storytelling**: Build narratives with scene-by-scene control

### Generate videos with Kling 3

Create videos by submitting a text prompt (T2V) or images with prompt (I2V) to the API. The service returns a task ID for async polling or webhook notification.

<div className="my-11">
  <Columns cols={2}>
    <Card title="POST /v1/ai/video/kling-v3-pro" icon="video" href="/api-reference/video/kling-v3/generate-pro">
      Generate video with Kling 3 Pro
    </Card>

    <Card title="POST /v1/ai/video/kling-v3-std" icon="video" href="/api-reference/video/kling-v3/generate-std">
      Generate video with Kling 3 Standard
    </Card>

    <Card title="GET /v1/ai/video/kling-v3" icon="list" href="/api-reference/video/kling-v3/kling-v3-tasks">
      List all Kling 3 tasks
    </Card>

    <Card title="GET /v1/ai/video/kling-v3/{task-id}" icon="magnifying-glass" href="/api-reference/video/kling-v3/task-by-id">
      Get task status by ID
    </Card>
  </Columns>
</div>

### Parameters

| Parameter         | Type      | Required | Default | Description                                                            |
| ----------------- | --------- | -------- | ------- | ---------------------------------------------------------------------- |
| `prompt`          | `string`  | No       | -       | Text prompt describing the video (max 2500 chars). Required for T2V.   |
| `negative_prompt` | `string`  | No       | -       | Text describing what to avoid (max 2500 chars)                         |
| `image_list`      | `array`   | No       | -       | Reference images with `image_url` and `type` (first\_frame/end\_frame) |
| `multi_shot`      | `boolean` | No       | `false` | Enable multi-shot mode for multi-scene videos                          |
| `shot_type`       | `string`  | No       | -       | Use `customize` for custom shot definitions                            |
| `multi_prompt`    | `array`   | No       | -       | Shot definitions: `index` (0-5), `prompt`, `duration` (min 3s)         |
| `element_list`    | `array`   | No       | -       | Pre-registered element IDs for character/style consistency             |
| `aspect_ratio`    | `string`  | No       | `16:9`  | Video ratio: `16:9`, `9:16`, `1:1`                                     |
| `duration`        | `integer` | No       | `5`     | Duration in seconds: 3-15 (default 5)                                  |
| `cfg_scale`       | `number`  | No       | `0.5`   | Prompt adherence: 0 (creative) to 1 (strict)                           |
| `webhook_url`     | `string`  | No       | -       | URL for task completion notification                                   |

### Image list item

| Field       | Type     | Description                                                         |
| ----------- | -------- | ------------------------------------------------------------------- |
| `image_url` | `string` | Publicly accessible image URL (300x300 min, 10MB max, JPG/JPEG/PNG) |
| `type`      | `string` | Image role: `first_frame` or `end_frame`                            |

### Multi-prompt item

| Field      | Type      | Description                                |
| ---------- | --------- | ------------------------------------------ |
| `index`    | `integer` | Shot order (0-5)                           |
| `prompt`   | `string`  | Text prompt for this shot (max 2500 chars) |
| `duration` | `number`  | Shot duration (minimum 3 seconds)          |

## Frequently Asked Questions

<AccordionGroup>
  <Accordion title="What is Kling 3 and how does it work?">
    Kling 3 is an AI video generation model that creates videos from text prompts (T2V) or images (I2V). You submit your request via the API, receive a task ID immediately, then poll for results or receive a webhook notification when processing completes. Typical generation takes 30-120 seconds depending on duration and complexity.
  </Accordion>

  <Accordion title="What is multi-shot mode?">
    Multi-shot mode lets you create videos with up to 6 distinct scenes. Each scene can have its own prompt and duration. The total duration across all shots cannot exceed 15 seconds, and each shot must be at least 3 seconds. Enable with `multi_shot: true` and define scenes in `multi_prompt`.
  </Accordion>

  <Accordion title="How do first_frame and end_frame work?">
    Use the `image_list` parameter to provide reference images. Set `type: "first_frame"` to use an image as the video's starting point, or `type: "end_frame"` for the ending point. You can use both to create a transition from one image to another.
  </Accordion>

  <Accordion title="What image formats does Kling 3 support?">
    Kling 3 accepts JPG, JPEG, and PNG images via publicly accessible URLs. Requirements: minimum 300x300 pixels, maximum 10MB file size, aspect ratio between 1:2.5 and 2.5:1.
  </Accordion>

  <Accordion title="What is cfg_scale and how should I set it?">
    CFG scale controls how closely the model follows your prompt. Use 0 for maximum creativity and artistic interpretation, 0.5 (default) for balanced results, or 1 for strict adherence to your prompt with less creative variation.
  </Accordion>

  <Accordion title="What is the difference between Pro and Standard?">
    Pro delivers higher fidelity with richer detail, ideal for premium content and marketing. Standard offers good quality with faster processing, suitable for high-volume generation and testing. Both share the same parameters and capabilities.
  </Accordion>

  <Accordion title="What are the rate limits for Kling 3?">
    Rate limits vary by subscription tier. See [Rate Limits](/ratelimits) for current limits and quotas.
  </Accordion>

  <Accordion title="How much does Kling 3 cost?">
    Pricing varies based on model tier (Pro vs Standard) and video duration. See the [Pricing](/pricing) page for current rates.
  </Accordion>
</AccordionGroup>

## Best practices

* **Prompt clarity**: Write detailed prompts specifying subject, action, camera movement, and atmosphere
* **Start simple**: Begin with single-shot mode before attempting multi-shot sequences
* **Image quality**: For I2V, use high-resolution source images with clear subjects (min 300x300)
* **Duration planning**: For multi-shot, plan scene durations to stay within 15-second total limit
* **Element consistency**: Use pre-registered elements for recurring characters across multiple videos
* **CFG tuning**: Start with 0.5, decrease for more creativity, increase for prompt precision
* **Production integration**: Use webhooks instead of polling for scalable applications
* **Error handling**: Implement retry logic with exponential backoff for 503 errors

## Related APIs

* **[Kling 3 Omni](/api-reference/video/kling-v3-omni/overview)**: Kling 3 with video reference support for motion/style guidance
* **[Kling 2.6 Pro](/api-reference/image-to-video/kling-v2-6-pro)**: Previous generation with motion control capabilities
* **[Kling O1](/api-reference/image-to-video/kling-o1/overview)**: High-performance video generation
* **[Runway Gen 4.5](/api-reference/video/runway-gen-4-5/overview)**: Alternative video generation model
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.freepik.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Kling 3 API

> Generate AI videos from text or images with Kling 3. Multi-shot support, first/end frame control, and durations from 3-15 seconds. Pro and Standard tiers for creative video production.

<Card title="Kling 3 integration" icon="video">
  Generate high-quality videos from text prompts or images using Kling's latest V3 model with multi-shot support and advanced frame control.
</Card>

Kling 3 is a dual-mode video generation API that creates professional-grade videos from either text descriptions or source images. It supports multi-shot mode for creating complex narratives with up to 6 scenes, first and end frame image control, and flexible durations from 3 to 15 seconds. Available in Pro and Standard tiers to balance quality and cost.

### Key capabilities

* **Text-to-Video (T2V)**: Generate videos from text prompts up to 2500 characters
* **Image-to-Video (I2V)**: Use first\_frame and/or end\_frame images to control video start and end points
* **Multi-shot mode**: Create videos with up to 6 scenes, each with custom prompts and durations (max 15 seconds total)
* **Flexible durations**: 3-15 seconds with per-shot duration control in multi-shot mode
* **Element consistency**: Pre-registered element IDs for consistent characters/styles across videos
* **CFG scale control**: Adjust prompt adherence from 0 (creative) to 1 (strict), default 0.5
* **Negative prompts**: Exclude unwanted elements, styles, or artifacts
* **Async processing**: Webhook notifications or polling for task completion

### Pro vs Standard

| Feature  | Kling 3 Pro                    | Kling 3 Standard             |
| -------- | ------------------------------ | ---------------------------- |
| Quality  | Higher fidelity, richer detail | Good quality, cost-effective |
| Speed    | Standard processing            | Faster processing            |
| Best for | Premium content, marketing     | High-volume, testing         |

### Use cases

* **Marketing and advertising**: Create multi-scene product narratives with consistent branding
* **Social media content**: Generate vertical videos for TikTok, Instagram Reels, and YouTube Shorts
* **E-commerce**: Animate product images with controlled start and end frames
* **Storyboarding**: Turn scripts into multi-shot video sequences
* **Creative storytelling**: Build narratives with scene-by-scene control

### Generate videos with Kling 3

Create videos by submitting a text prompt (T2V) or images with prompt (I2V) to the API. The service returns a task ID for async polling or webhook notification.

<div className="my-11">
  <Columns cols={2}>
    <Card title="POST /v1/ai/video/kling-v3-pro" icon="video" href="/api-reference/video/kling-v3/generate-pro">
      Generate video with Kling 3 Pro
    </Card>

    <Card title="POST /v1/ai/video/kling-v3-std" icon="video" href="/api-reference/video/kling-v3/generate-std">
      Generate video with Kling 3 Standard
    </Card>

    <Card title="GET /v1/ai/video/kling-v3" icon="list" href="/api-reference/video/kling-v3/kling-v3-tasks">
      List all Kling 3 tasks
    </Card>

    <Card title="GET /v1/ai/video/kling-v3/{task-id}" icon="magnifying-glass" href="/api-reference/video/kling-v3/task-by-id">
      Get task status by ID
    </Card>
  </Columns>
</div>

### Parameters

| Parameter         | Type      | Required | Default | Description                                                            |
| ----------------- | --------- | -------- | ------- | ---------------------------------------------------------------------- |
| `prompt`          | `string`  | No       | -       | Text prompt describing the video (max 2500 chars). Required for T2V.   |
| `negative_prompt` | `string`  | No       | -       | Text describing what to avoid (max 2500 chars)                         |
| `image_list`      | `array`   | No       | -       | Reference images with `image_url` and `type` (first\_frame/end\_frame) |
| `multi_shot`      | `boolean` | No       | `false` | Enable multi-shot mode for multi-scene videos                          |
| `shot_type`       | `string`  | No       | -       | Use `customize` for custom shot definitions                            |
| `multi_prompt`    | `array`   | No       | -       | Shot definitions: `index` (0-5), `prompt`, `duration` (min 3s)         |
| `element_list`    | `array`   | No       | -       | Pre-registered element IDs for character/style consistency             |
| `aspect_ratio`    | `string`  | No       | `16:9`  | Video ratio: `16:9`, `9:16`, `1:1`                                     |
| `duration`        | `integer` | No       | `5`     | Duration in seconds: 3-15 (default 5)                                  |
| `cfg_scale`       | `number`  | No       | `0.5`   | Prompt adherence: 0 (creative) to 1 (strict)                           |
| `webhook_url`     | `string`  | No       | -       | URL for task completion notification                                   |

### Image list item

| Field       | Type     | Description                                                         |
| ----------- | -------- | ------------------------------------------------------------------- |
| `image_url` | `string` | Publicly accessible image URL (300x300 min, 10MB max, JPG/JPEG/PNG) |
| `type`      | `string` | Image role: `first_frame` or `end_frame`                            |

### Multi-prompt item

| Field      | Type      | Description                                |
| ---------- | --------- | ------------------------------------------ |
| `index`    | `integer` | Shot order (0-5)                           |
| `prompt`   | `string`  | Text prompt for this shot (max 2500 chars) |
| `duration` | `number`  | Shot duration (minimum 3 seconds)          |

## Frequently Asked Questions

<AccordionGroup>
  <Accordion title="What is Kling 3 and how does it work?">
    Kling 3 is an AI video generation model that creates videos from text prompts (T2V) or images (I2V). You submit your request via the API, receive a task ID immediately, then poll for results or receive a webhook notification when processing completes. Typical generation takes 30-120 seconds depending on duration and complexity.
  </Accordion>

  <Accordion title="What is multi-shot mode?">
    Multi-shot mode lets you create videos with up to 6 distinct scenes. Each scene can have its own prompt and duration. The total duration across all shots cannot exceed 15 seconds, and each shot must be at least 3 seconds. Enable with `multi_shot: true` and define scenes in `multi_prompt`.
  </Accordion>

  <Accordion title="How do first_frame and end_frame work?">
    Use the `image_list` parameter to provide reference images. Set `type: "first_frame"` to use an image as the video's starting point, or `type: "end_frame"` for the ending point. You can use both to create a transition from one image to another.
  </Accordion>

  <Accordion title="What image formats does Kling 3 support?">
    Kling 3 accepts JPG, JPEG, and PNG images via publicly accessible URLs. Requirements: minimum 300x300 pixels, maximum 10MB file size, aspect ratio between 1:2.5 and 2.5:1.
  </Accordion>

  <Accordion title="What is cfg_scale and how should I set it?">
    CFG scale controls how closely the model follows your prompt. Use 0 for maximum creativity and artistic interpretation, 0.5 (default) for balanced results, or 1 for strict adherence to your prompt with less creative variation.
  </Accordion>

  <Accordion title="What is the difference between Pro and Standard?">
    Pro delivers higher fidelity with richer detail, ideal for premium content and marketing. Standard offers good quality with faster processing, suitable for high-volume generation and testing. Both share the same parameters and capabilities.
  </Accordion>

  <Accordion title="What are the rate limits for Kling 3?">
    Rate limits vary by subscription tier. See [Rate Limits](/ratelimits) for current limits and quotas.
  </Accordion>

  <Accordion title="How much does Kling 3 cost?">
    Pricing varies based on model tier (Pro vs Standard) and video duration. See the [Pricing](/pricing) page for current rates.
  </Accordion>
</AccordionGroup>

## Best practices

* **Prompt clarity**: Write detailed prompts specifying subject, action, camera movement, and atmosphere
* **Start simple**: Begin with single-shot mode before attempting multi-shot sequences
* **Image quality**: For I2V, use high-resolution source images with clear subjects (min 300x300)
* **Duration planning**: For multi-shot, plan scene durations to stay within 15-second total limit
* **Element consistency**: Use pre-registered elements for recurring characters across multiple videos
* **CFG tuning**: Start with 0.5, decrease for more creativity, increase for prompt precision
* **Production integration**: Use webhooks instead of polling for scalable applications
* **Error handling**: Implement retry logic with exponential backoff for 503 errors

## Related APIs

* **[Kling 3 Omni](/api-reference/video/kling-v3-omni/overview)**: Kling 3 with video reference support for motion/style guidance
* **[Kling 2.6 Pro](/api-reference/image-to-video/kling-v2-6-pro)**: Previous generation with motion control capabilities
* **[Kling O1](/api-reference/image-to-video/kling-o1/overview)**: High-performance video generation
* **[Runway Gen 4.5](/api-reference/video/runway-gen-4-5/overview)**: Alternative video generation model
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.freepik.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Kling 3 - List tasks

> Retrieve the list of all Kling 3 video generation tasks for the authenticated user.



## OpenAPI

````yaml get /v1/ai/video/kling-v3
openapi: 3.0.0
info:
  description: >-
    The Freepik API is your gateway to a vast collection of high-quality digital
    resources for your applications and projects. As a leading platform, it
    offers a wide range of graphics, including vectors, photos, illustrations,
    icons, PSD templates, and more, all curated by talented designers from
    around the world.
  title: Freepik API
  version: 1.0.0
servers:
  - description: B2B API Production V1
    url: https://api.freepik.com
security:
  - apiKey: []
paths:
  /v1/ai/video/kling-v3:
    get:
      tags:
        - video
        - kling-v3
      summary: Kling 3 - List tasks
      description: >-
        Retrieve the list of all Kling 3 video generation tasks for the
        authenticated user.
      operationId: getAiVideoKlingV3Tasks
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_200_response'
          description: OK - The list of Kling 3 tasks is returned
        '400':
          content:
            application/json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Parameter 'page' must be greater than 0
                invalid_query:
                  summary: Parameter 'query' is not valid
                  value:
                    message: Parameter 'query' must not be empty
                invalid_filter:
                  summary: Parameter 'filter' is not valid
                  value:
                    message: Parameter 'filter' is not valid
                generic_bad_request:
                  summary: Bad Request
                  value:
                    message: Parameter ':attribute' is not valid
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
            application/problem+json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Your request parameters didn't validate.
                    invalid_params:
                      - name: page
                        reason: Parameter 'page' must be greater than 0
                      - name: per_page
                        reason: Parameter 'per_page' must be greater than 0
              schema:
                $ref: >-
                  #/components/schemas/get_all_style_transfer_tasks_400_response_1
          description: >-
            Bad Request - The server could not understand the request due to
            invalid syntax.
        '401':
          content:
            application/json:
              examples:
                invalid_api_key:
                  summary: API key is not valid
                  value:
                    message: Invalid API key
                missing_api_key:
                  summary: API key is not provided
                  value:
                    message: Missing API key
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
          description: >-
            Unauthorized - The client must authenticate itself to get the
            requested response.
        '500':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_500_response'
          description: >-
            Internal Server Error - The server has encountered a situation it
            doesn't know how to handle.
        '503':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_503_response'
          description: Service Unavailable
components:
  schemas:
    get_all_style_transfer_tasks_200_response:
      example:
        data:
          - task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
            status: CREATED
          - task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
            status: CREATED
      properties:
        data:
          items:
            $ref: '#/components/schemas/task'
          type: array
      required:
        - data
      type: object
    get_all_style_transfer_tasks_400_response:
      example:
        message: message
      properties:
        message:
          type: string
      type: object
    get_all_style_transfer_tasks_400_response_1:
      properties:
        problem:
          $ref: >-
            #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem
      type: object
    get_all_style_transfer_tasks_500_response:
      example:
        message: Internal Server Error
      properties:
        message:
          example: Internal Server Error
          type: string
      type: object
    get_all_style_transfer_tasks_503_response:
      example:
        message: Service Unavailable. Please try again later.
      properties:
        message:
          example: Service Unavailable. Please try again later.
          type: string
      type: object
    task:
      example:
        task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
        status: CREATED
      properties:
        task_id:
          description: Task identifier
          format: uuid
          type: string
        status:
          description: Task status
          enum:
            - CREATED
            - IN_PROGRESS
            - COMPLETED
            - FAILED
          type: string
      required:
        - status
        - task_id
      type: object
    get_all_style_transfer_tasks_400_response_1_problem:
      properties:
        message:
          example: Your request parameters didn't validate.
          type: string
        invalid_params:
          items:
            $ref: >-
              #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner
          type: array
      required:
        - invalid_params
        - message
      type: object
    get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner:
      properties:
        name:
          example: page
          type: string
        reason:
          example: Parameter 'page' must be greater than 0
          type: string
      required:
        - name
        - reason
      type: object
  securitySchemes:
    apiKey:
      description: >
        Your Freepik API key. Required for authentication. [Learn how to obtain
        an API
        key](https://docs.freepik.com/authentication#obtaining-an-api-key)
      in: header
      name: x-freepik-api-key
      type: apiKey

````
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.freepik.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Kling 3 - List tasks

> Retrieve the list of all Kling 3 video generation tasks for the authenticated user.



## OpenAPI

````yaml get /v1/ai/video/kling-v3
openapi: 3.0.0
info:
  description: >-
    The Freepik API is your gateway to a vast collection of high-quality digital
    resources for your applications and projects. As a leading platform, it
    offers a wide range of graphics, including vectors, photos, illustrations,
    icons, PSD templates, and more, all curated by talented designers from
    around the world.
  title: Freepik API
  version: 1.0.0
servers:
  - description: B2B API Production V1
    url: https://api.freepik.com
security:
  - apiKey: []
paths:
  /v1/ai/video/kling-v3:
    get:
      tags:
        - video
        - kling-v3
      summary: Kling 3 - List tasks
      description: >-
        Retrieve the list of all Kling 3 video generation tasks for the
        authenticated user.
      operationId: getAiVideoKlingV3Tasks
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_200_response'
          description: OK - The list of Kling 3 tasks is returned
        '400':
          content:
            application/json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Parameter 'page' must be greater than 0
                invalid_query:
                  summary: Parameter 'query' is not valid
                  value:
                    message: Parameter 'query' must not be empty
                invalid_filter:
                  summary: Parameter 'filter' is not valid
                  value:
                    message: Parameter 'filter' is not valid
                generic_bad_request:
                  summary: Bad Request
                  value:
                    message: Parameter ':attribute' is not valid
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
            application/problem+json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Your request parameters didn't validate.
                    invalid_params:
                      - name: page
                        reason: Parameter 'page' must be greater than 0
                      - name: per_page
                        reason: Parameter 'per_page' must be greater than 0
              schema:
                $ref: >-
                  #/components/schemas/get_all_style_transfer_tasks_400_response_1
          description: >-
            Bad Request - The server could not understand the request due to
            invalid syntax.
        '401':
          content:
            application/json:
              examples:
                invalid_api_key:
                  summary: API key is not valid
                  value:
                    message: Invalid API key
                missing_api_key:
                  summary: API key is not provided
                  value:
                    message: Missing API key
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
          description: >-
            Unauthorized - The client must authenticate itself to get the
            requested response.
        '500':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_500_response'
          description: >-
            Internal Server Error - The server has encountered a situation it
            doesn't know how to handle.
        '503':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_503_response'
          description: Service Unavailable
components:
  schemas:
    get_all_style_transfer_tasks_200_response:
      example:
        data:
          - task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
            status: CREATED
          - task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
            status: CREATED
      properties:
        data:
          items:
            $ref: '#/components/schemas/task'
          type: array
      required:
        - data
      type: object
    get_all_style_transfer_tasks_400_response:
      example:
        message: message
      properties:
        message:
          type: string
      type: object
    get_all_style_transfer_tasks_400_response_1:
      properties:
        problem:
          $ref: >-
            #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem
      type: object
    get_all_style_transfer_tasks_500_response:
      example:
        message: Internal Server Error
      properties:
        message:
          example: Internal Server Error
          type: string
      type: object
    get_all_style_transfer_tasks_503_response:
      example:
        message: Service Unavailable. Please try again later.
      properties:
        message:
          example: Service Unavailable. Please try again later.
          type: string
      type: object
    task:
      example:
        task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
        status: CREATED
      properties:
        task_id:
          description: Task identifier
          format: uuid
          type: string
        status:
          description: Task status
          enum:
            - CREATED
            - IN_PROGRESS
            - COMPLETED
            - FAILED
          type: string
      required:
        - status
        - task_id
      type: object
    get_all_style_transfer_tasks_400_response_1_problem:
      properties:
        message:
          example: Your request parameters didn't validate.
          type: string
        invalid_params:
          items:
            $ref: >-
              #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner
          type: array
      required:
        - invalid_params
        - message
      type: object
    get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner:
      properties:
        name:
          example: page
          type: string
        reason:
          example: Parameter 'page' must be greater than 0
          type: string
      required:
        - name
        - reason
      type: object
  securitySchemes:
    apiKey:
      description: >
        Your Freepik API key. Required for authentication. [Learn how to obtain
        an API
        key](https://docs.freepik.com/authentication#obtaining-an-api-key)
      in: header
      name: x-freepik-api-key
      type: apiKey

````> ## Documentation Index
> Fetch the complete documentation index at: https://docs.freepik.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Kling 3 Standard - Generate video

> Generate AI video using Kling 3 Standard with text-to-video or image-to-video capabilities.

**Features:**
- **Text-to-video**: Generate videos from text prompts
- **Image-to-video**: Use start and/or end frame images to guide generation
- **Multi-shot**: Create videos with up to 6 shots (max 15s total)
- **Element control**: Include reference images for consistent character/style

**Duration:** 3-15 seconds
**Quality:** Standard mode offers faster generation at slightly lower quality compared to Pro.




## OpenAPI

````yaml post /v1/ai/video/kling-v3-std
openapi: 3.0.0
info:
  description: >-
    The Freepik API is your gateway to a vast collection of high-quality digital
    resources for your applications and projects. As a leading platform, it
    offers a wide range of graphics, including vectors, photos, illustrations,
    icons, PSD templates, and more, all curated by talented designers from
    around the world.
  title: Freepik API
  version: 1.0.0
servers:
  - description: B2B API Production V1
    url: https://api.freepik.com
security:
  - apiKey: []
paths:
  /v1/ai/video/kling-v3-std:
    post:
      tags:
        - video
        - kling-v3-std
        - background_tasks
      summary: Kling 3 Standard - Generate video
      description: >
        Generate AI video using Kling 3 Standard with text-to-video or
        image-to-video capabilities.


        **Features:**

        - **Text-to-video**: Generate videos from text prompts

        - **Image-to-video**: Use start and/or end frame images to guide
        generation

        - **Multi-shot**: Create videos with up to 6 shots (max 15s total)

        - **Element control**: Include reference images for consistent
        character/style


        **Duration:** 3-15 seconds

        **Quality:** Standard mode offers faster generation at slightly lower
        quality compared to Pro.
      operationId: postAiVideoKlingV3Std
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/kling-v3-request'
        required: true
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/task-detail-200-default-response'
          description: OK - Task created successfully
        '400':
          content:
            application/json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Parameter 'page' must be greater than 0
                invalid_query:
                  summary: Parameter 'query' is not valid
                  value:
                    message: Parameter 'query' must not be empty
                invalid_filter:
                  summary: Parameter 'filter' is not valid
                  value:
                    message: Parameter 'filter' is not valid
                generic_bad_request:
                  summary: Bad Request
                  value:
                    message: Parameter ':attribute' is not valid
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
            application/problem+json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Your request parameters didn't validate.
                    invalid_params:
                      - name: page
                        reason: Parameter 'page' must be greater than 0
                      - name: per_page
                        reason: Parameter 'per_page' must be greater than 0
              schema:
                $ref: >-
                  #/components/schemas/get_all_style_transfer_tasks_400_response_1
          description: >-
            Bad Request - The server could not understand the request due to
            invalid syntax.
        '401':
          content:
            application/json:
              examples:
                invalid_api_key:
                  summary: API key is not valid
                  value:
                    message: Invalid API key
                missing_api_key:
                  summary: API key is not provided
                  value:
                    message: Missing API key
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
          description: >-
            Unauthorized - The client must authenticate itself to get the
            requested response.
        '500':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_500_response'
          description: >-
            Internal Server Error - The server has encountered a situation it
            doesn't know how to handle.
        '503':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_503_response'
          description: Service Unavailable
      security:
        - apiKey: []
components:
  schemas:
    kling-v3-request:
      properties:
        webhook_url:
          description: >
            Optional callback URL that receives asynchronous notifications when
            the task changes status.

            The payload includes the task status and result URL when completed.
          format: uri
          type: string
        prompt:
          description: >
            Text prompt describing the desired video content. Maximum 2500
            characters.

            Required for text-to-video mode or when not using multi_prompt.


            **Tips for better results:**

            - Be specific about motion, camera angles, and actions

            - Describe the scene, characters, and atmosphere

            - Reference elements in your prompt as @Element1, @Element2

            - Reference voices with <<<voice_1>>> and <<<voice_2>>>
          maxLength: 2500
          type: string
        multi_prompt:
          description: |
            Multi-shot prompts with durations for sequential video generation.
            Each item specifies a prompt and duration for that shot.
            Maximum 6 shots, total duration cannot exceed 15 seconds.
          items:
            $ref: '#/components/schemas/kling-v3-multi-prompt-item'
          maxItems: 6
          type: array
        start_image_url:
          description: |
            URL of the image to use as the first frame of the video.
            Required for image-to-video mode.

            **Image requirements:**
            - Minimum: 300x300 pixels
            - Maximum: 10MB file size
            - Aspect ratio: 1:2.5 to 2.5:1
            - Formats: JPG, JPEG, PNG
          type: string
        end_image_url:
          description: |
            URL of the image to use as the final frame of the video.
            Optional for image-to-video mode.

            **Image requirements:**
            - Same as start_image_url
          type: string
        elements:
          description: >
            Custom characters/objects with reference images for consistent
            identity across the video.

            Reference in your prompt as @Element1, @Element2, etc.

            When elements are provided, the request is processed in
            image-to-video mode.

            For best results, also provide a `start_image_url`.
          items:
            $ref: '#/components/schemas/kling-v3-element'
          type: array
        generate_audio:
          default: true
          description: Whether to generate native audio for the video.
          type: boolean
        voice_ids:
          description: >
            Custom voice identifiers for video generation.

            Maximum 2 voices per task.

            Reference voices in your prompt with <<<voice_1>>> and
            <<<voice_2>>>.
          items:
            type: string
          type: array
        shot_type:
          default: customize
          description: |
            Multi-shot generation type:
            - `customize`: Define each shot manually with multi_prompt
            - `intelligent`: AI-assisted shot generation
          enum:
            - customize
            - intelligent
          type: string
        aspect_ratio:
          $ref: '#/components/schemas/kling-v3-aspect-ratio'
        duration:
          $ref: '#/components/schemas/kling-v3-duration'
        negative_prompt:
          default: blur, distort, and low quality
          description: >-
            Undesired elements to avoid in the generated video. Maximum 2500
            characters.
          maxLength: 2500
          type: string
        cfg_scale:
          default: 0.5
          description: >
            Guidance scale for prompt adherence. Higher values mean stronger
            adherence to the prompt.


            - **0**: Maximum flexibility, more creative interpretation

            - **0.5** (default): Balanced between prompt adherence and
            creativity

            - **2**: Strict adherence to prompt, less creative variation
          format: float
          maximum: 2
          minimum: 0
          type: number
      type: object
    task-detail-200-default-response:
      description: OK - The task exists and the status is returned
    get_all_style_transfer_tasks_400_response:
      example:
        message: message
      properties:
        message:
          type: string
      type: object
    get_all_style_transfer_tasks_400_response_1:
      properties:
        problem:
          $ref: >-
            #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem
      type: object
    get_all_style_transfer_tasks_500_response:
      example:
        message: Internal Server Error
      properties:
        message:
          example: Internal Server Error
          type: string
      type: object
    get_all_style_transfer_tasks_503_response:
      example:
        message: Service Unavailable. Please try again later.
      properties:
        message:
          example: Service Unavailable. Please try again later.
          type: string
      type: object
    kling-v3-multi-prompt-item:
      description: Multi-shot prompt item with prompt text and duration for Kling V3.
      properties:
        prompt:
          description: Text prompt for this specific shot segment. Maximum 2500 characters.
          maxLength: 2500
          type: string
        duration:
          description: Duration of this segment in seconds (3-15).
          enum:
            - '3'
            - '4'
            - '5'
            - '6'
            - '7'
            - '8'
            - '9'
            - '10'
            - '11'
            - '12'
            - '13'
            - '14'
            - '15'
          type: string
      type: object
    kling-v3-element:
      description: >-
        Element definition for Kling V3 with reference images for consistent
        character/object identity.
      properties:
        reference_image_urls:
          description: >-
            Array of reference image URLs for this element. Multiple angles
            improve consistency.
          items:
            type: string
          type: array
        frontal_image_url:
          description: >-
            URL of a frontal/primary reference image for this element. Best
            results with clear face/front view.
          type: string
      type: object
    kling-v3-aspect-ratio:
      default: '16:9'
      description: >
        Aspect ratio for the generated video:

        - `16:9`: Landscape (widescreen) - ideal for YouTube, presentations

        - `9:16`: Portrait (vertical) - ideal for TikTok, Instagram Stories,
        Reels

        - `1:1`: Square - ideal for Instagram posts, social media
      enum:
        - '16:9'
        - '9:16'
        - '1:1'
      type: string
    kling-v3-duration:
      default: '5'
      description: >
        Duration of the generated video in seconds.


        **Range:** 3-15 seconds

        **Note:** When using multi-shot mode, total duration across all shots
        cannot exceed 15 seconds.
      enum:
        - '3'
        - '4'
        - '5'
        - '6'
        - '7'
        - '8'
        - '9'
        - '10'
        - '11'
        - '12'
        - '13'
        - '14'
        - '15'
      type: string
    get_all_style_transfer_tasks_400_response_1_problem:
      properties:
        message:
          example: Your request parameters didn't validate.
          type: string
        invalid_params:
          items:
            $ref: >-
              #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner
          type: array
      required:
        - invalid_params
        - message
      type: object
    get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner:
      properties:
        name:
          example: page
          type: string
        reason:
          example: Parameter 'page' must be greater than 0
          type: string
      required:
        - name
        - reason
      type: object
  securitySchemes:
    apiKey:
      description: >
        Your Freepik API key. Required for authentication. [Learn how to obtain
        an API
        key](https://docs.freepik.com/authentication#obtaining-an-api-key)
      in: header
      name: x-freepik-api-key
      type: apiKey

````
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.freepik.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Kling 3 Standard - Generate video

> Generate AI video using Kling 3 Standard with text-to-video or image-to-video capabilities.

**Features:**
- **Text-to-video**: Generate videos from text prompts
- **Image-to-video**: Use start and/or end frame images to guide generation
- **Multi-shot**: Create videos with up to 6 shots (max 15s total)
- **Element control**: Include reference images for consistent character/style

**Duration:** 3-15 seconds
**Quality:** Standard mode offers faster generation at slightly lower quality compared to Pro.




## OpenAPI

````yaml post /v1/ai/video/kling-v3-std
openapi: 3.0.0
info:
  description: >-
    The Freepik API is your gateway to a vast collection of high-quality digital
    resources for your applications and projects. As a leading platform, it
    offers a wide range of graphics, including vectors, photos, illustrations,
    icons, PSD templates, and more, all curated by talented designers from
    around the world.
  title: Freepik API
  version: 1.0.0
servers:
  - description: B2B API Production V1
    url: https://api.freepik.com
security:
  - apiKey: []
paths:
  /v1/ai/video/kling-v3-std:
    post:
      tags:
        - video
        - kling-v3-std
        - background_tasks
      summary: Kling 3 Standard - Generate video
      description: >
        Generate AI video using Kling 3 Standard with text-to-video or
        image-to-video capabilities.


        **Features:**

        - **Text-to-video**: Generate videos from text prompts

        - **Image-to-video**: Use start and/or end frame images to guide
        generation

        - **Multi-shot**: Create videos with up to 6 shots (max 15s total)

        - **Element control**: Include reference images for consistent
        character/style


        **Duration:** 3-15 seconds

        **Quality:** Standard mode offers faster generation at slightly lower
        quality compared to Pro.
      operationId: postAiVideoKlingV3Std
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/kling-v3-request'
        required: true
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/task-detail-200-default-response'
          description: OK - Task created successfully
        '400':
          content:
            application/json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Parameter 'page' must be greater than 0
                invalid_query:
                  summary: Parameter 'query' is not valid
                  value:
                    message: Parameter 'query' must not be empty
                invalid_filter:
                  summary: Parameter 'filter' is not valid
                  value:
                    message: Parameter 'filter' is not valid
                generic_bad_request:
                  summary: Bad Request
                  value:
                    message: Parameter ':attribute' is not valid
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
            application/problem+json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Your request parameters didn't validate.
                    invalid_params:
                      - name: page
                        reason: Parameter 'page' must be greater than 0
                      - name: per_page
                        reason: Parameter 'per_page' must be greater than 0
              schema:
                $ref: >-
                  #/components/schemas/get_all_style_transfer_tasks_400_response_1
          description: >-
            Bad Request - The server could not understand the request due to
            invalid syntax.
        '401':
          content:
            application/json:
              examples:
                invalid_api_key:
                  summary: API key is not valid
                  value:
                    message: Invalid API key
                missing_api_key:
                  summary: API key is not provided
                  value:
                    message: Missing API key
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
          description: >-
            Unauthorized - The client must authenticate itself to get the
            requested response.
        '500':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_500_response'
          description: >-
            Internal Server Error - The server has encountered a situation it
            doesn't know how to handle.
        '503':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_503_response'
          description: Service Unavailable
      security:
        - apiKey: []
components:
  schemas:
    kling-v3-request:
      properties:
        webhook_url:
          description: >
            Optional callback URL that receives asynchronous notifications when
            the task changes status.

            The payload includes the task status and result URL when completed.
          format: uri
          type: string
        prompt:
          description: >
            Text prompt describing the desired video content. Maximum 2500
            characters.

            Required for text-to-video mode or when not using multi_prompt.


            **Tips for better results:**

            - Be specific about motion, camera angles, and actions

            - Describe the scene, characters, and atmosphere

            - Reference elements in your prompt as @Element1, @Element2

            - Reference voices with <<<voice_1>>> and <<<voice_2>>>
          maxLength: 2500
          type: string
        multi_prompt:
          description: |
            Multi-shot prompts with durations for sequential video generation.
            Each item specifies a prompt and duration for that shot.
            Maximum 6 shots, total duration cannot exceed 15 seconds.
          items:
            $ref: '#/components/schemas/kling-v3-multi-prompt-item'
          maxItems: 6
          type: array
        start_image_url:
          description: |
            URL of the image to use as the first frame of the video.
            Required for image-to-video mode.

            **Image requirements:**
            - Minimum: 300x300 pixels
            - Maximum: 10MB file size
            - Aspect ratio: 1:2.5 to 2.5:1
            - Formats: JPG, JPEG, PNG
          type: string
        end_image_url:
          description: |
            URL of the image to use as the final frame of the video.
            Optional for image-to-video mode.

            **Image requirements:**
            - Same as start_image_url
          type: string
        elements:
          description: >
            Custom characters/objects with reference images for consistent
            identity across the video.

            Reference in your prompt as @Element1, @Element2, etc.

            When elements are provided, the request is processed in
            image-to-video mode.

            For best results, also provide a `start_image_url`.
          items:
            $ref: '#/components/schemas/kling-v3-element'
          type: array
        generate_audio:
          default: true
          description: Whether to generate native audio for the video.
          type: boolean
        voice_ids:
          description: >
            Custom voice identifiers for video generation.

            Maximum 2 voices per task.

            Reference voices in your prompt with <<<voice_1>>> and
            <<<voice_2>>>.
          items:
            type: string
          type: array
        shot_type:
          default: customize
          description: |
            Multi-shot generation type:
            - `customize`: Define each shot manually with multi_prompt
            - `intelligent`: AI-assisted shot generation
          enum:
            - customize
            - intelligent
          type: string
        aspect_ratio:
          $ref: '#/components/schemas/kling-v3-aspect-ratio'
        duration:
          $ref: '#/components/schemas/kling-v3-duration'
        negative_prompt:
          default: blur, distort, and low quality
          description: >-
            Undesired elements to avoid in the generated video. Maximum 2500
            characters.
          maxLength: 2500
          type: string
        cfg_scale:
          default: 0.5
          description: >
            Guidance scale for prompt adherence. Higher values mean stronger
            adherence to the prompt.


            - **0**: Maximum flexibility, more creative interpretation

            - **0.5** (default): Balanced between prompt adherence and
            creativity

            - **2**: Strict adherence to prompt, less creative variation
          format: float
          maximum: 2
          minimum: 0
          type: number
      type: object
    task-detail-200-default-response:
      description: OK - The task exists and the status is returned
    get_all_style_transfer_tasks_400_response:
      example:
        message: message
      properties:
        message:
          type: string
      type: object
    get_all_style_transfer_tasks_400_response_1:
      properties:
        problem:
          $ref: >-
            #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem
      type: object
    get_all_style_transfer_tasks_500_response:
      example:
        message: Internal Server Error
      properties:
        message:
          example: Internal Server Error
          type: string
      type: object
    get_all_style_transfer_tasks_503_response:
      example:
        message: Service Unavailable. Please try again later.
      properties:
        message:
          example: Service Unavailable. Please try again later.
          type: string
      type: object
    kling-v3-multi-prompt-item:
      description: Multi-shot prompt item with prompt text and duration for Kling V3.
      properties:
        prompt:
          description: Text prompt for this specific shot segment. Maximum 2500 characters.
          maxLength: 2500
          type: string
        duration:
          description: Duration of this segment in seconds (3-15).
          enum:
            - '3'
            - '4'
            - '5'
            - '6'
            - '7'
            - '8'
            - '9'
            - '10'
            - '11'
            - '12'
            - '13'
            - '14'
            - '15'
          type: string
      type: object
    kling-v3-element:
      description: >-
        Element definition for Kling V3 with reference images for consistent
        character/object identity.
      properties:
        reference_image_urls:
          description: >-
            Array of reference image URLs for this element. Multiple angles
            improve consistency.
          items:
            type: string
          type: array
        frontal_image_url:
          description: >-
            URL of a frontal/primary reference image for this element. Best
            results with clear face/front view.
          type: string
      type: object
    kling-v3-aspect-ratio:
      default: '16:9'
      description: >
        Aspect ratio for the generated video:

        - `16:9`: Landscape (widescreen) - ideal for YouTube, presentations

        - `9:16`: Portrait (vertical) - ideal for TikTok, Instagram Stories,
        Reels

        - `1:1`: Square - ideal for Instagram posts, social media
      enum:
        - '16:9'
        - '9:16'
        - '1:1'
      type: string
    kling-v3-duration:
      default: '5'
      description: >
        Duration of the generated video in seconds.


        **Range:** 3-15 seconds

        **Note:** When using multi-shot mode, total duration across all shots
        cannot exceed 15 seconds.
      enum:
        - '3'
        - '4'
        - '5'
        - '6'
        - '7'
        - '8'
        - '9'
        - '10'
        - '11'
        - '12'
        - '13'
        - '14'
        - '15'
      type: string
    get_all_style_transfer_tasks_400_response_1_problem:
      properties:
        message:
          example: Your request parameters didn't validate.
          type: string
        invalid_params:
          items:
            $ref: >-
              #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner
          type: array
      required:
        - invalid_params
        - message
      type: object
    get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner:
      properties:
        name:
          example: page
          type: string
        reason:
          example: Parameter 'page' must be greater than 0
          type: string
      required:
        - name
        - reason
      type: object
  securitySchemes:
    apiKey:
      description: >
        Your Freepik API key. Required for authentication. [Learn how to obtain
        an API
        key](https://docs.freepik.com/authentication#obtaining-an-api-key)
      in: header
      name: x-freepik-api-key
      type: apiKey

````
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.freepik.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Kling 3 Omni Pro - Generate video from text or image

> Generate AI video using Kling 3 Omni Pro with advanced multi-modal capabilities.

**Features:**
- **Text-to-video**: Generate videos from text prompts
- **Image-to-video**: Use start and/or end frame images to guide generation
- **Multi-shot**: Create videos with up to 6 shots (max 15s total)
- **Element control**: Include reference images for consistent character/style

**Duration:** 3-15 seconds
**Quality:** Pro mode offers highest quality output.

**Note:** For video-to-video generation using a reference video, use the `/ai/reference-to-video/kling-v3-omni-pro` endpoint instead.




## OpenAPI

````yaml post /v1/ai/video/kling-v3-omni-pro
openapi: 3.0.0
info:
  description: >-
    The Freepik API is your gateway to a vast collection of high-quality digital
    resources for your applications and projects. As a leading platform, it
    offers a wide range of graphics, including vectors, photos, illustrations,
    icons, PSD templates, and more, all curated by talented designers from
    around the world.
  title: Freepik API
  version: 1.0.0
servers:
  - description: B2B API Production V1
    url: https://api.freepik.com
security:
  - apiKey: []
paths:
  /v1/ai/video/kling-v3-omni-pro:
    post:
      tags:
        - video
        - kling-v3-omni-pro
        - background_tasks
      summary: Kling 3 Omni Pro - Generate video from text or image
      description: >
        Generate AI video using Kling 3 Omni Pro with advanced multi-modal
        capabilities.


        **Features:**

        - **Text-to-video**: Generate videos from text prompts

        - **Image-to-video**: Use start and/or end frame images to guide
        generation

        - **Multi-shot**: Create videos with up to 6 shots (max 15s total)

        - **Element control**: Include reference images for consistent
        character/style


        **Duration:** 3-15 seconds

        **Quality:** Pro mode offers highest quality output.


        **Note:** For video-to-video generation using a reference video, use the
        `/ai/reference-to-video/kling-v3-omni-pro` endpoint instead.
      operationId: postAiVideoKlingV3OmniPro
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/kling-v3-omni-request'
        required: true
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/task-detail-200-default-response'
          description: OK - Task created successfully
        '400':
          content:
            application/json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Parameter 'page' must be greater than 0
                invalid_query:
                  summary: Parameter 'query' is not valid
                  value:
                    message: Parameter 'query' must not be empty
                invalid_filter:
                  summary: Parameter 'filter' is not valid
                  value:
                    message: Parameter 'filter' is not valid
                generic_bad_request:
                  summary: Bad Request
                  value:
                    message: Parameter ':attribute' is not valid
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
            application/problem+json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Your request parameters didn't validate.
                    invalid_params:
                      - name: page
                        reason: Parameter 'page' must be greater than 0
                      - name: per_page
                        reason: Parameter 'per_page' must be greater than 0
              schema:
                $ref: >-
                  #/components/schemas/get_all_style_transfer_tasks_400_response_1
          description: >-
            Bad Request - The server could not understand the request due to
            invalid syntax.
        '401':
          content:
            application/json:
              examples:
                invalid_api_key:
                  summary: API key is not valid
                  value:
                    message: Invalid API key
                missing_api_key:
                  summary: API key is not provided
                  value:
                    message: Missing API key
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
          description: >-
            Unauthorized - The client must authenticate itself to get the
            requested response.
        '500':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_500_response'
          description: >-
            Internal Server Error - The server has encountered a situation it
            doesn't know how to handle.
        '503':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_503_response'
          description: Service Unavailable
      security:
        - apiKey: []
components:
  schemas:
    kling-v3-omni-request:
      properties:
        webhook_url:
          description: >
            Optional callback URL that receives asynchronous notifications when
            the task changes status.

            The payload includes the task status and result URL when completed.
          format: uri
          type: string
        prompt:
          description: >
            Text prompt describing the desired video content. Maximum 2500
            characters.


            **Usage by mode:**

            - **Text-to-video:** Required unless multi_prompt is provided

            - **Image-to-video:** Either prompt or multi_prompt must be
            provided, but not both
          maxLength: 2500
          type: string
        multi_prompt:
          description: >
            List of prompts for multi-shot video generation. Each item is a
            string prompt for that shot.

            Use with shot_type to control multi-shot behavior.
          items:
            type: string
          maxItems: 6
          type: array
        shot_type:
          default: customize
          description: >-
            The type of multi-shot video generation. Currently only 'customize'
            is supported for Omni.
          enum:
            - customize
          type: string
        image_url:
          description: |
            URL of the start frame image for image-to-video generation.
            Required for image-to-video mode.

            **Image requirements:**
            - Minimum: 300x300 pixels
            - Maximum: 10MB file size
            - Formats: JPG, JPEG, PNG
          type: string
        start_image_url:
          description: >
            Image to use as the first frame of the video.

            Use together with end_image_url to control both start and end frames
            in image-to-video mode.
          type: string
        end_image_url:
          description: |
            Image to use as the last frame of the video.
            Optional for image-to-video mode to guide the final frame.
          type: string
        image_urls:
          description: |
            Reference images for style/appearance guidance.
            Reference in your prompt as @Image1, @Image2, etc.
            Maximum 4 total (elements + reference images).
          items:
            type: string
          type: array
        elements:
          description: >
            Elements (characters/objects) to include for consistent identity
            across the video.

            Reference in your prompt as @Element1, @Element2, etc.
          items:
            $ref: '#/components/schemas/kling-v3-omni-element'
          type: array
        generate_audio:
          description: Whether to generate native audio for the video.
          type: boolean
        voice_ids:
          description: >
            Optional Voice IDs for video generation.

            Reference voices in your prompt with <<<voice_1>>> and
            <<<voice_2>>>.

            Maximum 2 voices per task.
          items:
            type: string
          type: array
        aspect_ratio:
          $ref: '#/components/schemas/kling-v3-omni-aspect-ratio'
        duration:
          $ref: '#/components/schemas/kling-v3-duration'
      type: object
    task-detail-200-default-response:
      description: OK - The task exists and the status is returned
    get_all_style_transfer_tasks_400_response:
      example:
        message: message
      properties:
        message:
          type: string
      type: object
    get_all_style_transfer_tasks_400_response_1:
      properties:
        problem:
          $ref: >-
            #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem
      type: object
    get_all_style_transfer_tasks_500_response:
      example:
        message: Internal Server Error
      properties:
        message:
          example: Internal Server Error
          type: string
      type: object
    get_all_style_transfer_tasks_503_response:
      example:
        message: Service Unavailable. Please try again later.
      properties:
        message:
          example: Service Unavailable. Please try again later.
          type: string
      type: object
    kling-v3-omni-element:
      description: Element definition for Kling V3 Omni with reference images.
      properties:
        reference_image_urls:
          description: >-
            Array of reference image URLs for this element. Multiple angles
            improve consistency.
          items:
            type: string
          type: array
        frontal_image_url:
          description: >-
            URL of a frontal/primary reference image for this element. Best
            results with clear face/front view.
          type: string
      type: object
    kling-v3-omni-aspect-ratio:
      default: '16:9'
      description: >
        Aspect ratio for Kling V3 Omni video generation:

        - `auto`: Automatically match the input image aspect ratio
        (image-to-video only)

        - `16:9`: Landscape (widescreen)

        - `9:16`: Portrait (vertical)

        - `1:1`: Square
      enum:
        - auto
        - '16:9'
        - '9:16'
        - '1:1'
      type: string
    kling-v3-duration:
      default: '5'
      description: >
        Duration of the generated video in seconds.


        **Range:** 3-15 seconds

        **Note:** When using multi-shot mode, total duration across all shots
        cannot exceed 15 seconds.
      enum:
        - '3'
        - '4'
        - '5'
        - '6'
        - '7'
        - '8'
        - '9'
        - '10'
        - '11'
        - '12'
        - '13'
        - '14'
        - '15'
      type: string
    get_all_style_transfer_tasks_400_response_1_problem:
      properties:
        message:
          example: Your request parameters didn't validate.
          type: string
        invalid_params:
          items:
            $ref: >-
              #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner
          type: array
      required:
        - invalid_params
        - message
      type: object
    get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner:
      properties:
        name:
          example: page
          type: string
        reason:
          example: Parameter 'page' must be greater than 0
          type: string
      required:
        - name
        - reason
      type: object
  securitySchemes:
    apiKey:
      description: >
        Your Freepik API key. Required for authentication. [Learn how to obtain
        an API
        key](https://docs.freepik.com/authentication#obtaining-an-api-key)
      in: header
      name: x-freepik-api-key
      type: apiKey

````
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.freepik.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Kling 3 Omni Pro - Video-to-video generation

> Generate AI video using Kling 3 Omni Pro with a reference video for motion and style guidance.

**Video-to-video mode:** This endpoint requires a `video_url` parameter. Reference the video in your prompt using `@Video1`.

**Features:**
- Use a reference video (3-10s) to guide motion and style
- Combine with an image for start frame control
- High-quality pro output

**Use case:** Create videos that follow motion patterns from a reference video while applying your creative prompt.

**Duration:** 3-15 seconds
**Quality:** Pro mode offers highest quality output.

**Tip:** For text-to-video or image-to-video without a reference video, use the `/ai/video/kling-v3-omni-pro` endpoint instead.




## OpenAPI

````yaml post /v1/ai/reference-to-video/kling-v3-omni-pro
openapi: 3.0.0
info:
  description: >-
    The Freepik API is your gateway to a vast collection of high-quality digital
    resources for your applications and projects. As a leading platform, it
    offers a wide range of graphics, including vectors, photos, illustrations,
    icons, PSD templates, and more, all curated by talented designers from
    around the world.
  title: Freepik API
  version: 1.0.0
servers:
  - description: B2B API Production V1
    url: https://api.freepik.com
security:
  - apiKey: []
paths:
  /v1/ai/reference-to-video/kling-v3-omni-pro:
    post:
      tags:
        - reference-to-video
        - kling-v3-omni-pro-r2v
        - background_tasks
      summary: Kling 3 Omni Pro - Video-to-video generation
      description: >
        Generate AI video using Kling 3 Omni Pro with a reference video for
        motion and style guidance.


        **Video-to-video mode:** This endpoint requires a `video_url` parameter.
        Reference the video in your prompt using `@Video1`.


        **Features:**

        - Use a reference video (3-10s) to guide motion and style

        - Combine with an image for start frame control

        - High-quality pro output


        **Use case:** Create videos that follow motion patterns from a reference
        video while applying your creative prompt.


        **Duration:** 3-15 seconds

        **Quality:** Pro mode offers highest quality output.


        **Tip:** For text-to-video or image-to-video without a reference video,
        use the `/ai/video/kling-v3-omni-pro` endpoint instead.
      operationId: postAiReferenceToVideoKlingV3OmniPro
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/kling-v3-omni-video-reference-request'
        required: true
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/task-detail-200-default-response'
          description: OK - Task created successfully
        '400':
          content:
            application/json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Parameter 'page' must be greater than 0
                invalid_query:
                  summary: Parameter 'query' is not valid
                  value:
                    message: Parameter 'query' must not be empty
                invalid_filter:
                  summary: Parameter 'filter' is not valid
                  value:
                    message: Parameter 'filter' is not valid
                generic_bad_request:
                  summary: Bad Request
                  value:
                    message: Parameter ':attribute' is not valid
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
            application/problem+json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Your request parameters didn't validate.
                    invalid_params:
                      - name: page
                        reason: Parameter 'page' must be greater than 0
                      - name: per_page
                        reason: Parameter 'per_page' must be greater than 0
              schema:
                $ref: >-
                  #/components/schemas/get_all_style_transfer_tasks_400_response_1
          description: >-
            Bad Request - The server could not understand the request due to
            invalid syntax.
        '401':
          content:
            application/json:
              examples:
                invalid_api_key:
                  summary: API key is not valid
                  value:
                    message: Invalid API key
                missing_api_key:
                  summary: API key is not provided
                  value:
                    message: Missing API key
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
          description: >-
            Unauthorized - The client must authenticate itself to get the
            requested response.
        '500':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_500_response'
          description: >-
            Internal Server Error - The server has encountered a situation it
            doesn't know how to handle.
        '503':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_503_response'
          description: Service Unavailable
      security:
        - apiKey: []
components:
  schemas:
    kling-v3-omni-video-reference-request:
      description: >
        Generate video using Kling 3 Omni with a reference video for
        motion/style guidance.


        **Required:** The `video_url` parameter is required for this endpoint.
        Reference the video in your prompt using `@Video1`.


        **Best for:**

        - Transferring motion patterns from reference videos

        - Maintaining visual consistency with reference material

        - Creating videos that follow a specific style or movement pattern
      properties:
        webhook_url:
          description: >
            Optional callback URL that receives asynchronous notifications when
            the task changes status.

            The payload includes the task status and result URL when completed.
          format: uri
          type: string
        prompt:
          description: >
            Text prompt describing the desired video content. Maximum 2500
            characters.

            Reference the video in your prompt as @Video1.


            **Tips for better results:**

            - Be specific about actions, camera movements, and mood

            - Reference @Video1 to indicate how the reference video should
            influence generation
          maxLength: 2500
          type: string
        image_url:
          description: >
            URL of the start frame image for image-to-video generation with
            video reference.


            **Image requirements:**

            - Minimum: 300x300 pixels

            - Maximum: 10MB file size

            - Formats: JPG, JPEG, PNG
          type: string
        video_url:
          description: >
            **Required.** URL of the reference video to use as a creative guide
            for video-to-video generation.

            Reference in your prompt as `@Video1`.


            **Video constraints:**

            - Duration: 3-10 seconds

            - Resolution: 720-2160px (minimum 720px width or height)

            - Max file size: 200MB

            - Frame rate: 24-60 FPS

            - Formats: `.mp4` or `.mov` only
          format: uri
          type: string
        duration:
          $ref: '#/components/schemas/kling-v3-duration'
        aspect_ratio:
          $ref: '#/components/schemas/kling-v3-omni-aspect-ratio'
        cfg_scale:
          default: 0.5
          description: >
            Guidance scale for prompt adherence. Higher values mean stronger
            adherence to the prompt.


            - **0**: Maximum flexibility, more creative interpretation

            - **0.5** (default): Balanced between prompt adherence and
            creativity

            - **2**: Strict adherence to prompt, less creative variation
          format: float
          maximum: 2
          minimum: 0
          type: number
        negative_prompt:
          default: blur, distort, and low quality
          description: >-
            Undesired elements to avoid in the generated video. Maximum 2500
            characters.
          maxLength: 2500
          type: string
      required:
        - video_url
      title: Kling 3 Omni Video Reference Request
      type: object
    task-detail-200-default-response:
      description: OK - The task exists and the status is returned
    get_all_style_transfer_tasks_400_response:
      example:
        message: message
      properties:
        message:
          type: string
      type: object
    get_all_style_transfer_tasks_400_response_1:
      properties:
        problem:
          $ref: >-
            #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem
      type: object
    get_all_style_transfer_tasks_500_response:
      example:
        message: Internal Server Error
      properties:
        message:
          example: Internal Server Error
          type: string
      type: object
    get_all_style_transfer_tasks_503_response:
      example:
        message: Service Unavailable. Please try again later.
      properties:
        message:
          example: Service Unavailable. Please try again later.
          type: string
      type: object
    kling-v3-duration:
      default: '5'
      description: >
        Duration of the generated video in seconds.


        **Range:** 3-15 seconds

        **Note:** When using multi-shot mode, total duration across all shots
        cannot exceed 15 seconds.
      enum:
        - '3'
        - '4'
        - '5'
        - '6'
        - '7'
        - '8'
        - '9'
        - '10'
        - '11'
        - '12'
        - '13'
        - '14'
        - '15'
      type: string
    kling-v3-omni-aspect-ratio:
      default: '16:9'
      description: >
        Aspect ratio for Kling V3 Omni video generation:

        - `auto`: Automatically match the input image aspect ratio
        (image-to-video only)

        - `16:9`: Landscape (widescreen)

        - `9:16`: Portrait (vertical)

        - `1:1`: Square
      enum:
        - auto
        - '16:9'
        - '9:16'
        - '1:1'
      type: string
    get_all_style_transfer_tasks_400_response_1_problem:
      properties:
        message:
          example: Your request parameters didn't validate.
          type: string
        invalid_params:
          items:
            $ref: >-
              #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner
          type: array
      required:
        - invalid_params
        - message
      type: object
    get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner:
      properties:
        name:
          example: page
          type: string
        reason:
          example: Parameter 'page' must be greater than 0
          type: string
      required:
        - name
        - reason
      type: object
  securitySchemes:
    apiKey:
      description: >
        Your Freepik API key. Required for authentication. [Learn how to obtain
        an API
        key](https://docs.freepik.com/authentication#obtaining-an-api-key)
      in: header
      name: x-freepik-api-key
      type: apiKey

````
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.freepik.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Kling 3 Omni Standard - Generate video from text or image

> Generate AI video using Kling 3 Omni Standard with advanced multi-modal capabilities.

**Features:**
- **Text-to-video**: Generate videos from text prompts
- **Image-to-video**: Use start and/or end frame images to guide generation
- **Multi-shot**: Create videos with up to 6 shots (max 15s total)
- **Element control**: Include reference images for consistent character/style

**Duration:** 3-15 seconds
**Quality:** Standard mode offers faster generation at slightly lower quality.

**Note:** For video-to-video generation using a reference video, use the `/ai/reference-to-video/kling-v3-omni-std` endpoint instead.




## OpenAPI

````yaml post /v1/ai/video/kling-v3-omni-std
openapi: 3.0.0
info:
  description: >-
    The Freepik API is your gateway to a vast collection of high-quality digital
    resources for your applications and projects. As a leading platform, it
    offers a wide range of graphics, including vectors, photos, illustrations,
    icons, PSD templates, and more, all curated by talented designers from
    around the world.
  title: Freepik API
  version: 1.0.0
servers:
  - description: B2B API Production V1
    url: https://api.freepik.com
security:
  - apiKey: []
paths:
  /v1/ai/video/kling-v3-omni-std:
    post:
      tags:
        - video
        - kling-v3-omni-std
        - background_tasks
      summary: Kling 3 Omni Standard - Generate video from text or image
      description: >
        Generate AI video using Kling 3 Omni Standard with advanced multi-modal
        capabilities.


        **Features:**

        - **Text-to-video**: Generate videos from text prompts

        - **Image-to-video**: Use start and/or end frame images to guide
        generation

        - **Multi-shot**: Create videos with up to 6 shots (max 15s total)

        - **Element control**: Include reference images for consistent
        character/style


        **Duration:** 3-15 seconds

        **Quality:** Standard mode offers faster generation at slightly lower
        quality.


        **Note:** For video-to-video generation using a reference video, use the
        `/ai/reference-to-video/kling-v3-omni-std` endpoint instead.
      operationId: postAiVideoKlingV3OmniStd
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/kling-v3-omni-request'
        required: true
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/task-detail-200-default-response'
          description: OK - Task created successfully
        '400':
          content:
            application/json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Parameter 'page' must be greater than 0
                invalid_query:
                  summary: Parameter 'query' is not valid
                  value:
                    message: Parameter 'query' must not be empty
                invalid_filter:
                  summary: Parameter 'filter' is not valid
                  value:
                    message: Parameter 'filter' is not valid
                generic_bad_request:
                  summary: Bad Request
                  value:
                    message: Parameter ':attribute' is not valid
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
            application/problem+json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Your request parameters didn't validate.
                    invalid_params:
                      - name: page
                        reason: Parameter 'page' must be greater than 0
                      - name: per_page
                        reason: Parameter 'per_page' must be greater than 0
              schema:
                $ref: >-
                  #/components/schemas/get_all_style_transfer_tasks_400_response_1
          description: >-
            Bad Request - The server could not understand the request due to
            invalid syntax.
        '401':
          content:
            application/json:
              examples:
                invalid_api_key:
                  summary: API key is not valid
                  value:
                    message: Invalid API key
                missing_api_key:
                  summary: API key is not provided
                  value:
                    message: Missing API key
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
          description: >-
            Unauthorized - The client must authenticate itself to get the
            requested response.
        '500':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_500_response'
          description: >-
            Internal Server Error - The server has encountered a situation it
            doesn't know how to handle.
        '503':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_503_response'
          description: Service Unavailable
      security:
        - apiKey: []
components:
  schemas:
    kling-v3-omni-request:
      properties:
        webhook_url:
          description: >
            Optional callback URL that receives asynchronous notifications when
            the task changes status.

            The payload includes the task status and result URL when completed.
          format: uri
          type: string
        prompt:
          description: >
            Text prompt describing the desired video content. Maximum 2500
            characters.


            **Usage by mode:**

            - **Text-to-video:** Required unless multi_prompt is provided

            - **Image-to-video:** Either prompt or multi_prompt must be
            provided, but not both
          maxLength: 2500
          type: string
        multi_prompt:
          description: >
            List of prompts for multi-shot video generation. Each item is a
            string prompt for that shot.

            Use with shot_type to control multi-shot behavior.
          items:
            type: string
          maxItems: 6
          type: array
        shot_type:
          default: customize
          description: >-
            The type of multi-shot video generation. Currently only 'customize'
            is supported for Omni.
          enum:
            - customize
          type: string
        image_url:
          description: |
            URL of the start frame image for image-to-video generation.
            Required for image-to-video mode.

            **Image requirements:**
            - Minimum: 300x300 pixels
            - Maximum: 10MB file size
            - Formats: JPG, JPEG, PNG
          type: string
        start_image_url:
          description: >
            Image to use as the first frame of the video.

            Use together with end_image_url to control both start and end frames
            in image-to-video mode.
          type: string
        end_image_url:
          description: |
            Image to use as the last frame of the video.
            Optional for image-to-video mode to guide the final frame.
          type: string
        image_urls:
          description: |
            Reference images for style/appearance guidance.
            Reference in your prompt as @Image1, @Image2, etc.
            Maximum 4 total (elements + reference images).
          items:
            type: string
          type: array
        elements:
          description: >
            Elements (characters/objects) to include for consistent identity
            across the video.

            Reference in your prompt as @Element1, @Element2, etc.
          items:
            $ref: '#/components/schemas/kling-v3-omni-element'
          type: array
        generate_audio:
          description: Whether to generate native audio for the video.
          type: boolean
        voice_ids:
          description: >
            Optional Voice IDs for video generation.

            Reference voices in your prompt with <<<voice_1>>> and
            <<<voice_2>>>.

            Maximum 2 voices per task.
          items:
            type: string
          type: array
        aspect_ratio:
          $ref: '#/components/schemas/kling-v3-omni-aspect-ratio'
        duration:
          $ref: '#/components/schemas/kling-v3-duration'
      type: object
    task-detail-200-default-response:
      description: OK - The task exists and the status is returned
    get_all_style_transfer_tasks_400_response:
      example:
        message: message
      properties:
        message:
          type: string
      type: object
    get_all_style_transfer_tasks_400_response_1:
      properties:
        problem:
          $ref: >-
            #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem
      type: object
    get_all_style_transfer_tasks_500_response:
      example:
        message: Internal Server Error
      properties:
        message:
          example: Internal Server Error
          type: string
      type: object
    get_all_style_transfer_tasks_503_response:
      example:
        message: Service Unavailable. Please try again later.
      properties:
        message:
          example: Service Unavailable. Please try again later.
          type: string
      type: object
    kling-v3-omni-element:
      description: Element definition for Kling V3 Omni with reference images.
      properties:
        reference_image_urls:
          description: >-
            Array of reference image URLs for this element. Multiple angles
            improve consistency.
          items:
            type: string
          type: array
        frontal_image_url:
          description: >-
            URL of a frontal/primary reference image for this element. Best
            results with clear face/front view.
          type: string
      type: object
    kling-v3-omni-aspect-ratio:
      default: '16:9'
      description: >
        Aspect ratio for Kling V3 Omni video generation:

        - `auto`: Automatically match the input image aspect ratio
        (image-to-video only)

        - `16:9`: Landscape (widescreen)

        - `9:16`: Portrait (vertical)

        - `1:1`: Square
      enum:
        - auto
        - '16:9'
        - '9:16'
        - '1:1'
      type: string
    kling-v3-duration:
      default: '5'
      description: >
        Duration of the generated video in seconds.


        **Range:** 3-15 seconds

        **Note:** When using multi-shot mode, total duration across all shots
        cannot exceed 15 seconds.
      enum:
        - '3'
        - '4'
        - '5'
        - '6'
        - '7'
        - '8'
        - '9'
        - '10'
        - '11'
        - '12'
        - '13'
        - '14'
        - '15'
      type: string
    get_all_style_transfer_tasks_400_response_1_problem:
      properties:
        message:
          example: Your request parameters didn't validate.
          type: string
        invalid_params:
          items:
            $ref: >-
              #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner
          type: array
      required:
        - invalid_params
        - message
      type: object
    get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner:
      properties:
        name:
          example: page
          type: string
        reason:
          example: Parameter 'page' must be greater than 0
          type: string
      required:
        - name
        - reason
      type: object
  securitySchemes:
    apiKey:
      description: >
        Your Freepik API key. Required for authentication. [Learn how to obtain
        an API
        key](https://docs.freepik.com/authentication#obtaining-an-api-key)
      in: header
      name: x-freepik-api-key
      type: apiKey

````
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.freepik.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Kling 3 Omni Standard - Video-to-video generation

> Generate AI video using Kling 3 Omni Standard with a reference video for motion and style guidance.

**Video-to-video mode:** This endpoint requires a `video_url` parameter. Reference the video in your prompt using `@Video1`.

**Features:**
- Use a reference video (3-10s) to guide motion and style
- Combine with an image for start frame control
- Faster generation at slightly lower quality

**Use case:** Create videos that follow motion patterns from a reference video while applying your creative prompt.

**Duration:** 3-15 seconds
**Quality:** Standard mode offers faster generation at slightly lower quality.

**Tip:** For text-to-video or image-to-video without a reference video, use the `/ai/video/kling-v3-omni-std` endpoint instead.




## OpenAPI

````yaml post /v1/ai/reference-to-video/kling-v3-omni-std
openapi: 3.0.0
info:
  description: >-
    The Freepik API is your gateway to a vast collection of high-quality digital
    resources for your applications and projects. As a leading platform, it
    offers a wide range of graphics, including vectors, photos, illustrations,
    icons, PSD templates, and more, all curated by talented designers from
    around the world.
  title: Freepik API
  version: 1.0.0
servers:
  - description: B2B API Production V1
    url: https://api.freepik.com
security:
  - apiKey: []
paths:
  /v1/ai/reference-to-video/kling-v3-omni-std:
    post:
      tags:
        - reference-to-video
        - kling-v3-omni-std-r2v
        - background_tasks
      summary: Kling 3 Omni Standard - Video-to-video generation
      description: >
        Generate AI video using Kling 3 Omni Standard with a reference video for
        motion and style guidance.


        **Video-to-video mode:** This endpoint requires a `video_url` parameter.
        Reference the video in your prompt using `@Video1`.


        **Features:**

        - Use a reference video (3-10s) to guide motion and style

        - Combine with an image for start frame control

        - Faster generation at slightly lower quality


        **Use case:** Create videos that follow motion patterns from a reference
        video while applying your creative prompt.


        **Duration:** 3-15 seconds

        **Quality:** Standard mode offers faster generation at slightly lower
        quality.


        **Tip:** For text-to-video or image-to-video without a reference video,
        use the `/ai/video/kling-v3-omni-std` endpoint instead.
      operationId: postAiReferenceToVideoKlingV3OmniStd
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/kling-v3-omni-video-reference-request'
        required: true
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/task-detail-200-default-response'
          description: OK - Task created successfully
        '400':
          content:
            application/json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Parameter 'page' must be greater than 0
                invalid_query:
                  summary: Parameter 'query' is not valid
                  value:
                    message: Parameter 'query' must not be empty
                invalid_filter:
                  summary: Parameter 'filter' is not valid
                  value:
                    message: Parameter 'filter' is not valid
                generic_bad_request:
                  summary: Bad Request
                  value:
                    message: Parameter ':attribute' is not valid
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
            application/problem+json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Your request parameters didn't validate.
                    invalid_params:
                      - name: page
                        reason: Parameter 'page' must be greater than 0
                      - name: per_page
                        reason: Parameter 'per_page' must be greater than 0
              schema:
                $ref: >-
                  #/components/schemas/get_all_style_transfer_tasks_400_response_1
          description: >-
            Bad Request - The server could not understand the request due to
            invalid syntax.
        '401':
          content:
            application/json:
              examples:
                invalid_api_key:
                  summary: API key is not valid
                  value:
                    message: Invalid API key
                missing_api_key:
                  summary: API key is not provided
                  value:
                    message: Missing API key
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
          description: >-
            Unauthorized - The client must authenticate itself to get the
            requested response.
        '500':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_500_response'
          description: >-
            Internal Server Error - The server has encountered a situation it
            doesn't know how to handle.
        '503':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_503_response'
          description: Service Unavailable
      security:
        - apiKey: []
components:
  schemas:
    kling-v3-omni-video-reference-request:
      description: >
        Generate video using Kling 3 Omni with a reference video for
        motion/style guidance.


        **Required:** The `video_url` parameter is required for this endpoint.
        Reference the video in your prompt using `@Video1`.


        **Best for:**

        - Transferring motion patterns from reference videos

        - Maintaining visual consistency with reference material

        - Creating videos that follow a specific style or movement pattern
      properties:
        webhook_url:
          description: >
            Optional callback URL that receives asynchronous notifications when
            the task changes status.

            The payload includes the task status and result URL when completed.
          format: uri
          type: string
        prompt:
          description: >
            Text prompt describing the desired video content. Maximum 2500
            characters.

            Reference the video in your prompt as @Video1.


            **Tips for better results:**

            - Be specific about actions, camera movements, and mood

            - Reference @Video1 to indicate how the reference video should
            influence generation
          maxLength: 2500
          type: string
        image_url:
          description: >
            URL of the start frame image for image-to-video generation with
            video reference.


            **Image requirements:**

            - Minimum: 300x300 pixels

            - Maximum: 10MB file size

            - Formats: JPG, JPEG, PNG
          type: string
        video_url:
          description: >
            **Required.** URL of the reference video to use as a creative guide
            for video-to-video generation.

            Reference in your prompt as `@Video1`.


            **Video constraints:**

            - Duration: 3-10 seconds

            - Resolution: 720-2160px (minimum 720px width or height)

            - Max file size: 200MB

            - Frame rate: 24-60 FPS

            - Formats: `.mp4` or `.mov` only
          format: uri
          type: string
        duration:
          $ref: '#/components/schemas/kling-v3-duration'
        aspect_ratio:
          $ref: '#/components/schemas/kling-v3-omni-aspect-ratio'
        cfg_scale:
          default: 0.5
          description: >
            Guidance scale for prompt adherence. Higher values mean stronger
            adherence to the prompt.


            - **0**: Maximum flexibility, more creative interpretation

            - **0.5** (default): Balanced between prompt adherence and
            creativity

            - **2**: Strict adherence to prompt, less creative variation
          format: float
          maximum: 2
          minimum: 0
          type: number
        negative_prompt:
          default: blur, distort, and low quality
          description: >-
            Undesired elements to avoid in the generated video. Maximum 2500
            characters.
          maxLength: 2500
          type: string
      required:
        - video_url
      title: Kling 3 Omni Video Reference Request
      type: object
    task-detail-200-default-response:
      description: OK - The task exists and the status is returned
    get_all_style_transfer_tasks_400_response:
      example:
        message: message
      properties:
        message:
          type: string
      type: object
    get_all_style_transfer_tasks_400_response_1:
      properties:
        problem:
          $ref: >-
            #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem
      type: object
    get_all_style_transfer_tasks_500_response:
      example:
        message: Internal Server Error
      properties:
        message:
          example: Internal Server Error
          type: string
      type: object
    get_all_style_transfer_tasks_503_response:
      example:
        message: Service Unavailable. Please try again later.
      properties:
        message:
          example: Service Unavailable. Please try again later.
          type: string
      type: object
    kling-v3-duration:
      default: '5'
      description: >
        Duration of the generated video in seconds.


        **Range:** 3-15 seconds

        **Note:** When using multi-shot mode, total duration across all shots
        cannot exceed 15 seconds.
      enum:
        - '3'
        - '4'
        - '5'
        - '6'
        - '7'
        - '8'
        - '9'
        - '10'
        - '11'
        - '12'
        - '13'
        - '14'
        - '15'
      type: string
    kling-v3-omni-aspect-ratio:
      default: '16:9'
      description: >
        Aspect ratio for Kling V3 Omni video generation:

        - `auto`: Automatically match the input image aspect ratio
        (image-to-video only)

        - `16:9`: Landscape (widescreen)

        - `9:16`: Portrait (vertical)

        - `1:1`: Square
      enum:
        - auto
        - '16:9'
        - '9:16'
        - '1:1'
      type: string
    get_all_style_transfer_tasks_400_response_1_problem:
      properties:
        message:
          example: Your request parameters didn't validate.
          type: string
        invalid_params:
          items:
            $ref: >-
              #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner
          type: array
      required:
        - invalid_params
        - message
      type: object
    get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner:
      properties:
        name:
          example: page
          type: string
        reason:
          example: Parameter 'page' must be greater than 0
          type: string
      required:
        - name
        - reason
      type: object
  securitySchemes:
    apiKey:
      description: >
        Your Freepik API key. Required for authentication. [Learn how to obtain
        an API
        key](https://docs.freepik.com/authentication#obtaining-an-api-key)
      in: header
      name: x-freepik-api-key
      type: apiKey

````
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.freepik.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Kling 3 Omni - List tasks

> Retrieve the list of all Kling 3 Omni video generation tasks for the authenticated user.



## OpenAPI

````yaml get /v1/ai/video/kling-v3-omni
openapi: 3.0.0
info:
  description: >-
    The Freepik API is your gateway to a vast collection of high-quality digital
    resources for your applications and projects. As a leading platform, it
    offers a wide range of graphics, including vectors, photos, illustrations,
    icons, PSD templates, and more, all curated by talented designers from
    around the world.
  title: Freepik API
  version: 1.0.0
servers:
  - description: B2B API Production V1
    url: https://api.freepik.com
security:
  - apiKey: []
paths:
  /v1/ai/video/kling-v3-omni:
    get:
      tags:
        - video
        - kling-v3-omni
      summary: Kling 3 Omni - List tasks
      description: >-
        Retrieve the list of all Kling 3 Omni video generation tasks for the
        authenticated user.
      operationId: getAiVideoKlingV3OmniTasks
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_200_response'
          description: OK - The list of Kling 3 Omni tasks is returned
        '400':
          content:
            application/json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Parameter 'page' must be greater than 0
                invalid_query:
                  summary: Parameter 'query' is not valid
                  value:
                    message: Parameter 'query' must not be empty
                invalid_filter:
                  summary: Parameter 'filter' is not valid
                  value:
                    message: Parameter 'filter' is not valid
                generic_bad_request:
                  summary: Bad Request
                  value:
                    message: Parameter ':attribute' is not valid
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
            application/problem+json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Your request parameters didn't validate.
                    invalid_params:
                      - name: page
                        reason: Parameter 'page' must be greater than 0
                      - name: per_page
                        reason: Parameter 'per_page' must be greater than 0
              schema:
                $ref: >-
                  #/components/schemas/get_all_style_transfer_tasks_400_response_1
          description: >-
            Bad Request - The server could not understand the request due to
            invalid syntax.
        '401':
          content:
            application/json:
              examples:
                invalid_api_key:
                  summary: API key is not valid
                  value:
                    message: Invalid API key
                missing_api_key:
                  summary: API key is not provided
                  value:
                    message: Missing API key
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
          description: >-
            Unauthorized - The client must authenticate itself to get the
            requested response.
        '500':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_500_response'
          description: >-
            Internal Server Error - The server has encountered a situation it
            doesn't know how to handle.
        '503':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_503_response'
          description: Service Unavailable
components:
  schemas:
    get_all_style_transfer_tasks_200_response:
      example:
        data:
          - task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
            status: CREATED
          - task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
            status: CREATED
      properties:
        data:
          items:
            $ref: '#/components/schemas/task'
          type: array
      required:
        - data
      type: object
    get_all_style_transfer_tasks_400_response:
      example:
        message: message
      properties:
        message:
          type: string
      type: object
    get_all_style_transfer_tasks_400_response_1:
      properties:
        problem:
          $ref: >-
            #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem
      type: object
    get_all_style_transfer_tasks_500_response:
      example:
        message: Internal Server Error
      properties:
        message:
          example: Internal Server Error
          type: string
      type: object
    get_all_style_transfer_tasks_503_response:
      example:
        message: Service Unavailable. Please try again later.
      properties:
        message:
          example: Service Unavailable. Please try again later.
          type: string
      type: object
    task:
      example:
        task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
        status: CREATED
      properties:
        task_id:
          description: Task identifier
          format: uuid
          type: string
        status:
          description: Task status
          enum:
            - CREATED
            - IN_PROGRESS
            - COMPLETED
            - FAILED
          type: string
      required:
        - status
        - task_id
      type: object
    get_all_style_transfer_tasks_400_response_1_problem:
      properties:
        message:
          example: Your request parameters didn't validate.
          type: string
        invalid_params:
          items:
            $ref: >-
              #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner
          type: array
      required:
        - invalid_params
        - message
      type: object
    get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner:
      properties:
        name:
          example: page
          type: string
        reason:
          example: Parameter 'page' must be greater than 0
          type: string
      required:
        - name
        - reason
      type: object
  securitySchemes:
    apiKey:
      description: >
        Your Freepik API key. Required for authentication. [Learn how to obtain
        an API
        key](https://docs.freepik.com/authentication#obtaining-an-api-key)
      in: header
      name: x-freepik-api-key
      type: apiKey

````
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.freepik.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Kling 3 Omni - Get task status

> Retrieve the status and result of a specific Kling 3 Omni video generation task by its task ID.



## OpenAPI

````yaml get /v1/ai/video/kling-v3-omni/{task-id}
openapi: 3.0.0
info:
  description: >-
    The Freepik API is your gateway to a vast collection of high-quality digital
    resources for your applications and projects. As a leading platform, it
    offers a wide range of graphics, including vectors, photos, illustrations,
    icons, PSD templates, and more, all curated by talented designers from
    around the world.
  title: Freepik API
  version: 1.0.0
servers:
  - description: B2B API Production V1
    url: https://api.freepik.com
security:
  - apiKey: []
paths:
  /v1/ai/video/kling-v3-omni/{task-id}:
    get:
      tags:
        - video
        - kling-v3-omni
      summary: Kling 3 Omni - Get task status
      description: >-
        Retrieve the status and result of a specific Kling 3 Omni video
        generation task by its task ID.
      operationId: getAiVideoKlingV3OmniTask
      parameters:
        - description: ID of the task
          in: path
          name: task-id
          required: true
          schema:
            type: string
      responses:
        '200':
          content:
            application/json:
              examples:
                success - completed task:
                  $ref: '#/components/examples/200-task-completed'
                success - in progress task:
                  $ref: '#/components/examples/200-task-in-progress'
              schema:
                $ref: >-
                  #/components/schemas/get_style_transfer_task_status_200_response
          description: OK - The task exists and the status is returned
        '400':
          content:
            application/json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Parameter 'page' must be greater than 0
                invalid_query:
                  summary: Parameter 'query' is not valid
                  value:
                    message: Parameter 'query' must not be empty
                invalid_filter:
                  summary: Parameter 'filter' is not valid
                  value:
                    message: Parameter 'filter' is not valid
                generic_bad_request:
                  summary: Bad Request
                  value:
                    message: Parameter ':attribute' is not valid
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
            application/problem+json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Your request parameters didn't validate.
                    invalid_params:
                      - name: page
                        reason: Parameter 'page' must be greater than 0
                      - name: per_page
                        reason: Parameter 'per_page' must be greater than 0
              schema:
                $ref: >-
                  #/components/schemas/get_all_style_transfer_tasks_400_response_1
          description: >-
            Bad Request - The server could not understand the request due to
            invalid syntax.
        '401':
          content:
            application/json:
              examples:
                invalid_api_key:
                  summary: API key is not valid
                  value:
                    message: Invalid API key
                missing_api_key:
                  summary: API key is not provided
                  value:
                    message: Missing API key
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
          description: >-
            Unauthorized - The client must authenticate itself to get the
            requested response.
        '500':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_500_response'
          description: >-
            Internal Server Error - The server has encountered a situation it
            doesn't know how to handle.
        '503':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_503_response'
          description: Service Unavailable
components:
  examples:
    200-task-completed:
      summary: Success - Task completed
      value:
        data:
          generated:
            - https://ai-statics.freepik.com/completed_task_image.jpg
          task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
          status: COMPLETED
    200-task-in-progress:
      summary: Success - Task in progress
      value:
        data:
          generated: []
          task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
          status: IN_PROGRESS
  schemas:
    get_style_transfer_task_status_200_response:
      example:
        data:
          generated:
            - https://openapi-generator.tech
            - https://openapi-generator.tech
          task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
          status: CREATED
      properties:
        data:
          $ref: '#/components/schemas/task-detail'
      required:
        - data
      type: object
    get_all_style_transfer_tasks_400_response:
      example:
        message: message
      properties:
        message:
          type: string
      type: object
    get_all_style_transfer_tasks_400_response_1:
      properties:
        problem:
          $ref: >-
            #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem
      type: object
    get_all_style_transfer_tasks_500_response:
      example:
        message: Internal Server Error
      properties:
        message:
          example: Internal Server Error
          type: string
      type: object
    get_all_style_transfer_tasks_503_response:
      example:
        message: Service Unavailable. Please try again later.
      properties:
        message:
          example: Service Unavailable. Please try again later.
          type: string
      type: object
    task-detail:
      allOf:
        - $ref: '#/components/schemas/task'
        - properties:
            generated:
              items:
                description: URL of the generated image
                format: uri
                type: string
              type: array
          required:
            - generated
          type: object
      example:
        generated:
          - https://openapi-generator.tech
          - https://openapi-generator.tech
        task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
        status: CREATED
    get_all_style_transfer_tasks_400_response_1_problem:
      properties:
        message:
          example: Your request parameters didn't validate.
          type: string
        invalid_params:
          items:
            $ref: >-
              #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner
          type: array
      required:
        - invalid_params
        - message
      type: object
    task:
      example:
        task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
        status: CREATED
      properties:
        task_id:
          description: Task identifier
          format: uuid
          type: string
        status:
          description: Task status
          enum:
            - CREATED
            - IN_PROGRESS
            - COMPLETED
            - FAILED
          type: string
      required:
        - status
        - task_id
      type: object
    get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner:
      properties:
        name:
          example: page
          type: string
        reason:
          example: Parameter 'page' must be greater than 0
          type: string
      required:
        - name
        - reason
      type: object
  securitySchemes:
    apiKey:
      description: >
        Your Freepik API key. Required for authentication. [Learn how to obtain
        an API
        key](https://docs.freepik.com/authentication#obtaining-an-api-key)
      in: header
      name: x-freepik-api-key
      type: apiKey

````
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.freepik.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Kling 3 Omni Reference-to-Video - List tasks

> Retrieve the list of all Kling 3 Omni reference-to-video tasks (both Pro and Standard) for the authenticated user.



## OpenAPI

````yaml get /v1/ai/reference-to-video/kling-v3-omni
openapi: 3.0.0
info:
  description: >-
    The Freepik API is your gateway to a vast collection of high-quality digital
    resources for your applications and projects. As a leading platform, it
    offers a wide range of graphics, including vectors, photos, illustrations,
    icons, PSD templates, and more, all curated by talented designers from
    around the world.
  title: Freepik API
  version: 1.0.0
servers:
  - description: B2B API Production V1
    url: https://api.freepik.com
security:
  - apiKey: []
paths:
  /v1/ai/reference-to-video/kling-v3-omni:
    get:
      tags:
        - reference-to-video
        - kling-v3-omni-r2v
      summary: Kling 3 Omni Reference-to-Video - List tasks
      description: >-
        Retrieve the list of all Kling 3 Omni reference-to-video tasks (both Pro
        and Standard) for the authenticated user.
      operationId: getAiReferenceToVideoKlingV3OmniTasks
      parameters:
        - description: Page number for pagination (1-indexed)
          in: query
          name: page
          schema:
            default: 1
            minimum: 1
            type: integer
        - description: Number of items per page
          in: query
          name: page_size
          schema:
            default: 20
            maximum: 100
            minimum: 1
            type: integer
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_200_response'
          description: OK - The list of Kling 3 Omni reference-to-video tasks is returned
        '400':
          content:
            application/json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Parameter 'page' must be greater than 0
                invalid_query:
                  summary: Parameter 'query' is not valid
                  value:
                    message: Parameter 'query' must not be empty
                invalid_filter:
                  summary: Parameter 'filter' is not valid
                  value:
                    message: Parameter 'filter' is not valid
                generic_bad_request:
                  summary: Bad Request
                  value:
                    message: Parameter ':attribute' is not valid
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
            application/problem+json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Your request parameters didn't validate.
                    invalid_params:
                      - name: page
                        reason: Parameter 'page' must be greater than 0
                      - name: per_page
                        reason: Parameter 'per_page' must be greater than 0
              schema:
                $ref: >-
                  #/components/schemas/get_all_style_transfer_tasks_400_response_1
          description: >-
            Bad Request - The server could not understand the request due to
            invalid syntax.
        '401':
          content:
            application/json:
              examples:
                invalid_api_key:
                  summary: API key is not valid
                  value:
                    message: Invalid API key
                missing_api_key:
                  summary: API key is not provided
                  value:
                    message: Missing API key
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
          description: >-
            Unauthorized - The client must authenticate itself to get the
            requested response.
        '500':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_500_response'
          description: >-
            Internal Server Error - The server has encountered a situation it
            doesn't know how to handle.
        '503':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_503_response'
          description: Service Unavailable
      security:
        - apiKey: []
components:
  schemas:
    get_all_style_transfer_tasks_200_response:
      example:
        data:
          - task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
            status: CREATED
          - task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
            status: CREATED
      properties:
        data:
          items:
            $ref: '#/components/schemas/task'
          type: array
      required:
        - data
      type: object
    get_all_style_transfer_tasks_400_response:
      example:
        message: message
      properties:
        message:
          type: string
      type: object
    get_all_style_transfer_tasks_400_response_1:
      properties:
        problem:
          $ref: >-
            #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem
      type: object
    get_all_style_transfer_tasks_500_response:
      example:
        message: Internal Server Error
      properties:
        message:
          example: Internal Server Error
          type: string
      type: object
    get_all_style_transfer_tasks_503_response:
      example:
        message: Service Unavailable. Please try again later.
      properties:
        message:
          example: Service Unavailable. Please try again later.
          type: string
      type: object
    task:
      example:
        task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
        status: CREATED
      properties:
        task_id:
          description: Task identifier
          format: uuid
          type: string
        status:
          description: Task status
          enum:
            - CREATED
            - IN_PROGRESS
            - COMPLETED
            - FAILED
          type: string
      required:
        - status
        - task_id
      type: object
    get_all_style_transfer_tasks_400_response_1_problem:
      properties:
        message:
          example: Your request parameters didn't validate.
          type: string
        invalid_params:
          items:
            $ref: >-
              #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner
          type: array
      required:
        - invalid_params
        - message
      type: object
    get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner:
      properties:
        name:
          example: page
          type: string
        reason:
          example: Parameter 'page' must be greater than 0
          type: string
      required:
        - name
        - reason
      type: object
  securitySchemes:
    apiKey:
      description: >
        Your Freepik API key. Required for authentication. [Learn how to obtain
        an API
        key](https://docs.freepik.com/authentication#obtaining-an-api-key)
      in: header
      name: x-freepik-api-key
      type: apiKey

````
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.freepik.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Kling 3 Omni Reference-to-Video - Get task status

> Retrieve the status and result of a specific Kling 3 Omni reference-to-video task (Pro or Standard) by its task ID.



## OpenAPI

````yaml get /v1/ai/reference-to-video/kling-v3-omni/{task-id}
openapi: 3.0.0
info:
  description: >-
    The Freepik API is your gateway to a vast collection of high-quality digital
    resources for your applications and projects. As a leading platform, it
    offers a wide range of graphics, including vectors, photos, illustrations,
    icons, PSD templates, and more, all curated by talented designers from
    around the world.
  title: Freepik API
  version: 1.0.0
servers:
  - description: B2B API Production V1
    url: https://api.freepik.com
security:
  - apiKey: []
paths:
  /v1/ai/reference-to-video/kling-v3-omni/{task-id}:
    get:
      tags:
        - reference-to-video
        - kling-v3-omni-r2v
      summary: Kling 3 Omni Reference-to-Video - Get task status
      description: >-
        Retrieve the status and result of a specific Kling 3 Omni
        reference-to-video task (Pro or Standard) by its task ID.
      operationId: getAiReferenceToVideoKlingV3OmniTask
      parameters:
        - description: ID of the task
          in: path
          name: task-id
          required: true
          schema:
            type: string
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: >-
                  #/components/schemas/get_style_transfer_task_status_200_response
          description: OK - The task exists and the status is returned
        '400':
          content:
            application/json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Parameter 'page' must be greater than 0
                invalid_query:
                  summary: Parameter 'query' is not valid
                  value:
                    message: Parameter 'query' must not be empty
                invalid_filter:
                  summary: Parameter 'filter' is not valid
                  value:
                    message: Parameter 'filter' is not valid
                generic_bad_request:
                  summary: Bad Request
                  value:
                    message: Parameter ':attribute' is not valid
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
            application/problem+json:
              examples:
                invalid_page:
                  summary: Parameter 'page' is not valid
                  value:
                    message: Your request parameters didn't validate.
                    invalid_params:
                      - name: page
                        reason: Parameter 'page' must be greater than 0
                      - name: per_page
                        reason: Parameter 'per_page' must be greater than 0
              schema:
                $ref: >-
                  #/components/schemas/get_all_style_transfer_tasks_400_response_1
          description: >-
            Bad Request - The server could not understand the request due to
            invalid syntax.
        '401':
          content:
            application/json:
              examples:
                invalid_api_key:
                  summary: API key is not valid
                  value:
                    message: Invalid API key
                missing_api_key:
                  summary: API key is not provided
                  value:
                    message: Missing API key
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_400_response'
          description: >-
            Unauthorized - The client must authenticate itself to get the
            requested response.
        '500':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_500_response'
          description: >-
            Internal Server Error - The server has encountered a situation it
            doesn't know how to handle.
        '503':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/get_all_style_transfer_tasks_503_response'
          description: Service Unavailable
      security:
        - apiKey: []
components:
  schemas:
    get_style_transfer_task_status_200_response:
      example:
        data:
          generated:
            - https://openapi-generator.tech
            - https://openapi-generator.tech
          task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
          status: CREATED
      properties:
        data:
          $ref: '#/components/schemas/task-detail'
      required:
        - data
      type: object
    get_all_style_transfer_tasks_400_response:
      example:
        message: message
      properties:
        message:
          type: string
      type: object
    get_all_style_transfer_tasks_400_response_1:
      properties:
        problem:
          $ref: >-
            #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem
      type: object
    get_all_style_transfer_tasks_500_response:
      example:
        message: Internal Server Error
      properties:
        message:
          example: Internal Server Error
          type: string
      type: object
    get_all_style_transfer_tasks_503_response:
      example:
        message: Service Unavailable. Please try again later.
      properties:
        message:
          example: Service Unavailable. Please try again later.
          type: string
      type: object
    task-detail:
      allOf:
        - $ref: '#/components/schemas/task'
        - properties:
            generated:
              items:
                description: URL of the generated image
                format: uri
                type: string
              type: array
          required:
            - generated
          type: object
      example:
        generated:
          - https://openapi-generator.tech
          - https://openapi-generator.tech
        task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
        status: CREATED
    get_all_style_transfer_tasks_400_response_1_problem:
      properties:
        message:
          example: Your request parameters didn't validate.
          type: string
        invalid_params:
          items:
            $ref: >-
              #/components/schemas/get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner
          type: array
      required:
        - invalid_params
        - message
      type: object
    task:
      example:
        task_id: 046b6c7f-0b8a-43b9-b35d-6489e6daee91
        status: CREATED
      properties:
        task_id:
          description: Task identifier
          format: uuid
          type: string
        status:
          description: Task status
          enum:
            - CREATED
            - IN_PROGRESS
            - COMPLETED
            - FAILED
          type: string
      required:
        - status
        - task_id
      type: object
    get_all_style_transfer_tasks_400_response_1_problem_invalid_params_inner:
      properties:
        name:
          example: page
          type: string
        reason:
          example: Parameter 'page' must be greater than 0
          type: string
      required:
        - name
        - reason
      type: object
  securitySchemes:
    apiKey:
      description: >
        Your Freepik API key. Required for authentication. [Learn how to obtain
        an API
        key](https://docs.freepik.com/authentication#obtaining-an-api-key)
      in: header
      name: x-freepik-api-key
      type: apiKey

````