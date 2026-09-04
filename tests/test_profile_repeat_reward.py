import pytest

from bot import database


@pytest.mark.asyncio
async def test_profile_only_generation_repeat_credits_author(tmp_path):
    database.DATABASE_PATH = str(tmp_path / "profile-repeat-reward.db")
    await database.init_db()

    author = await database.get_or_create_user(91001)
    repeater = await database.get_or_create_user(91002)
    await database.add_generation_task(
        author.id,
        author.telegram_id,
        "profile-source-image",
        "image",
        "miniapp_image",
        model="banana_2",
        aspect_ratio="1:1",
        prompt="A profile-only source image",
        cost=1.5,
    )
    await database.complete_video_task(
        "profile-source-image",
        "https://example.com/profile-source.png",
    )

    source = await database.share_to_feed(
        "profile-source-image",
        author.id,
        publication_scope="profile",
    )
    assert source is not None
    assert source["publication_scope"] == "profile"

    credited = await database.credit_feed_prompt_repeat(
        source["id"],
        repeater.id,
        repeat_task_id="profile-repeat-task",
        credits_spent=1.5,
    )

    assert credited is True
    overview = await database.get_partner_overview(author.telegram_id)
    assert overview["prompt_repeat_balance_rub"] == 10
    assert overview["prompt_repeat_total_rub"] == 10
