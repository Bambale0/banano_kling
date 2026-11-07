"""VK-only personal photos through signed sessions and private HTTP media."""
import asyncio
import io
import threading
from contextlib import asynccontextmanager

import aiohttp
import pytest
from PIL import Image

from bot import db as db_backend
from tests.test_shared_accounts import (
    ROOT,
    account_database,
    enable,
    login,
    preview_client,
    vk_launch,
)

__all__ = ['account_database']


def photo_bytes(format='PNG'):
    output = io.BytesIO()
    Image.new('RGB', (3, 2), (22, 144, 200)).save(output, format=format)
    return output.getvalue()


def upload_body(raw=None, mime='image/png'):
    body = aiohttp.FormData()
    body.add_field('file', photo_bytes() if raw is None else raw,
                   filename='private-name-secret.png', content_type=mime)
    return body


@asynccontextmanager
async def native_client(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    async with preview_client() as client:
        await enable(client, vk_app_id=123, vk_admin_ids=[2001, 2002])
        actors = []
        for user_id in (2001, 2002):
            login = await client.post(ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(user_id)})
            assert login.status == 200
            session = await login.json()
            actors.append({'Authorization': 'Bearer ' + session['session_token']})
        yield client, actors


@pytest.mark.parametrize('format', ['PNG', 'JPEG', 'WEBP'])
async def test_vk_only_upload_list_private_media_and_remove_without_telegram_user(monkeypatch, tmp_path, format):
    async with native_client(monkeypatch, tmp_path) as (client, (owner, _)):
        uploaded = await client.post(ROOT + '/references', headers=owner, data=upload_body(photo_bytes(format)))
        assert uploaded.status == 200, await uploaded.text()
        item = (await uploaded.json())['reference']
        assert item['mime'] == 'image/png'
        assert (item['width'], item['height']) == (3, 2)
        assert not {'url', 'storage_key', 'account_id', 'path'} & item.keys()
        listing = await (await client.get(ROOT + '/references', headers=owner)).json()
        assert [row['id'] for row in listing['references']] == [item['id']]
        media = await client.get(ROOT + f"/references/{item['id']}/content", headers=owner)
        assert media.status == 200
        assert media.headers['Cache-Control'] == 'no-store'
        assert media.headers['X-Content-Type-Options'] == 'nosniff'
        with Image.open(io.BytesIO(await media.read())) as decoded:
            assert decoded.format == 'PNG' and decoded.size == (3, 2)
        assert not list((tmp_path / 'static').rglob('*.png'))
        async with db_backend.connect() as db:
            assert (await (await db.execute('SELECT COUNT(*) FROM users')).fetchone())[0] == 0
        removed = await client.delete(ROOT + f"/references/{item['id']}", headers=owner)
        assert removed.status == 200
        assert (await client.delete(ROOT + f"/references/{item['id']}", headers=owner)).status == 200
        assert (await (await client.get(ROOT + '/references', headers=owner)).json())['references'] == []
        assert (await client.get(ROOT + f"/references/{item['id']}/content", headers=owner)).status == 404


async def test_another_account_and_query_tokens_cannot_read_or_remove_private_photo(monkeypatch, tmp_path):
    async with native_client(monkeypatch, tmp_path) as (client, (owner, other)):
        uploaded = await client.post(ROOT + '/references', headers=owner, data=upload_body())
        assert uploaded.status == 200
        item = (await uploaded.json())['reference']
        path = ROOT + f"/references/{item['id']}"
        assert (await client.get(path + '/content', headers=other)).status == 404
        assert (await client.delete(path, headers=other)).status == 404
        token = owner['Authorization'].removeprefix('Bearer ')
        assert (await client.get(path + '/content?session_token=' + token)).status == 401
        assert (await client.get(path + '/content', headers=owner)).status == 200


@pytest.mark.parametrize('raw', [b'<svg xmlns="http://www.w3.org/2000/svg"/>', b'not a photo', photo_bytes()[:30]])
async def test_declared_image_mime_cannot_save_invalid_image(monkeypatch, tmp_path, raw):
    async with native_client(monkeypatch, tmp_path) as (client, (owner, _)):
        response = await client.post(ROOT + '/references', headers=owner, data=upload_body(raw))
        assert response.status == 400
        assert (await (await client.get(ROOT + '/references', headers=owner)).json())['references'] == []


async def test_unauthenticated_upload_does_not_read_or_persist_file(monkeypatch, tmp_path):
    async with native_client(monkeypatch, tmp_path) as (client, _):
        response = await client.post(ROOT + '/references', data=upload_body())
        assert response.status == 401
        assert not (tmp_path / 'data' / 'account_references').exists()


async def test_only_the_file_field_is_accepted_and_stream_size_is_bounded(monkeypatch, tmp_path):
    from bot.shared_accounts import references

    async with native_client(monkeypatch, tmp_path) as (client, (owner, _)):
        extra = upload_body()
        extra.add_field('account_id', 'another-owner')
        assert (await client.post(ROOT + '/references', headers=owner, data=extra)).status == 400
        monkeypatch.setattr(references, 'DEFAULT_UPLOAD_MAX_BYTES', 12)
        assert (await client.post(ROOT + '/references', headers=owner, data=upload_body())).status == 413
        assert (await (await client.get(ROOT + '/references', headers=owner)).json())['references'] == []
        assert not list((tmp_path / 'data' / 'account_references').glob('*'))


async def test_first_multipart_part_is_inside_the_upload_deadline(monkeypatch, tmp_path):
    from bot.shared_accounts import references

    async with native_client(monkeypatch, tmp_path) as (client, (owner, _)):
        stalled = asyncio.Event()

        async def delayed_part(_reader):
            await stalled.wait()

        monkeypatch.setattr(aiohttp.MultipartReader, 'next', delayed_part)
        monkeypatch.setattr(references, 'UPLOAD_TIMEOUT_SECONDS', 0.03)
        request = asyncio.create_task(client.post(ROOT + '/references', headers=owner, data=upload_body()))
        try:
            response = await asyncio.wait_for(asyncio.shield(request), timeout=0.3)
            assert response.status == 408
            assert (await response.json())['error_code'] == 'upload_timeout'
            assert not list((tmp_path / 'data' / 'account_references').glob('*'))
        finally:
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)


async def test_session_revocation_and_policy_shutdown_deny_private_media(monkeypatch, tmp_path):
    from tests.test_shared_accounts import telegram_launch

    async with native_client(monkeypatch, tmp_path) as (client, (owner, other)):
        item = (await (await client.post(ROOT + '/references', headers=owner, data=upload_body())).json())['reference']
        await client.post(ROOT + '/logout', headers=owner)
        assert (await client.get(ROOT + f"/references/{item['id']}/content", headers=owner)).status == 401
        response = await client.put(ROOT + '/settings', json={
            'init_data': telegram_launch(), 'expected_revision': 1, 'settings': {'enabled': False},
        })
        assert response.status == 200
        assert (await client.get(ROOT + '/references', headers=other)).status == 404
        assert (await client.post(ROOT + '/references', headers=other, data=upload_body())).status == 404


async def test_photos_of_both_real_identities_survive_confirmed_merge(monkeypatch, tmp_path):
    from tests.test_shared_account_links import commit_link

    async with native_client(monkeypatch, tmp_path) as (client, (vk, other)):
        telegram_session = await (await login(client)).json()
        telegram = {'Authorization': 'Bearer ' + telegram_session['session_token']}
        before = set()
        ids = set()
        for headers in (telegram, vk):
            before.add((await (await client.get(ROOT + '/me', headers=headers)).json())['account']['id'])
            item = (await (await client.post(ROOT + '/references', headers=headers, data=upload_body())).json())['reference']
            ids.add(item['id'])
        assert len((await (await client.get(ROOT + '/references', headers=vk)).json())['references']) == 1
        merged, _ = await commit_link(client, telegram, vk)
        assert merged.status == 200
        fresh = await (await client.post(ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(2001)})).json()
        headers = {'Authorization': 'Bearer ' + fresh['session_token']}
        rows = (await (await client.get(ROOT + '/references', headers=headers)).json())['references']
        assert {row['id'] for row in rows} == ids
        for item_id in ids:
            assert (await client.get(ROOT + f'/references/{item_id}/content', headers=headers)).status == 200
            assert (await client.get(ROOT + f'/references/{item_id}/content', headers=other)).status == 404
        async with db_backend.connect() as db:
            owners = await (await db.execute('SELECT DISTINCT account_id FROM shared_account_references')).fetchall()
            assert {row[0] for row in owners} == before  # Provenance is not rewritten by merge.
            assert (await (await db.execute('SELECT COUNT(*) FROM users')).fetchone())[0] == 0


async def test_private_media_never_uses_a_client_or_corrupted_storage_path(monkeypatch, tmp_path):
    async with native_client(monkeypatch, tmp_path) as (client, (owner, _)):
        item = (await (await client.post(ROOT + '/references', headers=owner, data=upload_body())).json())['reference']
        async with db_backend.connect() as db:
            await db.execute('UPDATE shared_account_references SET storage_key = ? WHERE id = ?', ('../../private.txt', item['id']))
            await db.commit()
        (tmp_path / 'private.txt').write_text('not user media')
        response = await client.get(ROOT + f"/references/{item['id']}/content", headers=owner)
        assert response.status == 404
        assert 'not user media' not in await response.text()


async def test_metadata_and_thumbnails_do_not_expose_launch_token_or_filename(monkeypatch, tmp_path, caplog):
    async with native_client(monkeypatch, tmp_path) as (client, (owner, _)):
        item = (await (await client.post(ROOT + '/references', headers=owner, data=upload_body())).json())['reference']
        thumbnail = await client.get(ROOT + f"/references/{item['id']}/thumbnail", headers=owner)
        assert thumbnail.status == 200
        with Image.open(io.BytesIO(await thumbnail.read())) as image:
            assert max(image.size) <= 384
        assert 'private-name-secret' not in caplog.text
        assert owner['Authorization'] not in caplog.text


@pytest.mark.parametrize('representation', ['content', 'thumbnail'])
async def test_corrupted_private_file_is_reported_instead_of_served_as_a_broken_preview(monkeypatch, tmp_path, representation):
    from bot.shared_accounts.api import REFERENCE_STORE

    async with native_client(monkeypatch, tmp_path) as (client, (owner, _)):
        item = (await (await client.post(ROOT + '/references', headers=owner, data=upload_body())).json())['reference']
        root = client.server.app[REFERENCE_STORE].root
        suffix = '.thumbnail.png' if representation == 'thumbnail' else '.png'
        (root / (item['id'] + suffix)).write_bytes(b'broken image')
        response = await client.get(ROOT + f"/references/{item['id']}/{representation}", headers=owner)
        assert response.status == 404
        assert (await response.json())['error_code'] == 'reference_unavailable'


async def test_decoding_applies_orientation_and_strips_private_image_metadata(monkeypatch, tmp_path):
    raw = io.BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    exif[271] = 'private-camera-secret'
    Image.new('RGB', (3, 2), (1, 2, 3)).save(raw, format='JPEG', exif=exif)
    async with native_client(monkeypatch, tmp_path) as (client, (owner, _)):
        response = await client.post(ROOT + '/references', headers=owner, data=upload_body(raw.getvalue()))
        item = (await response.json())['reference']
        assert (item['width'], item['height']) == (2, 3)
        media = await client.get(ROOT + f"/references/{item['id']}/content", headers=owner)
        with Image.open(io.BytesIO(await media.read())) as image:
            assert image.size == (2, 3)
            assert not image.getexif()


async def test_pixel_limit_is_checked_before_unbounded_decode(monkeypatch, tmp_path):
    raw = io.BytesIO()
    Image.new('RGB', (5001, 5000)).save(raw, format='PNG')
    async with native_client(monkeypatch, tmp_path) as (client, (owner, _)):
        response = await client.post(ROOT + '/references', headers=owner, data=upload_body(raw.getvalue()))
        assert response.status == 400
        assert (await response.json())['error_code'] == 'media_dimensions_limit'
        assert not list((tmp_path / 'data' / 'account_references').glob('*'))


async def test_long_normalization_rechecks_revocation_before_persistence(monkeypatch, tmp_path):
    from bot.shared_accounts.api import REFERENCE_STORE

    async with native_client(monkeypatch, tmp_path) as (client, (owner, _)):
        await client.get(ROOT + '/references', headers=owner)
        store = client.server.app[REFERENCE_STORE]
        original = store._normalize
        entered, released = threading.Event(), threading.Event()

        def delayed(item_id):
            prepared = original(item_id)
            entered.set()
            assert released.wait(3)
            return prepared

        monkeypatch.setattr(store, '_normalize', delayed)
        upload = asyncio.create_task(client.post(ROOT + '/references', headers=owner, data=upload_body()))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            assert (await client.post(ROOT + '/logout', headers=owner)).status == 200
            released.set()
            assert (await upload).status == 401
        finally:
            released.set()
            await asyncio.gather(upload, return_exceptions=True)
        async with db_backend.connect() as db:
            assert (await (await db.execute('SELECT COUNT(*) FROM shared_account_references')).fetchone())[0] == 0
        assert not list(store.root.glob('*'))


@pytest.mark.parametrize('phase', ['before_commit', 'after_commit'])
async def test_uncertain_commit_never_deletes_a_saved_photo(monkeypatch, tmp_path, phase):
    from bot.shared_accounts.api import REFERENCE_STORE

    async with native_client(monkeypatch, tmp_path) as (client, (owner, _)):
        account_id = (await (await client.get(ROOT + '/me', headers=owner)).json())['account']['id']
        store = client.server.app[REFERENCE_STORE]
        transaction = store._transaction

        @asynccontextmanager
        async def interrupted(account):
            async with transaction(account) as state:
                yield state
                if phase == 'before_commit':
                    raise OSError('synthetic failed commit')
            raise asyncio.CancelledError('synthetic lost acknowledgement')

        async def chunks():
            yield photo_bytes()

        async def authorize():
            return None

        monkeypatch.setattr(store, '_transaction', interrupted)
        with pytest.raises(OSError if phase == 'before_commit' else asyncio.CancelledError):
            await store.save(account_id, chunks(), reauthorize=authorize)
        monkeypatch.setattr(store, '_transaction', transaction)
        rows = (await (await client.get(ROOT + '/references', headers=owner)).json())['references']
        assert len(rows) == (0 if phase == 'before_commit' else 1)
        if rows:
            media = await client.get(ROOT + f"/references/{rows[0]['id']}/content", headers=owner)
            assert media.status == 200
            with Image.open(io.BytesIO(await media.read())) as decoded:
                assert decoded.size == (3, 2)
        assert not list(store.root.glob('*.input'))
        assert not list(store.root.glob('*.staging'))


async def test_cancellation_waits_for_worker_before_removing_its_files(monkeypatch, tmp_path):
    from bot.shared_accounts.api import REFERENCE_STORE

    async with native_client(monkeypatch, tmp_path) as (client, (owner, _)):
        account_id = (await (await client.get(ROOT + '/me', headers=owner)).json())['account']['id']
        store = client.server.app[REFERENCE_STORE]
        original = store._normalize
        entered, released = threading.Event(), threading.Event()

        def delayed(item_id):
            entered.set()
            assert released.wait(3)
            return original(item_id)

        async def chunks():
            yield photo_bytes()

        async def authorize():
            return None

        monkeypatch.setattr(store, '_normalize', delayed)
        task = asyncio.create_task(store.save(account_id, chunks(), reauthorize=authorize))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert list(store.root.glob('*.input'))  # The decoder still owns its input.
        finally:
            released.set()
        for _ in range(100):
            if not list(store.root.glob('*')):
                break
            await asyncio.sleep(0.01)
        assert not list(store.root.glob('*'))
        assert (await (await client.get(ROOT + '/references', headers=owner)).json())['references'] == []


async def test_cancelled_uploads_keep_real_decoder_concurrency_bounded(monkeypatch, tmp_path):
    from bot.shared_accounts.api import REFERENCE_STORE

    async with native_client(monkeypatch, tmp_path) as (client, (owner, _)):
        account_id = (await (await client.get(ROOT + '/me', headers=owner)).json())['account']['id']
        store = client.server.app[REFERENCE_STORE]
        original = store._normalize
        entered = [threading.Event() for _ in range(3)]
        released, lock = threading.Event(), threading.Lock()
        count = 0

        def delayed(item_id):
            nonlocal count
            with lock:
                index = count
                count += 1
            entered[index].set()
            assert released.wait(5)
            return original(item_id)

        async def chunks():
            yield photo_bytes()

        async def authorize():
            return None

        monkeypatch.setattr(store, '_normalize', delayed)
        tasks = [asyncio.create_task(store.save(account_id, chunks(), reauthorize=authorize)) for _ in range(2)]
        try:
            for event in entered[:2]:
                assert await asyncio.to_thread(event.wait, 3)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            tasks.append(asyncio.create_task(store.save(account_id, chunks(), reauthorize=authorize)))
            assert not await asyncio.to_thread(entered[2].wait, 0.15), 'Cancelled decoders still occupy both permits'
            released.set()
            assert await asyncio.to_thread(entered[2].wait, 3)
            assert (await tasks[2])['mime'] == 'image/png'
        finally:
            released.set()
            await asyncio.gather(*tasks, return_exceptions=True)
