#!/usr/bin/env python3
"""
Demo script showing how to use the Gemini image generation module.

This script demonstrates the basic usage without requiring a real API key.
"""

import os
import sys

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def demo_without_api_key():
    """Demonstrate the module structure and error handling"""
    print("=== Gemini Image Generation Demo ===\n")

    print("1. Testing module import without API key...")
    try:
        import gemini_image_generation

        print("❌ This should have failed - no API key set")
    except ValueError as e:
        print(f"✅ Correctly caught API key error: {e}")

    print("\n2. Testing module import with fake API key...")
    os.environ["OPENROUTER_API_KEY"] = "fake_key"
    try:
        import gemini_image_generation

        print("✅ Module imported successfully with fake API key")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

    print("\n3. Testing function import...")
    try:
        from gemini_image_generation import generate_image, save_image_from_url

        print("✅ Functions imported successfully")
        print(f"   - generate_image: {generate_image.__name__}")
        print(f"   - save_image_from_url: {save_image_from_url.__name__}")
    except Exception as e:
        print(f"❌ Function import failed: {e}")

    print("\n4. Testing function call (will fail with 401)...")
    try:
        image_url = generate_image("A simple test image")
        print(
            f"✅ Generated image URL: {image_url[:50]}..."
            if image_url
            else "❌ No image generated"
        )
    except Exception as e:
        print(f"✅ Expected API error caught: {type(e).__name__}: {e}")

    print("\n=== Demo Complete ===")
    print("\nTo use this module with real image generation:")
    print("1. Get an API key from https://openrouter.ai/")
    print("2. Set: export OPENROUTER_API_KEY='your-key-here'")
    print("3. Run: python3 gemini_image_generation.py")


if __name__ == "__main__":
    demo_without_api_key()
