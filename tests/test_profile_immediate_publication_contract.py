from pathlib import Path


def test_profile_uses_publication_event_payload_directly():
    source = Path('frontend/miniapp-v0/components/tabs/profile-tab.tsx').read_text(encoding='utf-8')
    assert "(event as CustomEvent<FeedItem | undefined>).detail" in source
    assert "mergePublication(current, published, 'profile')" in source
    assert "loading && !profileItems.length" in source


def test_pending_publication_is_shared_across_dynamic_chunks():
    source = Path('frontend/miniapp-v0/lib/feed-events.ts').read_text(encoding='utf-8')
    assert '__BANANO_PENDING_PUBLICATION__' in source
    assert "new CustomEvent<FeedItem | undefined>('banano:feed-changed', { detail: item })" in source
