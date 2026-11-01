from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database, reference_library
from bot.handlers import generation


@pytest.mark.parametrize('deleted_selected', [False, True])
async def test_deleting_one_reference_never_drops_draft_inputs_from_other_categories(monkeypatch, deleted_selected):
    clothes = await reference_library.create_category(701, 'Одежда')
    cars = await reference_library.create_category(701, 'Машины')
    refs = []
    for index in range(3):
        refs.append(await database.save_user_reference(701, kind='image', file_url=f'https://example.test/{index}.png',
                                                       file_hash=str(index), category_id=clothes['id'] if index == 0 else cars['id']))
    original = [refs[0].file_url, refs[2].file_url if deleted_selected else refs[1].file_url]
    data = {'saved_ref_category_id': cars['id'], 'reference_images': original}

    class State:
        async def get_data(self):
            return data

        async def update_data(self, **patch):
            data.update(patch)

    callback = SimpleNamespace(data=f'savedref_delete_{refs[2].id}_0', from_user=SimpleNamespace(id=701),
                               message=SimpleNamespace(delete=AsyncMock(), answer=AsyncMock()), answer=AsyncMock())
    monkeypatch.setattr(generation, '_send_saved_reference_preview', AsyncMock())
    await generation.delete_saved_reference_from_library(callback, State())
    assert data['reference_images'] == ([refs[0].file_url] if deleted_selected else original)


async def test_telegram_can_select_an_outfit_after_the_first_hundred(monkeypatch):
    folder = await reference_library.create_category(701, 'Одежда')
    for index in range(105):
        await database.save_user_reference(701, kind='image', file_url=f'https://example.test/{index}.png',
                                           file_hash=str(index), category_id=folder['id'])
    data = {'saved_ref_category_id': folder['id'], 'saved_ref_page_offset': 80, 'reference_images': []}

    class State:
        async def get_data(self):
            return data

        async def update_data(self, **patch):
            data.update(patch)

    callback = SimpleNamespace(data='savedref_page:100', from_user=SimpleNamespace(id=701), answer=AsyncMock(),
                               message=SimpleNamespace(answer=AsyncMock(), delete=AsyncMock()))
    preview = AsyncMock()
    monkeypatch.setattr(generation, '_send_saved_reference_preview', preview)
    state = State()
    await generation.page_saved_reference_category(callback, state)
    assert len(preview.await_args.kwargs['refs']) == 5
    candidate = preview.await_args.kwargs['refs'][0]
    callback.data = f'savedref_use_{candidate.id}'
    await generation.use_saved_reference_from_library(callback, state)
    assert data['reference_images'] == [candidate.file_url]
