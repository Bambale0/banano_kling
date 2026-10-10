"""Independent regression cases; synthetic provider only, no network."""
import pytest

from bot.services.wan3_prime_service import Wan3PrimeService


@pytest.fixture(autouse=True)
def isolated_database():
    yield


@pytest.fixture
def service(monkeypatch):
    adapter = Wan3PrimeService(kie_key='synthetic-unit-test-key')
    submissions = []
    async def submit(endpoint, payload):
        submissions.append((endpoint, payload))
        return {'task_id': 'synthetic-provider-task', 'success': True}
    monkeypatch.setattr(adapter, '_kie_post', submit)
    return adapter, submissions


@pytest.mark.asyncio
@pytest.mark.parametrize('duration', [True, False, 2.8, 'not-a-duration', 0, 31, -2])
async def test_invalid_duration_never_creates_a_different_request(service, duration):
    adapter, submissions = service
    result = await adapter.generate_video('A landscape.', duration=duration)
    assert not submissions
    assert result.get('success') is False


@pytest.mark.asyncio
@pytest.mark.parametrize('seed', [True, False, 1.2, -1, 2147483648])
async def test_invalid_seed_is_not_coerced(service, seed):
    adapter, submissions = service
    result = await adapter.generate_video('A landscape.', seed=seed)
    assert not submissions
    assert result.get('success') is False


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario,extra', [
    ('text', {'reference_image_urls': ['https://media.example/person.png']}),
    ('first_frame', {}),
    ('first_last', {'first_frame_url': 'https://media.example/start.png'}),
    ('file', {'reference_link_urls': ['https://example.com/page']}),
    ('link', {'reference_file_urls': ['https://media.example/file.pdf']}),
    ('reference', {}),
])
async def test_selected_scenario_is_never_silently_reclassified(service, scenario, extra):
    adapter, submissions = service
    result = await adapter.generate_video('A landscape.', scenario=scenario, **extra)
    assert not submissions
    assert result.get('success') is False


@pytest.mark.asyncio
async def test_empty_slot_cannot_shift_image_numbering(service):
    adapter, submissions = service
    result = await adapter.generate_video('Use Image2.', scenario='reference',
        reference_image_urls=['', 'https://media.example/person.png'])
    assert not submissions
    assert result.get('success') is False


@pytest.mark.asyncio
async def test_audio_only_false_and_zero_are_supported(service):
    adapter, submissions = service
    result = await adapter.generate_video('', scenario='reference',
        reference_audio_urls=['https://media.example/sound.mp3'], audio=False, seed=0)
    assert result.get('task_id')
    payload = submissions[0][1]
    assert payload['model'] == 'wan/3-0-video-prime'
    assert payload['input']['seed'] == 0
    assert payload['input']['audio'] is False
    assert payload['input']['reference_audio_urls'] == ['https://media.example/sound.mp3']
    assert 'omni_reference_task_type' not in payload['input']
