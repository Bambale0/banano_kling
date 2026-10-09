"""Exercise the Docker copy guard on isolated source files, without bot startup."""

from pathlib import Path

import pytest

from scripts import apply_visible_copy_fixes as copy_guard

REPO_ROOT = Path(__file__).resolve().parents[1]
CURRENT_PARTNER_COPY = (
    '        f"• Новый пользователь получает 🍌 <code>{stats[\'new_user_bonus\']}</code> бананов при регистрации\\n"\n'
    '        f"• За реферала вам начисляется 🍌 <code>{stats[\'inviter_bonus\']}</code> банана после его первой генерации, принятой сервисом в работу\\n\\n"\n'
)


@pytest.fixture(autouse=True)
def isolated_database():
    """This build-time source check must not initialize a database."""
    yield


@pytest.fixture(autouse=True)
def mock_external_feed_downloads():
    """Do not import bot runtime modules for source-only build checks."""
    yield


@pytest.fixture
def common_source(tmp_path, monkeypatch):
    path = tmp_path / "bot/handlers/common.py"
    path.parent.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return path


def _normalized_source(partner_copy=CURRENT_PARTNER_COPY):
    return (
        copy_guard.DATABASE_IMPORT_WITH_WELCOME_BONUS
        + copy_guard.NEW_WELCOME_COPY
        + partner_copy
    )


def test_current_partner_policy_is_preserved_and_idempotent(common_source):
    source = (REPO_ROOT / "bot/handlers/common.py").read_text(encoding="utf-8")
    assert CURRENT_PARTNER_COPY in source
    common_source.write_text(source, encoding="utf-8")

    for _ in range(2):
        copy_guard.normalize_runtime_bonus_copy()
        assert common_source.read_text(encoding="utf-8") == source


def test_legacy_bonus_copy_still_normalizes_idempotently(common_source):
    source = (
        copy_guard.DATABASE_IMPORT_ANCHOR
        + copy_guard.OLD_WELCOME_COPY
        + copy_guard.OLD_PARTNER_BONUS_COPY
    )
    expected = _normalized_source(copy_guard.NEW_PARTNER_BONUS_COPY)
    common_source.write_text(source, encoding="utf-8")

    for _ in range(2):
        copy_guard.normalize_runtime_bonus_copy()
        assert common_source.read_text(encoding="utf-8") == expected


@pytest.mark.parametrize(
    "partner_copy",
    [
        "",
        CURRENT_PARTNER_COPY.splitlines(keepends=True)[0],
        CURRENT_PARTNER_COPY.splitlines(keepends=True)[1],
        CURRENT_PARTNER_COPY.replace(
            "после его первой генерации, принятой сервисом в работу",
            "при регистрации",
        ),
        CURRENT_PARTNER_COPY.replace("{stats['new_user_bonus']}", "15"),
        CURRENT_PARTNER_COPY.replace("{stats['inviter_bonus']}", "3"),
    ],
    ids=["missing", "missing-inviter", "missing-newcomer", "immediate", "fixed-newcomer", "fixed-inviter"],
)
def test_missing_or_changed_partner_policy_fails_without_writing(common_source, partner_copy):
    source = _normalized_source(partner_copy)
    common_source.write_text(source, encoding="utf-8")

    with pytest.raises(RuntimeError, match="Telegram partner cabinet bonus copy was not found"):
        copy_guard.normalize_runtime_bonus_copy()

    assert common_source.read_text(encoding="utf-8") == source


@pytest.mark.parametrize(
    "fragment",
    [
        "Новым пользователям — 15 бананов",
        "<code>15</code> бананов для тестирования бота",
    ],
)
def test_current_policy_does_not_hide_stale_bonus_copy(common_source, fragment):
    source = _normalized_source() + fragment
    common_source.write_text(source, encoding="utf-8")

    with pytest.raises(RuntimeError, match="Stale Telegram bonus copy remains"):
        copy_guard.normalize_runtime_bonus_copy()

    assert common_source.read_text(encoding="utf-8") == source


@pytest.mark.parametrize(
    ("source", "error"),
    [
        (copy_guard.NEW_WELCOME_COPY + CURRENT_PARTNER_COPY, "Welcome bonus database import anchor"),
        (copy_guard.DATABASE_IMPORT_WITH_WELCOME_BONUS + CURRENT_PARTNER_COPY, "Telegram welcome bonus copy"),
    ],
)
def test_current_policy_keeps_import_and_welcome_guards(common_source, source, error):
    common_source.write_text(source, encoding="utf-8")

    with pytest.raises(RuntimeError, match=error):
        copy_guard.normalize_runtime_bonus_copy()

    assert common_source.read_text(encoding="utf-8") == source


def test_complete_build_guard_is_idempotent_on_temporary_current_sources(tmp_path, monkeypatch):
    paths = (
        "bot/keyboards.py",
        "bot/handlers/image_analyzer.py",
        "bot/handlers/prompt_analyzer_v2.py",
        "bot/handlers/common.py",
        "bot/miniapp.py",
        "bot/database.py",
    )
    for relative in paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO_ROOT / relative).read_bytes())
    monkeypatch.chdir(tmp_path)
    original_common = (tmp_path / "bot/handlers/common.py").read_bytes()

    copy_guard.main()
    first_pass = {path: (tmp_path / path).read_bytes() for path in paths}
    assert first_pass["bot/handlers/common.py"] == original_common

    copy_guard.main()
    assert {path: (tmp_path / path).read_bytes() for path in paths} == first_pass
