"""
OpenAI-compatible Image Generation with Gemini

This module provides an OpenAI-compatible interface for generating images
using Google's Gemini models via OpenRouter API.

Usage:
    Set the OPENROUTER_API_KEY environment variable, then use the generate_image function.

Example:
    export OPENROUTER_API_KEY="your-api-key-here"
    python gemini_image_generation.py

Available Models:
    - google/gemini-3.1-flash-image-preview: Fast generation with good quality
    - google/gemini-3-pro-image-preview: Higher quality, more detailed
    - google/gemini-2.5-flash-image: Legacy model, still effective

Requirements:
    pip install openai
"""

import os

from openai import OpenAI

# Get API key from environment variable
_CLIENT = None


def _get_client():
    """Lazily create OpenAI client using OPENROUTER_API_KEY.

    This avoids raising at import time so tests can import the module
    without requiring the environment variable.
    """
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return None

    _CLIENT = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
    return _CLIENT


def generate_image(
    prompt: str, model: str = "google/gemini-3.1-flash-image-preview"
) -> str:
    """
    Generate an image using OpenRouter's Gemini model.

    Args:
        prompt (str): The text prompt describing what to generate
        model (str): The model to use for generation

    Returns:
        str: Base64 encoded image URL or None if generation failed

    Raises:
        ValueError: If API key is not set
        Exception: If image generation fails
    """
    client = _get_client()
    if client is None:
        raise ValueError("Please set the OPENROUTER_API_KEY environment variable")

    try:
        # Generate an image
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            extra_body={"modalities": ["image", "text"]},
        )

        # The generated image will be in the assistant message
        message = response.choices[0].message

        if hasattr(message, "images") and message.images:
            for image in message.images:
                if "image_url" in image and "url" in image["image_url"]:
                    image_url = image["image_url"]["url"]  # Base64 data URL
                    print(f"Generated image: {image_url[:50]}...")
                    return image_url

        print("No image found in response")
        return None

    except Exception as e:
        print(f"Error generating image: {e}")
        raise


def save_image_from_url(image_url: str, filename: str = "generated_image.png"):
    """
    Save a base64 encoded image to a file.

    Args:
        image_url (str): Base64 encoded image URL
        filename (str): Output filename
    """
    import base64

    try:
        # Extract base64 data from data URL
        if image_url.startswith("data:image"):
            # Remove data:image/png;base64, prefix
            base64_data = image_url.split(",", 1)[1]
        else:
            base64_data = image_url

        # Decode and save
        image_data = base64.b64decode(base64_data)
        with open(filename, "wb") as f:
            f.write(image_data)

        print(f"Image saved to {filename}")

    except Exception as e:
        print(f"Error saving image: {e}")


if __name__ == "__main__":
    # Example usage
    try:
        prompt = "Generate a beautiful sunset over mountains"
        image_url = generate_image(prompt)

        if image_url:
            save_image_from_url(image_url, "sunset.png")
        else:
            print("Failed to generate image")

    except ValueError as e:
        print(f"Configuration error: {e}")
        print("Please set the OPENROUTER_API_KEY environment variable")
    except Exception as e:
        print(f"Unexpected error: {e}")
