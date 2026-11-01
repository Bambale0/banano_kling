import base64
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from bot import database, miniapp, reference_library
from bot.reference_library_api import reference_library_action


def request(body):
    return SimpleNamespace(app={}, json=AsyncMock(return_value=body), content_type='application/json')


@pytest.mark.parametrize('multipart', [False, True])
async def test_http_folder_upload_is_pinned_and_reusable(monkeypatch, tmp_path, multipart):
    user = await database.get_or_create_user(701)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(701, {'user': user})))
    folder = await reference_library.create_category(701, 'Одежда')
    raw = io.BytesIO()
    Image.new('RGB', (512, 512), 'blue').save(raw, format='PNG')
    def upload_request():
        body = {
        'file_kind': 'image_reference', 'filename': 'dress.png', 'content_type': 'image/png',
        'data_base64': base64.b64encode(raw.getvalue()).decode(), 'reference_category_id': folder['id'],
        }
        if multipart:
            return SimpleNamespace(app={}, content_type='multipart/form-data', post=AsyncMock(return_value={
                **body, 'file': SimpleNamespace(file=io.BytesIO(raw.getvalue()), filename='dress.png', content_type='image/png'),
            }))
        return request(body)

    response = await miniapp.miniapp_upload(upload_request())
    assert response.status == 200, response.text
    uploaded = json.loads(response.text)
    response = await reference_library_action(request({'action': 'items', 'category_id': folder['id']}))
    assert response.status == 200, response.text
    assert json.loads(response.text)['items'][0]['url'] == uploaded['url']
    assert json.loads(response.text)['items'][0]['id'] == uploaded['reference']['id']
    # Re-uploading the same bytes is deduplicated and remains categorized.
    response = await miniapp.miniapp_upload(upload_request())
    assert response.status == 200
    assert len(await reference_library.list_items(701, folder['id'])) == 1


@pytest.mark.parametrize('action', ['items', 'rename_category', 'save_item', 'remove_item'])
async def test_http_rejects_forged_owner_and_foreign_category(monkeypatch, action):
    user = await database.get_or_create_user(702)
    folder = await reference_library.create_category(701, 'Одежда')
    item = await database.save_user_reference(701, kind='image', file_url='https://example.test/dress.png', file_hash='dress')
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(702, {'user': user})))
    response = await reference_library_action(request({
        'action': action, 'category_id': folder['id'], 'user_id': item.user_id, 'telegram_id': 701,
        'reference_id': item.id, 'name': 'Чужая',
    }))
    assert response.status == 403, response.text


async def test_foreign_category_upload_is_rejected_before_saving_any_bytes(monkeypatch):
    user = await database.get_or_create_user(702)
    folder = await reference_library.create_category(701, 'Одежда')
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(702, {'user': user})))
    save = AsyncMock(side_effect=AssertionError('no writes before owner check'))
    monkeypatch.setattr(miniapp, 'save_reference_file', save)
    response = await miniapp.miniapp_upload(request({
        'file_kind': 'image_reference', 'filename': 'dress.png', 'content_type': 'image/png',
        'data_base64': base64.b64encode(b'bytes').decode(), 'reference_category_id': folder['id'],
    }))
    assert response.status == 403
    save.assert_not_awaited()
