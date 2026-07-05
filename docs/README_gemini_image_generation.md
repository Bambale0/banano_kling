# Gemini Image Generation with OpenAI Compatibility

This project provides an OpenAI-compatible interface for generating images using Google's Gemini models via the OpenRouter API.

## Features

- ✅ OpenAI-compatible API interface
- ✅ Support for multiple Gemini models
- ✅ Base64 image output
- ✅ Error handling and validation
- ✅ Image saving functionality
- ✅ Comprehensive testing suite

## Installation

1. Install the required dependency:
```bash
pip install openai
```

2. Optional dependencies for testing:
```bash
pip install pillow
```

## Setup

1. Get an API key from [OpenRouter](https://openrouter.ai/)
2. Set the environment variable:
```bash
export OPENROUTER_API_KEY="your-api-key-here"
```

## Usage

### Basic Usage

```python
from gemini_image_generation import generate_image, save_image_from_url

# Generate an image
prompt = "A beautiful sunset over mountains"
image_url = generate_image(prompt)

# Save the image
if image_url:
    save_image_from_url(image_url, "sunset.png")
```

### Advanced Usage

```python
from gemini_image_generation import generate_image

# Use different models
models = [
    "google/gemini-3.1-flash-image-preview",  # Fast, good quality
    "google/gemini-3-pro-image-preview",     # High quality, detailed
    "google/gemini-2.5-flash-image"          # Legacy model
]

for model in models:
    image_url = generate_image(
        "A futuristic cityscape at night",
        model=model
    )
    if image_url:
        save_image_from_url(image_url, f"city_{model.split('-')[-1]}.png")
```

## Available Models

| Model | Description | Use Case |
|-------|-------------|----------|
| `google/gemini-3.1-flash-image-preview` | Fast generation with good quality | Quick prototyping, iterative design |
| `google/gemini-3-pro-image-preview` | Higher quality, more detailed | Professional artwork, detailed scenes |
| `google/gemini-2.5-flash-image` | Legacy model, still effective | Compatibility, specific style |

## API Reference

### `generate_image(prompt: str, model: str = "google/gemini-3.1-flash-image-preview") -> str`

Generate an image from a text prompt.

**Parameters:**
- `prompt` (str): The text prompt describing what to generate
- `model` (str): The model to use for generation (default: gemini-3.1-flash-image-preview)

**Returns:**
- `str`: Base64 encoded image URL or None if generation failed

**Raises:**
- `ValueError`: If API key is not set
- `Exception`: If image generation fails

### `save_image_from_url(image_url: str, filename: str = "generated_image.png")`

Save a base64 encoded image to a file.

**Parameters:**
- `image_url` (str): Base64 encoded image URL
- `filename` (str): Output filename (default: generated_image.png)

## Testing

Run the test suite to verify the implementation:

```bash
# Set your API key first
export OPENROUTER_API_KEY="your-api-key-here"

# Run tests
python test_gemini_generation.py
```

The test suite includes:
- API key validation
- Image generation with different models
- Image file validation
- Error handling

## Examples

### Generate a simple image
```python
from gemini_image_generation import generate_image, save_image_from_url

prompt = "A red apple on a wooden table"
image_url = generate_image(prompt)
save_image_from_url(image_url, "apple.png")
```

### Generate with different aspect ratios
```python
# Note: Aspect ratio can be specified in the prompt
prompts = [
    "A landscape painting, wide aspect ratio",
    "A portrait of a person, tall aspect ratio", 
    "A square logo design"
]

for i, prompt in enumerate(prompts):
    image_url = generate_image(prompt)
    save_image_from_url(image_url, f"image_{i}.png")
```

### Batch generation
```python
from gemini_image_generation import generate_image, save_image_from_url

prompts = [
    "A cat sitting on a couch",
    "A dog playing in a park",
    "A bird flying in the sky"
]

for i, prompt in enumerate(prompts):
    try:
        image_url = generate_image(prompt)
        if image_url:
            save_image_from_url(image_url, f"animal_{i}.png")
            print(f"Generated image {i+1}/3")
    except Exception as e:
        print(f"Failed to generate image {i+1}: {e}")
```

## Error Handling

The module includes comprehensive error handling:

- **Missing API Key**: Raises `ValueError` with clear instructions
- **Network Errors**: Catches and reports connection issues
- **Invalid Responses**: Handles malformed API responses
- **File I/O Errors**: Manages image saving failures

## Troubleshooting

### Common Issues

1. **"Please set the OPENROUTER_API_KEY environment variable"**
   - Make sure you've set the environment variable correctly
   - Check that the key is valid and has image generation permissions

2. **"Error generating image"**
   - Check your internet connection
   - Verify your API key has sufficient credits
   - Try a simpler prompt

3. **"Generated file is not a valid image"**
   - The API might have returned text instead of an image
   - Check the prompt format and model compatibility

### Debug Mode

For debugging, you can modify the `generate_image` function to print more detailed information:

```python
def generate_image(prompt: str, model: str = "google/gemini-3.1-flash-image-preview") -> str:
    try:
        response = client.chat.completions.create(...)
        print(f"Response type: {type(response)}")
        print(f"Response keys: {response.__dict__.keys()}")
        # ... rest of function
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Run the test suite
6. Submit a pull request

## License

This project is licensed under the MIT License.

## Support

For issues and questions:
- Check the troubleshooting section above
- Review the test examples
- Ensure your API key is valid and has sufficient credits