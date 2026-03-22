# WanX Task Creation with LoRA Using PiAPI

This document collects the practical payload structure for creating **WanX** tasks with **LoRA** support through **PiAPI**.

Useful references:
- WanX create task: https://piapi.ai/docs/wanx-api/create-task
- WanX LoRA types: https://piapi.ai/docs/wanx-lora-type
- WanX LoRA use cases: https://piapi.ai/docs/wanx-lora/use-case

## Basic Params

| Parameter | Type | Required | Description | JSON setting example |
|---|---|---:|---|---|
| `model` | string | Yes | Invoke WanX model | `"model": "Qubico/wanx"` |
| `task_type` | string | Yes | Task type to select when using LoRA, including `txt2video-14b-lora` and `img2video-14b-lora` | `"task_type": "txt2video-14b-lora"` |
| `prompt` | string | Yes | Video generation description | `"prompt": "A girl is sitting around the window."` |
| `image` | string | Yes for `img2video-14b-lora` | Image URL or base64; needed when using `img2video-14b-lora` | `"image": "https://i.ibb.co/wbw9GLY/girl.webp"` |
| `lora_settings` | array | Yes | Array containing LoRA invocation parameters | `"lora_settings": [{"lora_type": "ghibli", "lora_strength": 1.0}]` |
| `lora_type` | string | No | Select the LoRA type you need (e.g. `ghibli`) | `"lora_type": "ghibli"` |
| `lora_strength` | number | No | Controls the intensity of LoRA influence, range `0.0-1.0` | `"lora_strength": 1.0` |

## Request body example

Below is a typical request body for a `txt2video-14b-lora` task:

```json
{
  "model": "Qubico/wanx",
  "task_type": "txt2video-14b-lora",
  "input": {
    "prompt": "video of a young woman with long, dark hair and bangs. She is wearing a light gray t-shirt and appears to be sitting at a table.",
    "negative_prompt": "chaotic, distortion, morphing",
    "aspect_ratio": "16:9",
    "lora_settings": [
      {
        "lora_type": "ghibli",
        "lora_strength": 1.0
      }
    ]
  },
  "config": {
    "webhook_config": {
      "endpoint": "",
      "secret": ""
    }
  }
}
```

## `lora_settings` structure

The `lora_settings` field is an array of LoRA invocations. Each item controls one LoRA adapter.

| Parameter | Type | Description |
|---|---|---|
| `lora_settings` | array | Array containing LoRA configuration items |
| `lora_type` | string | LoRA type identifier, for example `ghibli` |
| `lora_strength` | number | Strength of LoRA influence, range `0.0` to `1.0` |

Example:

```json
"lora_settings": [
  {
    "lora_type": "ghibli",
    "lora_strength": 1.0
  }
]
```

## Recommended usage pattern

1. Select a supported WanX LoRA type from the official list.
2. Keep `lora_strength` in the `0.0-1.0` range.
3. Use a clear prompt and a negative prompt to reduce artifacts.
4. Set `aspect_ratio` to the final target format before sending the task.
5. Configure `webhook_config.endpoint` if you want async task completion notifications.

## NSFW-LoRA example

PiAPI also supports the `nsfw-general` LoRA type. It can be used with both:

- `txt2video-14b-lora`
- `img2video-14b-lora`

### NSFW-LoRA catalog

| lora_type | task_type | Example URL |
|---|---|---|
| `nsfw-general` | `txt2video-14b-lora`, `img2video-14b-lora` | `https://i.ibb.co/Y4nnsNVz/We-Chat047f39c5f723dc567699331aaa148451.jpg` |
| `nsfw-bouncing-boobs` | `img2video-14b-lora` | `https://i.ibb.co/vxnzfrX6/4391744989508-pic.jpg` |
| `nsfw-undress` | `txt2video-14b-lora`, `img2video-14b-lora` | `https://i.ibb.co/3mwVk4FV/We-Chataf7178d7947215887d289f4f0d55ffe5.jpg` |
| `nsfw-pov-blowjob` | `txt2video-14b-lora`, `img2video-14b-lora` | `https://i.ibb.co/nqz68G6g/4401744989684-pic.jpg` |
| `nsfw-pov-titfuck` | `txt2video-14b-lora`, `img2video-14b-lora` | `https://i.ibb.co/r2dRvvbx/We-Chatcccde5299c5c3c3294552a3c256d799b.jpg` |
| `nsfw-pov-missionary` | `txt2video-14b-lora`, `img2video-14b-lora` | `https://i.ibb.co/yFVGvcSz/We-Chatd183b54da23a35bf32c4ec8fadc50727.jpg` |
| `nsfw-pov-cowgirl` | `txt2video-14b-lora` | `https://i.ibb.co/KcCTKtxc/We-Chat042bf9d9fdefd54393a274f1c1f26746.jpg` |
| `nsfw-pov-doggy` | `img2video-14b-lora` | `https://i.ibb.co/Q30S2kVN/We-Chat8c7076e3160d2fc2392e888bcca8360b.jpg` |

Example configuration:

```json
{
  "model": "Qubico/wanx",
  "task_type": "txt2video-14b-lora",
  "input": {
    "prompt": "cinematic adult-themed scene, soft lighting, realistic motion",
    "negative_prompt": "chaotic, distortion, morphing",
    "aspect_ratio": "16:9",
    "lora_settings": [
      {
        "lora_type": "nsfw-general",
        "lora_strength": 0.8
      }
    ]
  },
  "config": {
    "webhook_config": {
      "endpoint": "https://your-domain.com/webhook/wanx",
      "secret": "your-secret"
    }
  }
}
```

Reference the official LoRA list and use-case pages for the latest examples and trigger words.

### NSFW-LoRA quick reference

- `lora_type`: `nsfw-general`
- Supported `task_type` values: `txt2video-14b-lora`, `img2video-14b-lora`

## Reference implementation

### txt2video-14b-lora

```json
{
  "model": "Qubico/wanx",
  "task_type": "txt2video-14b-lora",
  "input": {
    "prompt": "video of a young woman with long, dark hair and bangs. She is wearing a light gray t-shirt and appears to be sitting at a table.",
    "negative_prompt": "chaotic, distortion, morphing",
    "aspect_ratio": "16:9",
    "lora_settings": [
      {
        "lora_type": "ghibli",
        "lora_strength": 1.0
      }
    ]
  },
  "config": {
    "webhook_config": {
      "endpoint": "",
      "secret": ""
    }
  }
}
```

### img2video-14b-lora

```json
{
  "model": "Qubico/wanx",
  "task_type": "img2video-14b-lora",
  "input": {
    "prompt": "video of a young woman with long, dark hair and bangs. She is wearing a light gray t-shirt and appears to be sitting at a table.",
    "image": "https://i.ibb.co/wbw9GLY/girl.webp",
    "lora_settings": [
      {
        "lora_type": "inflate-effect"
      }
    ]
  },
  "config": {
    "webhook_config": {
      "endpoint": "",
      "secret": ""
    }
  }
}
```

## Example Python payload

```python
payload = {
    "model": "Qubico/wanx",
    "task_type": "txt2video-14b-lora",
    "input": {
        "prompt": "video of a young woman with long, dark hair and bangs",
        "negative_prompt": "chaotic, distortion, morphing",
        "aspect_ratio": "16:9",
        "lora_settings": [
            {
                "lora_type": "ghibli",
                "lora_strength": 1.0,
            }
        ],
    },
    "config": {
        "webhook_config": {
            "endpoint": "https://your-domain.com/webhook/wanx",
            "secret": "your-secret",
        }
    },
}
```

## Tips

- Start with `lora_strength = 0.6-1.0` and adjust based on how strongly you want the style to appear.
- Keep the prompt focused on the main subject and motion.
- If you are testing, use a webhook endpoint to capture the task result automatically.

