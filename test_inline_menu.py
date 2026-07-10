#!/usr/bin/env python3
"""Test inline menu callbacks"""

import json
import time

import requests

# Bot webhook endpoint
WEBHOOK_URL = "https://localhost:8443/webhook"

# VK Callback API signature (for testing, optional)
VK_API_VERSION = "5.131"
GROUP_ID = 229102399  # Your group ID


def simulate_callback(
    button_payload: str, user_id: int = 381643597, event_id: str = None
):
    """Simulate a VK callback button click."""

    event_id = event_id or f"test_{int(time.time())}"

    payload_dict = {"button": button_payload}
    payload_json = json.dumps(payload_dict, separators=(",", ":"), ensure_ascii=False)

    event = {
        "group_id": GROUP_ID,
        "type": "message_new",
        "event_id": event_id,
        "v": VK_API_VERSION,
        "object": {
            "message": {
                "date": int(time.time()),
                "from_id": user_id,
                "id": 9999,
                "version": 10003320,
                "out": 0,
                "fwd_messages": [],
                "important": False,
                "is_hidden": False,
                "attachments": [],
                "conversation_message_id": 9999,
                "payload": payload_json,
                "text": f"Button: {button_payload}",
                "peer_id": user_id,
                "random_id": 0,
            },
            "client_info": {
                "button_actions": [
                    "text",
                    "vkpay",
                    "open_app",
                    "location",
                    "open_link",
                ],
                "keyboard": True,
                "inline_keyboard": True,
                "lang_id": 0,
            },
        },
    }

    print(f"\n{'='*60}")
    print(f"Testing: {button_payload}")
    print(f"Payload: {payload_json}")
    print(f"{'='*60}")

    try:
        response = requests.post(WEBHOOK_URL, json=event, verify=False, timeout=5)
        print(f"✓ Response: {response.status_code}")
        if response.text:
            print(f"  Response body: {response.text[:200]}")
    except Exception as e:
        print(f"✗ Error: {e}")


def main():
    """Test sequence"""

    # Test 1: /start
    print("\n" + "=" * 70)
    print("TEST SEQUENCE: Image Flow")
    print("=" * 70)

    simulate_callback("start", event_id="test_start")
    time.sleep(1)

    # Test 2: Create image menu
    simulate_callback("create_image_refs_new", event_id="test_create_image")
    time.sleep(1)

    # Test 3: Select Nano Banana Pro model
    simulate_callback("model_banana_pro", event_id="test_model_select")
    time.sleep(1)

    # Test 4: Select ratio
    simulate_callback("img_ratio_1_1", event_id="test_ratio_select")
    time.sleep(1)

    # Test 5: Continue to references
    simulate_callback("img_ref_continue_new", event_id="test_continue_refs")
    time.sleep(1)

    # Test 6: Skip references
    simulate_callback("img_ref_skip_new", event_id="test_skip_refs")
    time.sleep(2)

    # Test 7: Video flow
    print("\n" + "=" * 70)
    print("TEST SEQUENCE: Video Flow")
    print("=" * 70)

    simulate_callback("create_video_new", event_id="test_create_video")
    time.sleep(1)

    simulate_callback("v_type_text", event_id="test_video_type")
    time.sleep(1)

    simulate_callback("v_model_v3_std", event_id="test_video_model")
    time.sleep(1)

    print("\n" + "=" * 70)
    print("Test complete! Check logs/vk_bot.log for details.")
    print("=" * 70)


if __name__ == "__main__":
    main()
