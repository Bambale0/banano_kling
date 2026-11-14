"""Provider contract regression tests (never send paid KIE requests)."""
import pytest

from bot.services.seedream55_service import (
    EDIT_MODEL, LAYERS_MODEL, TEXT_MODEL, Seedream55Service,
)


@pytest.fixture
def service(monkeypatch):
    provider = Seedream55Service(kie_key="test-key")
    captured = []

    async def post(endpoint, payload):
        captured.append((endpoint, payload))
        return {"code": 200, "data": {"taskId": "test-task"}}

    async def upload(urls):
        return [f"https://kie.example/input/{index}.png" for index, _ in enumerate(urls)]

    monkeypatch.setattr(provider, "_kie_post", post)
    monkeypatch.setattr(provider, "_prepare_effective_image_urls", upload)
    return provider, captured


@pytest.mark.asyncio
async def test_text_to_image_all_fields(service):
    svc, sent = service
    result = await svc.generate_text_to_image(
        "Create a photorealistic portrait", aspect_ratio="21:9", size="1.5K",
        output_format="png", background="transparent", nsfw_checker=True,
        callBackUrl="https://example.org/callback",
    )
    assert result["data"]["taskId"] == "test-task"
    endpoint, payload = sent[0]
    assert endpoint == "/api/v1/jobs/createTask"
    assert payload["model"] == TEXT_MODEL
    assert payload["callBackUrl"] == "https://example.org/callback"
    assert payload["input"] == {
        "prompt": "Create a photorealistic portrait", "aspect_ratio": "21:9",
        "size": "1.5K", "output_format": "png", "background": "transparent",
        "nsfw_checker": True,
    }


@pytest.mark.asyncio
async def test_image_to_image_preserves_ten_references(service):
    svc, sent = service
    refs = [f"https://example.org/{i}.jpg" for i in range(10)]
    result = await svc.generate_image(
        "Change the background to a forest", refs, size="2K",
        aspect_ratio="auto", output_format="jpeg", background="opaque",
    )
    assert result["code"] == 200
    payload = sent[0][1]
    assert payload["model"] == EDIT_MODEL
    assert payload["input"]["image_urls"] == [
        f"https://kie.example/input/{i}.png" for i in range(10)
    ]
    assert payload["input"]["size"] == "2K"
    assert payload["input"]["output_format"] == "jpeg"


@pytest.mark.asyncio
async def test_layer_decomposition_exact_provider_payload(service):
    svc, sent = service
    result = await svc.generate_layers(
        "https://example.org/photo.png", prompt="Split title from logo",
        size="auto", max_images=100, text_recognition=True,
    )
    assert result["code"] == 200
    assert sent[0][1]["model"] == LAYERS_MODEL
    assert sent[0][1]["input"] == {
        "image_url": "https://kie.example/input/0.png",
        "prompt": "Split title from logo", "size": "auto", "output_format": "png",
        "nsfw_checker": False, "max_images": 100, "text_recognition": True,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    {"prompt": "bad", "aspect_ratio": "1:1"},
    {"prompt": "valid prompt", "aspect_ratio": "4:5"},
    {"prompt": "valid prompt", "background": "transparent", "output_format": "jpeg"},
    {"prompt": "valid prompt", "size": "4K"},
])
async def test_invalid_t2i_rejected_before_network(service, kwargs):
    svc, sent = service
    response = await svc.generate_text_to_image(**kwargs)
    assert response["error"] == "invalid_input"
    assert not sent


@pytest.mark.asyncio
async def test_invalid_input_image_counts_rejected_before_upload(service):
    svc, sent = service
    for refs in ([], ["https://example.org/a.png"] * 11):
        response = await svc.generate_image("A valid prompt", refs)
        assert response["error"] == "invalid_input"
    assert sent == []


@pytest.mark.asyncio
async def test_invalid_layers_rejected_before_network(service):
    svc, sent = service
    for kw in ({"max_images": 1}, {"max_images": 101}, {"prompt": "x"*2001}, {"size": "4K"}):
        assert (await svc.generate_layers("https://example.org/a.png", **kw))["error"] == "invalid_input"
    assert sent == []
