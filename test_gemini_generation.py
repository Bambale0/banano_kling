#!/usr/bin/env python3
"""
Test script for Gemini image generation

This script tests the gemini_image_generation module to ensure it works correctly.
"""

import os
import sys
import base64
from io import BytesIO
from PIL import Image

# Add the current directory to Python path to import our module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from gemini_image_generation import generate_image, save_image_from_url
except ImportError as e:
    print(f"Error importing module: {e}")
    print("Make sure gemini_image_generation.py is in the same directory")
    sys.exit(1)


def test_api_key_check():
    """Test that the module properly checks for API key"""
    print("Testing API key validation...")
    
    # Temporarily remove API key to test error handling
    original_key = os.environ.get("OPENROUTER_API_KEY")
    if "OPENROUTER_API_KEY" in os.environ:
        del os.environ["OPENROUTER_API_KEY"]
    
    try:
        # This should raise ValueError
        import gemini_image_generation
        print("❌ API key check failed - should have raised ValueError")
        return False
    except ValueError:
        print("✅ API key check passed")
        return True
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False
    finally:
        # Restore original API key
        if original_key:
            os.environ["OPENROUTER_API_KEY"] = original_key


def test_image_generation():
    """Test actual image generation (requires valid API key)"""
    print("\nTesting image generation...")
    
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("⚠️  Skipping image generation test - no API key found")
        print("   Set OPENROUTER_API_KEY environment variable to test this")
        return True
    
    try:
        # Test with a simple prompt
        prompt = "A simple red circle on white background"
        print(f"Generating image with prompt: '{prompt}'")
        
        image_url = generate_image(prompt, model="google/gemini-3.1-flash-image-preview")
        
        if image_url:
            print("✅ Image generation successful")
            
            # Test saving the image
            save_image_from_url(image_url, "test_output.png")
            
            # Verify the file was created and is valid
            if os.path.exists("test_output.png"):
                try:
                    with Image.open("test_output.png") as img:
                        print(f"✅ Generated image is valid: {img.size}, {img.format}")
                        return True
                except Exception as e:
                    print(f"❌ Generated file is not a valid image: {e}")
                    return False
            else:
                print("❌ Image file was not created")
                return False
        else:
            print("❌ Image generation returned None")
            return False
            
    except Exception as e:
        print(f"❌ Image generation failed: {e}")
        return False


def test_different_models():
    """Test different Gemini models"""
    print("\nTesting different models...")
    
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("⚠️  Skipping model test - no API key found")
        return True
    
    models = [
        "google/gemini-3.1-flash-image-preview",
        "google/gemini-3-pro-image-preview", 
        "google/gemini-2.5-flash-image"
    ]
    
    for model in models:
        try:
            print(f"Testing model: {model}")
            image_url = generate_image("A blue square", model=model)
            if image_url:
                print(f"✅ {model} works")
            else:
                print(f"❌ {model} returned None")
        except Exception as e:
            print(f"❌ {model} failed: {e}")
    
    return True


def main():
    """Run all tests"""
    print("=== Gemini Image Generation Test Suite ===\n")
    
    tests = [
        test_api_key_check,
        test_image_generation,
        test_different_models
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"❌ Test {test.__name__} crashed: {e}")
            results.append(False)
    
    print(f"\n=== Test Results ===")
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("🎉 All tests passed!")
        return 0
    else:
        print("❌ Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())