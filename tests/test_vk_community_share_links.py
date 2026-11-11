"""VK links keep the server-owned community context across every share route."""
import pytest

from bot.miniapp_links import (
    feed_link,
    platform_miniapp_link,
    profile_link,
    prompt_link,
    referral_link,
    remix_link,
)


@pytest.mark.parametrize(('fn', 'args', 'fragment'), [
    (feed_link, (None, 123), 'feed_123'),
    (prompt_link, (None, 77), 'prompt_77'),
    (remix_link, (None, 85), 'remix_85'),
    (profile_link, (None, 'ABC'), 'profile_ABC_ref_ABC'),
    (referral_link, (None, 'ABC'), 'ref_ABC'),
])
def test_vk_shared_urls_keep_trusted_community(fn, args, fragment):
    result = fn(*args, platform='vk', vk_app_id=54880352, vk_community_id=239915802)
    assert result == f'https://vk.com/app54880352_-239915802#{fragment}'


def test_legacy_vk_without_community_keeps_compatible_generic_url():
    assert platform_miniapp_link(None,'prompt_10',platform='vk',vk_app_id=123) == 'https://vk.com/app123#prompt_10'


@pytest.mark.parametrize('owner', [-1, 0, 2**63, 'javascript:evil'])
def test_malformed_vk_community_is_not_placed_in_public_url(owner):
    with pytest.raises(ValueError):
        platform_miniapp_link(None,'prompt_10',platform='vk',vk_app_id=123,vk_community_id=owner)
