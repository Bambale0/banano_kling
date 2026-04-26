#!/usr/bin/env python3
"""Test script to verify seedance2 10 sec button is generated correctly"""

import sys

sys.path.insert(0, "/root/bot/banano_kling")

from bot.keyboards import get_create_video_keyboard
from bot.services.preset_manager import preset_manager

# Test 1: Check that seedance2 has duration costs configured
print("Test 1: Check seedance2 configuration in price.json")
costs = (
    preset_manager._price_config.get("costs_reference", {})
    .get("video_models", {})
    .get("seedance2", {})
)
print(f"  Seedance2 config: {costs}")
duration_costs = costs.get("duration_costs", {})
print(f"  Duration costs: {duration_costs}")
print(f"  Available durations: {sorted([int(k) for k in duration_costs.keys()])}")
print()

# Test 2: Generate keyboard for seedance2 with different durations
print("Test 2: Generate keyboard for seedance2")
for duration in [5, 10, 15]:
    keyboard = get_create_video_keyboard(
        current_v_type="imgtxt",
        current_model="seedance2",
        current_duration=duration,
        current_ratio="16:9",
    )

    # Extract button data from keyboard
    markup_dict = keyboard.model_dump()
    all_buttons = []
    for row in markup_dict.get("inline_keyboard", []):
        for btn in row:
            all_buttons.append(btn)

    # Find duration buttons
    duration_buttons = [btn for btn in all_buttons if "сек" in btn.get("text", "")]
    print(f"\n  Duration={duration} sec:")
    print(f"    Duration buttons found: {len(duration_buttons)}")
    for btn in duration_buttons:
        print(f"      Text: {btn['text']}, Callback: {btn.get('callback_data', 'N/A')}")

print("\nTest complete!")
