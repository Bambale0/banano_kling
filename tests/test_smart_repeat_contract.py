"""Smart repeats preserve provider slots independently of upload/display order."""
from copy import deepcopy

import pytest

from bot.smart_repeat_contract import (
    SmartRepeatError,
    compile_bindings,
    configure_template,
    infer_template,
    public_template,
)


def source(model='seedance_2_5'):
    return {
        'id': 42, 'user_id': 7, 'type': 'video', 'status': 'completed',
        'is_public_feed': True, 'model': model, 'prompt': 'Use @Image1 face and @Image2 car',
        'duration': 5, 'aspect_ratio': '9:16',
        'request_data': {'v_model': model, 'v_type': 'video', 'seedance25_scenario': 'multimodal',
                         'seedance25_resolution': '720p',
                         'reference_images': ['/uploads/refs/original-face.png', '/uploads/refs/original-car.png']},
        'feed_repeat_reference_selection': {'version': 1, 'images': [], 'videos': []},
    }


def ready(url, asset_id):
    return {'state': 'READY', 'url': url, 'asset_id': asset_id}


def test_reverse_upload_and_display_order_do_not_swap_provider_bindings():
    task = source()
    template = infer_template(task)
    first, second = template['slots']
    draft = {'slots': {second['slot_id']: ready('/uploads/refs/my-car.png', 'car'),
                       first['slot_id']: ready('/uploads/refs/my-face.png', 'face')}}
    submitted = public_template(template)
    submitted['slots'].reverse()
    submitted['slots'][0]['label'] = 'Ваша машина'
    configured = configure_template(task, submitted)
    compiled = compile_bindings(task, configured, draft)
    assert compiled['body']['reference_images'] == ['/uploads/refs/my-face.png', '/uploads/refs/my-car.png']
    assert compiled['snapshot']['references'][first['slot_id']]['asset_id'] == 'face'
    assert compiled['snapshot']['references'][second['slot_id']]['asset_id'] == 'car'
    assert 'original-face' not in str(public_template(configured))
    assert 'Use @Image1' not in str(public_template(configured))


@pytest.mark.parametrize('state', ['EMPTY', 'UPLOADING', 'PROCESSING', 'FAILED'])
def test_every_required_slot_must_be_server_ready(state):
    task = source()
    template = infer_template(task)
    slots = template['slots']
    draft = {'slots': {slots[0]['slot_id']: ready('/uploads/refs/my-face.png', 'face'),
                       slots[1]['slot_id']: {'state': state, 'url': '/uploads/refs/partial.png'}}}
    with pytest.raises(SmartRepeatError, match='REFERENCES_NOT_READY'):
        compile_bindings(task, template, draft)


def test_extra_slot_and_alias_duplicate_are_rejected():
    task = source()
    template = infer_template(task)
    ids = [slot['slot_id'] for slot in template['slots']]
    draft = {'slots': {ids[0]: ready('/uploads/refs/same.png', 'a'),
                       ids[1]: ready('https://tanyapi.chillcreative.ru/uploads/refs/same.png', 'b')}}
    with pytest.raises(SmartRepeatError, match='DUPLICATE_ASSET'):
        compile_bindings(task, template, draft)
    draft['slots']['injected-slot'] = ready('/uploads/refs/extra.png', 'c')
    with pytest.raises(SmartRepeatError, match='INVALID_SLOTS'):
        compile_bindings(task, template, draft)


def test_author_cannot_make_missing_file_optional_or_invent_provider_slot():
    task = source()
    template = infer_template(task)
    submitted = public_template(template)
    submitted['slots'][0]['required'] = False
    with pytest.raises(SmartRepeatError, match='ORIGINAL_NOT_PERMITTED'):
        configure_template(task, submitted)
    submitted = public_template(template)
    submitted['slots'].append({**submitted['slots'][0], 'slot_id': 'invented'})
    with pytest.raises(SmartRepeatError, match='INVALID_SLOTS'):
        configure_template(task, submitted)


def test_preset_can_only_keep_explicitly_permitted_originals_and_hides_prompt():
    task = source()
    task['feed_repeat_reference_selection']['images'] = list(task['request_data']['reference_images'])
    template = infer_template(task)
    face, car = template['slots']
    submitted = public_template(template)
    for slot in submitted['slots']:
        slot.update(binding='upload', required=True)
    submitted['presets'] = [{'id': 'face', 'label': 'Лицо', 'slot_ids': [face['slot_id']]},
                            {'id': 'car', 'label': 'Машина', 'slot_ids': [car['slot_id']]}]
    configured = configure_template(task, submitted)
    compiled = compile_bindings(task, configured, {'preset_id': 'face',
        'slots': {face['slot_id']: ready('/uploads/refs/my-face.png', 'face')}})
    assert compiled['body']['reference_images'] == ['/uploads/refs/my-face.png']
    assert compiled['source']['feed_repeat_reference_selection']['images'] == ['/uploads/refs/original-car.png']
    assert compiled['snapshot']['references'][car['slot_id']]['binding'] == 'fixed'
    changed = deepcopy(task)
    changed['feed_repeat_reference_selection']['images'] = []
    with pytest.raises(SmartRepeatError):
        configure_template(changed, submitted)


def test_wan_and_generic_models_reuse_their_existing_provider_slot_mapping():
    task = source('wan_3')
    task['request_data'] = {'model': 'wan_3', 'scenario': 'reference', 'prompt': task['prompt'],
        'resolution': '720P', 'aspect_ratio': '9:16', 'duration': 5,
        'reference_image_urls': ['/uploads/refs/one.png', '/uploads/refs/two.png']}
    template = infer_template(task)
    one, two = template['slots']
    compiled = compile_bindings(task, template, {'slots': {
        two['slot_id']: ready('/uploads/refs/new-two.png', 'two'),
        one['slot_id']: ready('/uploads/refs/new-one.png', 'one')}})
    assert compiled['body']['repeat_replacements'] == {
        'image:0': '/uploads/refs/new-one.png', 'image:1': '/uploads/refs/new-two.png'}


def test_added_slot_uses_capability_budget_and_keeps_stable_provider_index():
    import uuid
    task = source()
    submitted = public_template(infer_template(task), author=True)
    sid = uuid.uuid4().hex
    submitted['slots'].append({'slot_id': sid, 'kind': 'image', 'binding': 'upload',
        'required': True, 'label': 'Ваш торт', 'constraints': {'mime_types': ['image/png'], 'max_bytes': 1024}})
    configured = configure_template(task, submitted)
    assert configured['slots'][-1]['index'] == 2
    next_schema = public_template(configured, author=True)
    next_schema['slots'].reverse()
    configured = configure_template(task, next_schema, previous=configured)
    assert configured['slots'][0]['slot_id'] == sid and configured['slots'][0]['index'] == 2
    draft = {'slots': {slot['slot_id']: ready(f'/uploads/{slot["index"]}.png', str(slot['index'])) for slot in configured['slots']}}
    compiled = compile_bindings(task, configured, draft)
    assert compiled['body']['reference_images'] == ['/uploads/0.png', '/uploads/1.png', '/uploads/2.png']
    assert compiled['source']['request_data']['reference_images'] == compiled['body']['reference_images']
    from bot.smart_repeat_policy import validate_asset
    with pytest.raises(SmartRepeatError, match='ASSET_CONSTRAINTS_INVALID'):
        validate_asset(configured['slots'][0], {'size_bytes': 1025, 'media': {'mime_type': 'image/png'}})
    with pytest.raises(SmartRepeatError, match='ASSET_CONSTRAINTS_INVALID'):
        validate_asset(configured['slots'][0], {'size_bytes': 100, 'media': {'mime_type': 'image/jpeg'}})
    too_many = public_template(configured)
    for _ in range(30):
        too_many['slots'].append({**submitted['slots'][-1], 'slot_id': uuid.uuid4().hex})
    with pytest.raises(SmartRepeatError, match='MODEL_CONSTRAINTS_INVALID'):
        configure_template(task, too_many, previous=configured)


@pytest.mark.parametrize('model,maximum', [('seedance_2', 9), ('grok_imagine', 7)])
def test_mixed_frame_and_list_share_the_actual_provider_budget(model, maximum):
    import uuid
    task = source(model)
    task['prompt'] = 'Use the supplied images'
    task['request_data'] = {'v_type': 'imgtxt', 'v_image_url': '/uploads/frame.png',
        'reference_images': [f'/uploads/reference{index}.png' for index in range(maximum - 1)]}
    template = infer_template(task)
    submitted = public_template(template, author=True)
    assert len(configure_template(task, submitted)['slots']) == maximum
    submitted['slots'].append({'slot_id': uuid.uuid4().hex, 'kind': 'image', 'binding': 'upload',
        'required': True, 'label': 'Extra image'})
    with pytest.raises(SmartRepeatError, match='MODEL_CONSTRAINTS_INVALID'):
        configure_template(task, submitted)


def registered_repeat_models():
    from bot.miniapp import IMAGE_MODELS, VIDEO_MODELS
    from bot.model_capabilities import VIDEO_MODEL_CAPABILITIES
    return [(item['id'], 'image') for item in IMAGE_MODELS] + [
        (model, 'video') for model in sorted({item['id'] for item in VIDEO_MODELS} | set(VIDEO_MODEL_CAPABILITIES))]


@pytest.mark.parametrize('model,kind', registered_repeat_models())
def test_registered_repeat_models_keep_source_identity_settings_and_hidden_prompt(model, kind):
    from bot.smart_repeat_api import _engine_body
    task = source(model)
    task.update(type=kind, prompt='Private {{subject}} recipe', duration=5, aspect_ratio='9:16')
    task['request_data'] = {'img_quality': '4K', 'img_ratio': '9:16', 'v_ratio': '9:16',
        'v_model': model, 'img_service': model, 'v_type': 'imgtxt',
        'v_image_url': '/uploads/refs/source.png', 'reference_images': ['/uploads/refs/source.png'],
        'seedance25_resolution': '720p', 'seedance25_scenario': 'multimodal'}
    if model in {'wan_3', 'wan_3_prime'}:
        task['request_data'] = {'model': model, 'scenario': 'reference', 'prompt': task['prompt'],
            'resolution': '720P', 'aspect_ratio': '9:16', 'duration': 5,
            'reference_image_urls': ['/uploads/refs/source.png']}
    template = infer_template(task)
    template['variables'] = [{'id': 'subject', 'label': 'Сюжет', 'required': True, 'max_length': 40}]
    state = {'slots': {slot['slot_id']: ready('/uploads/refs/mine.png', 'my-media') for slot in template['slots']},
        'user_values': {'subject': 'car'}}
    compiled = compile_bindings(task, template, state)
    body = _engine_body(None, task, compiled, {'img_service': 'banana_pro', 'v_model': 'banana_pro',
        'model': 'banana_pro', 'prompt': 'forged prompt'}, {'id': 'test-draft'})
    assert template['model'] == compiled['snapshot']['model'] == model
    assert compiled['source']['prompt'] == 'Private car recipe'
    assert task['prompt'] == 'Private {{subject}} recipe'
    assert 'Private' not in str(public_template(template))
    if model in {'wan_3', 'wan_3_prime'}:
        assert body['model'] == model
        assert body['repeat_replacements'] == {'image:0': '/uploads/refs/mine.png'}
    else:
        assert body['img_service'] == body['v_model'] == model
        assert body['img_quality'] == '4K'
        assert body['img_ratio'] == body['v_ratio'] == '9:16'
        assert body['seedance25_resolution'] == '720p'
        assert body['prompt'] == ''
