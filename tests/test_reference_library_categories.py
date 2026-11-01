import pytest

from bot import database
from bot import reference_library as library


async def reference(actor, index):
    return await database.save_user_reference(actor, kind='image', file_url=f'https://example.test/{index}.png', file_hash=str(index))


async def test_personal_categories_keep_multiple_outfits_outside_recent_rotation(monkeypatch):
    monkeypatch.setattr(database, 'SAVED_REFERENCES_MAX_PER_KIND', 2)
    clothes = await library.create_category(101, 'Одежда')
    kept = []
    for index in range(6):
        item = await database.save_user_reference(101, kind='image', file_url=f'https://example.test/outfit{index}.png',
                                                 file_hash=str(index), category_id=clothes['id'])
        kept.append(item.id)
    for index in range(6, 12):
        await reference(101, index)
    assert [item['id'] for item in await library.list_items(101, clothes['id'])] == [str(value) for value in reversed(kept)]
    await database.cleanup_saved_references(keep_latest=2, max_age_days=1)
    assert len(await library.list_items(101, clothes['id'])) == 6
    assert await library.list_categories(202) == []


async def test_categories_and_references_cannot_be_accessed_or_changed_by_another_user():
    folder = await library.create_category(101, 'Одежда')
    item = await reference(101, 1)
    with pytest.raises(PermissionError):
        await library.save_item(202, folder['id'], item.id)
    with pytest.raises(PermissionError):
        await library.list_items(202, folder['id'])
    other = await library.create_category(202, 'Одежда')
    with pytest.raises(PermissionError):
        await library.save_item(202, other['id'], item.id)
    with pytest.raises(PermissionError):
        await library.rename_category(202, folder['id'], 'Чужая')


async def test_create_save_and_remove_are_idempotent_and_category_deletion_keeps_upload():
    folder = await library.create_category(101, ' Одежда ')
    assert (await library.create_category(101, 'одежда'))['id'] == folder['id']
    item = await reference(101, 1)
    await library.save_item(101, folder['id'], item.id, title='Чёрное платье')
    await library.save_item(101, folder['id'], item.id, title='Чёрное платье')
    items = await library.list_items(101, folder['id'])
    assert len(items) == 1 and items[0]['title'] == 'Чёрное платье'
    await library.rename_category(101, folder['id'], 'Наряды')
    assert (await library.list_categories(101))[0]['name'] == 'Наряды'
    await library.delete_category(101, folder['id'])
    await library.delete_category(101, folder['id'])
    assert await database.get_saved_reference_by_id(101, item.id) is not None


async def test_age_cleanup_never_deletes_categorized_references():
    folder = await library.create_category(101, 'Одежда')
    items = [await reference(101, index) for index in range(2)]
    for item in items:
        await library.save_item(101, folder['id'], item.id)
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE saved_references SET created_at = '2000-01-01', last_used_at = '2000-01-01'")
        await db.commit()
    await database.cleanup_saved_references(keep_latest=1, max_age_days=1)
    assert len(await library.list_items(101, folder['id'])) == 2
