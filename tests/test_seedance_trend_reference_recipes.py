from __future__ import annotations

import pytest

from bot.seedance_trend_recipe import (
    SeedanceTrendRecipeError,
    assemble_seedance_trend_inputs,
    compile_seedance_trend_recipe,
    extract_seedance_reference_snapshot,
)

FACE = "https://example.test/face.png"
DRESS = "https://example.test/dress.png"
EARRINGS = "https://example.test/earrings.png"
MOTION = "https://example.test/motion.mp4"
AUDIO = "https://example.test/audio.mp3"
USER_FACE = "https://example.test/user-face.png"


def test_extracts_seedance20_snapshot_in_provider_image_order() -> None:
    snapshot = extract_seedance_reference_snapshot(
        "seedance_2",
        {
            "v_image_url": FACE,
            "reference_images": [DRESS, EARRINGS],
            "v_reference_videos": [MOTION],
            "v_reference_audio": [AUDIO],
        },
    )

    assert snapshot.images == (FACE, DRESS, EARRINGS)
    assert snapshot.videos == (MOTION,)
    assert snapshot.audios == (AUDIO,)


def test_extracts_seedance25_multimodal_snapshot_without_duplicates() -> None:
    snapshot = extract_seedance_reference_snapshot(
        "seedance_2_5",
        {
            "seedance25_scenario": "multimodal",
            "first_frame_url": None,
            "reference_images": [FACE, DRESS, FACE],
            "v_reference_videos": [MOTION],
            "reference_audios": [AUDIO],
        },
    )

    assert snapshot.images == (FACE, DRESS)
    assert snapshot.videos == (MOTION,)
    assert snapshot.audios == (AUDIO,)


def test_compiler_replaces_author_identity_with_user_image_one() -> None:
    recipe = compile_seedance_trend_recipe(
        prompt=(
            "Put the person from @Image1 in the outfit from @Image2, "
            "use the earrings from @Image3 and motion from @Video1."
        ),
        model="seedance_2_5",
        source_images=[FACE, DRESS, EARRINGS],
        source_videos=[MOTION],
        source_audios=[],
        identity_image_index=1,
        fixed_image_indices=[2, 3],
        fixed_video_indices=[1],
        fixed_audio_indices=[],
    )

    assert [asset.source_url for asset in recipe.assets] == [DRESS, EARRINGS, MOTION]
    assert [(asset.media_type, asset.position) for asset in recipe.assets] == [
        ("image", 2),
        ("image", 3),
        ("video", 1),
    ]
    assert FACE not in [asset.source_url for asset in recipe.assets]
    assert "@Image1" in recipe.prompt
    assert "@Image2" in recipe.prompt
    assert "@Image3" in recipe.prompt
    assert "@Video1" in recipe.prompt
    assert "SEEDANCE_TREND_IDENTITY_CONTRACT_V1" in recipe.prompt


def test_compiler_remaps_identity_when_author_face_was_not_first() -> None:
    recipe = compile_seedance_trend_recipe(
        prompt="Use outfit @Image1 on person @Image2 with jewelry @Image3.",
        model="seedance_2",
        source_images=[DRESS, FACE, EARRINGS],
        source_videos=[],
        source_audios=[],
        identity_image_index=2,
        fixed_image_indices=[1, 3],
        fixed_video_indices=[],
        fixed_audio_indices=[],
    )

    assert [asset.source_url for asset in recipe.assets] == [DRESS, EARRINGS]
    assert "outfit @Image2" in recipe.prompt
    assert "person @Image1" in recipe.prompt
    assert "jewelry @Image3" in recipe.prompt


def test_compiler_keeps_source_order_even_if_client_indices_are_reversed() -> None:
    recipe = compile_seedance_trend_recipe(
        prompt="Person @Image1 wears @Image2 and jewelry @Image3.",
        model="seedance_2_5",
        source_images=[FACE, DRESS, EARRINGS],
        source_videos=[],
        source_audios=[],
        identity_image_index=1,
        fixed_image_indices=[3, 2],
        fixed_video_indices=[],
        fixed_audio_indices=[],
    )

    assert [asset.source_url for asset in recipe.image_assets] == [DRESS, EARRINGS]
    assert [asset.position for asset in recipe.image_assets] == [2, 3]



def test_compiler_rejects_prompt_reference_to_excluded_media() -> None:
    with pytest.raises(SeedanceTrendRecipeError, match="@Image3"):
        compile_seedance_trend_recipe(
            prompt="Person @Image1 wears @Image2 and holds @Image3.",
            model="seedance_2_5",
            source_images=[FACE, DRESS, EARRINGS],
            source_videos=[],
            source_audios=[],
            identity_image_index=1,
            fixed_image_indices=[2],
            fixed_video_indices=[],
            fixed_audio_indices=[],
        )


def test_compiler_rejects_excluded_middle_reference_even_after_renumbering() -> None:
    with pytest.raises(SeedanceTrendRecipeError, match="@Image2"):
        compile_seedance_trend_recipe(
            prompt="Person @Image1 ignores @Image2 but uses @Image3.",
            model="seedance_2",
            source_images=[FACE, DRESS, EARRINGS],
            source_videos=[],
            source_audios=[],
            identity_image_index=1,
            fixed_image_indices=[3],
            fixed_video_indices=[],
            fixed_audio_indices=[],
        )


def test_compiler_rejects_prompt_that_guard_pushes_over_model_limit() -> None:
    with pytest.raises(
        SeedanceTrendRecipeError,
        match="exceeds 20000 characters",
    ):
        compile_seedance_trend_recipe(
            prompt="@Image1 uses @Image2. " + ("x" * 20_000),
            model="seedance_2",
            source_images=[FACE, DRESS],
            source_videos=[],
            source_audios=[],
            identity_image_index=1,
            fixed_image_indices=[2],
            fixed_video_indices=[],
            fixed_audio_indices=[],
        )



def test_compiler_video_only_recipe_does_not_invent_image_two_binding() -> None:
    recipe = compile_seedance_trend_recipe(
        prompt="Person @Image1 follows motion from @Video1.",
        model="seedance_2_5",
        source_images=[FACE],
        source_videos=[MOTION],
        source_audios=[],
        identity_image_index=1,
        fixed_image_indices=[],
        fixed_video_indices=[1],
        fixed_audio_indices=[],
    )

    assert "@Image2" not in recipe.prompt
    assert "@Video1" in recipe.prompt



def test_assemble_inputs_keeps_user_identity_first_and_assets_typed() -> None:
    images, videos, audios = assemble_seedance_trend_inputs(
        [USER_FACE],
        [
            {"media_type": "video", "position": 1, "file_url": MOTION},
            {"media_type": "image", "position": 3, "file_url": EARRINGS},
            {"media_type": "audio", "position": 1, "file_url": AUDIO},
            {"media_type": "image", "position": 2, "file_url": DRESS},
        ],
    )

    assert images == [USER_FACE, DRESS, EARRINGS]
    assert videos == [MOTION]
    assert audios == [AUDIO]


def test_assemble_inputs_requires_exactly_one_user_identity() -> None:
    with pytest.raises(SeedanceTrendRecipeError, match="exactly one"):
        assemble_seedance_trend_inputs([], [])
    with pytest.raises(SeedanceTrendRecipeError, match="exactly one"):
        assemble_seedance_trend_inputs([USER_FACE, FACE], [])
