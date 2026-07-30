from pathlib import Path

PROFILE_PATH = Path('frontend/miniapp-v0/components/tabs/profile-tab.tsx')
EVENTS_PATH = Path('frontend/miniapp-v0/lib/feed-events.ts')


def test_profile_uses_publication_event_payload_directly():
    source = PROFILE_PATH.read_text(encoding='utf-8')
    assert "(event as CustomEvent<FeedItem | undefined>).detail" in source
    assert "mergePublication(current, published, 'profile')" in source
    assert "loading && !profileItems.length" in source


def test_pending_publication_is_shared_across_dynamic_chunks():
    source = EVENTS_PATH.read_text(encoding='utf-8')
    assert '__BANANO_PENDING_PUBLICATION__' in source
    assert "new CustomEvent<FeedItem | undefined>('banano:feed-changed', { detail: item })" in source


def test_pending_publication_is_not_injected_into_another_users_profile():
    source = PROFILE_PATH.read_text(encoding='utf-8')
    foreign_profile_block = source.split(
        'const result = await fetchProfileFeed(targetReferralCode, 120)',
        1,
    )[1]
    assert 'setItems(result.feed)' in foreign_profile_block
    assert "mergePendingPublication(result.feed, 'profile')" not in foreign_profile_block
