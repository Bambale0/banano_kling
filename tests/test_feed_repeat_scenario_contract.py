from bot.database import _feed_repeat_scenario


def test_seedance_multimodal_image_only_repeat_opens_photo_text_mode():
    assert (
        _feed_repeat_scenario(
            "seedance_2_5",
            {
                "v_type": "video",
                "seedance25_scenario": "multimodal",
            },
            has_image_references=True,
            has_video_references=False,
        )
        == "imgtxt"
    )


def test_seedance_multimodal_video_reference_stays_video_text_mode():
    assert (
        _feed_repeat_scenario(
            "seedance_2_5",
            {
                "v_type": "video",
                "seedance25_scenario": "multimodal",
            },
            has_image_references=True,
            has_video_references=True,
        )
        == "video"
    )


def test_non_seedance_feed_repeat_keeps_existing_scenario_contract():
    assert (
        _feed_repeat_scenario(
            "v3_pro",
            {"v_type": "video"},
            has_image_references=True,
            has_video_references=False,
        )
        == "video"
    )
