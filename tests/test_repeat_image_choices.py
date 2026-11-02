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
    # Image-only personalization preserves the private scene and overrides
    # its outfit via the selected reference instead of matching source text.
    assert 'blue coat' in rendered
    assert 'ПРИОРИТЕТ ПОЛЬЗОВАТЕЛЬСКИХ ИЗОБРАЖЕНИЙ' in rendered
    assert subject.repeat_image_references(fields, {'outfit': 'dress'}, telegram_id=42) == [
        'https://neuromixbot.com/uploads/repeat-choices/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg',
    ]



def test_image_group_requires_only_its_label_not_a_prompt_fragment():
    raw = raw_fields()
    raw[0]['label'] = 'Образ'
    raw[0]['original_value'] = 'образ которого нет в промпте'
    fields = subject.normalize_repeat_fields(raw, prompt=PROMPT)

    assert fields[0]['label'] == 'Образ'
    assert 'original_value' not in fields[0]
    assert 'original_value' not in subject._decode_fields(json.dumps(raw))[0]
    rendered = subject.render_repeat_base(
        PROMPT, fields, {'outfit': 'dress'}, image_indices=[2],
    )
    assert rendered.startswith(PROMPT)
    assert '«Образ»: используйте @Image2' in rendered
    assert 'имеют приоритет' in rendered


def test_image_groups_use_ordered_real_media_indices_with_face_preserved():
    raw = raw_fields()
    raw[0].pop('original_value')
    raw[0]['label'] = 'Одежда'
    for key, label, prefix in [('cake', 'Торт', 'c'), ('car', 'Машина', 'd')]:
        raw.append({
            'key': key, 'label': label,
            'image_choices': [{
                'id': key, 'label': label,
                'image_url': f"https://neuromixbot.com/uploads/repeat-choices/{prefix * 32}.jpg",
            }],
        })
    prompt = 'A woman with the face from @Image1 celebrates her birthday.'
    fields = subject.normalize_repeat_fields(raw, prompt=prompt)
    chosen = [field['image_choices'][0]['image_url'] for field in fields]
    face = 'https://neuromixbot.com/uploads/refs/image/42/face.jpg'
    provider_images = [face]
    indices = subject.append_repeat_images(provider_images, chosen)
    assert indices == [2, 3, 4]
    assert provider_images == [face, *chosen]

    rendered = subject.render_repeat_base(
        prompt, fields, {'outfit': 'dress', 'cake': 'cake', 'car': 'car'},
        image_indices=indices,
    )
    assert rendered.startswith(prompt)
    assert rendered.index('«Одежда»: используйте @Image2') < rendered.index(
        '«Торт»: используйте @Image3'
    ) < rendered.index('«Машина»: используйте @Image4')
    assert '@Image1' in rendered


def test_mixed_text_and_image_fields_keep_strict_text_source_bindings():
    raw = raw_fields()
    raw[0].pop('original_value')
    raw.append({'key': 'age', 'label': 'Возраст', 'original_value': '30'})
    base = 'Person aged 30 from @Image1 is walking by the river.'
    fields = subject.normalize_repeat_fields(raw, prompt=base)
    rendered = subject.render_repeat_base(
        base, fields, {'outfit': 'suit', 'age': '21'}, image_indices=[2],
    )
    assert 'aged 21' in rendered
    assert '«Наряд девушки»: используйте @Image2' in rendered
    raw[1]['original_value'] = 'not in prompt'
    with pytest.raises(ValueError, match='не найдено'):
        subject.normalize_repeat_fields(raw, prompt=base)


def test_duplicate_image_group_names_are_rejected_before_publish_and_repeat():
    first = raw_fields()[0]
    first.pop('original_value')
    duplicate = {**first, 'key': 'second', 'label': '  НАРЯД ДЕВУШКИ  '}
    with pytest.raises(ValueError, match='Названия групп с изображениями'):
        subject.normalize_repeat_fields([first, duplicate], prompt=PROMPT)

    # Old persisted configurations must also fail closed before a provider call.
    legacy = subject.normalize_repeat_fields([first], prompt=PROMPT)
    legacy.append({**legacy[0], 'key': 'second'})
    with pytest.raises(ValueError, match='Названия групп с изображениями'):
        subject.render_repeat_base(
            PROMPT, legacy, {'outfit': 'dress', 'second': 'dress'},
            image_indices=[2, 3],
        )


def test_image_field_requires_valid_selected_reference_indices():
    fields = subject.normalize_repeat_fields(
        [{key: value for key, value in raw_fields()[0].items()
          if key != 'original_value'}], prompt=PROMPT,
    )
    for indices in ([], [0], [True], [1, 2]):
        with pytest.raises(ValueError, match='изображени'):
            subject.render_repeat_base(PROMPT, fields, {'outfit': 'dress'}, image_indices=indices)



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


@pytest.mark.parametrize('tamper', [False, True])
async def test_wan_real_image_probe_quote_to_launch_keeps_choice_and_is_idempotent(tmp_path, monkeypatch, tamper):
    import io

    from PIL import Image

    from bot import miniapp
    from bot.services.wan3_prime_lifecycle import (
        Wan3PrimeLifecycle,
        Wan3PrimeLifecycleError,
    )
    from bot.services.wan3_prime_repeat import get_repeat_plan, public_plan
    from bot.services.wan3_prime_storage import ActualWan3PrimeProbe
    from tests.test_wan3_feed_repeat import FIXED, SECRET, USER_FACE, published_source
    from tests.test_wan3_prime_lifecycle import (
        Prices,
        Probe,
        Provider,
        balance,
        user_actor,
    )

    owner, source_id = await published_source()
    actor = await user_actor(100, telegram_id=991202)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(subject.FEATURE_FLAG, '1')
    monkeypatch.setattr(miniapp.config, 'is_admin', lambda _id: True)
    raw = io.BytesIO()
    Image.new('RGB', (512, 512), 'white').save(raw, format='PNG')
    choice = subject.save_repeat_choice_image(raw.getvalue())
    fields = subject.normalize_repeat_fields([{
        'key': 'outfit', 'label': 'Наряд', 'original_value': 'clothing',
        'image_choices': [{'id': 'dress', 'label': 'Платье', 'image_url': choice}],
    }], prompt=SECRET)
    await subject.save_repeat_fields(source_id, fields, actor_telegram_id=owner.telegram_id)

    class RealFilesProbe(Probe):
        async def probe_file(self, path, *, kind):
            return await ActualWan3PrimeProbe().probe_file(path, kind=kind)

    plan = public_plan(await get_repeat_plan(actor, source_id))
    request = {**plan['recipe'], 'source_feed_gen_id': source_id, 'repeat_plan_hash': plan['repeat_plan_hash'],
               'repeat_replacements': {'image:0': USER_FACE}, 'repeat_user_values': {'outfit': 'dress'}}
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=RealFilesProbe(), preset_manager=Prices(), transport=provider)
    quote = await lifecycle.quote(actor, request)
    if tamper:
        from pathlib import Path

        path = Path('static/uploads') / choice.split('/uploads/', 1)[1]
        Image.new('RGB', (512, 512), 'red').save(path, format='JPEG')
        with pytest.raises(Wan3PrimeLifecycleError, match='stale'):
            await lifecycle.launch(actor, request, quote, 'selected-image-once')
        assert provider.creates == 0
        assert await balance(actor.user_id) == 100
        return
    result = await lifecycle.launch(actor, request, quote, 'selected-image-once')
    assert provider.recipe.reference_image_urls == [USER_FACE, FIXED, choice]
    assert '@Image3' in provider.recipe.prompt
    assert (await lifecycle.launch(actor, request, quote, 'selected-image-once'))['task_id'] == result['task_id']
    assert provider.creates == 1


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
