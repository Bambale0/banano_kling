from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise AssertionError(f"{path}: expected one anchor, got {count}: {old[:120]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "bot/database.py",
        '''        await db.execute(
            "UPDATE generation_tasks SET feed_blurred = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (int(bool(blurred)), row["id"]),
        )''',
        '''        next_blurred = True if generation_adult_content(row) else bool(blurred)
        await db.execute(
            "UPDATE generation_tasks SET feed_blurred = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (int(next_blurred), row["id"]),
        )''',
    )

    replace_once(
        "frontend/miniapp-v0/components/tabs/profile-tab.tsx",
        '''                disabled={!isLive || busyId === previewItem.id}
                onClick={() => handleToggleBlur(previewItem)}
              >
                {previewItem.feed_blurred ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
                <span>{previewItem.feed_blurred ? 'Убрать blur' : 'Blur'}</span>''',
        '''                disabled={!isLive || previewItem.is_adult_content || busyId === previewItem.id}
                onClick={() => handleToggleBlur(previewItem)}
              >
                {previewItem.feed_blurred ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
                <span>
                  {previewItem.is_adult_content
                    ? 'Blur обязателен для 18+'
                    : previewItem.feed_blurred
                      ? 'Убрать blur'
                      : 'Blur'}
                </span>''',
    )

    replace_once(
        "tests/test_database.py",
        '''    assert card["feed_blurred"] is True
    assert card["feed_interactions_enabled"] is False
    assert await database.get_feed_generations(limit=20) == []


@pytest.mark.asyncio
async def test_feed_publication_is_visible_in_feed_and_profile''',
        '''    assert card["feed_blurred"] is True
    assert card["feed_interactions_enabled"] is False
    assert await database.get_feed_generations(limit=20) == []

    unblurred = await database.set_feed_blurred(card["id"], user.id, False)
    assert unblurred is not None
    assert unblurred["feed_blurred"] is True


@pytest.mark.asyncio
async def test_feed_publication_is_visible_in_feed_and_profile''',
    )

    Path(__file__).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
