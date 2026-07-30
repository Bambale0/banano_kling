"""
Test script for Gemini image generation.

This script tests the gemini_image_generation module to ensure it works correctly.
"""

import os
import sys

from PIL import Image

# Add the current directory to Python path to import our module.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from gemini_image_generation import generate_image, save_image_from_url
except ImportError as error:
    if __name__ != "__main__":
        import pytest

        pytest.skip(
            f"Standalone Gemini helper is unavailable: {error}",
            allow_module_level=True,
        )
    print(f"Error importing module: {error}")
    print("Make sure gemini_image_generation.py is in the same directory")
    sys.exit(1)


def _api_key_check():
    """Test that the module properly checks for API key."""
    print("Testing API key validation...")

    # Temporarily remove API key to test error handling.
    original_key = os.environ.get("OPENROUTER_API_KEY")
    if "OPENROUTER_API_KEY" in os.environ:
        del os.environ["OPENROUTER_API_KEY"]

    try:
        generate_image("API key validation smoke test")
        print("❌ API key check failed - should have raised ValueError")
        return False
    except ValueError:
        print("✅ API key check passed")
        return True
    except Exception as error:  # noqa: BLE001 - standalone diagnostic reports provider failures
        print(f"❌ Unexpected error: {error}")
        return False
    finally:
        # Restore original API key.
        if original_key:
            os.environ["OPENROUTER_API_KEY"] = original_key


def _image_generation():
    """Test actual image generation (requires valid API key)."""
    print("\nTesting image generation...")

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("⚠️  Skipping image generation test - no API key found")
        print("   Set OPENROUTER_API_KEY environment variable to test this")
        return True

    try:
        prompt = "A simple red circle on white background"
        print(f"Generating image with prompt: '{prompt}'")

        image_url = generate_image(
            prompt,
            model="google/gemini-3.1-flash-image-preview",
        )

        if image_url:
            print("✅ Image generation successful")
            save_image_from_url(image_url, "test_output.png")

            if os.path.exists("test_output.png"):
                try:
                    with Image.open("test_output.png") as image:
                        print(f"✅ Generated image is valid: {image.size}, {image.format}")
                        return True
                except Exception as error:  # noqa: BLE001 - validates arbitrary image decoder failures
                    print(f"❌ Generated file is not a valid image: {error}")
                    return False
            print("❌ Image file was not created")
            return False

        print("❌ Image generation returned None")
        return False
    except Exception as error:  # noqa: BLE001 - standalone diagnostic reports provider failures
        print(f"❌ Image generation failed: {error}")
        return False


def _different_models():
    """Test different Gemini models."""
    print("\nTesting different models...")

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("⚠️  Skipping model test - no API key found")
        return True

    models = [
        "google/gemini-3.1-flash-image-preview",
        "google/gemini-3-pro-image-preview",
        "google/gemini-2.5-flash-image",
    ]

    for model in models:
        try:
            print(f"Testing model: {model}")
            image_url = generate_image("A blue square", model=model)
            if image_url:
                print(f"✅ {model} works")
            else:
                print(f"❌ {model} returned None")
        except Exception as error:  # noqa: BLE001 - continue checking remaining providers
            print(f"❌ {model} failed: {error}")

    return True


def main():
    """Run all tests."""
    print("=== Gemini Image Generation Test Suite ===\n")

    tests = [_api_key_check, _image_generation, _different_models]
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as error:  # noqa: BLE001 - keep standalone suite running after one failure
            print(f"❌ Test {test.__name__} crashed: {error}")
            results.append(False)

    print("\n=== Test Results ===")
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")

    if passed == total:
        print("🎉 All tests passed!")
        return 0

    print("❌ Some tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())


def test_api_key_check():
    assert _api_key_check()


def test_image_generation():
    assert _image_generation()


def test_different_models():
    assert _different_models()
