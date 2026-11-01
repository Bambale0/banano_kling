import json

import pytest

from bot import repeat_personalization as subject

PROMPT = 'A woman in a blue coat by a red car. Camera follows @Image1.'


def raw_fields():
    return [{
        'key': 'outfit', 'label': 'Наряд девушки', 'original_value': 'blue coat',
        'image_choices': [
            {'id': 'dress', 'label': 'Чёрное платье', 'image_url': 'https://neuromixbot.com/uploads/repeat-choices/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg'},
            {'id': 'suit', 'label': 'Костюм', 'image_url': 'https://neuromixbot.com/uploads/repeat-choices/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg'},
        ],
        'allow_custom_image': True,
    }]


def test_image_choice_survives_normalization_storage_and_public_dto():
    fields = subject.normalize_repeat_fields(raw_fields(), prompt=PROMPT)
    public = subject.public_repeat_fields(subject._decode_fields(json.dumps(fields)))
    assert public[0]['image_choices'] == raw_fields()[0]['image_choices']
    assert public[0]['allow_custom_image'] is True
    assert 'blue coat' not in json.dumps(public)


def test_choice_uses_real_image_tag_after_existing_identity_and_retained_images():
    fields = subject.normalize_repeat_fields(raw_fields(), prompt=PROMPT)
    rendered = subject.render_repeat_base(PROMPT, fields, {'outfit': 'dress'}, image_start_index=3)
    assert '@Image3' in rendered
    assert '@Image1' in rendered
    assert 'red car' in rendered
    assert 'blue coat' not in rendered
    assert subject.repeat_image_references(fields, {'outfit': 'dress'}, telegram_id=42) == [
        'https://neuromixbot.com/uploads/repeat-choices/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg',
    ]


def test_forged_choice_and_foreign_custom_upload_rejected():
    fields = subject.normalize_repeat_fields(raw_fields(), prompt=PROMPT)
    for value in ['missing', 'https://evil.test/private', 'upload:https://neuromixbot.com/uploads/refs/image/99/foreign.jpg']:
        with pytest.raises(ValueError):
            subject.repeat_image_references(fields, {'outfit': value}, telegram_id=42)


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'http://127.0.0.1/private', 'https://neuromixbot.com/uploads/refs/image/42/temp.jpg'])
def test_author_cannot_save_unsafe_or_retention_managed_choice(url):
    raw = raw_fields()
    raw[0]['image_choices'][0]['image_url'] = url
    with pytest.raises(ValueError):
        subject.normalize_repeat_fields(raw, prompt=PROMPT)


def test_own_variant_must_be_enabled_and_belong_to_current_actor():
    fields = subject.normalize_repeat_fields(raw_fields(), prompt=PROMPT)
    own = 'upload:https://neuromixbot.com/uploads/refs/image/42/custom.jpg'
    assert subject.repeat_image_references(fields, {'outfit': own}, telegram_id=42) == [own[7:]]
    fields[0]['allow_custom_image'] = False
    with pytest.raises(ValueError):
        subject.repeat_image_references(fields, {'outfit': own}, telegram_id=42)


def test_repeated_image_reuses_its_actual_provider_ordinal():
    existing = ['https://neuromixbot.com/uploads/refs/image/42/person.jpg']
    choice = raw_fields()[0]['image_choices'][0]['image_url']
    assert subject.append_repeat_images(existing, [choice, choice]) == [2, 2]
    assert len(existing) == 2


def test_existing_host_aliases_do_not_shift_selected_image_ordinals():
    existing = ['https://neuromixbot.com/uploads/refs/image/42/person.jpg',
                'https://cdn.chillcreative.ru/uploads/refs/image/42/person.jpg']
    choice = raw_fields()[0]['image_choices'][0]['image_url']
    assert subject.append_repeat_images(existing, [choice]) == [2]
    assert existing == ['https://neuromixbot.com/uploads/refs/image/42/person.jpg', choice]


async def test_seedream_effective_provider_cap_rejects_selected_image_before_mutation(monkeypatch):
    from bot import miniapp

    monkeypatch.setenv(subject.FEATURE_FLAG, '1')
    monkeypatch.setattr(miniapp.config, 'is_admin', lambda _id: True)
    fields = subject.normalize_repeat_fields(raw_fields(), prompt=PROMPT)
    await subject.save_repeat_fields(42, fields, actor_telegram_id=42)
    images = [f'https://example.test/ref{index}.jpg' for index in range(5)]
    with pytest.raises(ValueError, match='Слишком много референсов'):
        await miniapp._repeat_personalized_source_prompt(42, PROMPT, {'repeat_user_values': {'outfit': 'dress'}},
            telegram_id=42, image_references=images, image_model='seedream_edit')
    assert len(images) == 5


async def test_wan_real_probe_accepts_only_the_selected_local_catalog_asset(tmp_path, monkeypatch):
    import io
    from types import SimpleNamespace

    from PIL import Image

    from bot.services.wan3_prime_media import Wan3PrimeValidationError
    from bot.services.wan3_prime_repeat import ConsentedMediaProbe
    from bot.services.wan3_prime_storage import ActualWan3PrimeProbe

    monkeypatch.chdir(tmp_path)
    raw = io.BytesIO()
    Image.new('RGB', (512, 512), 'white').save(raw, format='PNG')
    selected = subject.save_repeat_choice_image(raw.getvalue())
    actor = SimpleNamespace(user_id=7, telegram_id=42)
    plan = {'owner_id': 8, 'owner_telegram_id': 43, 'slots': []}
    probe = ConsentedMediaProbe(ActualWan3PrimeProbe(), actor, plan, [selected])
    info = await probe.probe_url(selected, kind='image')
    assert info.width == info.height == 512
    assert info.url == selected
    assert len(info.sha256) == 64
    # A completed personalized result can itself be published with explicit
    # consent for the same catalog asset, without a wan3_prime_media row.
    plan['slots'] = [{'kind': 'image', 'url': selected, 'binding': 'fixed'}]
    next_repeat_probe = ConsentedMediaProbe(ActualWan3PrimeProbe(), actor, plan)
    assert (await next_repeat_probe.probe_url(selected, kind='image')).sha256 == info.sha256
    with pytest.raises(Wan3PrimeValidationError, match='imported or uploaded'):
        await probe.probe_url('https://example.test/unselected.jpg', kind='image')


@pytest.mark.parametrize('model,scenario,expected', [
    ('seedance_2', 'text', True), ('seedance_2_5', 'multimodal', True),
    ('seedance_2_5', 'first_frame', False), ('wan_3', 'edit', True),
    ('wan_3_prime', 'reference', True), ('wan_3_prime', 'first_frame', False),
    ('grok_imagine_v15', 'imgtxt', False),
])
def test_only_supported_video_recipes_can_offer_image_choices(model, scenario, expected):
    assert subject.repeat_image_mode_supported({
        'type': 'video', 'model': model, 'request_data': {'seedance25_scenario': scenario, 'scenario': scenario},
    }) is expected


def test_catalog_upload_is_reencoded_and_survives_outside_personal_retention(tmp_path, monkeypatch):
    import io
    from pathlib import Path

    from PIL import Image

    monkeypatch.chdir(tmp_path)
    raw = io.BytesIO()
    Image.new('RGB', (300, 400), 'blue').save(raw, format='PNG')
    url = subject.save_repeat_choice_image(raw.getvalue())
    path = Path('static/uploads') / url.split('/uploads/', 1)[-1]
    assert path.is_file()
    assert '/refs/' not in url
    with Image.open(path) as decoded:
        assert decoded.format == 'JPEG'
        assert decoded.size == (300, 400)


async def test_configured_catalog_survives_the_real_scheduled_upload_cleanup(tmp_path, monkeypatch):
    import ast
    import logging
    import os
    import time
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / 'bot/main.py').read_text()
    tree = ast.parse(source)
    cleanup = next(node for node in tree.body if getattr(node, 'name', '') == '_remove_old_files')
    loop = next(node for node in tree.body if getattr(node, 'name', '') == '_cleanup_loop')
    call = next(node for node in ast.walk(loop) if isinstance(node, ast.Call)
                and getattr(node.func, 'id', '') == '_remove_old_files'
                and node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == 'static/uploads')
    excluded = ast.literal_eval(next(item.value for item in call.keywords if item.arg == 'skip_dirnames'))
    namespace = {'os': os, 'time': time, 'logger': logging.getLogger('catalog-cleanup')}
    exec(compile(ast.Module(body=[cleanup], type_ignores=[]), '<upload-cleanup>', 'exec'), namespace)  # noqa: S102
    monkeypatch.chdir(tmp_path)
    catalog = Path('static/uploads/repeat-choices')
    catalog.mkdir(parents=True)
    selected = catalog / ('a' * 32 + '.jpg')
    selected.write_bytes(b'active-catalog-asset')
    temporary = Path('static/uploads/old-temporary.jpg')
    temporary.write_bytes(b'temporary')
    os.utime(selected, (0, 0))
    os.utime(temporary, (0, 0))
    await namespace['_remove_old_files']('static/uploads', 1, skip_dirnames=excluded)
    assert selected.read_bytes() == b'active-catalog-asset'
    assert not temporary.exists()


@pytest.mark.parametrize('admin,flag,expected', [(True, '1', 200), (False, '1', 403), (True, '0', 403)])
async def test_catalog_http_upload_is_admin_only_and_not_a_personal_reference(monkeypatch, tmp_path, admin, flag, expected):
    import base64
    import io
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from PIL import Image

    from bot import miniapp

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(subject.FEATURE_FLAG, flag)
    monkeypatch.setattr(miniapp.config, 'is_admin', lambda _id: admin)
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(42, {})))
    personal_save = AsyncMock(side_effect=AssertionError('catalog must not enter personal retention'))
    monkeypatch.setattr(miniapp, 'save_reference_file', personal_save)
    picture = io.BytesIO()
    Image.new('RGB', (300, 400), 'white').save(picture, format='PNG')
    request = SimpleNamespace(app={}, content_type='application/json', json=AsyncMock(return_value={
        'init_data': 'signed', 'file_kind': 'repeat_choice_image', 'filename': 'dress.png',
        'content_type': 'image/png', 'data_base64': base64.b64encode(picture.getvalue()).decode(),
    }))
    response = await miniapp.miniapp_upload(request)
    assert response.status == expected, response.text
    if expected == 200:
        payload = json.loads(response.text)
        assert '/uploads/repeat-choices/' in payload['url']
        assert payload['reference'] is None
    personal_save.assert_not_awaited()
