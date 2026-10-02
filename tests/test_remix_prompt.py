from bot.services.remix_prompt import compose_feed_remix_prompt


def test_feed_remix_prompt_keeps_author_prompt_when_user_adds_changes():
    source_prompt = "cinematic portrait, soft light, red dress"
    user_changes = "Измени только причёску: блондинка"

    merged = compose_feed_remix_prompt(source_prompt, user_changes)

    assert source_prompt in merged
    assert user_changes in merged
    assert "keep everything else" in merged.lower()


def test_feed_remix_prompt_without_changes_uses_author_prompt_verbatim():
    source_prompt = "cinematic portrait, soft light, red dress"

    assert compose_feed_remix_prompt(source_prompt, "") == source_prompt
    assert compose_feed_remix_prompt(source_prompt, source_prompt) == source_prompt


def test_feed_remix_prompt_strips_legacy_duplicate_source_prompt():
    source_prompt = "cinematic portrait, soft light, red dress"
    legacy_prompt = f"Измени только причёску: {source_prompt}"

    merged = compose_feed_remix_prompt(source_prompt, legacy_prompt)

    assert merged.count(source_prompt) == 1
    assert "Измени только причёску" in merged
