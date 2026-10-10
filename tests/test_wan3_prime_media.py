from __future__ import annotations

import pytest

from bot.services.wan3_prime_media import (
    MediaInfo,
    Wan3PrimeValidationError,
    assert_public_url,
    normalize_wan3_body,
    validate_wan3_recipe,
)


class Probe:
    def __init__(self, durations: dict[str, float] | None = None):
        self.durations = durations or {}

    async def probe_url(self, url: str, *, kind: str) -> MediaInfo:
        ext = "." + url.rsplit(".", 1)[-1].split("?", 1)[0].lower()
        if kind == "image":
            return MediaInfo(kind=kind, url=url, extension=ext, size_bytes=1024, width=1024, height=768)
        if kind == "video":
            return MediaInfo(kind=kind, url=url, extension=ext, size_bytes=2048, width=1280, height=720, duration_seconds=self.durations.get(url, 5))
        if kind == "audio":
            return MediaInfo(kind=kind, url=url, extension=ext, size_bytes=2048, duration_seconds=self.durations.get(url, 4))
        return MediaInfo(kind=kind, url=url, extension=ext, size_bytes=2048)

    async def probe_file(self, path: str, *, kind: str) -> MediaInfo:
        return MediaInfo(kind=kind, path=path, duration_seconds=6, extension=".mp4")


@pytest.mark.asyncio
async def test_normalizer_accepts_aliases_and_preserves_seed_zero_audio_false():
    body = normalize_wan3_body(
        {
            "v_model": "wan_3_prime",
            "generation_type": "video",
            "v_duration": "2",
            "v_ratio": "16:9",
            "wan_resolution": "720P",
            "wan_seed": 0,
            "wan_audio": False,
            "v_reference_videos": ["https://cdn.example.com/source.mp4"],
        }
    )

    recipe = await validate_wan3_recipe(body, Probe())

    assert recipe.scenario == "reference"
    assert recipe.duration == 2
    assert recipe.aspect_ratio == "16:9"
    assert recipe.seed == 0
    assert recipe.audio is False
    assert recipe.reference_video_urls == ["https://cdn.example.com/source.mp4"]


@pytest.mark.asyncio
async def test_rejects_fraction_bool_duration_and_seed():
    for value in (True, "2.5"):
        with pytest.raises(Wan3PrimeValidationError):
            await validate_wan3_recipe({"scenario": "text", "prompt": "x", "duration": value}, Probe())
    with pytest.raises(Wan3PrimeValidationError):
        await validate_wan3_recipe({"scenario": "text", "prompt": "x", "seed": False}, Probe())


@pytest.mark.asyncio
async def test_explicit_scenario_must_match_inputs_and_edit_requires_video1():
    with pytest.raises(Wan3PrimeValidationError, match="scenario"):
        await validate_wan3_recipe(
            {"scenario": "text", "prompt": "x", "reference_image_urls": ["https://cdn.example.com/a.jpg"]},
            Probe(),
        )

    with pytest.raises(Wan3PrimeValidationError, match="Video1"):
        await validate_wan3_recipe({"scenario": "edit", "prompt": "change color"}, Probe())

    recipe = await validate_wan3_recipe(
        {
            "scenario": "edit",
            "prompt": "change color",
            "reference_video_urls": [
                "https://cdn.example.com/source1.mp4",
                "https://cdn.example.com/source2.mov",
            ],
        },
        Probe(),
    )
    assert recipe.reference_video_urls == [
        "https://cdn.example.com/source1.mp4",
        "https://cdn.example.com/source2.mov",
    ]
    assert recipe.prompt == "change color"


@pytest.mark.asyncio
async def test_video_audio_sums_and_output_cap_are_server_measured():
    probe = Probe(
        {
            "https://cdn.example.com/v1.mp4": 10,
            "https://cdn.example.com/v2.mp4": 6,
        }
    )
    with pytest.raises(Wan3PrimeValidationError, match="combined reference video"):
        await validate_wan3_recipe(
            {
                "scenario": "reference",
                "prompt": "",
                "duration": 2,
                "reference_video_urls": [
                    "https://cdn.example.com/v1.mp4",
                    "https://cdn.example.com/v2.mp4",
                ],
            },
            probe,
        )

    with pytest.raises(Wan3PrimeValidationError, match="plus output"):
        await validate_wan3_recipe(
                {
                    "scenario": "reference",
                    "duration": 21,
                    "reference_video_urls": ["https://cdn.example.com/v1.mp4"],
                },
            probe,
        )


@pytest.mark.asyncio
async def test_file_and_link_contract_and_private_urls():
    with pytest.raises(Wan3PrimeValidationError, match="mutually exclusive"):
        await validate_wan3_recipe(
            {
                "scenario": "file",
                "reference_file_urls": ["https://cdn.example.com/a.pdf"],
                "reference_link_urls": ["https://example.com/page"],
            },
            Probe(),
        )

    with pytest.raises(Wan3PrimeValidationError):
        await assert_public_url("http://127.0.0.1/private")

    recipe = await validate_wan3_recipe(
        {"scenario": "file", "reference_file_urls": ["https://cdn.example.com/a.pdf"]},
        Probe(),
    )
    assert recipe.upstream_page_validation_required is True
