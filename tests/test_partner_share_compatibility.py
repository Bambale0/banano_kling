"""Sharer referrals and original-author repeat rewards remain independent."""
from urllib.parse import parse_qs, urlparse

import pytest

from bot import database
from bot.partner_commission_settings import set_partner_commission_percent
from bot.partner_policy import mark_generation_accepted
from bot.services import referral_service
from tests import test_feed_share_attribution as share_fixtures

sharing_client = share_fixtures.sharing_client
published_card = share_fixtures.published_card
signed_init_data = share_fixtures.signed_init_data


@pytest.mark.parametrize("first_line,expected_rub", [(0, 0), (30, 300), (40, 400)])
async def test_shared_recipe_keeps_sharer_invite_and_author_repeat_separate(
    sharing_client, monkeypatch, first_line, expected_rub,
):
    monkeypatch.setattr(referral_service, "DATABASE_PATH", database.DATABASE_PATH)
    author, card = await published_card()
    sharer = await database.get_or_create_user(82002)
    newcomer = await database.get_or_create_user(82003)
    await set_partner_commission_percent(
        999999999, sharer.telegram_id, first_line, expected_revision=0,
    )
    response = await sharing_client.post("/mini-app/api/feed/share", json={
        "init_data": signed_init_data(sharer.telegram_id), "gen_id": card["id"],
    })
    assert response.status == 200
    link = (await response.json())["miniapp_repeat_link"]
    start = parse_qs(urlparse(link).query)["startapp"][0]
    code = referral_service.referral_code_from_start_param(start)
    assert code == sharer.referral_code
    attached = await referral_service.process_referral_click(
        newcomer.telegram_id, code, source="miniapp",
    )
    assert attached.attached
    assert (await database.get_or_create_user(sharer.telegram_id)).referral_earned == 0
    assert (await database.get_or_create_user(newcomer.telegram_id)).credits == 5

    assert await database.deduct_credits(newcomer.telegram_id, 5)
    assert await database.add_generation_task(
        newcomer.id, newcomer.telegram_id, "shared-accepted-repeat", "image", "test",
        cost=5, provider_accepted=True,
    )
    assert not await mark_generation_accepted("shared-accepted-repeat")
    for expected in (True, False):
        assert await database.credit_feed_prompt_repeat(
            card["id"], newcomer.id, repeat_task_id="shared-accepted-repeat", credits_spent=5,
        ) is expected
    assert (await database.get_or_create_user(newcomer.telegram_id)).credits == 0
    assert (await database.get_or_create_user(sharer.telegram_id)).referral_earned == 3
    assert (await database.get_or_create_user(sharer.telegram_id)).prompt_repeat_total_rub == 0
    assert (await database.get_or_create_user(author.telegram_id)).prompt_repeat_total_rub == 5
    assert (await database.get_or_create_user(author.telegram_id)).referral_earned == 0

    await database.create_transaction("shared-invoice", newcomer.id, "shared-pay", "test", 25, 1000)
    await set_partner_commission_percent(
        999999999, sharer.telegram_id, 15, expected_revision=1,
    )
    result = await database.complete_payment_atomic("shared-invoice")
    assert result["referral_bonus"]["value"] == expected_rub
    assert (await database.complete_payment_atomic("shared-invoice"))["already_completed"]
    assert (await database.get_or_create_user(sharer.telegram_id)).partner_balance_rub == expected_rub
    assert (await database.get_or_create_user(author.telegram_id)).partner_balance_rub == 5
