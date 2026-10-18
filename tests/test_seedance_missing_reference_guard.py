"""Regression: missing image references must never silently bind other media."""

import pytest

from bot.services.seedance_reference_binding import (
    canonicalize_seedance_reference_tags,
    missing_seedance_reference_tags,
)


@pytest.mark.parametrize(
    "prompt,images,videos,audios,expected",
    [
        ("Dance with @Image1 and @Image2", 1, 1, 0, ["@Image2"]),
        ("Use @Image3", 1, 1, 1, ["@Image3"]),
        ("Use @IMAGE 2", 0, 1, 1, ["@Image2"]),
        ("Use @Image1 @Video1", 1, 1, 0, []),
    ],
)
def test_missing_image_never_becomes_other_media(
    prompt, images, videos, audios, expected
):
    assert (
        missing_seedance_reference_tags(
            prompt, image_count=images, video_count=videos, audio_count=audios
        )
        == expected
    )


def test_legacy_combined_ordinals_require_explicit_opt_in():
    assert (
        canonicalize_seedance_reference_tags("@Image2", image_count=1, video_count=1)
        == "@Image2"
    )
    assert (
        canonicalize_seedance_reference_tags(
            "@Image2",
            image_count=1,
            video_count=1,
            allow_legacy_combined_ordinals=True,
        )
        == "@Video1"
    )
