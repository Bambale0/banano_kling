from bot.handlers.generation import _needs_background_target


def test_background_change_prompt_requires_target_with_reference():
    assert _needs_background_target("смени фон", 1)
    assert _needs_background_target("Фон поменяй!", 1)
    assert _needs_background_target("сделай другой задний фон", 1)


def test_background_change_prompt_allows_specific_target():
    assert not _needs_background_target("смени фон на неоновый город ночью", 1)
    assert not _needs_background_target("поставь сумку на пляжный фон", 1)
    assert not _needs_background_target("смени фон", 0)
